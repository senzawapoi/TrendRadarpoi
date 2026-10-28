#!/usr/bin/python3
"""Explicit, fail-closed forward recovery of an installed deployment.

Install beside load_environment.py and invoke through the fixed recovery wrapper.
This controller never restores databases, switches releases or changes systemd limits.
The original failed journal remains immutable; a separately identified transaction
uses the existing live-controller fence and finalization API.
"""

from __future__ import annotations

import argparse
import fcntl
import grp
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROLES = ("bot", "worker", "scheduler")
TIMERS = tuple(f"trendradar-{name}.timer" for name in (
    "scheduler", "collect-main", "collect-ai", "health", "backup",
))
SERVICES = tuple(f"trendradar-{name}.service" for name in (
    *ROLES, "collect-main", "collect-ai", "health", "backup",
))


class RecoveryError(RuntimeError):
    """A bounded local reason, never a command's potentially secret output."""


@dataclass(frozen=True)
class Config:
    release_id: str
    failed_transaction: str
    commit: str
    archive_sha: str
    archive: Path
    manifest: Path
    release_root: Path
    current: Path
    release_env: Path
    control: Path
    database: Path
    ai_database: Path
    backup: Path
    health: Path
    service_user: str
    service_gid: int
    deploy_lock: Path
    timers: tuple[str, ...]
    role_timeout: int = 300
    readiness_timeout: int = 300
    collector_timeout: int = 7200
    refresh: bool = False

    @property
    def target(self) -> Path:
        return self.release_root / self.release_id


def boottime_ns() -> int:
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def controller_identity() -> dict[str, Any]:
    return {
        "controller_pid": os.getpid(),
        "controller_start_time": Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(
            ")", 1)[1].split()[19],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    }


def controller_present(payload: dict[str, Any]) -> bool:
    # Even an expired lease does not authorize stealing from an existing process.
    try:
        pid = payload["controller_pid"]
        if type(pid) is not int or pid <= 1:
            raise RecoveryError("invalid prior controller identity")
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return (fields[0] != "Z" and fields[19] == payload["controller_start_time"]
                and controller_identity()["boot_id"] == payload["boot_id"])
    except FileNotFoundError:
        return False


def regular(path: Path) -> bytes:
    if not path.is_absolute() or ".." in path.parts:
        raise RecoveryError("unsafe input path")
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise RecoveryError("input is missing or symlinked")
    return path.read_bytes()


def object_file(path: Path) -> dict[str, Any]:
    value = json.loads(regular(path))
    if not isinstance(value, dict):
        raise RecoveryError("control input must be an object")
    return value


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_scene(config: Config) -> dict[str, Any]:
    for identity in (config.release_id, config.failed_transaction):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", identity):
            raise RecoveryError("invalid recovery identity")
    failed = object_file(config.control / "deploy-in-progress.json")
    archived = regular(config.control / f"deploy-{config.failed_transaction}.json")
    if regular(config.control / "deploy-in-progress.json") != archived:
        raise RecoveryError("failed transaction archive mismatch")
    valid_state = failed.get("state") == "failed:readiness" or (
        failed.get("kind") == "controlled_forward_recovery"
        and str(failed.get("state", "")).startswith("failed:recovery:")
    )
    if (not valid_state or failed.get("transaction_id") != config.failed_transaction
            or failed.get("new_release_id") != config.release_id
            or failed.get("business_boundary_crossed") is not True
            or failed.get("new_target") != str(config.target)
            or failed.get("current_link") != str(config.current)):
        raise RecoveryError("failed deployment identity or boundary mismatch")
    if controller_present(failed):
        raise RecoveryError("prior controller is still alive")
    if (not config.current.is_symlink() or config.current.resolve() != config.target
            or config.target.resolve() != config.target):
        raise RecoveryError("current release target mismatch")
    release_env = regular(config.release_env).decode().strip()
    if release_env != f"TRENDRADAR_RELEASE_ID={config.release_id}":
        raise RecoveryError("release environment identity mismatch")
    guard = object_file(config.control / "restore-guard.json")
    if (guard.get("state") != "maintenance" or guard.get("recovery_cutover_at")
            or any(guard.get(k) is not False for k in (
                "accept_new_work", "process_recovery", "allow_external_send", "allow_collection",
            ))):
        raise RecoveryError("explicit maintenance guard is invalid")
    if (config.control / "recovery-cutover.json").exists():
        raise RecoveryError("restore cutover requires separate recovery")
    for path in config.control.glob("restore-activation-*.json"):
        if object_file(path).get("state") not in {"complete", "rolled_back"}:
            raise RecoveryError("incomplete restore requires separate recovery")
    if any(unit not in TIMERS for unit in config.timers):
        raise RecoveryError("unrecognized timer intent")
    return failed


def verify_artifact(config: Config) -> int:
    manifest = object_file(config.manifest)
    if (not re.fullmatch(r"[a-f0-9]{40}", config.commit)
            or not re.fullmatch(r"[a-f0-9]{64}", config.archive_sha)
            or manifest.get("git_commit") != config.commit
            or manifest.get("release_id") != config.release_id
            or manifest.get("git_dirty") is not False
            or (manifest.get("artifact") or {}).get("sha256") != config.archive_sha
            or digest(regular(config.archive)) != config.archive_sha):
        raise RecoveryError("clean artifact identity mismatch")
    sites = list(config.target.glob("venv/lib/python3.*/site-packages"))
    if len(sites) != 1 or sites[0].resolve() != sites[0]:
        raise RecoveryError("ambiguous installed package location")
    site = sites[0]
    seen = set()
    package_files = set()
    with tarfile.open(config.archive, "r:gz") as stream:
        for member in stream:
            path = Path(member.name)
            if (path.is_absolute() or ".." in path.parts or len(path.parts) < 2
                    or path.parts[0] != f"trendradar-{config.release_id}"
                    or not (member.isfile() or member.isdir())):
                raise RecoveryError("unsafe artifact member")
            if member.isdir():
                continue
            relative = Path(*path.parts[1:])
            if relative in seen:
                raise RecoveryError("duplicate artifact member")
            seen.add(relative)
            content = stream.extractfile(member).read()
            if regular(config.target / relative) != content:
                raise RecoveryError("installed release differs from validated artifact")
            if relative.parts[0] in {"trendradar", "mcp_server"}:
                package_files.add(relative)
                if regular(site / relative) != content:
                    raise RecoveryError("installed Python package differs from artifact")
    actual = {p.relative_to(site) for name in ("trendradar", "mcp_server")
              for p in (site / name).rglob("*") if p.is_file()
              and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}}
    if not package_files or actual != package_files:
        raise RecoveryError("installed Python package has unexpected files")
    return len(seen)


def atomic_json(path: Path, payload: dict[str, Any], gid: int) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o640)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), 0, gid)
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)


class Journal:
    def __init__(self, config: Config, failed: dict[str, Any]) -> None:
        self.config = config
        self.original = regular(config.control / "deploy-in-progress.json")
        identity = f"recover-{config.release_id}-{uuid.uuid4().hex[:12]}"
        self.payload = dict(failed, **controller_identity())
        self.payload.update({
            "transaction_id": identity, "kind": "controlled_forward_recovery",
            "recovery_of": failed["transaction_id"], "failed_record_sha256": digest(self.original),
            "application_commit": config.commit, "artifact_sha256": config.archive_sha,
            "controller_sha256": digest(Path(__file__).read_bytes()),
            "prior_guard": object_file(config.control / "restore-guard.json"),
            "requested_timers": list(config.timers), "state": "recovery:prepare",
        })
        self.path = config.control / f"deploy-{identity}.json"
        self.active = config.control / "deploy-in-progress.json"
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.error: BaseException | None = None

    def _write(self, *, active: bool = True) -> None:
        self.payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.payload["controller_lease_boottime_ns"] = boottime_ns()
        if active:
            atomic_json(self.active, self.payload, self.config.service_gid)
        atomic_json(self.path, self.payload, self.config.service_gid)

    def begin(self) -> None:
        if regular(self.active) != self.original or self.path.exists():
            raise RecoveryError("failed scene changed before acquisition")
        self._write()

    def update(self, state: str | None = None, **extra: Any) -> None:
        with self.lock:
            if object_file(self.active).get("transaction_id") != self.payload["transaction_id"]:
                raise RecoveryError("recovery lost transaction ownership")
            previous = (self.payload["state"], self.payload.get("recovery_stage"))
            self.payload.update(extra)
            if state is not None:
                self.payload["state"] = state
            self._write()
            current = (self.payload["state"], self.payload.get("recovery_stage"))
            if current != previous:
                print(json.dumps({"state": current[0], "stage": current[1]}), flush=True)

    def check(self) -> None:
        if self.error is not None:
            raise RecoveryError("controller lease renewal failed") from self.error

    def start_lease(self) -> None:
        def renew() -> None:
            while not self.stop_event.wait(2):
                try:
                    self.update()
                except BaseException as exc:
                    self.error = exc
                    return
        self.thread = threading.Thread(target=renew, name="deployment-lease", daemon=True)
        self.thread.start()

    def stop_lease(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RecoveryError("controller lease writer did not stop")

    def complete(self) -> None:
        if self.active.exists():
            raise RecoveryError("finalization left the transaction active")
        self.payload["state"] = "complete"
        self._write(active=False)


def role_ready(payload: dict[str, Any], role: str, pid: int, release: str, now: int) -> bool:
    stamp = payload.get("updated_boottime_ns")
    return (pid > 1 and payload.get("pid") == pid and payload.get("release_id") == release
            and payload.get("boot_id") == controller_identity()["boot_id"]
            and payload.get("state") == ("connected" if role == "bot" else "running")
            and type(stamp) is int and 0 <= now - stamp <= 30_000_000_000)


class Host:
    def __init__(self, config: Config, journal: Journal) -> None:
        self.config = config
        self.journal = journal
        self.environment = dict(os.environ, TRENDRADAR_RELEASE_ID=config.release_id)
        self.cleaning_up = False

    def run(self, args: list[str], *, timeout: int = 60, check: bool = True) -> str:
        started = time.monotonic()
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, env=self.environment, start_new_session=True,
                              cwd=self.config.database.parent.parent) as process:
            try:
                while True:
                    if not self.cleaning_up:
                        self.journal.check()
                    if time.monotonic() - started > timeout:
                        raise RecoveryError("recovery subprocess timed out")
                    try:
                        stdout, _ = process.communicate(timeout=0.5)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise
        if check and process.returncode:
            raise RecoveryError(f"recovery subprocess failed with status {process.returncode}")
        return stdout

    def ops(self, *args: str, timeout: int = 60, check: bool = True) -> dict[str, Any]:
        output = self.run([
            "/usr/sbin/runuser", "-u", self.config.service_user, "--",
            str(self.config.target / "venv/bin/python"), "-I", "-m", "trendradar.ops", *args,
        ], timeout=timeout, check=check)
        value = json.loads(output)
        if not isinstance(value, dict):
            raise RecoveryError("operations command returned invalid evidence")
        return value

    def properties(self, unit: str) -> dict[str, str]:
        output = self.run(["/usr/bin/systemctl", "show", unit, "--property=ActiveState,"
                           "SubState,MainPID,ExecMainPID,ExecMainStatus,Result"], timeout=15)
        return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)

    def stop_all(self) -> None:
        self.run(["/usr/bin/systemctl", "stop", *TIMERS], timeout=90)
        self.run(["/usr/bin/systemctl", "stop", *SERVICES], timeout=120)
        for unit in (*TIMERS, *SERVICES):
            status = self.properties(unit)
            if status.get("ActiveState") not in {"inactive", "failed"} or int(
                status.get("MainPID", "0")
            ):
                raise RecoveryError("managed unit did not quiesce")

    def snapshot(self) -> dict[str, Any]:
        if self.config.ai_database.parent != self.config.database.parent:
            raise RecoveryError("recovery requires a shared runtime database root")
        for path, kind in [(self.config.database, "intelligence"),
                           (self.config.ai_database, "ai_frontier")]:
            self.ops("database", "check", "--database", str(path), "--kind", kind,
                     "--synchronous", "FULL")
        return self.ops("backup", "create", "--root", str(self.config.database.parent),
                        "--destination", str(self.config.backup),
                        "--release-id", self.config.release_id, timeout=300)

    def clear_guard(self) -> None:
        result = self.ops("maintenance", "clear", "--database", str(self.config.database))
        if result.get("cleared") is not True:
            raise RecoveryError("maintenance guard was not explicitly cleared")

    def enter_guard(self) -> None:
        self.cleaning_up = True
        self.ops("maintenance", "enter", "--database", str(self.config.database),
                 "--reason", f"controlled recovery {self.journal.payload['transaction_id']} failed")

    def evidence(self, label: str, report: dict[str, Any]) -> None:
        path = self.config.control / f"{self.journal.payload['transaction_id']}-{label}.json"
        atomic_json(path, report, self.config.service_gid)

    def start_once(self, unit: str, timeout: int) -> None:
        self.run(["/usr/bin/systemctl", "reset-failed", unit], check=False)
        # A blocking start waits for THIS oneshot job; an immediate inactive poll
        # after --no-block can accidentally accept the previous successful run.
        # run() stays interruptible and the separate lease thread continues.
        self.run(["/usr/bin/systemctl", "start", unit], timeout=timeout)
        status = self.properties(unit)
        if (status.get("ActiveState") != "inactive" or status.get("Result") != "success"
                or status.get("ExecMainStatus") != "0"):
            raise RecoveryError(f"{unit} did not complete successfully")

    def refresh_sources(self) -> None:
        if not self.config.refresh:
            return
        report = self.ops("health", "--readiness", "--allow-maintenance", "--json", check=False)
        self.evidence("before-source-refresh", report)
        source_errors = [str(v).split(":", 1)[1] for v in (
            report.get("warnings", []) + report.get("errors", [])
        ) if str(v).startswith(("stale_source:", "missing_source_run:", "source_unhealthy:"))]
        # Each enabled pipeline runs at most once; no retries or schedule changes.
        units = []
        if any(source.startswith("ai_frontier:") for source in source_errors):
            units.append("trendradar-collect-ai.service")
        if any(not source.startswith("ai_frontier:") for source in source_errors):
            units.append("trendradar-collect-main.service")
        for unit in units:
            self.journal.update("verify", recovery_stage=unit)
            self.start_once(unit, self.config.collector_timeout)

    def start_role(self, role: str) -> None:
        unit = f"trendradar-{role}.service"
        if role == "scheduler":
            self.start_once(unit, self.config.role_timeout)
            return
        self.run(["/usr/bin/systemctl", "reset-failed", unit], check=False)
        self.run(["/usr/bin/systemctl", "start", "--no-block", unit])
        deadline = time.monotonic() + self.config.role_timeout
        while time.monotonic() < deadline:
            self.journal.check()
            status = self.properties(unit)
            if status.get("ActiveState") == "failed":
                raise RecoveryError(f"{role} failed during serial startup")
            try:
                heartbeat = object_file(self.config.health / f"{role}.json")
                if (status.get("ActiveState") == "active" and role_ready(
                    heartbeat, role, int(status.get("MainPID", "0")),
                    self.config.release_id, boottime_ns(),
                )):
                    self.evidence(f"{role}-started", heartbeat)
                    return
            except (OSError, ValueError, RecoveryError):
                pass
            time.sleep(1)
        raise RecoveryError(f"{role} did not publish an accepting heartbeat")

    def start_timers(self) -> None:
        for unit in self.config.timers:
            self.run(["/usr/bin/systemctl", "start", unit])

    def readiness(self) -> None:
        deadline = time.monotonic() + self.config.readiness_timeout
        while time.monotonic() < deadline:
            report = self.ops("health", "--readiness", "--json", check=False)
            self.evidence("readiness", report)
            if report.get("status") == "healthy" and not report.get("errors"):
                return
            time.sleep(2)
        raise RecoveryError("strict readiness did not pass")

    def finalize(self) -> None:
        # Lease writer is stopped: it must never recreate a marker removed by finalize.
        # Bound this last call below the existing 15-second controller lease.
        result = self.ops("maintenance", "finalize-deployment", "--database",
                          str(self.config.database), timeout=12)
        if result.get("finalized") is not True or result.get("release_id") != self.config.release_id:
            raise RecoveryError("finalization did not confirm the exact release")


def recover(config: Config, journal: Journal, host: Host) -> None:
    journal.begin()
    stage = "quiesce"
    try:
        host.stop_all()
        stage = "snapshot"
        snapshot = host.snapshot()
        journal.update("recovery:snapshot", recovery_snapshot_id=snapshot["backup_id"])
        stage = "resume"
        journal.update("resume", recovery_stage=stage)
        journal.start_lease()
        host.clear_guard()
        stage = "sources"
        journal.update("verify", recovery_stage=stage)
        host.refresh_sources()
        for role in ROLES:
            stage = role
            journal.update("verify", recovery_stage=stage)
            host.start_role(role)
        stage = "timers"
        host.start_timers()
        stage = "readiness"
        journal.update("verify", recovery_stage=stage)
        host.readiness()
        journal.check()
        stage = "finalize"
        journal.stop_lease()
        journal.update("finalize", recovery_stage=stage)
        host.finalize()
        journal.complete()
    except BaseException:
        with suppress(Exception):
            journal.stop_lease()
        with suppress(Exception):
            journal.update(f"failed:recovery:{stage}", recovery_stage=stage)
        # A failed marker independently fences roles even if creating the guard fails.
        for action in (host.enter_guard, host.stop_all):
            try:
                action()
            except Exception as exc:
                print(json.dumps({"cleanup_error": type(exc).__name__}), flush=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("release-id", "failed-transaction", "commit", "archive-sha", "archive", "manifest"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--refresh-sources", action="store_true")
    parser.add_argument("--role-timeout", type=int, default=300)
    parser.add_argument("--readiness-timeout", type=int, default=300)
    parser.add_argument("--collector-timeout", type=int, default=7200)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise RecoveryError("recovery requires the root-owned entry point")
    if (not 30 <= args.role_timeout <= 600 or not 30 <= args.readiness_timeout <= 3600
            or not 60 <= args.collector_timeout <= 7200):
        raise RecoveryError("recovery time budget is outside bounds")
    os.umask(0o027)
    env = os.environ
    control = Path(env["TRENDRADAR_CONTROL_DIR"])
    restart = env.get("TRENDRADAR_RESTART_UNITS", "").split()
    if any(unit not in (*SERVICES, *TIMERS) for unit in restart):
        raise RecoveryError("unrecognized restart intent")
    config = Config(
        args.release_id, args.failed_transaction, args.commit, args.archive_sha,
        Path(args.archive), Path(args.manifest),
        Path(env.get("TRENDRADAR_RELEASE_ROOT", "/opt/trendradar/releases")),
        Path(env.get("TRENDRADAR_CURRENT_LINK", "/opt/trendradar/current")),
        Path(env.get("TRENDRADAR_RELEASE_ENV", "/etc/trendradar/release.env")),
        control, Path(env["INTELLIGENCE_DB_PATH"]), Path(env["AI_FRONTIER_DB_PATH"]),
        Path(env["TRENDRADAR_BACKUP_DIR"]), Path(env["TRENDRADAR_HEALTH_DIR"]),
        env.get("TRENDRADAR_SERVICE_USER", "trendradar"),
        grp.getgrnam(env.get("TRENDRADAR_SERVICE_GROUP", "trendradar")).gr_gid,
        Path(env.get("TRENDRADAR_DEPLOY_LOCK", str(control / "deploy.lock"))),
        tuple(unit for unit in restart if unit in TIMERS), args.role_timeout,
        args.readiness_timeout, args.collector_timeout, args.refresh_sources,
    )
    # The wrapper/loader pins trusted common.env; never accept request-supplied environment.
    from load_environment import trusted_file
    trusted_file(Path(__file__))
    trusted_file(config.archive)
    trusted_file(config.manifest)
    trusted_file(config.release_env)
    trusted_file((config.target / "venv/bin/python").resolve())
    trusted_file(config.target / "trendradar/__init__.py")
    for site in config.target.glob("venv/lib/python3.*/site-packages"):
        trusted_file(site / "trendradar/__init__.py")
    if not config.deploy_lock.is_absolute() or any(
        path.is_symlink() for path in config.deploy_lock.parents
    ):
        raise RecoveryError("unsafe deployment lock")
    descriptor = os.open(config.deploy_lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o640)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RecoveryError("deployment lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        failed = validate_scene(config)
        count = verify_artifact(config)
        if args.check_only:
            print(json.dumps({"validated_files": count, "release_id": config.release_id,
                              "failed_transaction": config.failed_transaction}))
            return 0
        if not restart:
            config = Config(**(config.__dict__ | {"timers": tuple(
                unit for unit in failed.get("pre_active_units", []) if unit in TIMERS
            )}))
        journal = Journal(config, failed)
        def interrupted(signum, frame):
            raise RecoveryError(f"recovery interrupted by signal {signum}")
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, interrupted)
        print(json.dumps({"recovery_transaction": journal.payload["transaction_id"],
                          "validated_files": count, "release_id": config.release_id}), flush=True)
        recover(config, journal, Host(config, journal))
        print(json.dumps({"recovered": True, "release_id": config.release_id}), flush=True)
        return 0
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RecoveryError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"recovery_error": type(error).__name__,
                          "reason": str(error) if isinstance(error, RecoveryError) else "invalid local input"}),
              flush=True)
        raise SystemExit(2) from error
