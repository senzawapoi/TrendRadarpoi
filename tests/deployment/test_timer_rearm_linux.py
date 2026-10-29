"""Health and scheduler timer override re-arm contract under real systemd 255.

Real-systemd cases scale the template (30s -> 2s, 300s -> 3s) so the effective
trigger list is exercised in seconds; unscaled values are asserted separately.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from .installer_harness import ROOT

ROLES = ("health", "scheduler")
# Shape of both production overrides observed on 2026-10-29 (empty reset, then 300s only).
LEGACY = "[Timer]\nOnUnitActiveSec=\nOnUnitActiveSec=300s\n"
SYSTEMCTL = "/usr/bin/systemctl"
UNITS = Path("/run/systemd/system")
real_systemd = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="requires disposable Linux root and actual systemd",
)


def _template(role: str) -> Path:
    return ROOT / f"deploy/systemd/overrides/trendradar-{role}.timer.d/50-every-5-min.conf"


def _ctl(*args: str) -> str:
    result = subprocess.run([SYSTEMCTL, *args], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, " ".join(args) + ": " + result.stderr
    return result.stdout


def _show(unit: str, *properties: str) -> dict[str, str]:
    output = _ctl("show", unit, "--no-pager", "--property=" + ",".join(properties))
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def _scaled(text: str) -> str:
    return text.replace("OnActiveSec=30s", "OnActiveSec=2s").replace(
        "OnUnitActiveSec=300s", "OnUnitActiveSec=3s")


class TimerScope:
    def __init__(self, sandbox: Path, role: str):
        prefix = f"trendradar-p7-test-{uuid.uuid4().hex}"
        self.role = role
        self.template = _template(role)
        self.service, self.timer = f"{prefix}-{role}.service", f"{prefix}-{role}.timer"
        self.runs = sandbox / "runs"
        self.paths = [UNITS / self.service, UNITS / self.timer, UNITS / f"{self.timer}.d"]

    def install(self, dropin: str) -> None:
        (UNITS / self.service).write_text(
            f"[Unit]\nDescription=Isolated {self.role} timer re-arm\n[Service]\nType=oneshot\n"
            f"ExecStart=/bin/sh -c 'echo run >> {self.runs}'\n")
        base = (ROOT / f"deploy/systemd/trendradar-{self.role}.timer").read_text(encoding="utf-8")
        assert f"Unit=trendradar-{self.role}.service" in base
        (UNITS / self.timer).write_text(
            base.replace(f"Unit=trendradar-{self.role}.service", f"Unit={self.service}"))
        (UNITS / f"{self.timer}.d").mkdir(exist_ok=True)
        (UNITS / f"{self.timer}.d/50-every-5-min.conf").write_text(dropin)
        verify = subprocess.run(["systemd-analyze", "verify", str(UNITS / self.timer)],
                                capture_output=True, text=True, timeout=30)
        assert verify.returncode == 0, verify.stderr
        _ctl("daemon-reload")

    def remove(self) -> None:
        for path in self.paths:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        _ctl("daemon-reload")

    def runs_count(self) -> int:
        return len(self.runs.read_text().splitlines()) if self.runs.exists() else 0

    def armed(self) -> bool:
        state = _show(self.timer, "ActiveState", "SubState", "NextElapseUSecMonotonic")
        return (state["ActiveState"], state["SubState"]) == ("active", "waiting") and state[
            "NextElapseUSecMonotonic"] not in {"", "0", "infinity"}

    def never_activated(self) -> bool:
        return _show(self.service, "InactiveExitTimestampMonotonic")[
            "InactiveExitTimestampMonotonic"] == "0"

    def wait_runs(self, count: int, timeout: float = 20) -> int:
        deadline = time.monotonic() + timeout
        while self.runs_count() < count and time.monotonic() < deadline:
            time.sleep(0.1)
        return self.runs_count()


@pytest.fixture
def timer_scope(request):
    if Path("/proc/1/comm").read_text().strip() != "systemd":
        pytest.skip("PID 1 is not systemd")
    sandbox = Path(tempfile.mkdtemp(prefix="p7-timer-", dir="/var/lib"))
    scope = TimerScope(sandbox, request.param)
    try:
        yield scope
    finally:
        subprocess.run([SYSTEMCTL, "stop", scope.timer, scope.service],
                       capture_output=True, timeout=30)
        scope.remove()
        subprocess.run([SYSTEMCTL, "reset-failed", scope.timer, scope.service],
                       capture_output=True, timeout=30)
        shutil.rmtree(sandbox)


@pytest.mark.parametrize("role", ROLES)
def test_override_template_resets_base_then_arms_each_start(role):
    lines = [line for line in _template(role).read_text(encoding="utf-8").splitlines()
             if line and not line.startswith("#")]
    assert lines == ["[Timer]", "OnUnitActiveSec=", "OnActiveSec=30s",
                     "OnUnitActiveSec=300s", "AccuracySec=1s"]


@real_systemd
@pytest.mark.parametrize("timer_scope", ROLES, indirect=True)
def test_legacy_override_leaves_fresh_timer_elapsed(timer_scope):
    scope = timer_scope
    scope.install(_scaled(LEGACY))
    assert scope.never_activated()
    _ctl("start", scope.timer)
    state = _show(scope.timer, "SubState", "NextElapseUSecMonotonic")
    assert state == {"SubState": "elapsed", "NextElapseUSecMonotonic": "infinity"}
    time.sleep(5)
    assert scope.runs_count() == 0


@real_systemd
@pytest.mark.parametrize("timer_scope", ROLES, indirect=True)
def test_project_override_rearms_after_start_restart_reload_and_unload(timer_scope):
    scope = timer_scope
    scope.install(scope.template.read_text(encoding="utf-8"))
    # One TimersMonotonic= line per effective trigger; the reset drops OnBootSec=.
    effective = sorted(line.split(";")[0] for line in _ctl(
        "show", scope.timer, "--no-pager", "--property=TimersMonotonic").splitlines())
    assert effective == ["TimersMonotonic={ OnActiveUSec=30s ",
                         "TimersMonotonic={ OnUnitActiveUSec=5min "]

    scope.install(_scaled(scope.template.read_text(encoding="utf-8")))
    assert scope.never_activated()
    _ctl("start", scope.timer)
    assert scope.armed()
    # First run from OnActiveSec, then at least two OnUnitActiveSec periods.
    assert scope.wait_runs(3) >= 3

    _ctl("stop", scope.timer, scope.service)
    before = scope.runs_count()
    _ctl("start", scope.timer)
    assert scope.armed()
    assert scope.wait_runs(before + 2) >= before + 2

    _ctl("daemon-reload")
    assert scope.armed()
    before = scope.runs_count()
    assert scope.wait_runs(before + 1) >= before + 1

    _ctl("stop", scope.timer, scope.service)
    scope.remove()
    scope.install(_scaled(scope.template.read_text(encoding="utf-8")))
    assert scope.never_activated()
    before = scope.runs_count()
    _ctl("start", scope.timer)
    assert scope.armed()
    assert scope.wait_runs(before + 2) >= before + 2
