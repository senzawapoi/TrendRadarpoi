"""Isolated collector concurrency tests; no providers or live database."""
import errno
import subprocess
import sys
import time
from pathlib import Path

import pytest

from trendradar.core import locking

ROOT = Path(__file__).resolve().parents[2]


class Clock:
    def __init__(self):
        self.now, self.sleeps = 0., []

    def __call__(self):
        return self.now

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


class Lock:
    def __init__(self, path):
        self.calls = self.releases = self.failures = 0
        self.error = errno.EAGAIN

    def acquire(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise locking.LockUnavailable("busy") from OSError(self.error, "fixture")

    def release(self):
        self.releases += 1


def slot(tmp_path, lock, clock, **kwargs):
    return locking.collector_slot(tmp_path / "db", clock=clock, sleep=clock.sleep,
                                  lock_factory=lambda path: lock, **kwargs)


def test_wait_then_run_once(tmp_path):
    clock, lock = Clock(), Lock(None)
    lock.failures = 2
    calls = []
    with slot(tmp_path, lock, clock, wait_seconds=3) as attempt:
        calls.append(True)
        assert attempt.wait_seconds == 2
    assert calls == [True] and lock.calls == 3 and lock.releases == 1
    assert clock.sleeps == [1, 1]


def test_timeout_bounded_sleep(tmp_path):
    clock, lock = Clock(), Lock(None)
    lock.failures = 99
    with pytest.raises(locking.LockUnavailable), slot(tmp_path, lock, clock, wait_seconds=2.25):
        pytest.fail("timeout ran body")
    assert clock.sleeps == [1, 1, .25] and lock.releases == 0


@pytest.mark.parametrize("boundary", ["before", "during", "after"])
def test_maintenance_no_io(tmp_path, boundary):
    clock, lock = Clock(), Lock(None)
    lock.failures = 99 if boundary == "during" else 0
    with pytest.raises(locking.CollectionBlocked), slot(tmp_path, lock, clock, wait_seconds=10,
              blocked=lambda: boundary == "before" or lock.calls > 0):
        pytest.fail("maintenance performed I/O")
    assert lock.calls == (0 if boundary == "before" else 1)
    assert lock.releases == int(boundary == "after")


def test_body_lock_error_not_replayed(tmp_path):
    clock, lock = Clock(), Lock(None)
    calls = []
    with pytest.raises(locking.LockUnavailable), slot(tmp_path, lock, clock, wait_seconds=10):
        calls.append(True)
        raise locking.LockUnavailable("body")
    assert calls == [True] and lock.calls == lock.releases == 1
    assert not clock.sleeps


@pytest.mark.parametrize("code", [errno.EACCES, errno.ENOSPC, errno.EIO])
def test_noncontention_immediate(tmp_path, code):
    clock, lock = Clock(), Lock(None)
    lock.failures, lock.error = 99, code
    with pytest.raises(OSError) as caught, slot(tmp_path, lock, clock, wait_seconds=1800):
        pytest.fail("I/O error ran body")
    assert caught.value.errno == code and lock.calls == 1 and not clock.sleeps


def test_unknown_lock_error_not_retried(tmp_path):
    clock = Clock()

    class Unsupported(Lock):
        def acquire(self):
            raise locking.LockUnavailable("unsupported")

    with pytest.raises(locking.LockUnavailable), slot(
        tmp_path, Unsupported(None), clock, wait_seconds=10,
    ):
        pytest.fail("unsupported")
    assert not clock.sleeps


@pytest.mark.parametrize("value", [True, False, -1, 1801, float("nan"), float("inf"), "1", None])
def test_invalid_wait_before_lock(tmp_path, value):
    def fail(path):
        pytest.fail("created lock")
    with pytest.raises(ValueError), locking.collector_slot(
        tmp_path / "db", wait_seconds=value, lock_factory=fail,
    ):
        pytest.fail("ran body")


def entrypoint(monkeypatch, tmp_path, role):
    from types import SimpleNamespace

    from trendradar import __main__ as main
    from trendradar.ai_frontier import __main__ as ai
    module = main if role == "main" else ai
    monkeypatch.setenv("TRENDRADAR_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.delenv("TRENDRADAR_COLLECTOR_WAIT_SECONDS", raising=False)
    monkeypatch.setattr(module, "load_settings", lambda *a, **k: SimpleNamespace(
        intelligence_database_path=tmp_path / "db"))
    monkeypatch.setattr(module, "read_guard", lambda *a: None)
    monkeypatch.setattr(sys, "argv", ["frontier"])
    monkeypatch.setattr(module, "_run_main" if role == "main" else "_run",
                        lambda *a: pytest.fail("provider I/O"))
    return module


@pytest.mark.parametrize("role", ["main", "ai"])
@pytest.mark.parametrize("value", ["nan", "inf", "-1", "1801", "true", "", "garbage"])
def test_invalid_env_before_io(tmp_path, monkeypatch, role, value):
    module = entrypoint(monkeypatch, tmp_path, role)
    monkeypatch.setenv("TRENDRADAR_COLLECTOR_WAIT_SECONDS", value)
    assert module.main() == (False if role == "main" else 1)
    assert not (tmp_path / "locks").exists()


@pytest.mark.parametrize("role", ["main", "ai"])
@pytest.mark.parametrize("wait", [0, .01])
def test_busy_exit_metadata(tmp_path, monkeypatch, role, wait):
    module = entrypoint(monkeypatch, tmp_path, role)
    monkeypatch.setenv("TRENDRADAR_COLLECTOR_WAIT_SECONDS", str(wait))
    events = []
    monkeypatch.setattr(module.log, "info", lambda *a, **k: events.append(k))
    with locking.runtime_locks(tmp_path / "db", "collector"):
        result = module.main()
    assert result == (False if role == "main" else (0 if wait == 0 else 1))
    assert [e["state"] for e in events] == (["waiting", "timeout"] if wait else ["timeout"])
    assert len({e["attempt_id"] for e in events}) == 1
    assert {e["collector"] for e in events} == {role}


@pytest.mark.parametrize("role", ["main", "ai"])
@pytest.mark.parametrize("success", [True, False])
def test_result_classification(tmp_path, monkeypatch, role, success):
    module = entrypoint(monkeypatch, tmp_path, role)
    events = []
    monkeypatch.setattr(module.log, "info", lambda *a, **k: events.append(k))
    if role == "main":
        monkeypatch.setattr(module, "_run_main", lambda: success)
    else:
        async def run(*a):
            return 0 if success else 1
        monkeypatch.setattr(module, "_run", run)
    result = module.main()
    assert result == (success if role == "main" else (0 if success else 1))
    assert [e["state"] for e in events] == ["acquired", "completed" if success else "failed"]
    assert events[-1]["wait_seconds"] >= 0 and events[-1]["run_seconds"] >= 0


@pytest.mark.parametrize("role", ["main", "ai"])
def test_entry_maintenance(tmp_path, monkeypatch, role):
    module = entrypoint(monkeypatch, tmp_path, role)
    monkeypatch.setattr(module, "read_guard", lambda *a: object())
    assert module.main() == (False if role == "main" else 0)


@pytest.mark.skipif(sys.platform != "linux", reason="actual Linux flock")
def test_two_process_release_wait_executes_once(tmp_path):
    script = """
import sys
from pathlib import Path
from trendradar.core.locking import collector_slot
def emit(**event):
    if event["state"] == "waiting": Path(sys.argv[3]).write_text("waiting")
with collector_slot(sys.argv[1], wait_seconds=5, emit=emit):
    with Path(sys.argv[2]).open("a") as f: print("once", file=f)
"""
    done = tmp_path / "done"
    waiting = tmp_path / "waiting"
    with locking.runtime_locks(tmp_path / "db", "collector"):
        process = subprocess.Popen([sys.executable, "-B", "-c", script,
                                    str(tmp_path / "db"), str(done), str(waiting)],
                                   cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not waiting.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            assert waiting.exists() and process.poll() is None and not done.exists()
        except BaseException:
            process.kill()
            process.communicate()
            raise
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, (stdout, stderr)
    assert done.read_text().splitlines() == ["once"]


@pytest.mark.parametrize("role", ["main", "ai"])
def test_secret_invalid_env_not_logged(tmp_path, monkeypatch, capsys, role):
    module = entrypoint(monkeypatch, tmp_path, role)
    monkeypatch.setenv("TRENDRADAR_COLLECTOR_WAIT_SECONDS", "SECRET-SENTINEL")
    assert module.main() == (False if role == "main" else 1)
    captured = capsys.readouterr()
    assert "SECRET-SENTINEL" not in captured.out + captured.err


@pytest.mark.parametrize("role", ["main", "ai"])
def test_body_lock_error_is_failed_not_timeout(tmp_path, monkeypatch, role):
    module = entrypoint(monkeypatch, tmp_path, role)
    monkeypatch.setenv("TRENDRADAR_COLLECTOR_WAIT_SECONDS", ".01")
    events, calls = [], []
    monkeypatch.setattr(module.log, "info", lambda *a, **k: events.append(k))
    def fail(*a):
        calls.append(True)
        raise locking.LockUnavailable("body")
    if role == "main":
        monkeypatch.setattr(module, "_run_main", fail)
    else:
        async def run(*a):
            fail()
        monkeypatch.setattr(module, "_run", run)
    assert module.main() == (False if role == "main" else 1)
    assert calls == [True] and [e["state"] for e in events] == ["acquired", "failed"]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux filesystem failures")
def test_actual_permission_error_before_sleep(tmp_path):
    import os
    if os.geteuid() != 0:
        pytest.skip("requires root to run unprivileged permission probe")
    tmp_path.chmod(0o755)
    denied = tmp_path / "denied"
    denied.mkdir(mode=0o700)
    script = """
from trendradar.core.locking import collector_slot
import sys
def sleep(delay): raise AssertionError("permission failure retried")
try:
    with collector_slot(sys.argv[1], wait_seconds=1800, sleep=sleep): pass
except PermissionError: pass
else: raise AssertionError("permission unexpectedly permitted")
"""
    result = subprocess.run([sys.executable, "-B", "-c", script, str(denied / "db")],
                            cwd=ROOT, user=65534, group=65534, extra_groups=[],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(sys.platform != "linux", reason="actual disposable systemd")
def test_systemd_active_oneshot_coalesces_and_timer_rearms(tmp_path):
    import json
    import os
    import shutil
    import tempfile
    import uuid
    if os.geteuid() != 0 or Path("/proc/1/comm").read_text().strip() != "systemd":
        pytest.skip("requires disposable root systemd")
    assert not str(Path(sys.executable).resolve()).startswith(("/tmp/", "/var/tmp/"))
    name = "trendradar-task5-" + uuid.uuid4().hex
    sandbox = Path(tempfile.mkdtemp(prefix=name + "-", dir="/var/lib"))
    sandbox.chmod(0o755)
    events = sandbox / "events"
    events.touch()
    events.chmod(0o666)
    script = sandbox / "probe.py"
    program = (
        'import time,json,subprocess\n'
        'from pathlib import Path\n'
        'p=Path(EVENT_PATH)\n'
        'time.sleep(.6)  # Intentional startup jitter after systemd activation.\n'
        'activation=int(subprocess.check_output(\n'
        "    ['systemctl','show',UNIT_NAME,'--value','-p','InactiveExitTimestampMonotonic'],\n"
        '    text=True,timeout=5))/1_000_000\n'
        'def event(state):\n'
        "    row={'state':state,'at':time.monotonic(),'wall':time.time(),\n"
        "         'activation':activation}\n"
        "    with p.open('a') as f: print(json.dumps(row),file=f)\n"
        "event('started')\n"
        'time.sleep(6.2)\n'
        "event('completed')\n"
    )
    script.write_text(program.replace('EVENT_PATH', repr(str(events))).replace(
        'UNIT_NAME', repr(name + '.service'),
    ))
    script.chmod(0o644)
    service = Path("/run/systemd/system") / (name + ".service")
    timer = service.with_suffix(".timer")
    def ctl(*args):
        result = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        return result.stdout
    def records():
        return [json.loads(line) for line in events.read_text().splitlines()]
    trace = []
    try:
        service.write_text(
            "[Unit]\nDescription=Task5 isolated coalescing probe\n[Service]\n"
            f"Type=oneshot\nUser=nobody\nPrivateTmp=true\nExecStart={sys.executable} -B {script}\n"
        )
        timer.write_text(
            "[Unit]\nDescription=Task5 scaled calendar\n[Timer]\n"
            f"OnCalendar=*-*-* *:*:00/5\nAccuracySec=1ms\nUnit={name}.service\n"
        )
        ctl("daemon-reload")
        ctl("start", name + ".timer")
        deadline = time.monotonic() + 40
        injected = False
        while time.monotonic() < deadline:
            rows = records()
            if rows and not injected:
                trace.append(ctl("show", name + ".service", "-p", "ActiveState,SubState,PrivateTmp"))
                ctl("start", "--no-block", name + ".service")
                injected = True
            if sum(r["state"] == "completed" for r in rows) >= 2:
                break
            time.sleep(.05)
        else:
            pytest.fail("scaled timer did not complete two runs")
        rows = records()
        starts = [r["at"] for r in rows if r["state"] == "started"]
        ends = [r["at"] for r in rows if r["state"] == "completed"]
        assert starts[1] >= ends[0]
        assert starts[1] - starts[0] >= 6.2
        first_start = next(r for r in rows if r["state"] == "started")
        first_end = next(r for r in rows if r["state"] == "completed")
        second_start = [r for r in rows if r["state"] == "started"][1]
        gap = _overdue_rearm_gap(first_end, second_start, period=5)
        # Model whole activation-to-completion runtime, including Python startup.
        model = _calendar_rearm_audit(
            {"probe": first_end["at"] - first_start["activation"]},
            {"probe": [0, 5, 10, 15]}, window=16, rearm_delay=gap, wake=.01,
        )
        predicted = [r["started"] for r in model["rows"] if "started" in r]
        assert abs(predicted[1] - (
            second_start["activation"] - first_start["activation"]
        )) < .01
        trace.append({"observed_activation_rearm_gap_seconds": gap,
                      "intentional_python_startup_delay_seconds": .6,
                      "conditional_model": model})
        assert any(isinstance(item, str) and "SubState=start" in item and "PrivateTmp=yes" in item
                   for item in trace)
        trace.append(ctl("show", name + ".timer", "-p", "ActiveState,LastTriggerUSec,NextElapseUSecRealtime"))
    finally:
        # Only this UUID's units; keep every fixture's logs, including failed runs.
        subprocess.run(["systemctl", "stop", name + ".timer", name + ".service"],
                       capture_output=True, timeout=10)
        log = subprocess.run(["journalctl", "-u", name + ".service", "-u", name + ".timer",
                              "--no-pager"], capture_output=True, text=True, timeout=10)
        evidence = ROOT / "output/resource-remediation-20261111" / ("task5-systemd-" + name)
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "journal.log").write_text(log.stdout + log.stderr)
        (evidence / "states.json").write_text(json.dumps(trace))
        shutil.copyfile(events, evidence / "events.jsonl")
        shutil.copyfile(service, evidence / "probe.service")
        shutil.copyfile(timer, evidence / "probe.timer")
        service.unlink(missing_ok=True)
        timer.unlink(missing_ok=True)
        ctl("daemon-reload")
        shutil.rmtree(sandbox)


@pytest.mark.skipif(sys.platform != "linux", reason="actual flock failure boundary")
@pytest.mark.parametrize("code", [errno.EACCES, errno.ENOSPC, errno.EIO])
def test_flock_nonbusy_error_not_retried(tmp_path, monkeypatch, code):
    clock = Clock()
    calls = []
    def fail(*args):
        calls.append(args)
        raise OSError(code, "fixture")
    monkeypatch.setattr(locking.fcntl, "flock", fail)
    with pytest.raises(OSError) as caught, locking.collector_slot(
        tmp_path / "db", wait_seconds=1800, clock=clock, sleep=clock.sleep,
    ):
        pytest.fail("nonbusy flock failure ran body")
    assert caught.value.errno == code and len(calls) == 1 and not clock.sleeps


def test_calendar_model_overdue_rearm_before_next_nominal():
    result = _calendar_rearm_audit(
        {"main": 2.2}, {"main": [0, 1, 2, 3, 4]}, window=5,
        rearm_delay=.05, wake=.01,
    )
    starts = [r["started"] for r in result["rows"] if "started" in r]
    assert starts[:2] == [0, 2.25]
    assert starts[1] < 3
    assert result["after_drain"]["main"]["coalesced"] > 0


def test_calendar_model_keeps_postwindow_pending_and_drains():
    result = _calendar_rearm_audit(
        {"main": 2.2}, {"main": [0, 1, 2, 3, 4]}, window=4.1,
        rearm_delay=.05, wake=.01,
    )
    assert result["at_window"]["main"]["pending"] > 0
    assert result["after_drain"]["main"]["pending"] == 0
    assert result["drained_at"] > 4.1
    for phase in ["at_window", "after_drain"]:
        row = result[phase]["main"]
        assert row["expected"] == sum(row[s] for s in ["completed", "coalesced", "timeout", "pending"])


@pytest.mark.parametrize("priority", ["waiter", "reactivation"])
def test_calendar_model_exact_deadline_no_late_acquire(priority):
    result = _calendar_rearm_audit(
        {"main": 30, "ai": 1}, {"main": [0], "ai": [0]}, window=2,
        wait=30, wake=1, priority=priority,
    )
    assert result["after_drain"]["ai"]["timeout"] == 1
    assert not any(r["role"] == "ai" and "started" in r for r in result["rows"])


def _calendar_rearm_audit(
    durations, schedules, *, window, wait=30., wake=1 / 60,
    rearm_delay=0., priority="waiter",
):
    """Conditional model, not a scheduler guarantee; all times use the same unit.

    v255 rearms relative to last actual trigger. While a oneshot is active,
    nominal ticks are accounting tokens only, not per-tick process invocations.
    On termination one overdue reactivation consumes elapsed tokens as a group.
    The oldest token represents that group; others are labelled coalesced.
    Wake polling deliberately permits a newly rearmed job to beat a sleeping waiter.
    """
    import heapq

    rows, queue = [], []
    active = dict.fromkeys(durations)
    buffered = {role: [] for role in durations}
    owner = None
    sequence = 0
    order = {"done": 0, "nominal": 2, "activate": 3, "poll": 1, "snapshot": 5}
    if priority == "reactivation":
        order.update(activate=1, poll=3)
    elif priority != "waiter":
        raise ValueError("unknown scenario ordering")

    def put(at, kind, role=None, row=None):
        nonlocal sequence
        sequence += 1
        heapq.heappush(queue, (at, order[kind], sequence, kind, role, row))

    def summarize():
        result = {}
        for role in durations:
            subset = [r for r in rows if r["role"] == role]
            result[role] = {
                "expected": len(subset),
                "started": sum("started" in r for r in subset),
                "completed": sum(r["state"] == "completed" for r in subset),
                "coalesced": sum(r["state"] == "coalesced" for r in subset),
                "timeout": sum(r["state"] == "timeout" for r in subset),
                "pending": sum(r["state"] not in {"completed", "coalesced", "timeout"}
                               for r in subset),
                "deferred": sum(r.get("deferred", False) for r in subset),
            }
            item = result[role]
            assert item["expected"] == sum(
                item[k] for k in ("completed", "coalesced", "timeout", "pending")
            )
        return result

    def finish(at, role, row, state):
        nonlocal owner
        row["state"] = state
        row["finished"] = at
        if owner == role:
            owner = None
        active[role] = None
        if buffered[role]:
            active[role] = "queued"
            put(at + rearm_delay, "activate", role)

    for role, times in schedules.items():
        for at in times:
            if at < window:
                put(at, "nominal", role)
    put(window, "snapshot")
    at_window = None
    last = 0.
    while queue:
        at, _, _, kind, role, row = heapq.heappop(queue)
        last = max(last, at)
        if kind == "snapshot":
            at_window = summarize()
        elif kind == "nominal":
            row = {"role": role, "nominal": at, "state": "pending"}
            rows.append(row)
            buffered[role].append(row)
            if active[role] is None:
                active[role] = "queued"
                put(at, "activate", role)
        elif kind == "activate":
            group, buffered[role] = buffered[role], []
            assert group
            row = group[0]
            row.update(entered=at, deadline=at + wait, state="waiting", polls=0,
                       covered_nominals=[r["nominal"] for r in group])
            for covered in group[1:]:
                covered.update(state="coalesced", representative=row["nominal"])
            active[role] = row
            put(at, "poll", role, row)
        elif kind == "poll":
            if row["polls"] and at >= row["deadline"] - 1e-9:
                finish(at, role, row, "timeout")
            elif owner is None:
                owner = role
                row.update(state="running", started=at)
                put(at + durations[role], "done", role, row)
            elif at >= row["deadline"] - 1e-9:
                finish(at, role, row, "timeout")
            else:
                row["deferred"] = True
                row["polls"] += 1
                put(min(row["entered"] + row["polls"] * wake, row["deadline"]),
                    "poll", role, row)
        else:
            finish(at, role, row, "completed")
    return {"at_window": at_window, "after_drain": summarize(), "drained_at": last,
            "rows": rows, "scenario": {"wake": wake, "rearm_delay": rearm_delay,
                                     "priority": priority}}


@pytest.mark.parametrize("main", [30, 37, 55, 65])
@pytest.mark.parametrize("ai", [18, 35])
def test_calendar_all_profiles_account_at_window_and_after_drain(main, ai):
    result = _calendar_rearm_audit(
        {"main": main, "ai": ai},
        {"main": list(range(30, 1440, 60)), "ai": list(range(0, 1440, 120))},
        window=1440, rearm_delay=.05 / 60,
    )
    for phase in ("at_window", "after_drain"):
        for role, expected in (("main", 24), ("ai", 12)):
            counts = result[phase][role]
            assert counts["expected"] == expected
            assert expected == sum(
                counts[k] for k in ("completed", "coalesced", "timeout", "pending")
            )
    assert all(c["pending"] == 0 for c in result["after_drain"].values())
    if main >= 37:
        assert result["at_window"]["main"]["pending"] > 0
        assert result["drained_at"] > 1440


def test_rearm_proof_accepts_delayed_python_started():
    first_end = {"at": 106.2, "wall": 1006.2}
    delayed_python = {"at": 106.9, "wall": 1006.9, "activation": 106.25}
    # A 0.65s Python-start delay must not hide prompt systemd activation.
    assert _overdue_rearm_gap(first_end, delayed_python, period=5) == pytest.approx(.05)


def test_rearm_proof_rejects_only_next_nominal_activation():
    first_end = {"at": 106.2, "wall": 1006.2}
    next_nominal = {"at": 110.6, "wall": 1010.6, "activation": 110.}
    with pytest.raises(AssertionError, match="next nominal"):
        _overdue_rearm_gap(first_end, next_nominal, period=5)


def _overdue_rearm_gap(first_end, next_start, *, period):
    """Prove systemd activation preceded the next nominal tick, not Python startup."""
    import math

    nominal_wall = (math.floor(first_end["wall"] / period) + 1) * period
    next_nominal = first_end["at"] + nominal_wall - first_end["wall"]
    activation = next_start["activation"]
    assert activation >= first_end["at"], "activation preceded prior completion"
    assert activation < next_nominal, "activation waited until the next nominal tick"
    return activation - first_end["at"]
