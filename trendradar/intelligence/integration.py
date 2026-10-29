"""Compatibility projections used by the existing crawler entry points."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trendradar.intelligence.pipeline import persist_adapter_results_best_effort
from trendradar.intelligence.runner import AdapterRunner, run_newsnow_adapters
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.intelligence.translation import CanonicalTitleTranslator
from trendradar.sources.base import AdapterResult
from trendradar.sources.newsnow import NewsNowAdapter
from trendradar.sources.rss import RSSAdapter
from trendradar.storage.base import NewsData, NewsItem, RSSData, RSSItem
from trendradar.utils.logging import log


def open_intelligence_storage(
    enabled: bool,
    database_path: str | Path,
    *,
    story_config: dict[str, Any] | None = None,
    require_existing: bool = False,
    synchronous: str = "FULL",
) -> IntelligenceStorage | None:
    """Open the unified local database, degrading cleanly when it is unavailable."""
    if not enabled:
        return None
    try:
        storage_factory = (
            IntelligenceStorage.open_existing if require_existing else IntelligenceStorage
        )
        return storage_factory(
            database_path,
            story_config=story_config if story_config is not None else {"enabled": True},
            synchronous=synchronous,
        )
    except Exception as exc:
        if require_existing:
            raise
        log.error("统一情报库不可用，旧链路继续", error=str(exc))
        return None


def _utc_now(value: datetime | None = None) -> datetime:
    timestamp = value or datetime.now(tz=timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("collected_at must be timezone-aware")
    return timestamp.astimezone(timezone.utc)


def _project_news(
    results: list[AdapterResult[Any]],
    *,
    crawl_date: str,
    crawl_time: str,
    platform_names: dict[str, str],
) -> NewsData:
    items: dict[str, list[NewsItem]] = {}
    failed_ids: list[str] = []
    for result in results:
        source_id = result.adapter_id.removeprefix("newsnow:")
        raw_items = [item for item in result.raw_items if isinstance(item, NewsItem)]
        if result.failed:
            failed_ids.append(source_id)
            continue
        items[source_id] = raw_items
    return NewsData(
        date=crawl_date,
        crawl_time=crawl_time,
        items=items,
        id_to_name=platform_names,
        failed_ids=failed_ids,
    )


def fetch_newsnow_with_adapters(
    platforms: list[dict[str, Any]],
    *,
    fetcher: Any,
    request_interval_ms: int,
    crawl_date: str,
    crawl_time: str,
    collected_at: datetime | None = None,
    storage: IntelligenceStorage | None = None,
    story_wording_client: object | None = None,
    digest_analyzer: object | None = None,
    title_translator: CanonicalTitleTranslator | None = None,
) -> NewsData:
    """Fetch NewsNow serially and return the exact legacy NewsData grouping."""
    timestamp = _utc_now(collected_at)
    adapters = [
        NewsNowAdapter(
            str(platform["id"]),
            str(platform.get("name") or platform["id"]),
            fetcher=fetcher,
            crawl_time=crawl_time,
        )
        for platform in platforms
    ]
    results = asyncio.run(
        run_newsnow_adapters(
            adapters,
            request_interval_ms=request_interval_ms,
            collected_at=timestamp,
            storage=storage,
        )
    )
    persist_adapter_results_best_effort(
        results,
        storage,
        wording_client=story_wording_client,
        digest_analyzer=digest_analyzer,
        title_translator=title_translator,
    )
    return _project_news(
        results,
        crawl_date=crawl_date,
        crawl_time=crawl_time,
        platform_names={
            str(platform["id"]): str(platform.get("name") or platform["id"])
            for platform in platforms
        },
    )


def _project_rss(
    results: list[AdapterResult[Any]],
    *,
    crawl_date: str,
    crawl_time: str,
    feed_names: dict[str, str],
) -> RSSData:
    items: dict[str, list[RSSItem]] = {}
    failed_ids: list[str] = []
    for result in results:
        feed_id = result.adapter_id.removeprefix("rss:")
        if result.failed:
            failed_ids.append(feed_id)
        else:
            items[feed_id] = [item for item in result.raw_items if isinstance(item, RSSItem)]
    return RSSData(
        date=crawl_date,
        crawl_time=crawl_time,
        items=items,
        id_to_name=feed_names,
        failed_ids=failed_ids,
    )


def fetch_rss_with_adapters(
    feeds: list[Any],
    *,
    max_concurrency: int = 5,
    crawl_date: str,
    crawl_time: str,
    collected_at: datetime | None = None,
    storage: IntelligenceStorage | None = None,
    story_wording_client: object | None = None,
    digest_analyzer: object | None = None,
    title_translator: CanonicalTitleTranslator | None = None,
    **fetcher_options: object,
) -> RSSData:
    """Fetch RSS feeds through bounded per-feed adapters and project to RSSData."""
    timestamp = _utc_now(collected_at)
    adapters = [RSSAdapter(feed, **fetcher_options) for feed in feeds]
    results = asyncio.run(
        AdapterRunner(max_concurrency=max_concurrency, storage=storage).run(
            adapters,
            collected_at=timestamp,
        )
    )
    persist_adapter_results_best_effort(
        results,
        storage,
        wording_client=story_wording_client,
        digest_analyzer=digest_analyzer,
        title_translator=title_translator,
    )
    return _project_rss(
        results,
        crawl_date=crawl_date,
        crawl_time=crawl_time,
        feed_names={feed.id: feed.name for feed in feeds},
    )


__all__ = [
    "fetch_newsnow_with_adapters",
    "fetch_rss_with_adapters",
    "open_intelligence_storage",
]
