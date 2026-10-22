"""NewsNow platform adapter using the existing DataFetcher transport."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from trendradar.core.models import ContentItem, content_from_news_item
from trendradar.crawler.fetcher import DataFetcher
from trendradar.sources.base import SourceAdapter
from trendradar.storage.base import NewsItem


class NewsNowAdapter(SourceAdapter[NewsItem]):
    domain = "general"

    def __init__(
        self,
        platform_id: str,
        platform_name: str | None = None,
        *,
        fetcher: DataFetcher | None = None,
        crawl_time: str = "",
    ) -> None:
        self.platform_id = platform_id
        self.platform_name = platform_name or platform_id
        self.adapter_id = f"newsnow:{platform_id}"
        self.fetcher = fetcher or DataFetcher()
        self.crawl_time = crawl_time
        super().__init__()

    async def fetch(self) -> list[NewsItem]:
        response, _, _ = await asyncio.to_thread(
            self.fetcher.fetch_data,
            (self.platform_id, self.platform_name),
        )
        if response is None:
            raise RuntimeError(f"NewsNow fetch failed: {self.platform_id}")
        try:
            data = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ValueError(f"NewsNow JSON invalid: {self.platform_id}") from exc

        grouped: dict[str, NewsItem] = {}
        for rank, raw in enumerate(data.get("items", []), 1):
            title_value = raw.get("title") if isinstance(raw, dict) else None
            if title_value is None or isinstance(title_value, float) or not str(title_value).strip():
                continue
            title = str(title_value).strip()
            existing = grouped.get(title)
            if existing is not None:
                existing.ranks.append(rank)
                continue
            grouped[title] = NewsItem(
                title=title,
                source_id=self.platform_id,
                source_name=self.platform_name,
                rank=rank,
                url=str(raw.get("url", "")),
                mobile_url=str(raw.get("mobileUrl", "")),
                ranks=[rank],
                count=1,
            )
        return list(grouped.values())

    def normalize(self, raw: NewsItem, *, collected_at: datetime) -> ContentItem:
        if not raw.crawl_time:
            raw.crawl_time = self.crawl_time or collected_at.strftime("%H:%M")
        if not raw.first_time:
            raw.first_time = raw.crawl_time
        if not raw.last_time:
            raw.last_time = raw.crawl_time
        return content_from_news_item(raw, collected_at=collected_at)


__all__ = ["NewsNowAdapter"]
