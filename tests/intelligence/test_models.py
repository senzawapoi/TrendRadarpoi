from datetime import datetime, timedelta, timezone

import pytest

from trendradar.ai_frontier.sources.base import AIItem
from trendradar.core.models import (
    ContentItem,
    ai_item_from_content,
    content_from_ai_item,
    content_from_news_item,
    content_from_rss_item,
    news_item_from_content,
    rss_item_from_content,
)
from trendradar.storage.base import NewsItem, RSSItem

NOW = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)


def test_content_item_requires_aware_timestamps_and_supported_domain():
    with pytest.raises(ValueError, match="collected_at"):
        ContentItem.create(
            title="title",
            source="rss:test",
            domain="general",
            collected_at=datetime(2026, 8, 21),
        )
    security = ContentItem.create(
        title="CVE update", source="security:nvd", domain="security", collected_at=NOW
    )
    assert security.domain == "security"

    with pytest.raises(ValueError, match="unsupported domain"):
        ContentItem.create(
            title="title", source="rss:test", domain="finance", collected_at=NOW
        )


def test_content_item_converts_timestamps_to_utc_and_round_trips_json():
    local = timezone(timedelta(hours=8))
    item = ContentItem.create(
        title="ＡＩ   News",
        content="  line\n break ",
        url="HTTPS://Example.COM:443/a?b=2&utm_source=x&a=1#part",
        source="rss:feed",
        domain="AI",
        published_time=datetime(2026, 8, 21, 20, tzinfo=local),
        collected_at=datetime(2026, 8, 21, 21, tzinfo=local),
        tags=[" AI ", "ai", "News"],
        metadata={"seen": datetime(2026, 8, 21, 21, tzinfo=local)},
    )

    restored = ContentItem.from_json(item.to_json())

    assert restored == item
    assert item.title == "AI News"
    assert item.content == "line break"
    assert item.url == "https://example.com/a?a=1&b=2"
    assert item.published_time == NOW
    assert item.tags == ["AI", "News"]


def test_content_id_is_stable_for_url_and_source_independent():
    first = ContentItem.create(
        title="One",
        url="https://EXAMPLE.com/post?utm_source=x&id=3",
        source="rss:a",
        domain="general",
        collected_at=NOW,
    )
    second = ContentItem.create(
        title="Changed",
        url="https://example.com/post?id=3#fragment",
        source="ai_frontier:blog",
        domain="ai",
        collected_at=NOW + timedelta(days=1),
    )
    assert first.id == second.id


def test_content_id_without_url_uses_source_title_and_event_date():
    first = ContentItem.create(
        title="  Same　Title ", source="newsnow:a", domain="general", collected_at=NOW
    )
    same = ContentItem.create(
        title="same title",
        source="newsnow:a",
        domain="general",
        collected_at=NOW + timedelta(hours=10),
    )
    next_day = ContentItem.create(
        title="same title",
        source="newsnow:a",
        domain="general",
        collected_at=NOW + timedelta(days=1),
    )
    assert first.id == same.id
    assert first.id != next_day.id


def test_news_item_lossless_round_trip():
    original = NewsItem(
        title="Headline",
        source_id="toutiao",
        source_name="Toutiao",
        rank=2,
        url="https://example.com/?utm_source=x&id=1",
        mobile_url="https://m.example.com/1",
        crawl_time="20:00",
        ranks=[2, 4],
        first_time="19:00",
        last_time="20:00",
        count=2,
        title_translated="标题",
        title_english="Headline",
        summary="Summary",
        summary_translated="摘要",
        summary_english="Summary",
        is_english=True,
    )
    content = content_from_news_item(original, collected_at=NOW)
    assert content.source == "newsnow:toutiao"
    assert news_item_from_content(content) == original


def test_rss_item_lossless_round_trip():
    original = RSSItem(
        title="Post",
        feed_id="feed",
        feed_name="Feed",
        url="https://example.com/post",
        published_at="2026-08-21T12:00:00+00:00",
        summary="Body",
        author="Author",
        crawl_time="20:00",
        first_time="20:00",
        last_time="20:00",
        count=3,
        guid="feed-guid-123",
    )
    content = content_from_rss_item(original, collected_at=NOW)
    assert content.source == "rss:feed"
    assert content.metadata["source_content_id"] == "feed-guid-123"
    assert content.metadata["guid"] == "feed-guid-123"
    assert rss_item_from_content(content) == original


def test_url_less_legacy_observation_identity_uses_utc_event_date():
    item = NewsItem(title="Same daily headline", source_id="sample")

    first = content_from_news_item(item, collected_at=NOW)
    next_day = content_from_news_item(item, collected_at=NOW + timedelta(days=1))

    assert first.metadata["source_content_id"].endswith(":2026-08-21")
    assert next_day.metadata["source_content_id"].endswith(":2026-08-22")
    assert "unknown" not in first.metadata["source_content_id"]


def test_ai_item_lossless_round_trip():
    original = AIItem(
        source="github",
        source_name="GitHub Trending",
        title="Repository",
        url="https://github.com/org/repo",
        published_at=NOW,
        score=321,
        author="org",
        summary="Description",
        tags=["python"],
        title_translated="仓库",
        is_new=True,
    )
    content = content_from_ai_item(original, collected_at=NOW)
    assert content.source == "ai_frontier:github"
    assert ai_item_from_content(content) == original
