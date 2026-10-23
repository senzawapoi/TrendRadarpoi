import json

from trendradar.core.heartbeat import RoleHeartbeat
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops.health import collect_health, main
from trendradar.ops.maintenance import (
    clear_guard,
    control_directory,
    read_guard,
    set_guard,
)


def test_health_missing_database_is_unhealthy_without_creating_it(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("intelligence:\n  enabled: true\n", encoding="utf-8")
    database = tmp_path / "missing.db"
    monkeypatch.setenv("INTELLIGENCE_DB_PATH", str(database))
    report = collect_health(config)
    assert report["status"] == "unhealthy"
    assert "database_missing" in report["errors"]
    assert not database.exists()


def test_health_reads_database_and_heartbeat_without_provider_io(tmp_path, monkeypatch):
    database = tmp_path / "intelligence.db"
    config = tmp_path / "config.yaml"
    config.write_text("intelligence:\n  enabled: true\n", encoding="utf-8")
    with IntelligenceStorage(database):
        pass
    monkeypatch.setenv("INTELLIGENCE_DB_PATH", str(database))
    monkeypatch.setenv("TRENDRADAR_HEALTH_DIR", str(tmp_path / "health"))
    heartbeat = RoleHeartbeat("worker", database)
    heartbeat.write(state="running", last_result="sent")
    report = collect_health(config)
    assert report["status"] == "healthy"
    assert report["database"]["schema"] == 7
    assert report["heartbeats"]["worker"]["state"] == "running"
    assert "last_result" not in json.dumps(report)


def test_health_json_has_no_secret_and_stable_exit_codes(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.yaml"
    config.write_text("intelligence:\n  enabled: false\n", encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-print")
    assert main(["--config", str(config), "--json"]) == 0
    output = capsys.readouterr().out
    assert "must-not-print" not in output
    payload = json.loads(output)
    assert payload["status"] == "disabled"


def test_readiness_gate_rejects_disabled_runtime(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("intelligence:\n  enabled: false\n", encoding="utf-8")
    assert main(["--config", str(config), "--readiness", "--json"]) == 2


def test_restore_guard_is_persistent_and_visible_to_health(tmp_path, monkeypatch):
    database = tmp_path / "intelligence.db"
    with IntelligenceStorage(database):
        pass
    config = tmp_path / "config.yaml"
    config.write_text("intelligence:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("INTELLIGENCE_DB_PATH", str(database))
    guard = set_guard(database, reason="isolated restore")
    assert guard["allow_external_send"] is False
    assert read_guard(database)["reason"] == "isolated restore"
    assert collect_health(config)["status"] == "maintenance"
    assert clear_guard(database)
    assert read_guard(database) is None


def test_health_rejects_missing_expected_role_heartbeat(tmp_path, monkeypatch):
    database = tmp_path / "intelligence.db"
    with IntelligenceStorage(database):
        pass
    config = tmp_path / "config.yaml"
    config.write_text(
        """intelligence:
  enabled: true
  health:
    expected_roles: [worker]
    require_backup: false
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("INTELLIGENCE_DB_PATH", str(database))
    monkeypatch.setenv("TRENDRADAR_HEALTH_DIR", str(tmp_path / "health"))
    report = collect_health(config)
    assert report["status"] == "unhealthy"
    assert "missing_heartbeat:worker" in report["errors"]


def test_health_rejects_disconnected_and_old_release_heartbeats(tmp_path, monkeypatch):
    database = tmp_path / "intelligence.db"
    with IntelligenceStorage(database):
        pass
    config = tmp_path / "config.yaml"
    config.write_text(
        """intelligence:
  enabled: true
  health:
    expected_roles: [bot]
    require_backup: false
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("INTELLIGENCE_DB_PATH", str(database))
    monkeypatch.setenv("TRENDRADAR_HEALTH_DIR", str(tmp_path / "health"))
    monkeypatch.setenv("TRENDRADAR_RELEASE_ID", "release-new")
    heartbeat = RoleHeartbeat("bot", database)
    heartbeat.write(state="disconnected")
    heartbeat_path = tmp_path / "health" / "bot.json"
    payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    payload["release_id"] = "release-old"
    heartbeat_path.write_text(json.dumps(payload), encoding="utf-8")

    report = collect_health(config)

    assert report["status"] == "unhealthy"
    assert "disconnected_heartbeat:bot" in report["errors"]
    assert "release_mismatch:bot" in report["errors"]


def test_health_ignores_malformed_offsite_array_without_crashing(tmp_path, monkeypatch):
    database = tmp_path / "intelligence.db"
    with IntelligenceStorage(database):
        pass
    config = tmp_path / "config.yaml"
    config.write_text("intelligence:\n  enabled: true\n", encoding="utf-8")
    backup = tmp_path / "backups" / "snapshot"
    backup.mkdir(parents=True)
    (backup / "manifest.json").write_text(
        json.dumps({
            "backup_id": "snapshot",
            "created_at": "2026-10-13T00:00:00+00:00",
            "complete": True,
            "databases": [],
        }),
        encoding="utf-8",
    )
    (backup / "offsite-manifest.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("INTELLIGENCE_DB_PATH", str(database))
    monkeypatch.setenv("TRENDRADAR_BACKUP_DIR", str(tmp_path / "backups"))

    report = collect_health(config)

    assert report["status"] in {"healthy", "degraded"}
    assert report["backups"]["offsite"] is None


def test_default_restore_control_directory_is_stable_parent_of_output(tmp_path, monkeypatch):
    monkeypatch.delenv("TRENDRADAR_CONTROL_DIR", raising=False)
    database = tmp_path / "output" / "intelligence.db"
    assert control_directory(database) == tmp_path / "control"
