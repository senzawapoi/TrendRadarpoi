"""Reproduce roles exiting on the active deployment marker before quiesce."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .installer_harness import ROOT, make_installer

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="requires the isolated Linux installer harness",
)


@pytest.mark.parametrize("point", ["acquire", "quiesce"])
@pytest.mark.parametrize("rollback", [False, True])
def test_guard_exit_keeps_worker_in_durable_restart_set(tmp_path, point, rollback):
    command, env, _ = make_installer(tmp_path)
    script = (ROOT / "scripts/deploy/install_release.sh").read_text()
    hook = '''
python3 - "$in_progress_file" <<'TESTPY'
import json, os, sys
from pathlib import Path
from trendradar.ops.maintenance import read_guard
assert read_guard(os.environ['INTELLIGENCE_DB_PATH']) is not None
marker = json.loads(Path(sys.argv[1]).read_text())
state = Path(os.environ['TEST_UNITS_STATE'])
active = json.loads(state.read_text())
assert 'test-worker.service' in active
active.remove('test-worker.service')
state.write_text(json.dumps(active))
(state.parent / 'guard-exit.json').write_text(json.dumps(marker))
TESTPY
'''
    anchor = f"write_state {point}\n"
    assert script.count(anchor) == 1
    script = script.replace(anchor, anchor + hook, 1)
    if rollback:
        script = script.replace("write_state migrate\n", 'fail "injected before migration"\n', 1)
    injected = tmp_path / "guard-exit-installer.sh"
    injected.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [command[0], str(injected), *command[2:]], env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert (result.returncode != 0) is rollback, result.stdout + result.stderr
    recorded = json.loads((tmp_path / "guard-exit.json").read_text())
    assert recorded["pre_active_units"] == ["test-bot.service", "test-worker.service"]
    commands = [json.loads(line) for line in Path(env["TEST_LOG"]).read_text().splitlines()]
    assert [item[1] for item in commands if item[0] == "start"] == [
        "test-bot.service", "test-worker.service",
    ]
    assert not (tmp_path / "control/deploy-in-progress.json").exists()
    assert not (tmp_path / "control/restore-guard.json").exists()
    expected = "previous" if rollback else "candidate"
    assert (tmp_path / "current").resolve() == tmp_path / "releases" / expected
    assert set(json.loads(Path(env["TEST_UNITS_STATE"]).read_text())) == {
        "test-bot.service", "test-worker.service",
    }


def test_acquire_failure_retains_initial_role_intent_without_starting_services(tmp_path):
    command, env, _ = make_installer(tmp_path, build_lock=False)
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    record = json.loads((tmp_path / "control/deploy-in-progress.json").read_text())
    assert record["pre_active_units"] == ["test-bot.service", "test-worker.service"]
    assert not record["business_boundary_crossed"]
    commands = [json.loads(line) for line in Path(env["TEST_LOG"]).read_text().splitlines()]
    assert all(item[0] == "is-active" for item in commands)
