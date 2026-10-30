import json
import sqlite3

import pytest

from trendradar.ai_frontier.storage import AIFrontierStorage
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops.backup import (
    activate_restore,
    create_snapshot,
    discover_databases,
    restore_snapshot,
)


def test_snapshot_uses_online_backup_and_restore_isolated(tmp_path):
    source = tmp_path / "source.db"
    with IntelligenceStorage(source) as storage:
        storage.connection.execute(
            "INSERT INTO content_items "
            "(id, title, content, url, source, domain, published_time, collected_at, "
            "tags_json, metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("item", "title", "content", "https://example.com", "rss:test", "general", None,
             "2026-10-12T00:00:00+00:00", "[]", "{}", "2026-10-12T00:00:00+00:00",
             "2026-10-12T00:00:00+00:00"),
        )
    result = create_snapshot([source], tmp_path / "backups", release_id="test-release")
    snapshot = tmp_path / "backups" / result["backup_id"]
    assert result["complete"] is True
    assert json.loads((snapshot / "manifest.json").read_text())["complete"] is True

    restored = restore_snapshot(snapshot, tmp_path / "restored")
    assert (tmp_path / "restored" / "database-0.db").is_file()
    assert restored["databases"][0]["integrity_check"] == "ok"


def test_snapshot_of_wal_source_is_self_contained_and_validation_leaves_no_sidecars(tmp_path):
    source = tmp_path / "source.db"
    with IntelligenceStorage(source) as storage:
        assert storage.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    result = create_snapshot([source], tmp_path / "backups")
    snapshot = tmp_path / "backups" / result["backup_id"]
    assert sorted(path.name for path in snapshot.iterdir()) == ["database-0.db", "manifest.json"]
    connection = sqlite3.connect(snapshot / "database-0.db")
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        connection.close()
    restore_snapshot(snapshot, tmp_path / "restored")
    assert sorted(path.name for path in snapshot.iterdir()) == ["database-0.db", "manifest.json"]


def test_snapshot_does_not_overwrite_existing_destination(tmp_path):
    source = tmp_path / "source.db"
    with IntelligenceStorage(source):
        pass
    destination = tmp_path / "backups"
    first = create_snapshot([source], destination)
    restore_snapshot(destination / first["backup_id"], tmp_path / "existing")
    with pytest.raises(FileExistsError):
        restore_snapshot(destination / first["backup_id"], tmp_path / "existing")


def test_discover_databases_includes_legacy_date_partitions(tmp_path):
    output = tmp_path / "output"
    (output / "news").mkdir(parents=True)
    (output / "rss").mkdir()
    for path in (
        output / "intelligence.db",
        output / "ai_frontier.db",
        output / "news" / "2026-10-12.db",
        output / "rss" / "2026-10-12.db",
    ):
        path.touch()
    assert discover_databases(output) == [
        output / "intelligence.db",
        output / "ai_frontier.db",
        output / "news" / "2026-10-12.db",
        output / "rss" / "2026-10-12.db",
    ]


def test_restore_and_activate_complete_database_set_by_relative_paths(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    intelligence = output / "intelligence.db"
    ai_frontier = output / "ai_frontier.db"
    with IntelligenceStorage(intelligence):
        pass
    with AIFrontierStorage(ai_frontier):
        pass
    (output / "news").mkdir()
    news = output / "news" / "2026-10-12.db"
    with IntelligenceStorage(news):
        pass

    snapshot = create_snapshot(
        discover_databases(output),
        tmp_path / "backups",
        root=output,
        release_id="restore-test",
    )
    restored_path = tmp_path / "restored"
    restore_snapshot(
        tmp_path / "backups" / snapshot["backup_id"],
        restored_path,
        guard_database=intelligence,
    )
    result = activate_restore(restored_path, intelligence, root=output)

    assert set(result["restored_databases"]) == {
        str(intelligence.resolve()),
        str(ai_frontier.resolve()),
        str(news.resolve()),
    }
    assert intelligence.is_file() and ai_frontier.is_file() and news.is_file()
