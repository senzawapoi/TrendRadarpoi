#!/usr/bin/env bash
set -Eeuo pipefail

release_id="${1:?release id is required}"
archive="${2:?archive path is required}"
manifest="${3:?manifest path is required}"
release_root="${TRENDRADAR_RELEASE_ROOT:-/opt/trendradar/releases}"
current_link="${TRENDRADAR_CURRENT_LINK:-/opt/trendradar/current}"
database="${INTELLIGENCE_DB_PATH:-/var/lib/trendradar/output/intelligence.db}"
ai_database="${AI_FRONTIER_DB_PATH:-/var/lib/trendradar/output/ai_frontier.db}"
control_dir="${TRENDRADAR_CONTROL_DIR:-/var/lib/trendradar/control}"
backup_dir="${TRENDRADAR_BACKUP_DIR:-/var/backups/trendradar/local}"
sync_mode="${INTELLIGENCE_SQLITE_SYNCHRONOUS:-FULL}"
verify_seconds="${TRENDRADAR_DEPLOY_VERIFY_SECONDS:-60}"
restart_units="${TRENDRADAR_RESTART_UNITS:-}"
initial_units="${TRENDRADAR_INITIAL_UNITS:-}"
managed_units="${TRENDRADAR_MANAGED_UNITS:-trendradar-bot.service trendradar-worker.service trendradar-scheduler.service trendradar-scheduler.timer trendradar-collect-main.service trendradar-collect-main.timer trendradar-collect-ai.service trendradar-collect-ai.timer trendradar-health.service trendradar-health.timer trendradar-backup.service trendradar-backup.timer}"
transaction_id="${release_id}-$(date -u +%Y%m%dT%H%M%SZ)-$$"
transaction_file="$control_dir/deploy-${transaction_id}.json"
in_progress_file="$control_dir/deploy-in-progress.json"
lock_file="${TRENDRADAR_DEPLOY_LOCK:-$control_dir/deploy.lock}"
old_target=""
old_release_id=""
snapshot_id=""
business_boundary=false
pre_active_units=""
stage_name="prepare"
active_transaction=false
guard_owned=false
quiesce_started=false
snapshot_root=""
release_env="${TRENDRADAR_RELEASE_ENV:-/etc/trendradar/release.env}"
service_group="${TRENDRADAR_SERVICE_GROUP:-trendradar}"
service_user="${TRENDRADAR_SERVICE_USER:-trendradar}"
controller_pid=$$
export INTELLIGENCE_DB_PATH="$database" AI_FRONTIER_DB_PATH="$ai_database"
export TRENDRADAR_CONTROL_DIR="$control_dir" TRENDRADAR_BACKUP_DIR="$backup_dir"

as_service() {
  runuser -u "$service_user" -- /bin/sh -c 'umask 0077; exec "$@"' sh "$@"
}

case "$release_id" in
  (*[!A-Za-z0-9._-]*|'') echo "invalid release id" >&2; exit 2 ;;
esac
if ! getent group "$service_group" >/dev/null 2>&1; then
  echo "service group does not exist: $service_group" >&2
  exit 2
fi
getent passwd "$service_user" >/dev/null || { echo "service user does not exist" >&2; exit 2; }
if [[ -z "${CONFIG_PATH:-}" ]] || ! as_service /usr/bin/test -r "$CONFIG_PATH"; then
  echo "runtime configuration is not readable by the service user" >&2
  exit 2
fi
for path in "$archive" "$manifest"; do
  [[ -f "$path" ]] || { echo "missing deployment input: $path" >&2; exit 2; }
done
if ! [[ "$verify_seconds" =~ ^[0-9]+$ ]] || (( verify_seconds < 1 || verify_seconds > 3600 )); then
  echo "invalid TRENDRADAR_DEPLOY_VERIFY_SECONDS" >&2
  exit 2
fi

mkdir -p "$release_root"
install -d -m 0750 -o "$service_user" -g "$service_group" "$control_dir" \
  "$backup_dir" "$(dirname "$database")" "$(dirname "$ai_database")" \
  "${TRENDRADAR_LOCK_DIR:-$(dirname "$database")/locks}" \
  "${TRENDRADAR_HEALTH_DIR:-$(dirname "$database")/health}"
exec 9>"$lock_file"
if ! flock -n 9; then
  echo "deployment lock is busy" >&2
  exit 3
fi

write_state() {
  local state="$1"
  stage_name="$state"
  python3 - "$transaction_file" "$in_progress_file" "$active_transaction" "$transaction_id" "$state" "$release_id" "$old_target" "$snapshot_id" "$business_boundary" "$pre_active_units" "$controller_pid" "$current_link" "${release_dir:-}" "$snapshot_root" <<'PY'
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

transaction_path, active_path, active, transaction_id, state, new_release, old_target, snapshot_id, boundary, active_units, controller_pid, current_link, new_target, snapshot_root = sys.argv[1:]
payload = {
    "transaction_id": transaction_id,
    "state": state,
    "new_release_id": new_release,
    "old_target": old_target or None,
    "snapshot_id": snapshot_id or None,
    "snapshot_root": snapshot_root or None,
    "business_boundary_crossed": boundary == "true",
    "pre_active_units": active_units.split(),
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "controller_lease_boottime_ns": time.clock_gettime_ns(time.CLOCK_BOOTTIME),
    "controller_pid": int(controller_pid),
    "controller_start_time": Path(f"/proc/{controller_pid}/stat").read_text().rsplit(")", 1)[1].split()[19],
    "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    "current_link": current_link,
    "new_target": new_target,
}

def write_atomic(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)
    fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# The active marker is written first so recovery can never observe a newer
# archive record while the deployment guard still advertises an older stage.
targets = [Path(active_path), Path(transaction_path)] if active == "true" else [Path(transaction_path)]
for target in targets:
    write_atomic(target)
PY
}

stop_managed_units() {
  for unit in $(ordered_managed_units); do
    systemctl stop "${unit}" >/dev/null 2>&1 || true
  done
}

ordered_managed_units() {
  for unit in $managed_units; do
    [[ "$unit" == *.timer ]] && printf '%s\n' "$unit"
  done
  for unit in $managed_units; do
    [[ "$unit" != *.timer ]] && printf '%s\n' "$unit"
  done
  return 0
}

retain_maintenance_after_resume_failure() {
  write_state failed:resume
  stop_managed_units
  if [[ -f "${database}" && -x "${release_dir:-}/venv/bin/python" ]]; then
    as_service "${release_dir}/venv/bin/python" -m trendradar.ops maintenance enter \
      --database "${database}" --reason "deployment ${transaction_id} failed after resume" >/dev/null 2>&1 || true
  fi
}

fail() {
  local reason="$1"
  local failed_stage="$stage_name"
  trap - ERR TERM INT
  if [[ "${business_boundary}" == true ]]; then
    retain_maintenance_after_resume_failure
  elif ! rollback_before_resume; then
    active_transaction=true
    write_state failed:rollback
    stop_managed_units
  fi
  write_state "failed:${failed_stage}"
  echo "deployment failed during ${failed_stage}: ${reason}" >&2
  exit 1
}

rollback_before_resume() {
  [[ "${business_boundary}" == true ]] && return 0
  [[ -n "${old_target}" && -d "${old_target}" ]] || return 0
  [[ "${quiesce_started}" == true ]] || return 0
  [[ -n "${release_dir:-}" && -x "${release_dir}/venv/bin/python" ]] || return 0
  [[ -x "${old_target}/venv/bin/python" ]] || return 1
  units_to_start="${restart_units:-$pre_active_units}"
  stop_managed_units
  if [[ -e "${current_link}" || -L "${current_link}" ]]; then
    ln -sfn "${old_target}" "${current_link}.rollback"
    mv -Tf "${current_link}.rollback" "${current_link}" || return 1
  fi
  if [[ -n "${snapshot_id}" ]]; then
    [[ -d "${backup_dir}/${snapshot_id}" ]] || return 1
    write_state rollback
    restore_dir="${control_dir}/restore-${transaction_id}"
    if ! as_service "${release_dir}/venv/bin/python" -m trendradar.ops backup restore \
      --snapshot "${backup_dir}/${snapshot_id}" --destination "${restore_dir}" \
      --guard-database "${database}" >/dev/null 2>&1; then
      return 1
    fi
    # Restore validation may exceed the controller lease; renew before activation.
    write_state rollback
    if ! as_service "${release_dir}/venv/bin/python" -m trendradar.ops backup activate \
      --restored "${restore_dir}" --database "${database}" --root "${snapshot_root}" \
      --deployment-rollback >/dev/null 2>&1; then
      return 1
    fi
    write_state rollback
  fi
  release_env="${TRENDRADAR_RELEASE_ENV:-/etc/trendradar/release.env}"
  printf 'TRENDRADAR_RELEASE_ID=%s\n' "${old_release_id}" > "${release_env}"
  export TRENDRADAR_RELEASE_ID="$old_release_id"
  # The restored schema belongs to the old release, not the candidate.
  as_service "${old_target}/venv/bin/python" -m trendradar.ops database check \
    --database "$database" --synchronous "$sync_mode" >/dev/null || return 1
  if [[ -f "$ai_database" ]]; then
    as_service "${old_target}/venv/bin/python" -m trendradar.ops database check \
      --database "$ai_database" --kind ai_frontier --synchronous "$sync_mode" >/dev/null || return 1
  fi
  write_state rollback_complete
  systemctl daemon-reload >/dev/null 2>&1 || return 1
  as_service "${release_dir}/venv/bin/python" -m trendradar.ops maintenance confirm-deployment-rollback \
    --database "$database" >/dev/null 2>&1 || return 1
  for unit in $units_to_start; do
    systemctl start "${unit}" >/dev/null 2>&1 || return 1
  done
  active_transaction=false
  return 0
}

expected_sha="$(python3 - "$manifest" "$release_id" <<'PY'
import json
import os
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
artifact = value.get("artifact") or {}
sha = artifact.get("sha256")
if not isinstance(sha, str) or len(sha) != 64:
    raise SystemExit("release manifest has no artifact sha256")
if value.get("release_id") != sys.argv[2]:
    raise SystemExit("release manifest release id mismatch")
if value.get("git_dirty") is True and os.environ.get("TRENDRADAR_ALLOW_DIRTY_RELEASE") != "true":
    raise SystemExit("dirty release is not installable")
print(sha)
PY
)" || { echo "invalid manifest" >&2; exit 2; }
actual_sha="$(sha256sum "$archive" | awk '{print $1}')"
[[ "$expected_sha" == "$actual_sha" ]] || { echo "release checksum mismatch" >&2; exit 2; }

# Reject malformed archives before probing or changing service state. Role
# capture still happens before the maintenance marker and potentially long setup.
python3 - "$archive" "$release_id" <<'PY'
import sys
import tarfile
from pathlib import Path

archive, release_id = sys.argv[1:]
prefix = f"trendradar-{release_id}/"
with tarfile.open(archive, "r:gz") as stream:
    members = stream.getmembers()
    for member in members:
        name = member.name
        if not name.startswith(prefix) or name.startswith("/") or ".." in Path(name).parts:
            raise SystemExit(f"invalid archive member: {name}")
        if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
            raise SystemExit(f"unsupported archive member: {name}")
PY

write_state prepare
if [[ -e "$current_link" || -L "$current_link" ]]; then
  old_target="$(readlink -f "$current_link")"
  old_release_id="$(basename "$old_target")"
fi
if [[ -f "$control_dir/restore-guard.json" ]]; then
  fail "existing restore guard requires operator review"
fi
if [[ -f "$in_progress_file" ]]; then
  fail "another deployment transaction is incomplete"
fi
# The active marker itself tells running roles to stop accepting work. Capture
# their restart intent while holding the deployment lock, before publishing it;
# a Worker can exit during acquire, long before the explicit quiesce step.
for unit in $managed_units; do
  if systemctl is-active --quiet "$unit"; then
    pre_active_units="$pre_active_units $unit"
  fi
done
active_transaction=true
write_state prepare

stage="$(mktemp -d "$release_root/.staging-${release_id}.XXXXXX")"
release_dir="$release_root/$release_id"
cleanup() { rm -rf "$stage"; }
trap cleanup EXIT
trap 'fail "unexpected command failure"' ERR
trap 'fail "installer interrupted"' TERM INT

write_state acquire
python3 - "$archive" "$stage" "$release_id" <<'PY'
import shutil
import sys
import tarfile
from pathlib import Path

archive, destination, release_id = map(Path, sys.argv[1:])
prefix = f"trendradar-{release_id}/"
with tarfile.open(archive, "r:gz") as stream:
    members = stream.getmembers()
    for member in members:
        name = member.name
        parts = Path(name).parts
        if not name.startswith(prefix) or name.startswith("/") or ".." in parts:
            raise SystemExit(f"invalid archive member: {name}")
        if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
            raise SystemExit(f"unsupported archive member: {name}")
        target = (destination / name).resolve()
        if destination.resolve() not in target.parents:
            raise SystemExit(f"archive member escapes destination: {name}")
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            source = stream.extractfile(member)
            if source is None:
                raise SystemExit(f"archive member has no data: {name}")
            with target.open("wb") as output:
                shutil.copyfileobj(source, output)
root = destination / f"trendradar-{release_id}"
if not root.is_dir():
    raise SystemExit("archive has no expected release root")
PY
payload_dir="$stage/trendradar-${release_id}"
[[ -d "$payload_dir" ]] || fail "archive root mismatch"
[[ -f "$payload_dir/build-requirements.lock" ]] || fail "archive missing build-requirements.lock"
[[ -f "$payload_dir/requirements.lock" ]] || fail "archive missing requirements.lock"
[[ ! -e "$release_dir" ]] || fail "release already installed: $release_id"
mv "$payload_dir" "$release_dir"

python3 -m venv "$release_dir/venv" || fail "venv creation"
"$release_dir/venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir \
  --requirement "$release_dir/build-requirements.lock" || fail "locked build dependency installation"
"$release_dir/venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir \
  --requirement "$release_dir/requirements.lock" || fail "locked dependency installation"
"$release_dir/venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir --no-build-isolation --no-deps \
  "$release_dir" || fail "application installation"
"$release_dir/venv/bin/python" -m trendradar.integrations.lark --help >/dev/null || fail "offline import smoke"

if [[ -f "$database" ]]; then
  as_service "$release_dir/venv/bin/python" -m trendradar.ops maintenance enter \
    --database "$database" --reason "deployment ${transaction_id}" >/dev/null || fail "deployment guard"
  guard_owned=true
fi

write_state quiesce
quiesce_started=true
for unit in $(ordered_managed_units); do
  systemctl stop "$unit" || fail "could not stop $unit"
done
write_state snapshot
if [[ -f "$database" ]]; then
  # Discover legacy partitions only beside intelligence; explicitly include
  # configured AI paths and absent targets without scanning a wider root.
  snapshot_json="$(as_service "$release_dir/venv/bin/python" - "$database" "$ai_database" "$backup_dir" "$old_release_id" <<'PY'
import json
import os
import sys
from pathlib import Path
from trendradar.ops.backup import create_snapshot

database, ai_database, destination = map(Path, sys.argv[1:4])
targets = [database.resolve(), ai_database.resolve()]
for directory in (database.parent / "news", database.parent / "rss"):
    if directory.is_dir():
        targets.extend(sorted(directory.glob("*.db")))
targets = list(dict.fromkeys(path.resolve() for path in targets))
root = Path(os.path.commonpath([str(path.parent) for path in targets]))
snapshot = create_snapshot([path for path in targets if path.is_file()], destination,
                          release_id=sys.argv[4], root=root, target_mapping=targets)
print(json.dumps(snapshot | {"runtime_root": str(root)}))
PY
)" || fail "pre-release snapshot"
  snapshot_id="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["backup_id"])' <<<"$snapshot_json")" || fail "snapshot id"
  snapshot_root="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["runtime_root"])' <<<"$snapshot_json")" || fail "snapshot root"
  write_state snapshot
fi

write_state migrate
as_service "$release_dir/venv/bin/python" -m trendradar.ops database migrate \
  --database "$database" --synchronous "$sync_mode" || fail "intelligence migration"
if [[ "${TRENDRADAR_PREPARE_AI_DATABASE:-true}" == "true" ]]; then
  as_service "$release_dir/venv/bin/python" -m trendradar.ops database migrate \
    --database "$ai_database" --kind ai_frontier --synchronous "$sync_mode" || fail "AI Frontier migration"
fi
"$release_dir/venv/bin/python" -m trendradar.ops database check --database "$database" --synchronous "$sync_mode" >/dev/null || fail "database policy check"

write_state switch
if [[ -e "$current_link" || -L "$current_link" ]]; then
  ln -sfn "$release_dir" "${current_link}.next"
  mv -Tf "${current_link}.next" "$current_link"
else
  ln -s "$release_dir" "$current_link"
fi
install -d -m 0750 "$(dirname "$release_env")"
printf 'TRENDRADAR_RELEASE_ID=%s\n' "$release_id" > "$release_env"
# The release id is non-secret; make this marker readable by the fixed units
# even when a fresh host created the parent as root:root.
chgrp "$service_group" "$(dirname "$release_env")"
chmod 0750 "$(dirname "$release_env")"
chgrp "$service_group" "$release_env"
chmod 0640 "$release_env"
# The readiness process is outside systemd, so load the same release identity
# that the role units receive through EnvironmentFile.
set -a
# shellcheck disable=SC1090
source "$release_env"
set +a
systemctl daemon-reload || fail "systemd reload"

write_state pre_resume
"$release_dir/venv/bin/python" -m trendradar.ops database check --database "$database" --synchronous "$sync_mode" >/dev/null || fail "candidate database check"
write_state resume
business_boundary=true
write_state resume
if [[ "${guard_owned:-false}" == true ]]; then
  as_service "$release_dir/venv/bin/python" -m trendradar.ops maintenance clear --database "$database" >/dev/null || fail "deployment guard clear"
  guard_owned=false
fi
write_state verify
if [[ -n "$old_target" ]]; then
  units_to_start="${restart_units:-$pre_active_units}"
else
  units_to_start="${restart_units:-$initial_units}"
fi
for unit in $units_to_start; do
  write_state verify
  systemctl start "$unit" || fail "could not start $unit"
done
deadline=$(( $(date +%s) + verify_seconds ))
while (( $(date +%s) < deadline )); do
  write_state verify
  if [[ -z "${TRENDRADAR_SKIP_READINESS:-}" ]] && TRENDRADAR_RELEASE_ID="$release_id" as_service "$release_dir/venv/bin/python" -m trendradar.ops health \
      --config "${CONFIG_PATH:-/etc/trendradar/config.yaml}" --readiness --json >/dev/null 2>&1; then
    write_state finalize
    if finalize_output=$(as_service "$release_dir/venv/bin/python" -m trendradar.ops maintenance finalize-deployment \
        --database "$database"); then
      :
    else
      finalize_status=$?
      printf 'finalize exit=%s diagnostic=%s\n' "$finalize_status" "$finalize_output" >&2
      fail "finalize confirmation"
    fi
    rm -f "$in_progress_file"
    echo "release activated and readiness verified: $release_id"
    exit 0
  fi
  sleep 2
done

stop_managed_units
if [[ -f "$database" ]]; then
  "$release_dir/venv/bin/python" -m trendradar.ops maintenance enter --database "$database" \
    --reason "deployment $transaction_id failed readiness; manual rollback required" >/dev/null || true
fi
write_state failed:readiness
echo "release $release_id is installed but not ready; maintenance guard retained; manual rollback required" >&2
exit 1

