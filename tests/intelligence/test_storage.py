import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from trendradar.core.models import (
    Cluster,
    ContentItem,
    Story,
    deterministic_cluster_id,
    deterministic_story_id,
)
from trendradar.intelligence.storage import (
    SCHEMA_VERSION,
    ContentObservation,
    IntelligenceStorage,
    SourceRunRecord,
)

NOW = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)


def _item(url: str = "https://example.com/1", title: str = "Title") -> ContentItem:
    return ContentItem.create(
        title=title,
        content="Body",
        url=url,
        source="rss:feed",
        domain="general",
        collected_at=NOW,
        metadata={"source_content_id": url or title, "raw_url": url},
    )


def test_storage_initializes_required_pragmas_and_schema(tmp_path):
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        assert storage.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert storage.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert storage.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert storage.connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert storage.connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        tables = {
            row[0]
            for row in storage.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {
            "clusters",
            "content_items",
            "content_observations",
            "source_runs",
            "stories",
            "story_members",
            "assistant_sessions",
            "assistant_messages",
        } <= tables


def test_storage_strict_open_refuses_missing_or_unmigrated_database(tmp_path):
    path = tmp_path / "intelligence.db"
    with pytest.raises(FileNotFoundError):
        IntelligenceStorage.open_existing(path)
    IntelligenceStorage(path).close()
    with IntelligenceStorage.open_existing(path) as storage:
        assert storage.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_storage_closes_connection_when_initialization_fails(tmp_path, monkeypatch):
    captured = {}

    def fail_initialization(storage):
        captured["connection"] = storage.connection
        raise RuntimeError("migration failed")

    monkeypatch.setattr(IntelligenceStorage, "_initialize_schema", fail_initialization)
    with pytest.raises(RuntimeError, match="migration failed"):
        IntelligenceStorage(tmp_path / "intelligence.db")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        captured["connection"].execute("SELECT 1")


def test_write_batch_persists_provenance_and_is_idempotent(tmp_path):
    item = _item()
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        assert storage.write_batch([item]) == (1, 1)
        assert storage.write_batch([item]) == (0, 0)
        assert storage.count() == 1
        assert storage.count("content_observations") == 1
        assert storage.get_item(item.id) == item


def test_write_batch_rolls_back_item_when_observation_is_invalid(tmp_path):
    item = _item()
    invalid = ContentObservation(
        content_item_id="00000000-0000-0000-0000-000000000000",
        source="rss:feed",
        source_content_id="missing",
        title="Missing",
        observed_at=NOW,
    )
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        with pytest.raises(sqlite3.IntegrityError):
            storage.write_batch([item], [invalid])
        assert storage.count() == 0


def test_observation_keeps_first_and_last_seen(tmp_path):
    item = _item()
    first = ContentObservation.from_item(item)
    later = ContentObservation.from_item(item)
    later.observed_at = NOW + timedelta(hours=2)
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        storage.write_batch([item], [first])
        storage.write_batch([item], [later])
        row = storage.connection.execute(
            "SELECT first_observed_at, last_observed_at FROM content_observations"
        ).fetchone()
        assert row["first_observed_at"] == NOW.isoformat()
        assert row["last_observed_at"] == (NOW + timedelta(hours=2)).isoformat()


def test_source_run_is_recorded(tmp_path):
    record = SourceRunRecord(
        adapter_id="rss:feed",
        status="degraded",
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=1),
        duration_ms=1000,
        fetched_count=2,
        normalized_count=1,
        error_count=1,
        error_summary="one failed",
    )
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        run_id = storage.record_source_run(record)
        assert run_id == 1
        assert storage.count("source_runs") == 1


def test_two_connections_can_upsert_same_item(tmp_path):
    path = tmp_path / "intelligence.db"
    item = _item()
    with IntelligenceStorage(path) as first, IntelligenceStorage(path) as second:
        assert first.write_batch([item]) == (1, 1)
        assert second.write_batch([item]) == (0, 0)
        assert second.count() == 1


def _story(item: ContentItem) -> tuple[Cluster, Story]:
    cluster = Cluster(
        id=deterministic_cluster_id([item.id]),
        member_ids=[item.id],
        domain=item.domain,
        event_time=NOW,
        last_activity_at=NOW,
    )
    identity_key = f"{item.domain}:{item.id}"
    story = Story(
        id=deterministic_story_id(identity_key),
        identity_key=identity_key,
        title=item.title,
        summary=item.content,
        domain=item.domain,
        event_time=NOW,
        last_activity_at=NOW,
        member_ids=[item.id],
        metadata={"cluster_id": cluster.id},
    )
    return cluster, story


def test_v1_database_migrates_without_losing_content(tmp_path):
    path = tmp_path / "intelligence.db"
    with IntelligenceStorage(path) as storage:
        storage.write_batch([_item()])
        storage.connection.execute("DROP TABLE story_members")
        storage.connection.execute("DROP TABLE stories")
        storage.connection.execute("DROP TABLE clusters")
        storage.connection.execute("PRAGMA user_version = 1")

    with IntelligenceStorage(path) as migrated:
        assert migrated.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert migrated.count() == 1
        assert migrated.count("stories") == 0


def test_v2_database_migrates_to_assistant_schema_without_losing_stories(tmp_path):
    path = tmp_path / "intelligence.db"
    item = _item()
    cluster, story = _story(item)
    with IntelligenceStorage(path) as storage:
        storage.write_batch([item])
        storage.upsert_story_batch([cluster], [story])
        storage.connection.execute("DROP TABLE assistant_messages")
        storage.connection.execute("DROP TABLE assistant_sessions")
        storage.connection.execute("PRAGMA user_version = 2")

    with IntelligenceStorage(path) as migrated:
        assert migrated.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert migrated.get_story(story.id) == story
        assert migrated.count("assistant_sessions") == 0
        assert migrated.count("assistant_messages") == 0


def test_v3_migration_rolls_back_on_schema_failure(tmp_path, monkeypatch):
    import trendradar.intelligence.storage as storage_module

    path = tmp_path / "intelligence.db"
    with IntelligenceStorage(path) as storage:
        storage.connection.execute("DROP TABLE assistant_messages")
        storage.connection.execute("DROP TABLE assistant_sessions")
        storage.connection.execute("PRAGMA user_version = 2")

    monkeypatch.setattr(
        storage_module,
        "ASSISTANT_SCHEMA",
        "CREATE TABLE assistant_sessions (session_id TEXT); INVALID SQL;",
    )
    with pytest.raises(sqlite3.OperationalError):
        IntelligenceStorage(path)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "assistant_sessions" not in tables
    finally:
        connection.close()


def test_from_connection_initializes_schema_without_taking_ownership():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    storage = IntelligenceStorage.from_connection(connection)

    storage.close()

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO assistant_messages
                (session_id, sequence, request_id, role, content, created_at)
            VALUES ('missing', 0, 'request', 'tool', 'content', ?)
            """,
            (NOW.isoformat(),),
        )
    connection.close()


def test_storage_rejects_unsupported_future_schema(tmp_path):
    path = tmp_path / "intelligence.db"
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    connection.close()

    with pytest.raises(RuntimeError, match="newer than supported"):
        IntelligenceStorage(path)


def test_story_batch_is_idempotent_and_preserves_evidence(tmp_path):
    item = _item()
    cluster, story = _story(item)
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        storage.write_batch([item])
        assert storage.upsert_story_batch([cluster], [story]) == (1, 1, 1)
        assert storage.upsert_story_batch([cluster], [story]) == (0, 0, 0)
        assert storage.get_story(story.id) == story
        assert storage.list_story_items(story.id) == [item]
        assert len(storage.list_story_evidence(story.id)) == 1


def test_two_connections_can_upsert_same_story(tmp_path):
    path = tmp_path / "intelligence.db"
    item = _item()
    cluster, story = _story(item)
    with IntelligenceStorage(path) as first, IntelligenceStorage(path) as second:
        first.write_batch([item])
        assert second.upsert_story_batch([cluster], [story]) == (1, 1, 1)
        assert first.upsert_story_batch([cluster], [story]) == (0, 0, 0)
        assert first.count("stories") == 1
        assert second.count("story_members") == 1


def test_story_listing_uses_half_open_time_range(tmp_path):
    item = _item()
    cluster, story = _story(item)
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        storage.write_batch([item])
        storage.upsert_story_batch([cluster], [story])

        assert storage.list_stories(start=NOW - timedelta(days=1), end=NOW) == []
        assert storage.list_stories(
            start=NOW - timedelta(days=1),
            end=NOW + timedelta(microseconds=1),
        ) == [story]


def test_story_batch_rolls_back_when_membership_references_missing_item(tmp_path):
    item = _item()
    cluster, story = _story(item)
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        with pytest.raises(sqlite3.IntegrityError):
            storage.upsert_story_batch([cluster], [story])
        assert storage.count("clusters") == 0
        assert storage.count("stories") == 0
        assert storage.count("story_members") == 0


def test_story_upsert_never_shrinks_persisted_membership(tmp_path):
    first = _item("https://example.com/1", "First")
    second = _item("https://example.com/2", "Second")
    cluster, story = _story(first)
    cluster.member_ids = sorted([first.id, second.id])
    cluster.id = deterministic_cluster_id(cluster.member_ids)
    story.member_ids = sorted([first.id, second.id])
    story.metadata["cluster_id"] = cluster.id

    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        storage.write_batch([first, second])
        storage.upsert_story_batch([cluster], [story])
        reduced = Story.from_dict({**story.to_dict(), "member_ids": [first.id]})
        storage.upsert_story_batch([], [reduced])

        persisted = storage.get_story(story.id)
        assert persisted is not None
        assert persisted.member_ids == sorted([first.id, second.id])
        assert storage.count("story_members") == 2


def test_storage_finds_exact_security_cve_context_across_time(tmp_path):
    matching = ContentItem.create(
        title="Matching CVE",
        url="https://example.com/cve-1",
        source="security:nvd",
        domain="security",
        collected_at=NOW,
        metadata={"cve_ids": ["cve-2026-12345"]},
    )
    unrelated = ContentItem.create(
        title="Unrelated CVE",
        url="https://example.com/cve-2",
        source="security:nvd",
        domain="security",
        collected_at=NOW,
        metadata={"cve_ids": ["CVE-2026-99999"]},
    )
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        storage.write_batch([matching, unrelated])

        found = storage.list_security_items_by_cves(["CVE-2026-12345"])
        assert [item.id for item in found] == [matching.id]
        assert found[0].metadata["cve_ids"] == ["CVE-2026-12345"]
        assert storage.list_security_items_by_cves(["invalid"]) == []


def test_security_view_uses_observation_when_general_canonical_owns_url(tmp_path):
    general = ContentItem.create(
        title="Vendor advisory",
        url="https://nvd.nist.gov/vuln/detail/CVE-2026-12345",
        source="rss:vendor",
        domain="general",
        collected_at=NOW,
        metadata={"source_content_id": "vendor-1"},
    )
    security = ContentItem.create(
        title="CVE-2026-12345: NVD record",
        url=general.url,
        source="security:nvd",
        domain="security",
        published_time=NOW - timedelta(days=2),
        collected_at=NOW + timedelta(hours=1),
        metadata={
            "source_content_id": "CVE-2026-12345",
            "source_name": "NVD",
            "cve_ids": ["CVE-2026-12345"],
            "entities": ["CVE-2026-12345"],
            "cvss_score": 8.8,
            "published_time": (NOW - timedelta(days=2)).isoformat(),
        },
    )
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        storage.write_batch([general])
        from trendradar.intelligence.pipeline import process_content_items

        result = process_content_items([security], storage=storage)
        view = storage.get_security_item_view(general.id)
        found = storage.list_security_items_by_cves(["cve-2026-12345"])

        assert result.canonical_ids == [general.id]
        assert storage.count("content_items") == 1
        assert view is not None
        assert view.id == general.id
        assert view.domain == "security"
        assert view.source == "security:nvd"
        assert view.metadata["cvss_score"] == 8.8
        assert [item.id for item in found] == [general.id]
