"""Source adapters for CISA KEV, NVD CVE 2.0, and security RSS feeds."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from trendradar.ai_frontier._http import make_session, request_with_retry
from trendradar.core.models import ContentItem, normalize_text
from trendradar.crawler.rss.fetcher import RSSFeedConfig, RSSFetcher
from trendradar.domains.security.collector import (
    CISA_KEV_URL,
    NVD_CVE_API_URL,
    SecurityRecord,
    parse_cisa_catalog,
    parse_nvd_page,
    security_record_from_rss,
)
from trendradar.sources.base import SourceAdapter
from trendradar.storage.base import RSSItem


def _positive_int(value: Any, default: int, *, maximum: int | None = None) -> int:
    try:
        result = max(1, int(value))
    except (TypeError, ValueError):
        result = default
    return min(result, maximum) if maximum is not None else result


def _bounded_count(value: Any, default: int, *, maximum: int) -> int:
    """Resolve a bounded item count; zero/invalid values use the safe default."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if result <= 0:
        result = default
    return min(result, maximum)


def _bounded_float(value: Any, default: float, *, maximum: float) -> float:
    try:
        result = max(0.0, float(value))
    except (TypeError, ValueError):
        result = default
    return min(result, maximum)


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = normalize_text(value).casefold()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return default


class CisaKevAdapter(SourceAdapter[SecurityRecord]):
    domain = "security"
    adapter_id = "security:cisa-kev"

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        values = config if isinstance(config, Mapping) else {}
        self.enabled = _as_bool(values.get("enabled"), True)
        self.url = normalize_text(values.get("url")) or CISA_KEV_URL
        self.timeout = _positive_int(values.get("timeout"), 30, maximum=120)
        self.max_items = _bounded_count(values.get("max_items"), 500, maximum=5000)
        self.proxy_url = normalize_text(values.get("proxy_url"))
        super().__init__()

    async def fetch(self) -> list[SecurityRecord]:
        if not self.enabled:
            return []
        async with make_session(total_timeout=self.timeout, max_per_host=2) as session:
            response = await request_with_retry(
                session,
                "GET",
                self.url,
                label="CISA KEV",
                max_attempts=2,
                timeout=self.timeout,
                proxy=self.proxy_url or None,
            )
            if response is None:
                raise RuntimeError("CISA KEV request failed")
            if response.status != 200:
                status = response.status
                response.release()
                raise RuntimeError(f"CISA KEV returned HTTP {status}")
            try:
                payload = await response.json(content_type=None)
            finally:
                response.release()
        records = parse_cisa_catalog(payload, source_url=self.url)
        return sorted(
            records,
            key=lambda record: (
                record.published_at or datetime.min.replace(tzinfo=timezone.utc),
                record.external_id,
            ),
            reverse=True,
        )[: self.max_items]

    def normalize(self, raw: SecurityRecord, *, collected_at: datetime) -> ContentItem:
        return raw.to_content_item(collected_at=collected_at)


class NvdCveAdapter(SourceAdapter[SecurityRecord]):
    domain = "security"
    adapter_id = "security:nvd"

    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        now: datetime | None = None,
        api_key: str = "",
    ) -> None:
        values = config if isinstance(config, Mapping) else {}
        self.enabled = _as_bool(values.get("enabled"), True)
        self.url = normalize_text(values.get("url")) or NVD_CVE_API_URL
        self.timeout = _positive_int(values.get("timeout"), 30, maximum=120)
        self.lookback_hours = _positive_int(values.get("lookback_hours"), 48, maximum=2880)
        self.results_per_page = _positive_int(
            values.get("results_per_page"), 100, maximum=2000
        )
        self.max_pages = _positive_int(values.get("max_pages"), 2, maximum=20)
        self.max_items = _positive_int(values.get("max_items"), 200, maximum=10000)
        self.request_interval = _bounded_float(
            values.get("request_interval_seconds"),
            0.6 if api_key else 6.0,
            maximum=60.0,
        )
        self.proxy_url = normalize_text(values.get("proxy_url"))
        timestamp = now or datetime.now(tz=timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("NVD reference time must be timezone-aware")
        self.now = timestamp.astimezone(timezone.utc)
        self.api_key = normalize_text(api_key)
        super().__init__()

    def _params(self, start_index: int) -> dict[str, Any]:
        start = self.now - timedelta(hours=self.lookback_hours)
        return {
            "lastModStartDate": start.isoformat(timespec="milliseconds"),
            "lastModEndDate": self.now.isoformat(timespec="milliseconds"),
            "resultsPerPage": self.results_per_page,
            "startIndex": start_index,
        }

    async def fetch(self) -> list[SecurityRecord]:
        if not self.enabled:
            return []
        headers = {"apiKey": self.api_key} if self.api_key else None
        records: list[SecurityRecord] = []
        start_index = 0
        async with make_session(total_timeout=self.timeout, max_per_host=1) as session:
            for page in range(self.max_pages):
                response = await request_with_retry(
                    session,
                    "GET",
                    self.url,
                    params=self._params(start_index),
                    headers=headers,
                    proxy=self.proxy_url or None,
                    label="NVD CVE 2.0",
                    max_attempts=2,
                    timeout=self.timeout,
                )
                if response is None:
                    raise RuntimeError("NVD request failed")
                if response.status != 200:
                    status = response.status
                    response.release()
                    raise RuntimeError(f"NVD returned HTTP {status}")
                try:
                    payload = await response.json(content_type=None)
                finally:
                    response.release()
                page_records, total, returned_start, returned_count = parse_nvd_page(payload)
                records.extend(page_records)
                if len(records) >= self.max_items:
                    break
                step = returned_count or len(page_records)
                next_index = returned_start + step
                if step <= 0 or next_index >= total:
                    break
                start_index = next_index
                if page + 1 < self.max_pages and self.request_interval:
                    await asyncio.sleep(self.request_interval)
        return records[: self.max_items]

    def normalize(self, raw: SecurityRecord, *, collected_at: datetime) -> ContentItem:
        return raw.to_content_item(collected_at=collected_at)


class SecurityRSSAdapter(SourceAdapter[RSSItem]):
    domain = "security"

    def __init__(self, feed: RSSFeedConfig, **fetcher_options: object) -> None:
        self.feed = feed
        self.adapter_id = f"security:rss:{feed.id}"
        self.fetcher = RSSFetcher(feeds=[feed], **fetcher_options)
        super().__init__()

    async def fetch(self) -> list[RSSItem]:
        result = await self.fetcher.async_fetch_all(max_workers=1)
        if self.feed.id in result.failed_ids:
            raise RuntimeError(f"security RSS fetch failed: {self.feed.id}")
        items = result.items.get(self.feed.id, [])
        filtered, _ = self.fetcher._filter_by_freshness(items, self.feed)
        return filtered

    def normalize(self, raw: RSSItem, *, collected_at: datetime) -> ContentItem:
        return security_record_from_rss(raw).to_content_item(collected_at=collected_at)


__all__ = ["CisaKevAdapter", "NvdCveAdapter", "SecurityRSSAdapter"]
