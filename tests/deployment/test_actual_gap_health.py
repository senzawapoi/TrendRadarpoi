"""Behavior regressions for the Phase 7 readiness defects."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from trendradar.core.heartbeat import RoleHeartbeat
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops import health
from trendradar.ops.health import main


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    database = tmp_path / "output" / "intelligence.db"
    database.parent.mkdir()
    with IntelligenceStorage(database, synchronous="FULL"):
        pass
    config = tmp_path / "config.yaml"
    config.write_text("intelligence:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("INTELLIGENCE_ENABLED", "true")
    monkeypatch.setenv("INTELLIGENCE_DB_PATH", str(database))
    monkeypatch.setenv("INTELLIGENCE_SQLITE_SYNCHRONOUS", "FULL")
    monkeypatch.setenv("TRENDRADAR_HEALTH_DIR", str(tmp_path / "health"))
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", str(tmp_path / "control"))
    monkeypatch.setenv("TRENDRADAR_RELEASE_ID", "gap-test")
    monkeypatch.setenv("TRENDRADAR_HEALTH_EXPECTED_ROLES", "bot,worker")
    monkeypatch.setenv("INTELLIGENCE_HEALTH_REQUIRE_BACKUP", "false")
    monkeypatch.setenv("INTELLIGENCE_HEALTH_REQUIRE_SOURCE_RUNS", "false")
    RoleHeartbeat("bot", database).write(state="connected", sqlite_synchronous="FULL")
    RoleHeartbeat("worker", database).write(state="running", sqlite_synchronous="FULL")
    return database, config


@pytest.mark.parametrize("state", [
    "connected", "connecting", "retrying", "cooldown", "stopped", "disabled",
    "unknown", "maintenance", "disconnected",
])
def test_bot_readiness_requires_connected(runtime, capsys, state):
    database, config = runtime
    RoleHeartbeat("bot", database).write(state=state, sqlite_synchronous="FULL")
    result = main(["--config", str(config), "--readiness", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert result == (0 if state == "connected" else 2), report
    assert report["status"] == ("healthy" if state == "connected" else "unhealthy")


def test_required_sources_cannot_be_empty(runtime, monkeypatch, capsys):
    _, config = runtime
    monkeypatch.setenv("INTELLIGENCE_HEALTH_REQUIRE_SOURCE_RUNS", "true")
    result = main(["--config", str(config), "--readiness", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert result == 2, report
    assert "source_runs_unverified" in report["errors"]


def test_explicit_source_without_run_is_rejected(runtime, monkeypatch, capsys):
    _, config = runtime
    monkeypatch.setenv("INTELLIGENCE_HEALTH_REQUIRE_SOURCE_RUNS", "true")
    monkeypatch.setenv("TRENDRADAR_HEALTH_EXPECTED_SOURCES", "rss:never-ran")
    assert main(["--config", str(config), "--readiness", "--json"]) == 2
    assert "missing_source_run:rss:never-ran" in json.loads(capsys.readouterr().out)["errors"]


@pytest.mark.parametrize("condition,ordinary,ready", [
    ("missing", 2, 2), ("schema", 2, 2), ("disabled", 0, 2),
    ("maintenance", 0, 2), ("healthy", 0, 0),
])
def test_health_and_readiness_preserve_readonly_exit_contract(runtime, monkeypatch, capsys,
                                                            condition, ordinary, ready):
    from trendradar.ops.maintenance import set_guard

    database, config = runtime
    if condition == "missing":
        database.unlink()
    elif condition == "schema":
        import sqlite3
        connection = sqlite3.connect(database)
        connection.execute("PRAGMA user_version=987")
        connection.close()
    elif condition == "disabled":
        monkeypatch.setenv("INTELLIGENCE_ENABLED", "false")
    elif condition == "maintenance":
        set_guard(database, reason="fixture maintenance")
    before = database.read_bytes() if database.exists() else None
    assert main(["--config", str(config), "--json"]) == ordinary
    capsys.readouterr()
    assert main(["--config", str(config), "--readiness", "--json"]) == ready
    assert (database.read_bytes() if database.exists() else None) == before


@pytest.mark.parametrize("state", ["running", "connected", "maintenance", "stopped", "unknown"])
def test_worker_uses_its_own_state_rules(runtime, capsys, state):
    database, config = runtime
    RoleHeartbeat("worker", database).write(state=state, sqlite_synchronous="FULL")
    assert main(["--config", str(config), "--readiness", "--json"]) == (
        0 if state == "running" else 2
    )


@pytest.mark.parametrize("age,release,present,expected", [
    (60, "gap-test", True, 0), (60.001, "gap-test", True, 2),
    (0, "old", True, 2), (0, "unknown", True, 2),
    (0, None, True, 2), (0, "gap-test", False, 2), (-1, "gap-test", True, 2),
])
def test_heartbeat_identity_and_exact_age_boundary(runtime, monkeypatch, age, release, present, expected):
    database, config = runtime
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    monkeypatch.setattr(health, "_utc_now", lambda: now)
    directory = health.heartbeat_directory(database)
    for role in ("bot", "worker"):
        path = directory / f"{role}.json"
        payload = json.loads(path.read_text())
        payload["updated_at"] = (now - timedelta(seconds=age)).isoformat()
        payload["release_id"] = release
        path.write_text(json.dumps(payload))
    if not present:
        (directory / "bot.json").unlink()
    assert main(["--config", str(config), "--readiness", "--json"]) == expected


@pytest.mark.parametrize("runs,required,expected", [
    ([], True, 2), ([], False, 0),
    ([("healthy", 0)], True, 0), ([("unhealthy", 0)], True, 2),
    ([("unknown", 0)], True, 2), ([("healthy", 21600)], True, 0),
    ([("healthy", 21600.01)], True, 2),
])
def test_source_runs_required_and_fresh(runtime, monkeypatch, runs, required, expected):
    database, config = runtime
    now = health._utc_now()
    monkeypatch.setattr(health, "_utc_now", lambda: now)
    monkeypatch.setenv("INTELLIGENCE_HEALTH_REQUIRE_SOURCE_RUNS", str(required).lower())
    for status, age in runs:
        finished = (now - timedelta(seconds=age)).isoformat()
        with IntelligenceStorage(database) as storage:
            storage.connection.execute(
                "INSERT INTO source_runs (adapter_id, status, started_at, finished_at, "
                "duration_ms, fetched_count, normalized_count, error_count, error_summary) "
                "VALUES ('rss:test',?,?,?,0,1,1,0,'')", (status, finished, finished),
            )
    assert main(["--config", str(config), "--readiness", "--json"]) == expected


@pytest.mark.parametrize("wait,status,attempts,expected", [
    (299, "failed", 1, 0), (300, "failed", 1, 0), (300.01, "failed", 1, 2),
    (999, "completed", 1, 0), (999, "failed", 3, 0),
])
def test_queue_age_survives_recent_retry(runtime, monkeypatch, wait, status, attempts, expected):
    database, config = runtime
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(health, "_utc_now", lambda: now)
    with IntelligenceStorage(database) as storage:
        storage.connection.execute(
            "INSERT INTO feishu_events (event_id,scope,status,owner,attempts,lease_until,"
            "updated_at,event_json) VALUES ('queued','scope',?,'',?,?,?,?)",
            (status, attempts, now.isoformat(), now.isoformat(), json.dumps({
                "received_at": (now - timedelta(seconds=wait)).isoformat(),
            })),
        )
    assert main(["--config", str(config), "--readiness", "--json"]) == expected


def test_real_transport_state_written_to_heartbeat_then_health(runtime):
    from trendradar.integrations.feishu.config import FeishuConfig
    from trendradar.integrations.feishu.transport import FeishuTransport

    database, config = runtime
    transport = None

    class FakeConnection:
        async def connect(self):
            assert transport.state == "connecting"
            RoleHeartbeat("bot", database).write(state=transport.state, sqlite_synchronous="FULL")
            assert main(["--config", str(config), "--readiness", "--json"]) == 2

        async def wait_closed(self):
            RoleHeartbeat("bot", database).write(state=transport.state, sqlite_synchronous="FULL")
            assert main(["--config", str(config), "--readiness", "--json"]) == 0
            raise asyncio.CancelledError

        async def close(self):
            pass

    transport = FeishuTransport(FeishuConfig(), FakeConnection)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(transport.run())


@pytest.mark.parametrize("age,receipt,required,expected", [
    (0, "valid", True, 0), (26 * 3600 + 1, "valid", True, 2),
    (0, "array", True, 2), (0, "wrong_digest", True, 2),
    (0, "wrong_backup", True, 2), (0, "missing", True, 2),
    (999999, "missing", False, 0),
])
def test_backup_gate_binds_receipt_and_data_age(runtime, monkeypatch, age, receipt, required, expected):
    import hashlib

    from trendradar.ops.backup import create_snapshot

    database, config = runtime
    backup_root = database.parent.parent / "backups"
    snapshot = create_snapshot([database], backup_root)
    path = health.Path(snapshot["path"])
    now = datetime.now(timezone.utc)
    manifest = json.loads((path / "manifest.json").read_text())
    manifest["created_at"] = (now - timedelta(seconds=age)).isoformat()
    (path / "manifest.json").write_text(json.dumps(manifest))
    payload = {
        "success": True, "backup_id": snapshot["backup_id"],
        "finished_at": now.isoformat(), "snapshot_created_at": manifest["created_at"],
        "manifest_sha256": hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest(),
        "remote_snapshot_id": "fake-remote-snapshot",
    }
    if receipt == "wrong_digest":
        payload["manifest_sha256"] = "0" * 64
    if receipt == "wrong_backup":
        payload["backup_id"] = "wrong"
    if receipt != "missing":
        (path / "offsite-manifest.json").write_text(json.dumps([] if receipt == "array" else payload))
    monkeypatch.setenv("TRENDRADAR_BACKUP_DIR", str(backup_root))
    monkeypatch.setenv("INTELLIGENCE_HEALTH_REQUIRE_BACKUP", str(required).lower())
    monkeypatch.setattr(health, "_utc_now", lambda: now)
    assert main(["--config", str(config), "--readiness", "--json"]) == expected
