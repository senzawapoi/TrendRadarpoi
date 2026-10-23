"""RG-03: real installer/systemd/SQLite, synthetic archive and business writers.

Only pip/venv setup is simulated on normal paths. Test-local wrappers observe
real snapshot/migration boundaries, route systemctl to uniquely owned units,
and inject the explicitly named failures. This is not RG-04 or provider evidence.
Running Type=oneshot jobs are activating; their active timers, rather than the
interrupted invocation, are restored according to systemctl's is-active result.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
ROLES = ("bot", "worker", "scheduler", "collect-main", "collect-ai", "health", "backup")
TIMED_ROLES = ROLES[2:]
SYSTEMCTL = "/usr/bin/systemctl"
SAFE_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}
pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="requires disposable Linux root and actual systemd",
)


def _config(sandbox: Path) -> dict:
    return json.loads((sandbox / "fixture.json").read_text())


def _event(sandbox: Path, name: str, **fields: object) -> None:
    record = {"event": name, "pid": os.getpid(), "uid": os.getuid(),
              "at": time.monotonic_ns(), **fields}
    fd = os.open(sandbox / "events/events.jsonl", os.O_WRONLY | os.O_APPEND)
    try:
        os.write(fd, (json.dumps(record) + "\n").encode())
    finally:
        os.close(fd)


def _events(sandbox: Path) -> list[dict]:
    return [json.loads(line) for line in (sandbox / "events/events.jsonl").read_text().splitlines()]


def _ctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run([SYSTEMCTL, *args], env=SAFE_ENV, capture_output=True,
                            text=True, timeout=30)
    if check:
        assert result.returncode == 0, " ".join(args) + ": " + result.stderr
    return result


def _properties(unit: str) -> dict[str, str]:
    result = _ctl("show", unit, "--no-pager", "--property=ActiveState,SubState,MainPID,"
                  "ControlPID,PrivateTmp,LastTriggerUSec,NextElapseUSecRealtime")
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def _states(sandbox: Path) -> dict[str, dict[str, str]]:
    return {unit: _properties(unit) for unit in _config(sandbox)["managed"]}


def _probe(database: str | Path) -> dict[str, list[int]]:
    path = Path(database)
    if not path.exists():
        return {}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='quiesce_probe'"
        ).fetchone():
            return {}
        return {role: [starts, writes] for role, starts, writes in connection.execute(
            "SELECT role, starts, writes FROM quiesce_probe ORDER BY role"
        )}


def _boundary(sandbox: Path, name: str, **fields: object) -> None:
    states = _states(sandbox)
    _event(sandbox, name, states=states, probe=_probe(_config(sandbox)["database"]), **fields)
    assert all(state["ActiveState"] == "inactive"
               and state.get("MainPID", "0") == "0"
               and state.get("ControlPID", "0") == "0" for state in states.values()), states


def _wait_for(predicate, *, timeout: float = 30, process=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        if process is not None and process.poll() is not None:
            raise AssertionError(f"installer exited before barrier: {process.returncode}")
        time.sleep(0.05)
    raise AssertionError("timed out waiting for a test-owned event")


def _python_entry(sandbox: Path, args: list[str]) -> int:
    config = _config(sandbox)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.path.insert(0, str(ROOT))
    if args[:2] == ["-m", "venv"]:
        binary = Path(args[2]) / "bin"
        binary.mkdir(parents=True)
        (binary / "python").symlink_to(sandbox / "bin/python3")
        _event(sandbox, "simulated-venv", args=args)
        return 0
    if args[:2] == ["-m", "pip"]:
        _event(sandbox, "simulated-pip", args=args)
        return 0
    if args and args[0] == "-" and args[1:2] == [config["database"]]:
        from trendradar.ops import backup

        original = backup.create_snapshot

        def observed_snapshot(*positional, **keywords):
            _boundary(sandbox, "snapshot-before")
            if config["failure"] == "snapshot":
                raise RuntimeError("test-owned exception before snapshot creation")
            result = original(*positional, **keywords)
            _boundary(sandbox, "snapshot-after", snapshot=result)
            return result

        backup.create_snapshot = observed_snapshot
        sys.argv = ["-", *args[1:]]
        exec(compile(sys.stdin.read(), "<real-installer-snapshot>", "exec"),
             {"__name__": "__main__"})
        return 0
    if args[:2] == ["-m", "trendradar.ops"]:
        from trendradar.ops.__main__ import main

        migration = args[2:4] == ["database", "migrate"]
        if migration:
            _boundary(sandbox, "migration-before", args=args)
        if args[2:3] == ["health"] and config["failure"] == "health-error":
            _event(sandbox, "health-command-exception")
            raise RuntimeError("test-owned health command exception")
        if (args[2:4] == ["maintenance", "finalize-deployment"]
                and config["failure"] == "finalize-heartbeat-race"):
            from trendradar.ops import health

            original_clock = health._utc_now

            def sampled_before_writer():
                sampled = original_clock()
                time.sleep(0.25)  # Actual service writers publish every 100 ms.
                return sampled

            health._utc_now = sampled_before_writer
        if (args[2:4] == ["maintenance", "finalize-deployment"]
                and config["failure"] == "finalize-clock-correction"):
            from trendradar.ops import health

            original_clock = health._utc_now
            health._utc_now = lambda: original_clock() - timedelta(seconds=5)
        if args[2:4] in (["maintenance", "confirm-deployment-rollback"],
                         ["maintenance", "finalize-deployment"]):
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(args[2:])
            name = "rollback-confirmation" if args[3].startswith("confirm-") else "finalize-confirmation"
            _event(sandbox, name, returncode=result, output=output.getvalue())
            if result:
                print(output.getvalue(), end="")
        else:
            result = main(args[2:])
        if (args[2:4] == ["backup", "restore"] and result == 0
                and config.get("expired_restore_lease")):
            marker = Path(os.environ["TRENDRADAR_CONTROL_DIR"]) / "deploy-in-progress.json"
            payload = json.loads(marker.read_text())
            payload["updated_at"] = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
            payload["controller_lease_boottime_ns"] -= 30_000_000_000
            temporary = marker.with_name(f".test-expired-lease-{os.getpid()}")
            temporary.write_text(json.dumps(payload))
            os.replace(temporary, marker)
            _event(sandbox, "restore-controller-lease-expired")
        if migration and result == 0:
            _boundary(sandbox, "migration-after", args=args)
            if config["failure"] == "migration" and "ai_frontier" in args:
                with closing(sqlite3.connect(config["database"])) as connection, connection:
                    connection.execute("UPDATE deployment_marker SET value='candidate-mutation'")
                _event(sandbox, "candidate-data-mutated")
                raise RuntimeError("test-owned exception after both real migrations")
        if args[2:4] == ["backup", "activate"]:
            assert "--deployment-rollback" in args
            _boundary(sandbox, "rollback-after", args=args)
        return result
    os.execve(sys.executable, [sys.executable, "-B", *args], dict(os.environ))
    return 1


def _systemctl_entry(sandbox: Path, args: list[str]) -> int:
    config = _config(sandbox)
    assert args and args[0] in {"daemon-reload", "is-active", "stop", "start"}, args
    if args[0] == "daemon-reload":
        assert len(args) == 1
    else:
        assert args[-1] in config["managed"], args
        assert args[1:-1] in ([], ["--quiet"]), args
    _event(sandbox, "systemctl-before", args=args)
    if config["timer_race"] and args == ["stop", config["timers"]["scheduler"]]:
        _event(sandbox, "timer-stop-barrier")
        _wait_for(lambda: (sandbox / "events/allow-timer-stop").exists())
    result = _ctl(*args, check=False)
    _event(sandbox, "systemctl-after", args=args, returncode=result.returncode)
    if (config["timer_race"] and args == ["stop", config["services"]["health"]]
            and not (sandbox / "events/allow-writer-stop").exists()):
        _event(sandbox, "writer-stop-barrier")
        _wait_for(lambda: (sandbox / "events/allow-writer-stop").exists(), timeout=45)
    return result.returncode


def _writer(sandbox: Path, role: str) -> int:
    config = _config(sandbox)
    sys.path.insert(0, str(ROOT))
    from trendradar.core.heartbeat import RoleHeartbeat

    stop = False

    def stopping(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, stopping)
    database = config["database"]
    with closing(sqlite3.connect(database, timeout=10)) as connection, connection:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("CREATE TABLE IF NOT EXISTS quiesce_probe "
                           "(role TEXT PRIMARY KEY, starts INTEGER, writes INTEGER)")
        connection.execute("INSERT INTO quiesce_probe VALUES (?,1,1) "
                           "ON CONFLICT(role) DO UPDATE SET starts=starts+1,writes=writes+1", (role,))
    heartbeat = RoleHeartbeat(role, database) if role in {"bot", "worker"} else None
    _event(sandbox, "writer-start", role=role, release=os.environ["TRENDRADAR_RELEASE_ID"],
           process_start=Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19])
    while not stop:
        with closing(sqlite3.connect(database, timeout=10)) as connection, connection:
            connection.execute("UPDATE quiesce_probe SET writes=writes+1 WHERE role=?", (role,))
        if heartbeat:
            state = "connected" if role == "bot" else "running"
            if config["failure"] == "readiness" and os.environ["TRENDRADAR_RELEASE_ID"] == "candidate":
                state = "connecting"
            heartbeat.write(state=state, sqlite_synchronous="FULL")
        time.sleep(0.1)
    if heartbeat:
        heartbeat.stop()
    _event(sandbox, "writer-stop", role=role, release=os.environ["TRENDRADAR_RELEASE_ID"])
    return 0


def _helper_main() -> int:
    action, directory, *args = sys.argv[1:]
    sandbox = Path(directory)
    if action == "writer":
        return _writer(sandbox, args[0])
    if action == "start-check":
        config = _config(sandbox)
        if (config["failure"] == "worker" and args == ["worker"]
                and os.environ.get("TRENDRADAR_RELEASE_ID") == "candidate"):
            _event(sandbox, "actual-start-pre-failure", role="worker")
            return 42
        return 0
    if action == "witness":
        _event(sandbox, "witness-fired")
        (sandbox / "events/witness-fired").write_text("actual systemd timer elapsed")
        return 0
    raise AssertionError(action)


class QuiesceScope:
    def __init__(self, sandbox: Path):
        self.sandbox = sandbox
        self.config = _config(sandbox)
        self.process = None

    def update(self, **values):
        self.config.update(values)
        (self.sandbox / "fixture.json").write_text(json.dumps(self.config))

    def start_previous(self, roles=(), timed_roles=()):
        for role in roles:
            _ctl("start", "--no-block", self.config["services"][role])
        _wait_for(lambda: set(roles) <= {event["role"] for event in _events(self.sandbox)
                                      if event["event"] == "writer-start"})
        for role in timed_roles:
            _ctl("start", self.config["timers"][role])
        states = _states(self.sandbox)
        active = [unit for unit in self.config["managed"]
                  if _ctl("is-active", "--quiet", unit, check=False).returncode == 0]
        _event(self.sandbox, "pre-install", states=states, active=active,
               probe=_probe(self.config["database"]))
        return active

    def run(self, *, initial=(), restart=(), first_install=False):
        environment = {
            **SAFE_ENV, **self.config["environment"],
            "PATH": f"{self.sandbox}/bin:{SAFE_ENV['PATH']}",
            "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
            "TRENDRADAR_INITIAL_UNITS": " ".join(initial),
            "TRENDRADAR_RESTART_UNITS": " ".join(restart),
        }
        if first_install:
            assert not (self.sandbox / "current").exists()
        command = ["bash", str(ROOT / "scripts/deploy/install_release.sh"), "candidate",
                   str(self.sandbox / "candidate.tar.gz"), str(self.sandbox / "manifest.json")]
        (self.sandbox / "command.json").write_text(json.dumps(command))
        with (self.sandbox / "installer.stdout").open("w") as stdout, (
            self.sandbox / "installer.stderr"
        ).open("w") as stderr:
            self.process = subprocess.Popen(command, env=environment, stdout=stdout,
                                            stderr=stderr, start_new_session=True)
            if self.config["timer_race"]:
                self._timer_race()
            code = self.process.wait(timeout=120)
        _event(self.sandbox, "installer-exit", returncode=code)
        return code

    def _timer_race(self):
        sandbox = self.sandbox
        _wait_for(lambda: any(event["event"] == "timer-stop-barrier"
                             for event in _events(sandbox)), process=self.process)
        timer = self.config["timers"]["health"]
        timer_file = Path("/run/systemd/system") / timer
        original = timer_file.read_text()
        calendar = (datetime.now(timezone.utc) + timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S UTC")
        timer_file.write_text(original.replace("OnActiveSec=3600", f"OnCalendar={calendar}"))
        witness_timer = Path("/run/systemd/system") / self.config["witness_timer"]
        witness_timer.write_text(_timer_text(self.config["witness_service"], f"OnCalendar={calendar}"))
        _ctl("daemon-reload")
        _ctl("restart", timer)
        _ctl("start", self.config["witness_timer"])
        deadline = _properties(timer)["NextElapseUSecRealtime"]
        assert deadline and deadline == _properties(self.config["witness_timer"])["NextElapseUSecRealtime"]
        _event(sandbox, "timer-armed", calendar=calendar, deadline=deadline)
        (sandbox / "events/allow-timer-stop").touch()
        _wait_for(lambda: any(event["event"] == "writer-stop-barrier"
                             for event in _events(sandbox)), process=self.process)
        assert all(_properties(unit)["ActiveState"] == "inactive"
                   for unit in self.config["timers"].values())
        assert _properties(self.config["services"]["health"])["ActiveState"] == "inactive"
        counts = _probe(self.config["database"])
        _wait_for(lambda: (sandbox / "events/witness-fired").exists(), process=self.process)
        assert _probe(self.config["database"])["health"] == counts["health"]
        assert _properties(timer)["LastTriggerUSec"] in {"", "n/a"}
        assert _properties(self.config["services"]["health"])["ActiveState"] == "inactive"
        _event(sandbox, "timer-suppressed", states=_states(sandbox), probe=_probe(self.config["database"]))
        timer_file.write_text(original)
        _ctl("daemon-reload")
        (sandbox / "events/allow-writer-stop").touch()

    def diagnostic(self) -> str:
        return (self.sandbox / "installer.stdout").read_text() + (self.sandbox / "installer.stderr").read_text()


def _timer_text(service: str, schedule="OnActiveSec=3600") -> str:
    return ("[Unit]\nDescription=Isolated RG-03 timer\n[Timer]\n" + schedule + "\n"
            f"Unit={service}\nAccuracySec=1us\nRandomizedDelaySec=0\nPersistent=false\n")


@pytest.fixture
def quiesce_scope():
    from trendradar.intelligence.storage import IntelligenceStorage

    if Path("/proc/1/comm").read_text().strip() != "systemd":
        pytest.skip("PID 1 is not systemd")
    assert not str(Path(sys.executable).resolve()).startswith(("/tmp/", "/var/tmp/"))
    sandbox = Path(tempfile.mkdtemp(prefix="p7-quiesce-", dir="/var/lib"))
    sandbox.chmod(0o755)
    prefix = f"trendradar-p7-test-{uuid.uuid4().hex}"
    services = {role: f"{prefix}-{role}.service" for role in ROLES}
    timers = {role: f"{prefix}-{role}.timer" for role in TIMED_ROLES}
    # Deliberately interleave the input list; installer must impose timer-first order.
    managed = [services["health"], services["bot"], services["worker"]]
    for role in TIMED_ROLES:
        if role != "health":
            managed.append(services[role])
        managed.append(timers[role])
    witness_service, witness_timer = f"{prefix}-witness.service", f"{prefix}-witness.timer"
    all_units = [*managed, witness_service, witness_timer]
    unit_paths = [Path("/run/systemd/system") / unit for unit in all_units]
    scope = None
    try:
        for name in ("events", "runtime", "control", "health", "locks", "backups", "bin"):
            directory = sandbox / name
            directory.mkdir(mode=0o750)
            os.chown(directory, 65534, 65534)
        log = sandbox / "events/events.jsonl"
        log.touch(mode=0o660)
        os.chown(log, 65534, 65534)
        config_file = sandbox / "config.yaml"
        config_file.write_text("intelligence:\n  enabled: true\n")
        database = sandbox / "runtime/intelligence.db"
        with IntelligenceStorage(database, synchronous="FULL"):
            pass
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("CREATE TABLE deployment_marker (value TEXT)")
            connection.execute("INSERT INTO deployment_marker VALUES ('previous')")
        os.chown(database, 65534, 65534)
        database.chmod(0o600)
        environment = {
            "CONFIG_PATH": str(config_file), "INTELLIGENCE_DB_PATH": str(database),
            "AI_FRONTIER_DB_PATH": str(sandbox / "runtime/ai_frontier.db"),
            "TRENDRADAR_RELEASE_ROOT": str(sandbox / "releases"),
            "TRENDRADAR_CURRENT_LINK": str(sandbox / "current"),
            "TRENDRADAR_RELEASE_ENV": str(sandbox / "release.env"),
            "TRENDRADAR_CONTROL_DIR": str(sandbox / "control"),
            "TRENDRADAR_HEALTH_DIR": str(sandbox / "health"),
            "TRENDRADAR_LOCK_DIR": str(sandbox / "locks"),
            "TRENDRADAR_BACKUP_DIR": str(sandbox / "backups"),
            "TRENDRADAR_SERVICE_USER": "nobody", "TRENDRADAR_SERVICE_GROUP": "nogroup",
            "TRENDRADAR_RELEASE_ID": "previous", "TRENDRADAR_MANAGED_UNITS": " ".join(managed),
            "TRENDRADAR_HEALTH_EXPECTED_ROLES": "bot,worker",
            "INTELLIGENCE_SQLITE_SYNCHRONOUS": "FULL",
            "INTELLIGENCE_HEALTH_REQUIRE_SOURCE_RUNS": "false",
            "INTELLIGENCE_HEALTH_REQUIRE_BACKUP": "false", "TRENDRADAR_DEPLOY_VERIFY_SECONDS": "8",
            "LARK_ENABLED": "false", "TRENDRADAR_RESEARCH_ENABLED": "false",
        }
        config = {"services": services, "timers": timers, "managed": managed,
                  "witness_service": witness_service, "witness_timer": witness_timer,
                  "database": str(database), "environment": environment,
                  "timer_race": False, "failure": ""}
        (sandbox / "fixture.json").write_text(json.dumps(config))
        release = sandbox / "release.env"
        release.write_text("TRENDRADAR_RELEASE_ID=previous\n")
        os.chown(release, 0, 65534)
        release.chmod(0o640)
        common = sandbox / "common.env"
        common.write_text("\n".join(f'{key}="{value}"' for key, value in {
            **environment, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
        }.items()))
        for name, function in (("python3", "_python_entry"), ("systemctl", "_systemctl_entry")):
            executable = sandbox / "bin" / name
            executable.write_text(
                f"#!{sys.executable} -B\nimport runpy,sys\nfrom pathlib import Path\n"
                f"sys.path.insert(0,{str(ROOT)!r})\n"
                "arguments=sys.argv[1:]\n"
                f"helpers=runpy.run_path({str(SELF)!r})\n"
                f"raise SystemExit(helpers[{function!r}](Path({str(sandbox)!r}),arguments))\n"
            )
            executable.chmod(0o755)
        previous = sandbox / "releases/previous/venv/bin"
        previous.mkdir(parents=True)
        (previous / "python").symlink_to(sandbox / "bin/python3")
        (sandbox / "current").symlink_to(previous.parents[1])
        archive = sandbox / "candidate.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            for name in ("requirements.lock", "build-requirements.lock", "pyproject.toml"):
                member = tarfile.TarInfo(f"trendradar-candidate/{name}")
                stream.addfile(member, io.BytesIO(b""))
        (sandbox / "manifest.json").write_text(json.dumps({
            "release_id": "candidate", "git_dirty": False,
            "artifact": {"sha256": hashlib.sha256(archive.read_bytes()).hexdigest()},
        }))
        for role, unit in services.items():
            unit_type = "simple" if role in {"bot", "worker"} else "oneshot"
            text = (
                f"[Unit]\nDescription=Isolated RG-03 {role}\n[Service]\nType={unit_type}\n"
                f"User=65534\nGroup=65534\nWorkingDirectory={sandbox}\n"
                f"EnvironmentFile={common}\nEnvironmentFile={release}\n"
                f"ExecStartPre={sys.executable} -B {SELF} start-check {sandbox} {role}\n"
                f"ExecStart={sys.executable} -B {SELF} writer {sandbox} {role}\n"
                "PrivateTmp=yes\nProtectHome=yes\nProtectSystem=strict\nNoNewPrivileges=yes\n"
                f"ReadWritePaths={sandbox}\nKillMode=control-group\nTimeoutStopSec=15\n"
                "TimeoutStartSec=infinity\nRestart=no\nUMask=0077\n"
            )
            (Path("/run/systemd/system") / unit).write_text(text)
        for role, unit in timers.items():
            (Path("/run/systemd/system") / unit).write_text(_timer_text(services[role]))
        witness_path = Path("/run/systemd/system") / witness_service
        witness_path.write_text(
            "[Unit]\nDescription=Isolated RG-03 deadline witness\n[Service]\nType=oneshot\n"
            f"User=65534\nGroup=65534\nPrivateTmp=yes\n"
            f"EnvironmentFile={common}\n"
            f"ExecStart={sys.executable} -B {SELF} witness {sandbox}\n"
        )
        (Path("/run/systemd/system") / witness_timer).write_text(_timer_text(witness_service))
        verify = subprocess.run(["systemd-analyze", "verify", *map(str, unit_paths)],
                                env=SAFE_ENV, capture_output=True, text=True, timeout=30)
        assert verify.returncode == 0, verify.stderr
        _ctl("daemon-reload")
        scope = QuiesceScope(sandbox)
        yield scope
    finally:
        for name in ("allow-timer-stop", "allow-writer-stop"):
            (sandbox / "events" / name).touch()
        if scope and scope.process and scope.process.poll() is None:
            os.killpg(scope.process.pid, signal.SIGTERM)
            try:
                scope.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(scope.process.pid, signal.SIGKILL)
                scope.process.wait(timeout=5)
        # Stop only our exact names, timers first; retain the fixture evidence.
        cleanup = _ctl("stop", *(unit for unit in all_units if unit.endswith(".timer")),
                       *(unit for unit in all_units if unit.endswith(".service")), check=False)
        states = {unit: _properties(unit) for unit in all_units}
        _event(sandbox, "cleanup", returncode=cleanup.returncode, states=states)
        for path in unit_paths:
            path.unlink(missing_ok=True)
        _ctl("daemon-reload")
        _ctl("reset-failed", *all_units, check=False)
        assert all(state.get("MainPID", "0") == "0" and state.get("ControlPID", "0") == "0"
                   and state["ActiveState"] in {"inactive", "failed"} for state in states.values())
        print(f"RG03 evidence retained: {sandbox}; exact owned units stopped and removed")


def _assert_quiesced(scope: QuiesceScope, *, snapshot=True, migration=True):
    events = _events(scope.sandbox)
    calls = [event["args"] for event in events if event["event"] == "systemctl-before"]
    first_stops = [args[1] for args in calls if args[0] == "stop"][:len(scope.config["managed"])]
    assert set(first_stops) == set(scope.config["managed"])
    first_writer = next(index for index, unit in enumerate(first_stops) if unit.endswith(".service"))
    assert first_writer == len(scope.config["timers"])
    assert all(unit.endswith(".timer") for unit in first_stops[:first_writer])
    names = {event["event"] for event in events}
    assert ("snapshot-after" in names) is snapshot
    assert ("migration-after" in names) is migration
    boundaries = [event for event in events if event["event"] in {
        "snapshot-before", "snapshot-after", "migration-before", "migration-after",
    }]
    assert boundaries
    probes = [event["probe"] for event in boundaries]
    assert all(probe == probes[0] for probe in probes)
    for event in boundaries:
        assert event["uid"] == 65534
        assert all(state["ActiveState"] == "inactive" and state.get("MainPID", "0") == "0"
                   and state.get("ControlPID", "0") == "0" for state in event["states"].values())
    if migration:
        assert len([event for event in boundaries if event["event"] == "migration-after"]) == 2
    starts = [event for event in events if event["event"] == "writer-start"]
    assert all(event["uid"] == 65534 for event in starts)
    pre = next(event for event in events if event["event"] == "pre-install")
    for role, unit in scope.config["services"].items():
        assert pre["states"][unit]["PrivateTmp"] == "yes", role


def _restored(scope: QuiesceScope) -> list[str]:
    return [event["args"][1] for event in _events(scope.sandbox)
            if event["event"] == "systemctl-before" and event["args"][0] == "start"]


@pytest.mark.parametrize("mode", ["all-writers", "mixed", "first-install", "explicit-restart",
                                  "finalize-heartbeat-race", "finalize-clock-correction"])
def test_real_systemd_quiesce_and_exact_successful_restoration(quiesce_scope, mode):
    scope = quiesce_scope
    services, timers = scope.config["services"], scope.config["timers"]
    initial = [services["bot"], services["worker"], timers["backup"]]
    restart = []
    if mode in {"finalize-heartbeat-race", "finalize-clock-correction"}:
        scope.update(failure=mode)
    if mode == "all-writers":
        scope.update(timer_race=True)
        active = scope.start_previous(ROLES, TIMED_ROLES)
        pre = next(event for event in _events(scope.sandbox) if event["event"] == "pre-install")
        assert set(pre["probe"]) == set(ROLES)
        assert all(writes > 0 for _, writes in pre["probe"].values())
        for role in TIMED_ROLES:
            assert pre["states"][services[role]]["ActiveState"] == "activating"
            assert int(pre["states"][services[role]]["MainPID"]) > 0
    elif mode == "first-install":
        (scope.sandbox / "current").unlink()
        Path(scope.config["database"]).unlink()
        active = scope.start_previous()
    else:
        active = scope.start_previous(("bot", "worker", "scheduler"), ("scheduler", "health"))
        if mode == "explicit-restart":
            restart = [services["bot"], services["worker"], timers["backup"]]
    expected = restart or (initial if mode == "first-install" else active)
    code = scope.run(initial=initial, restart=restart, first_install=mode == "first-install")
    assert code == 0, scope.diagnostic()
    _assert_quiesced(scope, snapshot=mode != "first-install")
    assert _restored(scope) == expected
    for unit in scope.config["managed"]:
        assert _properties(unit)["ActiveState"] == ("active" if unit in expected else "inactive")
    assert not (scope.sandbox / "control/deploy-in-progress.json").exists()
    assert not (scope.sandbox / "control/restore-guard.json").exists()
    if mode == "all-writers":
        names = {event["event"] for event in _events(scope.sandbox)}
        assert {"timer-armed", "witness-fired", "timer-suppressed"} <= names


def test_inactive_upgrade_does_not_fall_back_to_initial_units(quiesce_scope):
    scope = quiesce_scope
    scope.update(failure="readiness")
    scope.start_previous()
    code = scope.run(initial=[scope.config["services"][role] for role in ("bot", "worker")])
    assert code != 0
    _assert_quiesced(scope)
    assert _restored(scope) == []
    assert all(state["ActiveState"] == "inactive" for state in _states(scope.sandbox).values())
    assert (scope.sandbox / "control/restore-guard.json").is_file()


@pytest.mark.parametrize("failure", ["worker", "readiness", "health-error"])
def test_real_service_or_health_failure_stops_resumed_roles_and_retains_guard(quiesce_scope, failure):
    scope = quiesce_scope
    scope.update(failure=failure)
    active = scope.start_previous(("bot", "worker"), ("scheduler", "backup"))
    code = scope.run()
    assert code != 0
    _assert_quiesced(scope)
    restored = _restored(scope)
    assert restored == (active[:2] if failure == "worker" else active)
    assert all(state["ActiveState"] in {"inactive", "failed"} and state.get("MainPID", "0") == "0"
               and state.get("ControlPID", "0") == "0" for state in _states(scope.sandbox).values())
    marker = json.loads((scope.sandbox / "control/deploy-in-progress.json").read_text())
    assert marker["business_boundary_crossed"] is True
    assert marker["new_release_id"] == "candidate"
    assert (scope.sandbox / "current").resolve() == scope.sandbox / "releases/candidate"
    assert (scope.sandbox / "control/restore-guard.json").is_file()
    events = _events(scope.sandbox)
    assert any(event["event"] == "writer-start" and event["role"] == "bot"
               and event["release"] == "candidate" for event in events)
    last_start = max(event["at"] for event in events if event["event"] == "systemctl-before"
                     and event["args"][0] == "start")
    assert {event["args"][1] for event in events if event["event"] == "systemctl-after"
            and event["args"][0] == "stop" and event["at"] > last_start} == set(scope.config["managed"])
    if failure == "worker":
        assert any(event["event"] == "actual-start-pre-failure" for event in events)
    if failure == "health-error":
        assert any(event["event"] == "health-command-exception" for event in events)


def test_exception_before_snapshot_restores_only_previous_active_units(quiesce_scope):
    scope = quiesce_scope
    scope.update(failure="snapshot")
    active = scope.start_previous(("bot", "worker", "scheduler"), ("scheduler",))
    code = scope.run(initial=[scope.config["timers"]["backup"]])
    assert code != 0
    _assert_quiesced(scope, snapshot=False, migration=False)
    assert _restored(scope) == active
    assert not list((scope.sandbox / "backups").glob("*/manifest.json"))
    assert (scope.sandbox / "current").resolve() == scope.sandbox / "releases/previous"
    assert (scope.sandbox / "release.env").read_text() == "TRENDRADAR_RELEASE_ID=previous\n"
    assert not (scope.sandbox / "control/deploy-in-progress.json").exists()
    assert not (scope.sandbox / "control/restore-guard.json").exists()
    for unit in scope.config["managed"]:
        assert _properties(unit)["ActiveState"] == ("active" if unit in active else "inactive")


@pytest.mark.parametrize("expired_restore_lease", [False, True])
def test_snapshot_backed_rollback_keeps_real_writers_stopped_and_restores_active_units(
    quiesce_scope, expired_restore_lease,
):
    scope = quiesce_scope
    scope.update(failure="migration", expired_restore_lease=expired_restore_lease)
    active = scope.start_previous(("bot", "worker", "scheduler"), ("scheduler", "collect-ai"))
    code = scope.run(initial=[scope.config["timers"]["backup"]])
    assert code != 0
    _assert_quiesced(scope)
    events = _events(scope.sandbox)
    assert any(event["event"] == "candidate-data-mutated" for event in events)
    rollback, = (event for event in events if event["event"] == "rollback-after")
    assert rollback["uid"] == 65534
    assert all(state["ActiveState"] == "inactive" for state in rollback["states"].values())
    confirmation, = (event for event in events if event["event"] == "rollback-confirmation")
    assert confirmation["uid"] == 65534 and confirmation["returncode"] == 0, confirmation
    assert sum(event["event"] == "restore-controller-lease-expired" for event in events) == (
        1 if expired_restore_lease else 0
    )
    snapshot, = (event["snapshot"] for event in events if event["event"] == "snapshot-after")
    entry, = (entry for entry in snapshot["databases"] if entry["relative_path"] == "intelligence.db")
    assert rollback["probe"] == _probe(Path(snapshot["path"]) / entry["file"])
    with closing(sqlite3.connect(scope.config["database"])) as connection:
        assert connection.execute("SELECT value FROM deployment_marker").fetchone() == ("previous",)
    assert not Path(scope.config["environment"]["AI_FRONTIER_DB_PATH"]).exists()
    assert (scope.sandbox / "current").resolve() == scope.sandbox / "releases/previous"
    assert (scope.sandbox / "release.env").read_text() == "TRENDRADAR_RELEASE_ID=previous\n"
    assert _restored(scope) == active, [
        event for event in _events(scope.sandbox) if event["event"] == "rollback-confirmation"
    ]
    assert not (scope.sandbox / "control/deploy-in-progress.json").exists()
    assert not (scope.sandbox / "control/restore-guard.json").exists()
    for unit in scope.config["managed"]:
        assert _properties(unit)["ActiveState"] == ("active" if unit in active else "inactive")


if __name__ == "__main__":
    raise SystemExit(_helper_main())
