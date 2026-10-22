"""Run the real installer; simulated installation is not artifact evidence."""

import json
import os
import selectors
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from trendradar.ops.maintenance import read_guard

from .installer_harness import ROOT, make_installer

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="requires Linux Bash and root in a disposable test scope",
)


def run_installer(command, environment):
    return subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60)


def unit_commands(tmp_path):
    return [json.loads(line) for line in (tmp_path / "systemctl.jsonl").read_text().splitlines()]


def seed_probe(database, value):
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE deployment_probe (value TEXT NOT NULL)")
        connection.execute("INSERT INTO deployment_probe VALUES (?)", (value,))


def probe(database):
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        return (connection.execute("PRAGMA user_version").fetchone()[0],
                connection.execute("SELECT value FROM deployment_probe").fetchone()[0])


def inject_fault(tmp_path, command, point, action, *, mutate_ai=False):
    script = (ROOT / "scripts/deploy/install_release.sh").read_text()
    anchors = {
        "quiesce": ('write_state snapshot\nif [[ -f "$database" ]]; then', False),
        "snapshot": ("write_state migrate", False),
        "migrate": ("write_state switch", False),
        "switch": ("write_state pre_resume", False),
        "before-clear": ('if [[ "${guard_owned:-false}" == true ]]; then', False),
        "after-clear": ('  guard_owned=false', True),
        "first-start": ('  systemctl start "$unit" || fail "could not start $unit"', True),
        "verify": ('  if [[ -z "${TRENDRADAR_SKIP_READINESS:-}" ]]', False),
        "finalize": ('    write_state finalize', True),
    }
    anchor, after = anchors[point]
    assert script.count(anchor) == 1, (point, anchor)
    hook = ("python3 -c 'raise RuntimeError(\"test-owned ordinary exception\")'\n"
            if action == "exception" else "printf 'FAULT-REACHED\\n'\nkill -STOP $$\n")
    if mutate_ai:
        hook = '''python3 - "$ai_database" <<'TESTPY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as connection:
    connection.execute("UPDATE deployment_probe SET value='candidate-ai'")
TESTPY
''' + hook
    script = script.replace(anchor, anchor + "\n" + hook if after else hook + anchor, 1)
    injected = tmp_path / "injected-installer.sh"
    injected.write_text(script, encoding="utf-8")
    return [command[0], str(injected), *command[2:]]


def interrupt_installer(command, environment, signum):
    process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    output = b""
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 60
            while b"FAULT-REACHED\n" not in output and time.monotonic() < deadline:
                if selector.select(timeout=1):
                    chunk = os.read(process.stdout.fileno(), 65536)
                    output += chunk
                    if not chunk:
                        break
            assert b"FAULT-REACHED\n" in output, output.decode()
        if signum == signal.SIGKILL:
            os.killpg(process.pid, signum)
        else:
            os.kill(process.pid, signum)
            os.kill(process.pid, signal.SIGCONT)
        remainder, _ = process.communicate(timeout=30)
        output += remainder
        return process.returncode, process.pid, output.decode()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        process.stdout.close()


def assert_restart_protected(environment, database):
    # A fresh process simulates automatic restart and exercises real entry guards.
    child_environment = environment | {
        "TRENDRADAR_RELEASE_ID": "candidate", "LARK_ENABLED": "true",
        "INTELLIGENCE_ENABLED": "true", "LARK_APP_ID": "fixture-app",
        "LARK_APP_SECRET": "fixture-only", "LARK_BOT_ID": "fixture-bot",
        "LARK_IDENTITY_FIELDS": '{"open_id":["fixture-owner"]}',
    }
    script = '''
import json, sys
from trendradar import __main__ as collector
from trendradar.ai_frontier import __main__ as frontier
from trendradar.integrations.feishu import __main__ as runner
from trendradar.ops.maintenance import read_guard
calls=[]
def unexpected(*args, **kwargs):
    calls.append(True)
    raise AssertionError("protected restart attempted business I/O")
runner.FeishuClient.from_credentials=unexpected
runner.run_bot=unexpected
runner.run_bot_role=unexpected
runner.run_worker_role=unexpected
runner.run_scheduler_once=unexpected
collector._run_main=unexpected
frontier._run=unexpected
assert read_guard(sys.argv[1]) is not None
for role in ("combined", "bot", "worker", "scheduler-once"):
    assert runner.main(["--config", sys.argv[2], "--role", role]) == 1
assert collector.main() is False
sys.argv=["frontier", "--config", sys.argv[2]]
assert frontier.main() == 0
assert not calls
print("RESTART-PROTECTED")
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, str(database),
                             environment["CONFIG_PATH"]], env=child_environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESTART-PROTECTED" in result.stdout


def assert_restart_accepting(environment, database):
    # Exercise actual main/guard checks, replacing only clients and business loops.
    child_environment = environment | {
        "LARK_ENABLED": "true", "INTELLIGENCE_ENABLED": "true",
        "LARK_APP_ID": "fixture-app", "LARK_APP_SECRET": "fixture-only",
        "LARK_BOT_ID": "fixture-bot",
        "LARK_IDENTITY_FIELDS": '{"open_id":["fixture-owner"]}',
        "GEMINI_ENABLED": "false",
    }
    script = '''
import sys
from trendradar import __main__ as collector
from trendradar.ai_frontier import __main__ as frontier
from trendradar.integrations.feishu import __main__ as runner
from trendradar.ops.maintenance import read_guard
calls=[]
def collect():
    calls.append("collector")
    return True
async def frontier_run(config):
    calls.append("frontier")
    return 0
async def combined(*args):
    calls.append("combined")
async def bot(*args):
    calls.append("bot")
def worker(*args):
    calls.append("worker")
def scheduler(*args):
    calls.append("scheduler-once")
    return "fixture-completed"
class Client:
    available=True
client_calls=[]
def client(*args, **kwargs):
    client_calls.append(True)
    return Client()
database,config=sys.argv[1:]
assert read_guard(database) is None
collector._run_main=collect
frontier._run=frontier_run
runner.FeishuClient.from_credentials=client
runner.run_bot=combined
runner.run_bot_role=bot
runner.run_worker_role=worker
runner.run_scheduler_once=scheduler
assert collector.main() is True
sys.argv=["frontier", "--config", config]
assert frontier.main() == 0
for role in ("combined", "bot", "worker", "scheduler-once"):
    assert runner.main(["--config", config, "--role", role]) == 0
assert calls == ["collector", "frontier", "combined", "bot", "worker", "scheduler-once"]
assert len(client_calls) == 4
print("RESTART-ACCEPTING")
'''
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(database), environment["CONFIG_PATH"]],
        env=child_environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESTART-ACCEPTING" in result.stdout


def test_installer_success_with_real_health_and_configured_paths(tmp_path):
    command, environment, database = make_installer(tmp_path, ai_present=True)
    ai = Path(environment["AI_FRONTIER_DB_PATH"])
    seed_probe(database, "before-deploy")
    seed_probe(ai, "ai-before-deploy")
    before = {path: probe(path) for path in (database, ai)}
    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "control/deploy-in-progress.json").exists()
    assert (tmp_path / "current").resolve() == tmp_path / "releases/candidate"
    assert (tmp_path / "etc/release.env").read_text().strip() == "TRENDRADAR_RELEASE_ID=candidate"
    assert not (database.parent / "health").exists()
    assert (tmp_path / "health/bot.json").is_file()
    commands = [json.loads(line) for line in (tmp_path / "systemctl.jsonl").read_text().splitlines()]
    stops = [entry[1] for entry in commands if entry[0] == "stop"]
    assert stops.index("test-scheduler.timer") < stops.index("test-scheduler.service")
    starts = [entry[1] for entry in commands if entry[0] == "start"]
    assert starts == ["test-bot.service", "test-worker.service"]
    assert {path: probe(path) for path in before} == before
    assert_restart_accepting(environment | {"TRENDRADAR_RELEASE_ID": "candidate"}, database)


def test_fixed_entry_loads_common_and_clears_caller_environment():
    # /var/lib has trusted root-owned ancestors; /tmp deliberately does not.
    sandbox = Path(tempfile.mkdtemp(prefix="trendradar-p7-entry-", dir="/var/lib"))
    try:
        command, environment, database = make_installer(sandbox)
        installer = sandbox / "installer.sh"
        installer.write_text((ROOT / "scripts/deploy/install_release.sh").read_text())
        installer.chmod(0o750)
        common = sandbox / "common.env"
        common.write_text("\n".join(
            f'{key}="{value}"' for key, value in environment.items()
            if key not in {"PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"}
            and not key.startswith("TEST_")
        ))
        common.chmod(0o640)
        loader = sandbox / "loader.py"
        # The isolated copy uses fake executables in its trusted PATH. Parsing,
        # caller cleanup, input validation and installer execution are real.
        loader.write_text((ROOT / "scripts/deploy/load_environment.py").read_text().replace(
            '"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"', f'"PATH": {environment["PATH"]!r}',
        ))
        entry = sandbox / "entry"
        entry.write_text((ROOT / "deploy/bin/trendradar-install-release").read_text()
                         .replace("/usr/local/libexec/trendradar/install_release.sh", str(installer))
                         .replace("/usr/local/libexec/trendradar/load_environment.py", str(loader))
                         .replace("/etc/trendradar/common.env", str(common)))
        entry.chmod(0o750)
        result = subprocess.run([str(entry), *command[2:]], env={
            "PATH": "/usr/bin:/bin", "INTELLIGENCE_DB_PATH": "/should-not-be-used.db",
            "PYTHONPATH": "/malicious-caller", "TRENDRADAR_ALLOW_DIRTY_RELEASE": "true",
        }, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        assert database.is_file()
        assert not (sandbox / "control/deploy-in-progress.json").exists()
        assert (sandbox / "health/bot.json").is_file()
        assert not (database.parent / "health").exists()
        # Invalid common config must fail before even creating an archive record.
        common.write_text("CONFIG_PATH=relative;value\n")
        invalid = subprocess.run([str(entry), *command[2:]], capture_output=True, text=True)
        assert invalid.returncode == 2
        assert "invalid or missing trusted production configuration" in invalid.stderr
    finally:
        shutil.rmtree(sandbox)


@pytest.mark.parametrize("failure", ["worker", "readiness", "health-error"])
def test_installer_post_boundary_failure_stops_roles_and_retains_guard(tmp_path, monkeypatch, failure):
    command, environment, database = make_installer(tmp_path, failure=failure, business_write=True)
    seed_probe(database, "before-deploy")
    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", environment["TRENDRADAR_CONTROL_DIR"])
    assert read_guard(database) is not None
    marker = json.loads((tmp_path / "control/deploy-in-progress.json").read_text())
    assert marker["business_boundary_crossed"] is True
    if failure in {"readiness", "health-error"}:
        assert marker["state"] == "failed:readiness"
        events = [json.loads(line) for line in (tmp_path / "operations.jsonl").read_text().splitlines()]
        assert any(event["args"][2:3] == ["health"] for event in events)
    commands = [json.loads(line) for line in (tmp_path / "systemctl.jsonl").read_text().splitlines()]
    last_start = max(i for i, entry in enumerate(commands) if entry[0] == "start")
    assert ["stop", "test-bot.service"] in commands[last_start:]
    assert (tmp_path / "current").resolve() == tmp_path / "releases/candidate"
    assert probe(database) == (6, "candidate-work")
    assert json.loads((tmp_path / "units.json").read_text()) == []
    assert_restart_protected(environment, database)


@pytest.mark.parametrize("point", ["before-clear", "after-clear", "first-start", "verify", "finalize"])
@pytest.mark.parametrize("action", ["sigkill", "sigterm", "exception"])
def test_installer_interruption_preserves_protection(tmp_path, monkeypatch, point, action):
    finalize_killed = point == "finalize" and action == "sigkill"
    command, environment, database = make_installer(tmp_path, ai_present=finalize_killed)
    before_finalize = None
    if finalize_killed:
        ai = Path(environment["AI_FRONTIER_DB_PATH"])
        seed_probe(database, "before-finalize")
        seed_probe(ai, "ai-before-finalize")
        before_finalize = {path: probe(path) for path in (database, ai)}
    command = inject_fault(tmp_path, command, point, action)
    if action == "exception":
        result = run_installer(command, environment)
        assert result.returncode != 0, result.stdout + result.stderr
        pid = None
    else:
        code, pid, output = interrupt_installer(
            command, environment, signal.SIGKILL if action == "sigkill" else signal.SIGTERM)
        assert code != 0, output
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", environment["TRENDRADAR_CONTROL_DIR"])
    assert read_guard(database) is not None
    from trendradar.ops.maintenance import main
    assert main(["clear", "--database", str(database)]) == 2
    marker = json.loads((tmp_path / "control/deploy-in-progress.json").read_text())
    if pid:
        assert marker["controller_pid"] == pid
    assert marker["business_boundary_crossed"] is True
    assert marker["new_release_id"] == "candidate"
    assert marker["old_target"] == str(tmp_path / "releases/previous")
    assert (tmp_path / "backups" / marker["snapshot_id"] / "manifest.json").is_file()
    assert (tmp_path / "current").resolve() == tmp_path / "releases/candidate"
    assert_restart_protected(environment, database)
    if action != "sigkill":
        assert json.loads((tmp_path / "units.json").read_text()) == []
    if finalize_killed:
        assert {path: probe(path) for path in before_finalize} == before_finalize
        target_before = (tmp_path / "current").resolve()
        identity_before = (tmp_path / "etc/release.env").read_bytes()
        environment["TRENDRADAR_RELEASE_ID"] = "candidate"
        confirmed = subprocess.run([
            sys.executable, "-B", "-m", "trendradar.ops", "maintenance",
            "finalize-deployment", "--database", str(database),
        ], env=environment, capture_output=True, text=True, timeout=30)
        assert confirmed.returncode == 0, confirmed.stdout + confirmed.stderr
        assert not (tmp_path / "control/deploy-in-progress.json").exists()
        assert {path: probe(path) for path in before_finalize} == before_finalize
        assert (tmp_path / "current").resolve() == target_before
        assert (tmp_path / "etc/release.env").read_bytes() == identity_before
        assert_restart_accepting(environment, database)


@pytest.mark.parametrize("first_install,active,initial,expected", [
    (False, ["test-bot.service", "test-worker.service"], "test-health.timer",
     ["test-bot.service", "test-worker.service"]),
    (False, [], "test-bot.service test-worker.service", []),
    (True, [], "test-bot.service test-worker.service", ["test-bot.service", "test-worker.service"]),
])
def test_only_previously_active_or_first_install_initial_units_resume(
        tmp_path, first_install, active, initial, expected):
    command, environment, _ = make_installer(tmp_path, first_install=first_install,
                                              active_units=active)
    environment["TRENDRADAR_INITIAL_UNITS"] = initial
    result = run_installer(command, environment)
    assert [entry[1] for entry in unit_commands(tmp_path) if entry[0] == "start"] == expected
    if expected:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        # An intentionally inactive upgrade still has to satisfy real readiness.
        assert result.returncode != 0
        assert (tmp_path / "control/deploy-in-progress.json").is_file()


@pytest.mark.parametrize("rollback", [False, True])
def test_all_timers_stop_before_writers_and_snapshot_migration(tmp_path, rollback):
    roles = ["bot", "worker", "scheduler", "collect-main", "collect-ai", "health", "backup"]
    units = [f"test-{role}.service" for role in roles]
    units += [f"test-{role}.timer" for role in roles[2:]]
    active = [unit for unit in units if unit != "test-health.service"]
    command, environment, _ = make_installer(tmp_path, active_units=active)
    environment["TRENDRADAR_MANAGED_UNITS"] = " ".join(units)
    if rollback:
        command = inject_fault(tmp_path, command, "migrate", "exception")
    result = run_installer(command, environment)
    assert (result.returncode != 0) is rollback, result.stdout + result.stderr
    commands = unit_commands(tmp_path)
    assert any(entry[0] == "timer-suppressed" for entry in commands)
    assert not any(entry[0] == "timer-fired" for entry in commands)
    stops = [entry[1] for entry in commands if entry[0] == "stop"]
    for offset in range(0, len(stops), len(units)):
        batch = stops[offset:offset + len(units)]
        assert set(batch) == set(units)
        assert all(unit.endswith(".timer") for unit in batch[:5])
    assert [entry[1] for entry in commands if entry[0] == "start"] == active
    events = [json.loads(line) for line in (tmp_path / "operations.jsonl").read_text().splitlines()]
    migrations = [event for event in events if event["args"][2:4] == ["database", "migrate"]]
    assert len(migrations) == 2
    snapshots = [event for event in events if event["args"][2:4] == ["backup", "create"]
                 or (event["args"][0:1] == ["-"] and len(event["args"]) == 5)]
    assert snapshots
    assert all(not event["active"] for event in migrations + snapshots)


@pytest.mark.parametrize("point", ["quiesce", "snapshot", "migrate", "switch"])
@pytest.mark.parametrize("action", ["exception", "sigterm"])
def test_pre_boundary_failure_restores_code_data_identity_and_units(tmp_path, point, action):
    command, environment, database = make_installer(tmp_path, ai_present=True)
    ai = Path(environment["AI_FRONTIER_DB_PATH"])
    legacy = database.parent / "news/2026-10-01.db"
    legacy.parent.mkdir()
    for path, value in ((database, "intelligence-before"), (ai, "ai-before"), (legacy, "legacy-before")):
        seed_probe(path, value)
    before = {path: probe(path) for path in (database, ai, legacy)}
    command = inject_fault(tmp_path, command, point, action)
    if action == "exception":
        result = run_installer(command, environment)
        assert result.returncode != 0
    else:
        code, _, output = interrupt_installer(command, environment, signal.SIGTERM)
        assert code != 0, output
    assert (tmp_path / "current").resolve() == tmp_path / "releases/previous"
    assert (tmp_path / "etc/release.env").read_text().strip() == "TRENDRADAR_RELEASE_ID=previous"
    assert {path: probe(path) for path in before} == before
    assert not (tmp_path / "control/deploy-in-progress.json").exists()
    assert not (tmp_path / "control/restore-guard.json").exists()
    assert set(json.loads((tmp_path / "units.json").read_text())) == {
        "test-bot.service", "test-worker.service"}


@pytest.mark.parametrize("case", ["old-schema", "ai-absent", "ai-external", "cutover"])
def test_pre_boundary_rollback_restores_complete_previous_state(tmp_path, case):
    command, environment, database = make_installer(
        tmp_path, old_schema=5 if case == "old-schema" else 6,
        ai_present=case != "ai-absent", ai_external=case == "ai-external")
    ai = Path(environment["AI_FRONTIER_DB_PATH"])
    seed_probe(database, "intelligence-before")
    if ai.exists():
        seed_probe(ai, "ai-before")
    cutover = tmp_path / "control/recovery-cutover.json"
    previous_cutover = b'{"recovery_cutover_at":"2026-08-01T00:00:00+00:00"}\n'
    if case == "cutover":
        cutover.parent.mkdir()
        cutover.write_bytes(previous_cutover)
    command = inject_fault(tmp_path, command, "switch", "exception", mutate_ai=case == "ai-external")
    result = run_installer(command, environment)
    assert result.returncode != 0
    assert (tmp_path / "current").resolve() == tmp_path / "releases/previous"
    assert probe(database) == (5 if case == "old-schema" else 6, "intelligence-before")
    if case == "ai-absent":
        assert not ai.exists(), "deployment-created AI database must be removed by journaled rollback"
        assert not Path(str(ai) + "-wal").exists()
        assert not Path(str(ai) + "-shm").exists()
    else:
        assert probe(ai)[1] == "ai-before"
    assert not (tmp_path / "control/deploy-in-progress.json").exists()
    assert not (tmp_path / "control/restore-guard.json").exists()
    if case == "cutover":
        assert cutover.read_bytes() == previous_cutover
    else:
        assert not cutover.exists(), "a pre-business deployment rollback must not set a new cutoff"
    assert_restart_accepting(environment, database)


@pytest.mark.parametrize("operation", ["enter", "persist-cutover", "clear"])
@pytest.mark.parametrize("fail_sync", [False, True])
def test_control_marker_directory_durability(tmp_path, monkeypatch, operation, fail_sync):
    from trendradar.ops import maintenance

    database = tmp_path / "intelligence.db"
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", str(tmp_path / "control"))
    if operation != "enter":
        maintenance.set_guard(database, reason="fixture", recovery_cutover_at=(
            "2026-08-01T00:00:00+00:00" if operation == "persist-cutover" else None))
    real_sync = os.fsync
    calls = []

    def sync(descriptor):
        directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
        calls.append("directory" if directory else "file")
        if directory and fail_sync:
            raise OSError("test-owned directory fsync failure")
        real_sync(descriptor)

    monkeypatch.setattr(maintenance.os, "fsync", sync)
    action = (lambda: maintenance.set_guard(database, reason="fixture")) if operation == "enter" \
        else lambda: maintenance.clear_guard(database)
    if fail_sync:
        with pytest.raises(OSError, match="test-owned directory fsync"):
            action()
        assert maintenance.guard_path(database).is_file(), "failed clear must remain protected"
    else:
        action()
    assert "directory" in calls
    if operation != "clear":
        assert calls.index("file") < calls.index("directory")


@pytest.mark.parametrize("fault", ["release", "current", "heartbeat", "unfinished", "dir-fsync"])
def test_finalize_reconfirmation_rejects_mismatch_and_retains_marker(tmp_path, monkeypatch, fault):
    from trendradar.ops import maintenance

    command, environment, database = make_installer(tmp_path)
    command = inject_fault(tmp_path, command, "finalize", "sigkill")
    code, _, output = interrupt_installer(command, environment, signal.SIGKILL)
    assert code != 0, output
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("TRENDRADAR_RELEASE_ID", "candidate")
    marker = tmp_path / "control/deploy-in-progress.json"
    original = marker.read_bytes()
    if fault == "release":
        monkeypatch.setenv("TRENDRADAR_RELEASE_ID", "previous")
    elif fault == "current":
        current = tmp_path / "current"
        current.unlink()
        current.symlink_to(tmp_path / "releases/previous")
    elif fault == "heartbeat":
        heartbeat = tmp_path / "health/bot.json"
        payload = json.loads(heartbeat.read_text())
        payload["state"] = "connecting"
        heartbeat.write_text(json.dumps(payload), encoding="utf-8")
    elif fault == "unfinished":
        payload = json.loads(original)
        payload["state"] = "verify"
        marker.write_text(json.dumps(payload), encoding="utf-8")
    else:
        real_sync = os.fsync

        def sync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("test-owned directory fsync failure")
            real_sync(descriptor)

        monkeypatch.setattr(maintenance.os, "fsync", sync)
    with pytest.raises((RuntimeError, OSError)):
        maintenance.finalize_deployment(database)
    assert marker.is_file()
    assert maintenance.read_guard(database) is not None
    if fault == "dir-fsync":
        assert marker.read_bytes() == original


@pytest.mark.parametrize("build_lock", [False, True])
def test_installer_requires_build_lock_and_uses_both_locks_without_build_isolation(tmp_path, build_lock):
    command, environment, database = make_installer(tmp_path, build_lock=build_lock)
    seed_probe(database, "before-deploy")
    result = run_installer(command, environment)
    if not build_lock:
        assert result.returncode != 0
        assert "build-requirements.lock" in result.stderr
        assert probe(database) == (6, "before-deploy")
        assert (tmp_path / "current").resolve() == tmp_path / "releases/previous"
        assert not (tmp_path / "systemctl.jsonl").exists()
        return
    assert result.returncode == 0, result.stdout + result.stderr
    events = [json.loads(line) for line in (tmp_path / "operations.jsonl").read_text().splitlines()]
    installs = [event["args"] for event in events if event["args"][:2] == ["-m", "pip"]]
    assert len(installs) == 3
    candidate = tmp_path / "releases/candidate"
    assert installs[0][-2:] == ["--requirement", str(candidate / "build-requirements.lock")]
    assert installs[1][-2:] == ["--requirement", str(candidate / "requirements.lock")]
    assert installs[2][-3:] == ["--no-build-isolation", "--no-deps", str(candidate)]
    assert all("--upgrade" not in args and "--no-cache-dir" in args for args in installs)


@pytest.mark.parametrize("fault", [None, "boundary-missing", "boundary-unknown", "boundary-integer",
                                  "schema", "absent-ai", "snapshot-root", "pending-restore",
                                  "marker-sync", "guard-sync"])
def test_rollback_confirmation_uses_snapshot_schema_and_keeps_failed_confirmation_protected(
        tmp_path, monkeypatch, fault):
    from trendradar.ops import maintenance
    from trendradar.ops.backup import create_snapshot

    _, environment, database = make_installer(tmp_path, old_schema=5)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    ai = Path(environment["AI_FRONTIER_DB_PATH"])
    seed_probe(database, "previous-schema-five")
    snapshot = create_snapshot([database], environment["TRENDRADAR_BACKUP_DIR"],
                               root=database.parent, release_id="previous",
                               target_mapping=[database, ai])
    maintenance.set_guard(database, reason="fixture deployment rollback")
    marker = tmp_path / "control/deploy-in-progress.json"
    payload = {
        "state": "rollback_complete", "business_boundary_crossed": False,
        "old_target": str(tmp_path / "releases/previous"),
        "current_link": str(tmp_path / "current"),
        "snapshot_id": snapshot["backup_id"], "snapshot_root": str(database.parent),
    }
    if fault == "boundary-missing":
        del payload["business_boundary_crossed"]
    elif fault == "boundary-unknown":
        payload["business_boundary_crossed"] = None
    elif fault == "boundary-integer":
        payload["business_boundary_crossed"] = 0
    elif fault == "schema":
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA user_version=6")
    elif fault == "absent-ai":
        seed_probe(ai, "unexpected-candidate-database")
    elif fault == "snapshot-root":
        payload["snapshot_root"] = str(tmp_path)
    elif fault == "pending-restore":
        (marker.parent / "restore-activation-pending.json").write_text(
            '{"state":"prepared"}', encoding="utf-8")
    elif fault in {"marker-sync", "guard-sync"}:
        real_sync = maintenance._sync_directory
        calls = 0

        def sync(path):
            nonlocal calls
            calls += 1
            if calls == (1 if fault == "marker-sync" else 2):
                raise OSError("test-owned confirmation fsync failure")
            real_sync(path)

        monkeypatch.setattr(maintenance, "_sync_directory", sync)
    marker.write_text(json.dumps(payload), encoding="utf-8")
    if fault is None:
        assert maintenance.confirm_deployment_rollback(database) == {"rolled_back": True}
        assert not marker.exists()
        assert maintenance.read_guard(database) is None
        assert probe(database) == (5, "previous-schema-five")
    else:
        with pytest.raises((RuntimeError, OSError)):
            maintenance.confirm_deployment_rollback(database)
        assert marker.is_file()
        assert maintenance.guard_path(database).is_file()
        assert maintenance.read_guard(database) is not None
