"""Compatibility projections used by the existing crawler entry points."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
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
    process_stories: bool = True,
    save_story_report: bool = True,
    pending_story_ids: set[str] | None = None,
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
        process_stories=process_stories,
        save_story_report=save_story_report,
        pending_story_ids=pending_story_ids,
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
    process_stories: bool = True,
    save_story_report: bool = True,
    pending_story_ids: set[str] | None = None,
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
    if storage is not None:
        _expire_undated_rss_results(adapters, results, storage=storage, now=timestamp)
    persist_adapter_results_best_effort(
        results,
        storage,
        wording_client=story_wording_client,
        digest_analyzer=digest_analyzer,
        title_translator=title_translator,
        process_stories=process_stories,
        save_story_report=save_story_report,
        pending_story_ids=pending_story_ids,
    )
    return _project_rss(
        results,
        crawl_date=crawl_date,
        crawl_time=crawl_time,
        feed_names={feed.id: feed.name for feed in feeds},
    )



def _expire_undated_rss_results(
    adapters: list[RSSAdapter],
    results: list[AdapterResult[Any]],
    *,
    storage: IntelligenceStorage,
    now: datetime,
) -> None:
    """Drop undated RSS items whose canonical first-seen timestamp exceeds feed max_age_days."""
    from trendradar.intelligence.storage import ContentObservation

    max_days_by_id = {adapter.adapter_id: adapter.effective_max_age_days for adapter in adapters}
    for result in results:
        max_days = max_days_by_id.get(result.adapter_id, 0)
        if max_days <= 0 or not result.items:
            continue
        cutoff = now - timedelta(days=max_days)
        kept_items = []
        kept_norm_raw = []
        expired_raw_ids: set[int] = set()
        for raw_item, content in zip(result.normalized_raw_items, result.items, strict=False):
            if content.published_time is None:
                obs = ContentObservation.from_item(content)
                existing_id = storage.find_observation_item_id(obs.source, obs.source_content_id)
                existing = (
                    storage.get_item(existing_id)
                    if existing_id
                    else (storage.find_by_url(content.url) if content.url else None)
                )
                if existing is not None and (existing.published_time or existing.collected_at) < cutoff:
                    expired_raw_ids.add(id(raw_item))
                    continue
            kept_items.append(content)
            kept_norm_raw.append(raw_item)
        if expired_raw_ids:
            result.items = kept_items
            result.normalized_raw_items = kept_norm_raw
            result.raw_items = [r for r in result.raw_items if id(r) not in expired_raw_ids]

__all__ = [
    "fetch_newsnow_with_adapters",
    "fetch_rss_with_adapters",
    "open_intelligence_storage",
]
