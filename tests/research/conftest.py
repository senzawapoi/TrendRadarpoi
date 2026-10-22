from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trendradar.core.models import (
    Cluster,
    ContentItem,
    ImportanceBreakdown,
    Story,
    deterministic_cluster_id,
    deterministic_story_id,
)
from trendradar.intelligence.storage import IntelligenceStorage

NOW = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)


@pytest.fixture
def seeded_intelligence(tmp_path):
    storage = IntelligenceStorage(tmp_path / "intelligence.db")
    first = ContentItem.create(
        title="Alpha AI model release", content="The Alpha model shipped.",
        url="https://example.com/alpha-release", source="ai_frontier:blog", domain="ai",
        published_time=NOW - timedelta(hours=4), collected_at=NOW - timedelta(hours=3),
        tags=["AI", "Alpha"], metadata={"source_content_id": "alpha-blog"},
    )
    second = ContentItem.create(
        title="Developers discuss Alpha AI model", content="Discussion confirms details.",
        url="https://example.net/alpha-discussion", source="ai_frontier:hackernews", domain="ai",
        published_time=NOW - timedelta(hours=3), collected_at=NOW - timedelta(hours=2),
        tags=["AI", "Alpha"], metadata={"source_content_id": "alpha-hn"},
    )
    standalone = ContentItem.create(
        title="Independent AI chip bulletin", content="A separate update.",
        url="https://example.org/chip-update", source="rss:hardware", domain="ai",
        published_time=NOW - timedelta(hours=2), collected_at=NOW - timedelta(hours=1),
        tags=["AI", "hardware"], metadata={"source_content_id": "chip-update"},
    )
    storage.write_batch([first, second, standalone])
    member_ids = [first.id, second.id]
    cluster = Cluster(
        id=deterministic_cluster_id(member_ids), member_ids=member_ids, domain="ai",
        event_time=first.published_time, last_activity_at=second.collected_at,
        tags=["AI", "Alpha"], entities=["Alpha"],
    )
    story = Story(
        id=deterministic_story_id("ai:alpha-release"), identity_key="ai:alpha-release",
        title="Alpha AI model released", summary="Two sources describe the release.", domain="ai",
        event_time=first.published_time, last_activity_at=second.collected_at,
        member_ids=member_ids, tags=["AI", "Alpha"], entities=["Alpha"],
        importance=ImportanceBreakdown(score=88, reasons=["multiple sources"]),
        metadata={"cluster_id": cluster.id},
    )
    storage.upsert_story_batch([cluster], [story])
    try:
        yield type("Seeded", (), {"storage": storage, "story": story})()
    finally:
        storage.close()
