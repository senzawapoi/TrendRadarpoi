"""TDD tests for RSS adapter zero-fresh health distinction and undated item first-seen TTL."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from trendradar.core.models import ContentItem
from trendradar.crawler.rss.fetcher import RSSFeedConfig
from trendradar.intelligence.integration import fetch_rss_with_adapters
from trendradar.intelligence.runner import AdapterRunner
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.intelligence.stories import StoryService
from trendradar.sources.base import HealthStatus
from trendradar.sources.rss import RSSAdapter
from trendradar.storage.base import RSSData, RSSItem


def test_rss_adapter_with_valid_upstream_but_zero_fresh_items_is_healthy(monkeypatch):
    now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    old_pub = (now - timedelta(days=10)).isoformat()
    feed = RSSFeedConfig(
        id="deepmind",
        name="DeepMind Blog",
        url="https://deepmind.example/rss.xml",
        max_age_days=3,
    )
    adapter = RSSAdapter(feed, timezone="UTC", freshness_enabled=True, default_max_age_days=3)

    async def fake_fetch_all(max_workers: int = 1):
        return RSSData(
            date="2026-11-25",
            crawl_time="12:00",
            items={
                "deepmind": [
                    RSSItem(
                        title="Ten Days Ago Post",
                        feed_id="deepmind",
                        feed_name="DeepMind Blog",
                        url="https://deepmind.example/old",
                        published_at=old_pub,
                    )
                ]
            },
            id_to_name={"deepmind": "DeepMind Blog"},
            failed_ids=[],
        )

    monkeypatch.setattr(adapter.fetcher, "async_fetch_all", fake_fetch_all)
    result = asyncio.run(AdapterRunner().run([adapter], collected_at=now))[0]
    assert result.items == []
    assert result.health.status is HealthStatus.HEALTHY

    # Conversely, truly empty upstream feed must still report DEGRADED
    async def fake_empty_fetch(max_workers: int = 1):
        return RSSData(
            date="2026-11-25",
            crawl_time="12:00",
            items={"deepmind": []},
            id_to_name={"deepmind": "DeepMind Blog"},
            failed_ids=[],
        )

    monkeypatch.setattr(adapter.fetcher, "async_fetch_all", fake_empty_fetch)
    empty_res = asyncio.run(AdapterRunner().run([adapter], collected_at=now))[0]
    assert empty_res.health.status is HealthStatus.DEGRADED


def test_fetch_rss_with_adapters_expires_undated_items_beyond_first_seen_max_age(
    tmp_path, monkeypatch
):
    now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    db_path = tmp_path / "intelligence.db"
    story_cfg = {"enabled": True, "report": {"enabled": False}}

    with IntelligenceStorage(db_path, story_config=story_cfg) as storage:
        stale_ad = ContentItem.create(
            title="Best cash back card of 2022",
            url="https://cnn.example/ad-2022",
            source="rss:cnn_world",
            domain="general",
            published_time=None,
            collected_at=thirty_days_ago,
        )
        storage.write_batch([stale_ad])

        feed = RSSFeedConfig(
            id="cnn_world",
            name="CNN World",
            url="https://cnn.example/rss",
            max_age_days=3,
        )

        async def fake_fetch(self):
            self._upstream_fetched_count = 2
            return [
                RSSItem(
                    title="Best cash back card of 2022",
                    feed_id="cnn_world",
                    feed_name="CNN World",
                    url="https://cnn.example/ad-2022",
                    published_at="",
                ),
                RSSItem(
                    title="Breaking News Today",
                    feed_id="cnn_world",
                    feed_name="CNN World",
                    url="https://cnn.example/today",
                    published_at=now.isoformat(),
                ),
            ]

        monkeypatch.setattr(RSSAdapter, "fetch", fake_fetch)

        seen_batch_urls: list[list[str]] = []
        orig_process = StoryService.process

        def spy_process(self, items, **kwargs):
            seen_batch_urls.append([item.url for item in items])
            return orig_process(self, items, **kwargs)

        monkeypatch.setattr(StoryService, "process", spy_process)

        rss_data = fetch_rss_with_adapters(
            [feed],
            crawl_date="2026-11-25",
            crawl_time="20:00",
            collected_at=now,
            storage=storage,
            timezone="Asia/Shanghai",
        )

        assert [i.url for i in rss_data.items["cnn_world"]] == ["https://cnn.example/today"]
        assert seen_batch_urls == [["https://cnn.example/today"]]
