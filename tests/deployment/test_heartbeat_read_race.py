import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trendradar.core import heartbeat
from trendradar.ops import health


def test_heartbeat_published_during_read_is_not_from_future(tmp_path, monkeypatch):
    directory = tmp_path / "health"
    directory.mkdir()
    path = directory / "bot.json"
    before = datetime(2026, 10, 23, tzinfo=timezone.utc)
    current = [before]
    payload = {"state": "connected", "release_id": "test", "updated_at": before.isoformat()}
    path.write_text(json.dumps(payload))
    original = Path.read_text

    def read(file, *args, **kwargs):
        if file == path:
            current[0] = before + timedelta(milliseconds=10)
            payload["updated_at"] = current[0].isoformat()
            path.write_text(json.dumps(payload))
        return original(file, *args, **kwargs)

    monkeypatch.setenv("TRENDRADAR_HEALTH_DIR", str(directory))
    monkeypatch.setattr(health, "_utc_now", lambda: current[0])
    monkeypatch.setattr(Path, "read_text", read)
    _, _, errors = health._heartbeats(tmp_path / "intelligence.db", expected_roles=["bot"],
                                      expected_release_id="test")
    assert errors == []


def test_actual_future_heartbeat_is_still_rejected(tmp_path, monkeypatch):
    directory = tmp_path / "health"
    directory.mkdir()
    now = datetime(2026, 10, 23, tzinfo=timezone.utc)
    (directory / "bot.json").write_text(json.dumps({
        "state": "connected", "release_id": "test",
        "updated_at": (now + timedelta(seconds=30)).isoformat(),
    }))
    monkeypatch.setenv("TRENDRADAR_HEALTH_DIR", str(directory))
    monkeypatch.setattr(health, "_utc_now", lambda: now)
    _, _, errors = health._heartbeats(tmp_path / "intelligence.db", expected_roles=["bot"],
                                      expected_release_id="test")
    assert errors == ["future_heartbeat:bot"]


@pytest.mark.parametrize("wall_jump", [-3600, 3600])
def test_live_boot_heartbeat_survives_wall_clock_correction(tmp_path, monkeypatch, wall_jump):
    directory = tmp_path / "health"
    monkeypatch.setenv("TRENDRADAR_HEALTH_DIR", str(directory))
    now = datetime(2026, 10, 23, tzinfo=timezone.utc)
    monkeypatch.setattr(heartbeat, "_now", lambda: now.isoformat())
    monkeypatch.setattr(heartbeat, "boot_clock", lambda: ("same-boot", 10_000_000_000))
    heartbeat.RoleHeartbeat("bot", tmp_path / "db").write(state="connected")
    monkeypatch.setattr(health, "_utc_now", lambda: now + timedelta(seconds=wall_jump))
    monkeypatch.setattr(health, "boot_clock", lambda: ("same-boot", 11_000_000_000))
    report, _, errors = health._heartbeats(tmp_path / "db", expected_roles=["bot"])
    assert errors == []
    assert report["bot"]["age_seconds"] == 1
    assert report["bot"]["wall_age_seconds"] == wall_jump
    assert report["bot"]["clock_basis"] == "boottime"


@pytest.mark.parametrize(("stamp", "identity", "error"), [
    (1, "same-boot", "stale_heartbeat:bot"),
    (102_000_000_000, "same-boot", "future_heartbeat:bot"),
    (100_000_000_000, "previous-boot", "invalid_heartbeat:bot.json"),
    (True, "same-boot", "invalid_heartbeat:bot.json"),
    ("100", "same-boot", "invalid_heartbeat:bot.json"),
    (-1, "same-boot", "invalid_heartbeat:bot.json"),
    (None, "same-boot", "invalid_heartbeat:bot.json"),
    (10**400, "same-boot", "invalid_heartbeat:bot.json"),
])
def test_boot_heartbeat_rejects_stale_future_or_invalid_clock(
    tmp_path, monkeypatch, stamp, identity, error,
):
    directory = tmp_path / "health"
    directory.mkdir()
    now = datetime.now(timezone.utc)
    (directory / "bot.json").write_text(json.dumps({
        "state": "connected", "updated_at": now.isoformat(),
        "boot_id": identity, "updated_boottime_ns": stamp,
    }))
    monkeypatch.setenv("TRENDRADAR_HEALTH_DIR", str(directory))
    monkeypatch.setattr(health, "_utc_now", lambda: now)
    monkeypatch.setattr(health, "boot_clock", lambda: ("same-boot", 101_000_000_000))
    _, _, errors = health._heartbeats(tmp_path / "db", expected_roles=["bot"])
    assert errors == ([error, "missing_heartbeat:bot"] if error.startswith("invalid") else [error])
