"""Read-only backlog, age, failure and restore quarantine health."""

import json
from datetime import timedelta
from unittest.mock import Mock

import pytest

from trendradar.core.settings import load_settings
from trendradar.integrations.feishu.config import FeishuConfig
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops import health
from trendradar.ops.maintenance import clear_guard, set_guard

from .test_instant import NOW, scheduler, seed


@pytest.mark.parametrize("mode", ["instant", "INSTANT", "InStAnT", " \tINSTANT \n"])
@pytest.mark.parametrize("source", ["environment", "yaml"])
def test_health_counts_unregistered_overflow_and_saved_failures_without_exposing_content(
    tmp_path, monkeypatch, mode, source,
):
    path = tmp_path / "db"
    config = tmp_path / "config.yaml"
    config.write_text(
        "intelligence:\n  enabled: true\n"
        + (f"lark:\n  delivery:\n    mode: {json.dumps(mode)}\n" if source == "yaml" else ""),
        encoding="utf-8",
    )
    monkeypatch.setenv("INTELLIGENCE_DB_PATH", str(path))
    monkeypatch.setenv("LARK_ENABLED", "true")
    monkeypatch.setenv("LARK_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("LARK_DELIVERY_TARGET", "chat")
    monkeypatch.delenv("FEISHU_DELIVERY_MODE", raising=False)
    if source == "environment":
        monkeypatch.setenv("LARK_DELIVERY_MODE", mode)
    else:
        monkeypatch.delenv("LARK_DELIVERY_MODE", raising=False)
    monkeypatch.setenv("INTELLIGENCE_HEALTH_QUEUE_WAIT_SECONDS", "120")
    monkeypatch.setattr(health, "_utc_now", lambda: NOW + timedelta(seconds=301))
    settings = load_settings(config)
    transport = FeishuConfig.from_settings(settings)
    assert transport.delivery_mode == "instant" and transport.delivery_enabled
    with IntelligenceStorage(path) as storage:
        seed(storage, 25)
        run = scheduler(storage, Mock(send=Mock(return_value=False)), config=transport)
        assert run.tick() == "send_failed"
        before = storage.connection.total_changes
        report = health.collect_health(config)
        instant = report["instant_delivery"]
        assert instant["backlog"] == 25
        assert instant["pending_stories"] == 20
        assert instant["unregistered_stories"] == 5
        assert instant["failed_batches"] == 1
        assert instant["oldest_age_seconds"] == 301
        expected_errors = {"instant_delivery_failed", "instant_delivery_wait_exceeded"}
        assert expected_errors <= set(report.get("warnings", []))
        assert settings.lark_config["delivery_mode"] == "instant"
        assert report["config"]["lark_delivery_mode"] == transport.delivery_mode
        assert storage.connection.total_changes == before
        output = json.dumps(report)
        assert "Story 000 marker" not in output and '"chat"' not in output
        readiness = health.collect_health(config, readiness=True)
        assert readiness["status"] == "unhealthy"
        assert {
            error for error in readiness.get("errors", []) if error.startswith("instant_delivery_")
        } == expected_errors
        storage.connection.execute("UPDATE lark_instant_batches SET status='processing'")
        report = health.collect_health(config)
        assert report["instant_delivery"]["expired_leases"] == 1
        assert "instant_delivery_lease_expired" in report["warnings"]
        set_guard(path, reason="restore", recovery_cutover_at=NOW.isoformat())
        before = storage.connection.total_changes
        report = health.collect_health(config, readiness=True, allow_maintenance=True)
        assert report["instant_delivery"]["restore_held_stories"] == 25
        assert report["instant_delivery"]["backlog"] == 0
        assert report["instant_delivery"]["failed_batches"] == 0
        assert report["instant_delivery"]["expired_leases"] == 0
        assert not any(item.startswith("instant_delivery_") for item in report.get("errors", []))
        assert storage.connection.total_changes == before
        clear_guard(path)
        assert run.tick() == "quarantined"
        report = health.collect_health(config)
        assert report["instant_delivery"]["backlog"] == 0
        assert report["instant_delivery"]["oldest_age_seconds"] == 0
        assert report["instant_delivery"]["quarantined_stories"] == 25
        assert report["instant_delivery"]["restore_held_stories"] == 0
        assert report["instant_delivery"]["batches"] == {"quarantined": 1}


def test_health_missing_instant_tables_fails_closed_and_daily_does_not_alert(tmp_path, monkeypatch):
    path = tmp_path / "db"
    config = tmp_path / "config.yaml"
    config.write_text("intelligence:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("INTELLIGENCE_DB_PATH", str(path))
    monkeypatch.setenv("LARK_DELIVERY_TARGET", "chat")
    monkeypatch.setenv("LARK_DELIVERY_MODE", "daily")
    with IntelligenceStorage(path) as storage:
        seed(storage, persisted=NOW - timedelta(days=365))
        report = health.collect_health(config)
        assert "instant_delivery_wait_exceeded" not in report.get("warnings", [])
        storage.connection.execute("DROP TABLE lark_story_deliveries")
        report = health.collect_health(config)
        assert report["status"] == "unhealthy"
        assert "database_read_failed:OperationalError" in report["errors"]
