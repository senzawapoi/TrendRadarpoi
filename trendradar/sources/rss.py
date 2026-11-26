"""Per-feed adapter around the existing RSSFetcher implementation."""

from __future__ import annotations

from datetime import datetime

from trendradar.core.models import ContentItem, content_from_rss_item
from trendradar.crawler.rss.fetcher import RSSFeedConfig, RSSFetcher
from trendradar.sources.base import SourceAdapter
from trendradar.storage.base import RSSItem


class RSSAdapter(SourceAdapter[RSSItem]):
    domain = "general"

    def __init__(self, feed: RSSFeedConfig, **fetcher_options: object) -> None:
        self.feed = feed
        self.adapter_id = f"rss:{feed.id}"
        self.fetcher = RSSFetcher(feeds=[feed], **fetcher_options)
        self._upstream_fetched_count: int | None = None
        super().__init__()

    @property
    def upstream_fetched_count(self) -> int | None:
        return self._upstream_fetched_count

    @property
    def effective_max_age_days(self) -> int:
        if not self.fetcher.freshness_enabled:
            return 0
        max_days = self.feed.max_age_days
        if max_days is None:
            max_days = self.fetcher.default_max_age_days
        return max(0, int(max_days or 0))

    async def fetch(self) -> list[RSSItem]:
        result = await self.fetcher.async_fetch_all(max_workers=1)
        if self.feed.id in result.failed_ids:
            self._upstream_fetched_count = None
            raise RuntimeError(f"RSS fetch failed: {self.feed.id}")
        items = result.items.get(self.feed.id, [])
        self._upstream_fetched_count = len(items)
        filtered, _ = self.fetcher._filter_by_freshness(items, self.feed)
        return filtered

    def normalize(self, raw: RSSItem, *, collected_at: datetime) -> ContentItem:
        return content_from_rss_item(raw, collected_at=collected_at)


__all__ = ["RSSAdapter"]
