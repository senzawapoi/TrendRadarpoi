"""Explicit v6-to-v7 migration preserves old rows and rejects partial upgrades."""

import sqlite3

import pytest

from trendradar.intelligence import storage as module
from trendradar.intelligence.storage import IntelligenceStorage


def v6_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            module.BASE_SCHEMA + module.STORY_SCHEMA + module.ASSISTANT_SCHEMA
            + module.FEISHU_SCHEMA + module.FEISHU_DELIVERY_SCHEMA
            + "PRAGMA user_version=6;"
        )
        connection.execute(
            """INSERT INTO stories
               (id, identity_key, title, domain, event_time, last_activity_at, generator_version,
                created_at, updated_at) VALUES ('story', 'identity', 'saved', 'general',
                '2020-01-01T00:00:00+00:00', '2020-01-01T00:00:00+00:00', 'v1',
                '2026-10-01T00:00:00+00:00', '2026-10-22T00:00:00+00:00')"""
        )
        connection.execute(
            """INSERT INTO feishu_events (event_id, scope, status, owner, lease_until, updated_at,
                                         reply_json, event_json, binding_json, delivery_attempts)
               VALUES ('event', 'scope', 'completed', 'owner', 'lease', 'stamp',
                       '{"text":"saved"}', '{}', '{}', 1)"""
        )
        connection.execute(
            """INSERT INTO feishu_deliveries
                   (delivery_key, status, owner, lease_until, updated_at, chunks_json, next_chunk)
               VALUES ('daily', 'completed', 'owner', 'lease', 'stamp', '["saved"]', 1)"""
        )


def test_v6_requires_explicit_migration_and_keeps_every_existing_schema_and_row(tmp_path):
    path = tmp_path / "db"
    v6_database(path)
    with sqlite3.connect(path) as connection:
        schema_before = list(connection.execute("SELECT type, name, sql FROM sqlite_master"))
        data_before = {name: list(connection.execute(f"SELECT * FROM {name}")) for name in (
            "stories", "feishu_events", "feishu_deliveries",
        )}
    with pytest.raises(RuntimeError, match="explicit migration"):
        IntelligenceStorage.open_existing(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
    with IntelligenceStorage.migrate(path) as storage:
        assert storage.connection.execute("PRAGMA user_version").fetchone()[0] == 7
        for name, rows in data_before.items():
            assert [tuple(row) for row in storage.connection.execute(f"SELECT * FROM {name}")] == rows
        schema_after = {tuple(row) for row in storage.connection.execute(
            "SELECT type, name, sql FROM sqlite_master"
        )}
        assert set(schema_before) <= schema_after
        assert storage.connection.execute("SELECT COUNT(*) FROM lark_story_deliveries").fetchone()[0] == 0
    with IntelligenceStorage.open_existing(path):
        pass
    with IntelligenceStorage.migrate(path) as storage:
        assert storage.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_v7_migration_failure_rolls_back_tables_indexes_and_version(tmp_path, monkeypatch):
    path = tmp_path / "db"
    v6_database(path)
    monkeypatch.setattr(module, "LARK_INSTANT_SCHEMA", module.LARK_INSTANT_SCHEMA + "INVALID SQL;")
    with pytest.raises(sqlite3.OperationalError):
        IntelligenceStorage.migrate(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert not list(connection.execute("SELECT name FROM sqlite_master WHERE name LIKE 'lark_%'"))
        assert not list(connection.execute(
            "SELECT name FROM sqlite_master WHERE name='idx_stories_first_persisted'"
        ))
        assert connection.execute("SELECT title FROM stories").fetchone()[0] == "saved"


def test_incomplete_v7_database_is_rejected_without_repair(tmp_path):
    path = tmp_path / "db"
    with IntelligenceStorage(path) as storage:
        storage.connection.execute("DROP TABLE lark_story_deliveries")
    with pytest.raises(RuntimeError, match="incomplete or corrupt"):
        IntelligenceStorage.open_existing(path)
