"""Persistent transaction protection must apply even without a guard file."""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trendradar.ops.maintenance import control_directory, main, read_guard, set_guard


@pytest.mark.parametrize("state", [
    "prepare", "acquire", "quiesce", "snapshot", "migrate", "switch",
    "pre_resume", "resume", "verify", "failed:readiness", "unknown",
])
def test_uncontrolled_deployment_blocks_work(tmp_path, monkeypatch, state):
    database = tmp_path / "output" / "intelligence.db"
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", str(tmp_path / "control"))
    control = control_directory(database)
    control.mkdir()
    (control / "deploy-in-progress.json").write_text(json.dumps({
        "state": state, "new_release_id": "gap-test", "business_boundary_crossed": True,
    }), encoding="utf-8")
    assert read_guard(database) is not None


@pytest.mark.parametrize("payload", [
    '{"state":"prepared"}', '{"state":"installing"}', '[]', '{broken',
])
def test_public_clear_refuses_incomplete_restore(tmp_path, monkeypatch, payload):
    database = tmp_path / "output" / "intelligence.db"
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", str(tmp_path / "control"))
    set_guard(database, reason="restore")
    journal = control_directory(database) / "restore-activation-test.json"
    journal.write_text(payload, encoding="utf-8")
    assert main(["clear", "--database", str(database)]) != 0
    assert journal.exists()
    assert read_guard(database) is not None


@pytest.mark.parametrize("payload", ["{broken", "[]", '{"state":"unknown"}'])
def test_invalid_deployment_blocks_all_cli_roles_before_io(tmp_path, monkeypatch, payload):
    from trendradar import __main__ as collector
    from trendradar.ai_frontier import __main__ as frontier
    from trendradar.integrations.feishu import __main__ as runner

    database = tmp_path / "output/intelligence.db"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    for key, value in {
        "INTELLIGENCE_DB_PATH": str(database), "CONFIG_PATH": str(config),
        "TRENDRADAR_CONTROL_DIR": str(tmp_path / "control"),
        "LARK_ENABLED": "true", "INTELLIGENCE_ENABLED": "true",
        "LARK_APP_ID": "fixture-app", "LARK_APP_SECRET": "fixture-only",
        "LARK_IDENTITY_FIELDS": '{"open_id":["fixture-owner"]}', "LARK_BOT_ID": "fixture-bot",
    }.items():
        monkeypatch.setenv(key, value)
    control_directory(database).mkdir()
    (control_directory(database) / "deploy-in-progress.json").write_text(payload, encoding="utf-8")
    calls = []

    def unexpected(*args, **kwargs):
        calls.append(True)
        raise AssertionError("protected role attempted provider or acquisition")

    monkeypatch.setattr(runner.FeishuClient, "from_credentials", unexpected)
    monkeypatch.setattr(collector, "_run_main", unexpected)
    monkeypatch.setattr(frontier, "_run", unexpected)
    for role in ("combined", "bot", "worker", "scheduler-once"):
        assert runner.main(["--config", str(config), "--role", role]) == 1
    assert collector.main() is False
    monkeypatch.setattr(sys, "argv", ["frontier", "--config", str(config)])
    assert frontier.main() == 0
    assert calls == []
    assert not database.exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux controller identity fence")
@pytest.mark.parametrize("state", ["resume", "verify", "finalize"])
@pytest.mark.parametrize("lease_clock", ["utc", "boottime"])
@pytest.mark.parametrize("fault", [
    None, "pid", "start", "boot", "expired", "future", "release", "boundary",
    "wall-forward", "wall-backward",
])
def test_controlled_resume_requires_live_exact_controller(
    tmp_path, monkeypatch, state, fault, lease_clock,
):
    database = tmp_path / "output/intelligence.db"
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", str(tmp_path / "control"))
    monkeypatch.setenv("TRENDRADAR_RELEASE_ID", "candidate")
    directory = control_directory(database)
    directory.mkdir()
    now = datetime.now(timezone.utc)
    payload = {
        "state": state, "business_boundary_crossed": True, "new_release_id": "candidate",
        "controller_pid": os.getpid(),
        "controller_start_time": Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "updated_at": now.isoformat(),
    }
    if lease_clock == "boottime":
        payload["controller_lease_boottime_ns"] = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    if fault == "pid":
        payload["controller_pid"] = 2**30
    elif fault == "start":
        payload["controller_start_time"] = "0"
    elif fault == "boot":
        payload["boot_id"] = "different-boot"
    elif fault == "expired":
        payload["updated_at"] = (now - timedelta(seconds=16)).isoformat()
        if lease_clock == "boottime":
            payload["controller_lease_boottime_ns"] -= 16_000_000_000
    elif fault == "future":
        payload["updated_at"] = (now + timedelta(seconds=5)).isoformat()
        if lease_clock == "boottime":
            payload["controller_lease_boottime_ns"] += 5_000_000_000
    elif fault == "release":
        payload["new_release_id"] = "old"
    elif fault == "boundary":
        payload["business_boundary_crossed"] = False
    elif fault == "wall-forward":
        payload["updated_at"] = (now - timedelta(hours=1)).isoformat()
    elif fault == "wall-backward":
        payload["updated_at"] = (now + timedelta(hours=1)).isoformat()
    (directory / "deploy-in-progress.json").write_text(json.dumps(payload), encoding="utf-8")
    allowed = fault is None or (
        lease_clock == "boottime" and fault in {"wall-forward", "wall-backward"}
    )
    assert (read_guard(database) is None) is allowed


@pytest.mark.skipif(sys.platform != "linux", reason="Linux controller identity fence")
@pytest.mark.parametrize("lease,allowed", [
    (40_000_000_000, True), (25_000_000_000, True), (24_999_999_999, False),
    (40_000_000_001, False), (True, False), (None, False),
    ("40000000000", False), (40_000_000_000.0, False), (-1, False),
])
def test_controller_boottime_lease_is_strict_and_bounded(monkeypatch, lease, allowed):
    from trendradar.ops import maintenance

    payload = {
        "controller_pid": os.getpid(),
        "controller_start_time": Path(f"/proc/{os.getpid()}/stat").read_text()
        .rsplit(")", 1)[1].split()[19],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "controller_lease_boottime_ns": lease,
    }

    def boottime(clock):
        assert clock == time.CLOCK_BOOTTIME
        return 40_000_000_000

    monkeypatch.setattr(maintenance.time, "clock_gettime_ns", boottime)
    assert maintenance._controller_alive(payload) is allowed
