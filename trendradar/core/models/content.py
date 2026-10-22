"""Unified content model shared by every intelligence source."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid5

from trendradar.core.models.normalization import (
    canonicalize_url,
    normalize_identity_title,
    normalize_tags,
    normalize_text,
)

CONTENT_ID_NAMESPACE = UUID("eeafdbba-8d78-5e42-b875-c21ef54c39f0")
SUPPORTED_DOMAINS = frozenset({"general", "ai", "security"})


def _require_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def deterministic_content_id(
    *,
    source: str,
    title: str,
    url: str = "",
    published_time: datetime | None = None,
    collected_at: datetime,
) -> str:
    """Generate the stable UUIDv5 identity required by the unified data contract."""
    canonical_url = canonicalize_url(url)
    if canonical_url:
        identity = f"url:{canonical_url}"
    else:
        if published_time is not None:
            event_time = _require_utc(published_time, "published_time")
        else:
            event_time = _require_utc(collected_at, "collected_at")
        identity = f"event:{source}:{normalize_identity_title(title)}:{event_time.date().isoformat()}"
    return str(uuid5(CONTENT_ID_NAMESPACE, identity))


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return _require_utc(value, "metadata datetime").isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


@dataclass
class ContentItem:
    """Canonical intelligence item persisted in ``intelligence.db``."""

    id: str
    title: str
    content: str
    url: str
    source: str
    domain: str
    published_time: datetime | None
    collected_at: datetime
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            self.id = str(UUID(str(self.id)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("id must be a valid UUID") from exc
        self.title = normalize_text(self.title)
        if not self.title:
            raise ValueError("title must not be empty")
        self.content = normalize_text(self.content)
        self.url = canonicalize_url(self.url)
        self.source = normalize_text(self.source)
        if not self.source or ":" not in self.source:
            raise ValueError("source must use a non-empty namespace")
        self.domain = normalize_text(self.domain).casefold()
        if self.domain not in SUPPORTED_DOMAINS:
            raise ValueError(f"unsupported domain: {self.domain}")
        if self.published_time is not None:
            self.published_time = _require_utc(self.published_time, "published_time")
        self.collected_at = _require_utc(self.collected_at, "collected_at")
        self.tags = normalize_tags(self.tags)
        self.metadata = _json_safe(dict(self.metadata or {}))

    @classmethod
    def create(
        cls,
        *,
        title: str,
        content: str = "",
        url: str = "",
        source: str,
        domain: str,
        published_time: datetime | None = None,
        collected_at: datetime,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ContentItem:
        canonical_url = canonicalize_url(url)
        item_id = deterministic_content_id(
            source=source,
            title=title,
            url=canonical_url,
            published_time=published_time,
            collected_at=collected_at,
        )
        return cls(
            id=item_id,
            title=title,
            content=content,
            url=canonical_url,
            source=source,
            domain=domain,
            published_time=published_time,
            collected_at=collected_at,
            tags=tags or [],
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["published_time"] = (
            self.published_time.isoformat() if self.published_time is not None else None
        )
        data["collected_at"] = self.collected_at.isoformat()
        return _json_safe(data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContentItem:
        published = data.get("published_time")
        collected = data.get("collected_at")
        try:
            published_time = datetime.fromisoformat(str(published)) if published else None
            collected_at = datetime.fromisoformat(str(collected))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid ContentItem timestamp") from exc
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            content=str(data.get("content", "")),
            url=str(data.get("url", "")),
            source=str(data.get("source", "")),
            domain=str(data.get("domain", "")),
            published_time=published_time,
            collected_at=collected_at,
            tags=list(data.get("tags") or []),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_json(cls, payload: str) -> ContentItem:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("ContentItem JSON must contain an object")
        return cls.from_dict(data)


__all__ = [
    "CONTENT_ID_NAMESPACE",
    "SUPPORTED_DOMAINS",
    "ContentItem",
    "deterministic_content_id",
]
