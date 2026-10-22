"""Readiness under the requested fully enabled local release policy."""

import hashlib
import json
import socket
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from trendradar.ai_frontier.storage import AIFrontierStorage
from trendradar.core import heartbeat
from trendradar.core.heartbeat import RoleHeartbeat
from trendradar.core.settings import load_settings
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops import backup, health

SOURCES = ("rss:release-policy", "rss:second-required")


def _write_sources(database, now):
    with IntelligenceStorage(database, synchronous="FULL") as storage:
        storage.connection.execute("DELETE FROM source_runs")
        for source in SOURCES:
            storage.connection.execute(
                "INSERT INTO source_runs (adapter_id, status, started_at, finished_at, "
                "duration_ms, fetched_count, normalized_count, error_count, error_summary) "
                "VALUES (?,'healthy',?,?,1,1,1,0,'')",
                (source, now.isoformat(), now.isoformat()),
            )


def _write_backup_time(manifest_path, now, age=0):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["created_at"] = (now - timedelta(seconds=age)).isoformat()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    # This is a synthetic local receipt, never proof of a remote restic upload.
    manifest_path.with_name("offsite-manifest.json").write_text(
        json.dumps({
            "success": True,
            "backup_id": manifest["backup_id"],
            "finished_at": now.isoformat(),
            "snapshot_created_at": manifest["created_at"],
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "remote_snapshot_id": "synthetic-release-policy",
        }),
        encoding="utf-8",
    )


@pytest.fixture
def release_policy(tmp_path, monkeypatch):
    now = datetime(2026, 10, 14, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(health, "_utc_now", lambda: now)
    monkeypatch.setattr(heartbeat, "_now", lambda: now.isoformat())
    monkeypatch.setattr(backup, "_now", lambda: now.isoformat())
    monkeypatch.setattr(health.shutil, "disk_usage", lambda _: SimpleNamespace(
        total=1_000_000, free=900_000,
    ))
    network_calls = []

    def no_network(*args, **kwargs):
        network_calls.append(True)
        pytest.fail("local readiness attempted network I/O")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    database = tmp_path / "output" / "intelligence.db"
    ai_database = tmp_path / "output" / "ai_frontier.db"
    backup_dir = tmp_path / "backups"
    config = tmp_path / "config.yaml"
    config.write_text(
        """intelligence:
  enabled: true
  health:
    expected_roles: [bot, worker]
    expected_sources: [rss:release-policy, rss:second-required]
    require_source_runs: true
    require_backup: true
ai_frontier:
  enabled: true
""",
        encoding="utf-8",
    )
    for key, value in {
        "CONFIG_PATH": str(config),
        "INTELLIGENCE_ENABLED": "true",
        "INTELLIGENCE_DB_PATH": str(database),
        "AI_FRONTIER_DB_PATH": str(ai_database),
        "INTELLIGENCE_SQLITE_SYNCHRONOUS": "FULL",
        "TRENDRADAR_HEALTH_DIR": str(tmp_path / "health"),
        "TRENDRADAR_CONTROL_DIR": str(tmp_path / "control"),
        "TRENDRADAR_LOCK_DIR": str(tmp_path / "locks"),
        "TRENDRADAR_BACKUP_DIR": str(backup_dir),
        "TRENDRADAR_RELEASE_ID": "release-policy",
        "TRENDRADAR_HEALTH_EXPECTED_ROLES": "bot,worker",
        "TRENDRADAR_HEALTH_EXPECTED_SOURCES": ",".join(SOURCES),
        "INTELLIGENCE_HEALTH_REQUIRE_SOURCE_RUNS": "true",
        "INTELLIGENCE_HEALTH_REQUIRE_BACKUP": "true",
        "INTELLIGENCE_HEALTH_HEARTBEAT_MAX_AGE_SECONDS": "60",
        "INTELLIGENCE_HEALTH_SOURCE_MAX_AGE_HOURS": "6",
        "INTELLIGENCE_HEALTH_QUEUE_WAIT_SECONDS": "300",
        "INTELLIGENCE_HEALTH_BACKUP_MAX_AGE_HOURS": "26",
        "GEMINI_ENABLED": "false",
        "LARK_ENABLED": "false",
    }.items():
        monkeypatch.setenv(key, value)
    _write_sources(database, now)
    with AIFrontierStorage(ai_database, synchronous="FULL"):
        pass
    for role, state in (("bot", "connected"), ("worker", "running")):
        RoleHeartbeat(role, database).write(state=state, sqlite_synchronous="FULL")
    snapshot = backup.create_snapshot(
        [database, ai_database], backup_dir, release_id="release-policy", root=database.parent,
    )
    manifest_path = backup_dir / snapshot["backup_id"] / "manifest.json"
    _write_backup_time(manifest_path, now)
    return database, config, manifest_path, now, network_calls


@pytest.mark.parametrize("fault,errors", [
    (None, set()),
    ("bot", {"non_accepting_heartbeat:bot:connecting"}),
    ("worker", {"non_accepting_heartbeat:worker:connected"}),
    ("missing-bot", {"missing_heartbeat:bot", "sqlite_policy_mismatch:bot:unknown"}),
    ("old-release", {"release_mismatch:bot"}),
    ("unknown-release", {"release_mismatch:bot"}),
    ("missing-release", {"release_mismatch:bot"}),
    ("heartbeat-boundary", set()),
    ("stale-heartbeat", {"stale_heartbeat:bot"}),
    ("future-heartbeat", {"future_heartbeat:bot"}),
    ("source", {"source_unhealthy:rss:second-required"}),
    ("missing-source", {"missing_source_run:rss:second-required"}),
    ("source-boundary", set()),
    ("source-age", {"stale_source:rss:second-required"}),
    ("backup-receipt", {"backup_overdue:offsite"}),
    ("backup-boundary", set()),
    ("backup-age", {"backup_overdue:local", "backup_overdue:offsite"}),
    ("queue-boundary", set()),
    ("queue-age", {"queue_wait_exceeded"}),
])
def test_actual_release_policy_requires_roles_sources_and_backups(
    release_policy, capsys, fault, errors,
):
    database, config, manifest_path, now, network_calls = release_policy

    def check(expected_errors):
        policy = load_settings(config).intelligence_health_config
        assert policy["require_source_runs"] is True
        assert policy["require_backup"] is True
        assert policy["expected_roles"] == ["bot", "worker"]
        assert policy["expected_sources"] == list(SOURCES)
        paths = (database, database.with_name("ai_frontier.db"))
        before = [path.read_bytes() for path in paths]
        result = health.main(["--config", str(config), "--readiness", "--json"])
        report = json.loads(capsys.readouterr().out)
        assert result == (2 if expected_errors else 0), report
        assert report["status"] == ("unhealthy" if expected_errors else "healthy"), report
        assert set(report.get("errors", [])) == expected_errors, report
        assert report["database"]["schema"] == 6
        assert report["ai_frontier_database"]["schema"] == 1
        assert report["config"]["lark_enabled"] is False
        assert report["config"]["gemini_enabled"] is False
        assert [path.read_bytes() for path in paths] == before
        assert network_calls == []

    check(set())
    bot_path = RoleHeartbeat("bot", database).path
    if fault in {"bot", "worker"}:
        role, state = ("bot", "connecting") if fault == "bot" else ("worker", "connected")
        RoleHeartbeat(role, database).write(state=state, sqlite_synchronous="FULL")
    elif fault == "missing-bot":
        bot_path.unlink()
    elif fault in {"old-release", "unknown-release", "missing-release",
                   "heartbeat-boundary", "stale-heartbeat", "future-heartbeat"}:
        payload = json.loads(bot_path.read_text(encoding="utf-8"))
        if fault == "missing-release":
            del payload["release_id"]
        elif fault in {"old-release", "unknown-release"}:
            payload["release_id"] = "previous" if fault == "old-release" else "unknown"
        else:
            age = {"heartbeat-boundary": 60, "stale-heartbeat": 60.001, "future-heartbeat": -1}
            payload["updated_at"] = (now - timedelta(seconds=age[fault])).isoformat()
        bot_path.write_text(json.dumps(payload), encoding="utf-8")
    elif fault in {"source", "missing-source", "source-boundary", "source-age"}:
        with IntelligenceStorage(database, synchronous="FULL") as storage:
            if fault == "missing-source":
                storage.connection.execute(
                    "DELETE FROM source_runs WHERE adapter_id=?", (SOURCES[1],),
                )
            elif fault == "source":
                storage.connection.execute(
                    "UPDATE source_runs SET status='failed', error_count=1 WHERE adapter_id=?",
                    (SOURCES[1],),
                )
            else:
                age = 21600 if fault == "source-boundary" else 21600.001
                storage.connection.execute(
                    "UPDATE source_runs SET finished_at=? WHERE adapter_id=?",
                    ((now - timedelta(seconds=age)).isoformat(), SOURCES[1]),
                )
    elif fault == "backup-receipt":
        receipt_path = manifest_path.with_name("offsite-manifest.json")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["manifest_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    elif fault in {"backup-boundary", "backup-age"}:
        _write_backup_time(manifest_path, now, 93600 if fault == "backup-boundary" else 93600.001)
    elif fault in {"queue-boundary", "queue-age"}:
        age = 300 if fault == "queue-boundary" else 300.001
        with IntelligenceStorage(database, synchronous="FULL") as storage:
            storage.connection.execute(
                "INSERT INTO feishu_events (event_id,scope,status,owner,attempts,lease_until,"
                "updated_at,event_json) VALUES ('queued','scope','failed','',1,?,?,?)",
                (now.isoformat(), now.isoformat(), json.dumps({
                    "received_at": (now - timedelta(seconds=age)).isoformat(),
                })),
            )
    check(errors)
    for role, state in (("bot", "connected"), ("worker", "running")):
        RoleHeartbeat(role, database).write(state=state, sqlite_synchronous="FULL")
    _write_sources(database, now)
    _write_backup_time(manifest_path, now)
    with IntelligenceStorage(database, synchronous="FULL") as storage:
        storage.connection.execute("DELETE FROM feishu_events WHERE event_id='queued'")
    check(set())
