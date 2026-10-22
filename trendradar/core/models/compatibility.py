"""Lossless compatibility projections between ContentItem and legacy models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from trendradar.ai_frontier.sources.base import AIItem
from trendradar.core.models.content import ContentItem
from trendradar.core.models.normalization import (
    canonicalize_url,
    normalize_datetime,
    normalize_identity_title,
    normalize_text,
)
from trendradar.storage.base import NewsItem, RSSItem


def _metadata(model: str, data: dict[str, Any], source_content_id: str) -> dict[str, Any]:
    return {
        "legacy_model": model,
        "legacy_data": data,
        "source_content_id": source_content_id,
        "raw_url": data.get("url", ""),
        "source_name": data.get("source_name") or data.get("feed_name", ""),
    }


def _source_content_id(
    *,
    source: str,
    title: str,
    url: str,
    published_time: datetime | None,
    collected_at: datetime,
    source_content_id: str = "",
) -> str:
    """Return a stable observation key when a legacy record has no URL."""
    explicit_id = normalize_text(source_content_id)
    if explicit_id:
        return canonicalize_url(explicit_id) or explicit_id
    canonical_url = canonicalize_url(url)
    if canonical_url:
        return canonical_url
    event_time = published_time or collected_at
    event_date = event_time.astimezone(timezone.utc).date().isoformat()
    return f"title:{source}:{normalize_identity_title(title)}:{event_date}"


def content_from_news_item(item: NewsItem, *, collected_at: datetime) -> ContentItem:
    data = item.to_dict()
    source_content_id = _source_content_id(
        source=f"newsnow:{item.source_id}",
        title=item.title,
        url=item.url,
        published_time=None,
        collected_at=collected_at,
    )
    return ContentItem.create(
        title=item.title,
        content=item.summary,
        url=item.url,
        source=f"newsnow:{item.source_id}",
        domain="general",
        collected_at=collected_at,
        metadata=_metadata("NewsItem", data, source_content_id),
    )


def news_item_from_content(item: ContentItem) -> NewsItem:
    legacy = item.metadata.get("legacy_data")
    if item.metadata.get("legacy_model") == "NewsItem" and isinstance(legacy, dict):
        return NewsItem.from_dict(legacy)
    source_id = item.source.removeprefix("newsnow:")
    return NewsItem(
        title=item.title,
        source_id=source_id,
        source_name=str(item.metadata.get("source_name", source_id)),
        url=str(item.metadata.get("raw_url", item.url)),
        summary=item.content,
        title_translated=str(item.metadata.get("title_translated", "")),
        title_english=str(item.metadata.get("title_english", "")),
        summary_translated=str(item.metadata.get("summary_translated", "")),
        summary_english=str(item.metadata.get("summary_english", "")),
        is_english=bool(item.metadata.get("is_english", False)),
    )


def content_from_rss_item(item: RSSItem, *, collected_at: datetime) -> ContentItem:
    data = item.to_dict()
    published_time = normalize_datetime(item.published_at)
    source_content_id = _source_content_id(
        source=f"rss:{item.feed_id}",
        title=item.title,
        url=item.url,
        published_time=published_time,
        collected_at=collected_at,
        source_content_id=item.guid,
    )
    metadata = _metadata("RSSItem", data, source_content_id)
    metadata["guid"] = item.guid
    return ContentItem.create(
        title=item.title,
        content=item.summary,
        url=item.url,
        source=f"rss:{item.feed_id}",
        domain="general",
        published_time=published_time,
        collected_at=collected_at,
        metadata=metadata,
    )


def rss_item_from_content(item: ContentItem) -> RSSItem:
    legacy = item.metadata.get("legacy_data")
    if item.metadata.get("legacy_model") == "RSSItem" and isinstance(legacy, dict):
        return RSSItem.from_dict(legacy)
    feed_id = item.source.removeprefix("rss:")
    return RSSItem(
        title=item.title,
        feed_id=feed_id,
        feed_name=str(item.metadata.get("source_name", feed_id)),
        url=str(item.metadata.get("raw_url", item.url)),
        published_at=item.published_time.isoformat() if item.published_time else "",
        summary=item.content,
        author=str(item.metadata.get("author", "")),
        guid=str(item.metadata.get("guid", "")),
    )


def content_from_ai_item(item: AIItem, *, collected_at: datetime) -> ContentItem:
    data = item.to_dict()
    published_time = normalize_datetime(item.published_at)
    source_content_id = _source_content_id(
        source=f"ai_frontier:{item.source}",
        title=item.title,
        url=item.url,
        published_time=published_time,
        collected_at=collected_at,
    )
    metadata = _metadata("AIItem", data, source_content_id)
    metadata.update(
        {
            "author": item.author,
            "score": item.score,
            "title_translated": item.title_translated,
            "is_new": item.is_new,
        }
    )
    return ContentItem.create(
        title=item.title,
        content=item.summary,
        url=item.url,
        source=f"ai_frontier:{item.source}",
        domain="ai",
        published_time=published_time,
        collected_at=collected_at,
        tags=item.tags,
        metadata=metadata,
    )


def ai_item_from_content(item: ContentItem) -> AIItem:
    legacy = item.metadata.get("legacy_data")
    if item.metadata.get("legacy_model") == "AIItem" and isinstance(legacy, dict):
        published = normalize_datetime(legacy.get("published_at"))
        return AIItem(
            source=legacy.get("source", item.source.removeprefix("ai_frontier:")),
            source_name=legacy.get("source_name", ""),
            title=legacy.get("title", item.title),
            url=legacy.get("url", item.url),
            published_at=published,
            score=int(legacy.get("score", 0) or 0),
            author=legacy.get("author", ""),
            summary=legacy.get("summary", ""),
            tags=list(legacy.get("tags") or []),
            title_translated=legacy.get("title_translated", ""),
            is_new=bool(legacy.get("is_new", False)),
        )
    return AIItem(
        source=item.source.removeprefix("ai_frontier:"),
        source_name=str(item.metadata.get("source_name", "")),
        title=item.title,
        url=str(item.metadata.get("raw_url", item.url)),
        published_at=item.published_time,
        score=int(item.metadata.get("score", 0) or 0),
        author=str(item.metadata.get("author", "")),
        summary=item.content,
        tags=list(item.tags),
        title_translated=str(item.metadata.get("title_translated", "")),
        is_new=bool(item.metadata.get("is_new", False)),
    )


__all__ = [
    "ai_item_from_content",
    "content_from_ai_item",
    "content_from_news_item",
    "content_from_rss_item",
    "news_item_from_content",
    "rss_item_from_content",
]
