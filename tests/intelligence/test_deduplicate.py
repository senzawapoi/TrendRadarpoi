from datetime import datetime, timedelta, timezone

from trendradar.core.models import ContentItem
from trendradar.intelligence.deduplicate import Deduplicator
from trendradar.intelligence.storage import IntelligenceStorage

NOW = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)


def _item(
    title: str,
    *,
    source: str = "rss:a",
    url: str = "",
    published: datetime | None = None,
    collected: datetime = NOW,
) -> ContentItem:
    return ContentItem.create(
        title=title,
        url=url,
        source=source,
        domain="ai" if source.startswith("ai_frontier:") else "general",
        published_time=published,
        collected_at=collected,
        metadata={"source_content_id": url, "raw_url": url},
    )


def test_same_url_deduplicates_across_sources_and_keeps_observations():
    first = _item("First", url="https://example.com/post", source="rss:a")
    second = _item(
        "Second", url="https://example.com/post?utm_source=x", source="ai_frontier:blog"
    )
    result = Deduplicator().process([second, first])
    assert len(result.canonical_items) == 1
    assert len(result.observations) == 2
    assert {row.content_item_id for row in result.observations} == {first.id}


def test_exact_and_fuzzy_titles_dedupe_only_within_same_source_and_window():
    first = _item("A sufficiently long model announcement", collected=NOW)
    exact = _item("  A sufficiently long model announcement ", collected=NOW + timedelta(hours=2))
    fuzzy = _item("A sufficiently long model announcements", collected=NOW + timedelta(hours=3))
    cross_source = _item(
        "A sufficiently long model announcement",
        source="rss:b",
        collected=NOW + timedelta(hours=2),
    )
    outside = _item(
        "A sufficiently long model announcement",
        collected=NOW + timedelta(hours=25),
    )
    result = Deduplicator().process([outside, fuzzy, cross_source, exact, first])
    assert len(result.canonical_items) == 3
    assert result.canonical_ids[0] == outside.id
    assert result.canonical_ids[1] == first.id
    assert result.canonical_ids[2] == cross_source.id
    assert result.canonical_ids[3] == first.id
    assert result.canonical_ids[4] == first.id


def test_short_similar_titles_are_not_fuzzy_deduplicated():
    first = _item("Short title")
    second = _item("Short titles", collected=NOW + timedelta(hours=1))
    assert len(Deduplicator().process([first, second]).canonical_items) == 2


def test_new_batch_selects_earliest_event_then_id_as_canonical():
    later = _item("A sufficiently long release note", collected=NOW + timedelta(hours=1))
    earlier = _item("A sufficiently long release notes", collected=NOW)
    result = Deduplicator().process([later, earlier])
    assert result.canonical_items == [earlier]
    assert result.canonical_ids == [earlier.id, earlier.id]


def test_existing_observation_keeps_stored_canonical_id(tmp_path):
    original = _item("Original sufficiently long title")
    path = tmp_path / "intelligence.db"
    with IntelligenceStorage(path) as storage:
        first = Deduplicator(storage).process([original])
        storage.write_batch(first.canonical_items, first.observations)

        repeated = _item(
            "Changed title that would have another id",
            collected=NOW + timedelta(days=1),
        )
        repeated.metadata["source_content_id"] = original.id
        original_observation = storage.list_observations()[0]
        repeated.metadata["source_content_id"] = original_observation["source_content_id"]
        second = Deduplicator(storage).process([repeated])
        assert second.canonical_items == []
        assert second.canonical_ids == [original.id]


def test_repeated_persistence_is_idempotent(tmp_path):
    item = _item("Persistent title", url="https://example.com/persistent")
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        for _ in range(2):
            result = Deduplicator(storage).process([item])
            storage.write_batch(result.canonical_items, result.observations)
        assert storage.count() == 1
        assert storage.count("content_observations") == 1
