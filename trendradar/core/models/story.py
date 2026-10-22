"""Canonical Cluster, Story, and Importance models for intelligence analysis."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid5

from trendradar.core.models.normalization import normalize_tags, normalize_text

CLUSTER_ID_NAMESPACE = UUID("f2ec8a26-8efe-56c8-b083-a19e60aa2e03")
STORY_ID_NAMESPACE = UUID("c0f07df2-37e5-51bd-9096-6e46fef2957e")


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _uuid(value: str, field_name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid UUID") from exc


def _member_ids(values: list[str]) -> list[str]:
    normalized = sorted({_uuid(value, "member_id") for value in values})
    if not normalized:
        raise ValueError("at least one member_id is required")
    return normalized


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _utc(value, "metadata datetime").isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _parse_time(value: Any, field_name: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field_name}") from exc
    return _utc(parsed, field_name)


def deterministic_cluster_id(member_ids: list[str], *, scope: str = "") -> str:
    """Return an order-independent identity for one clustering result."""
    normalized_scope = normalize_text(scope).casefold()
    signature = "\n".join(_member_ids(member_ids))
    if normalized_scope:
        signature = f"{normalized_scope}\n{signature}"
    return str(uuid5(CLUSTER_ID_NAMESPACE, signature))


def deterministic_story_id(identity_key: str) -> str:
    """Return a stable Story identity from a deterministic event key."""
    normalized = normalize_text(identity_key).casefold()
    if not normalized:
        raise ValueError("story identity_key must not be empty")
    return str(uuid5(STORY_ID_NAMESPACE, normalized))


@dataclass
class ImportanceBreakdown:
    """Persistable, explainable importance score."""

    score: float = 0.0
    components: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    version: str = "importance-v1"

    def __post_init__(self) -> None:
        self.score = round(max(0.0, min(100.0, float(self.score))), 4)
        self.components = {
            normalize_text(key): round(max(0.0, min(1.0, float(value))), 6)
            for key, value in sorted(self.components.items())
            if normalize_text(key)
        }
        self.reasons = normalize_tags(self.reasons)
        self.version = normalize_text(self.version) or "importance-v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ImportanceBreakdown:
        payload = data or {}
        return cls(
            score=float(payload.get("score", 0.0) or 0.0),
            components=dict(payload.get("components") or {}),
            reasons=list(payload.get("reasons") or []),
            version=str(payload.get("version") or "importance-v1"),
        )


@dataclass
class Cluster:
    """A deterministic connected component of related canonical content."""

    id: str
    member_ids: list[str]
    domain: str
    event_time: datetime
    last_activity_at: datetime
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    signature: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = _uuid(self.id, "id")
        self.member_ids = _member_ids(self.member_ids)
        self.domain = normalize_text(self.domain).casefold()
        if not self.domain:
            raise ValueError("domain must not be empty")
        self.event_time = _utc(self.event_time, "event_time")
        self.last_activity_at = _utc(self.last_activity_at, "last_activity_at")
        if self.last_activity_at < self.event_time:
            raise ValueError("last_activity_at must not precede event_time")
        self.tags = normalize_tags(self.tags)
        self.entities = normalize_tags(self.entities)
        self.signature = normalize_text(self.signature) or "|".join(self.member_ids)
        self.metadata = _json_value(dict(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_time"] = self.event_time.isoformat()
        data["last_activity_at"] = self.last_activity_at.isoformat()
        return _json_value(data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Cluster:
        return cls(
            id=str(data.get("id", "")),
            member_ids=list(data.get("member_ids") or []),
            domain=str(data.get("domain", "")),
            event_time=_parse_time(data.get("event_time"), "event_time"),
            last_activity_at=_parse_time(
                data.get("last_activity_at"), "last_activity_at"
            ),
            tags=list(data.get("tags") or []),
            entities=list(data.get("entities") or []),
            signature=str(data.get("signature") or ""),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_json(cls, payload: str) -> Cluster:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("Cluster JSON must contain an object")
        return cls.from_dict(data)


@dataclass
class Story:
    """Stable intelligence object backed by one or more canonical items."""

    id: str
    identity_key: str
    title: str
    summary: str
    domain: str
    event_time: datetime
    last_activity_at: datetime
    member_ids: list[str]
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    importance: ImportanceBreakdown = field(default_factory=ImportanceBreakdown)
    generator_version: str = "story-v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = _uuid(self.id, "id")
        self.identity_key = normalize_text(self.identity_key).casefold()
        if not self.identity_key:
            raise ValueError("identity_key must not be empty")
        self.title = normalize_text(self.title)
        if not self.title:
            raise ValueError("title must not be empty")
        self.summary = normalize_text(self.summary)
        self.domain = normalize_text(self.domain).casefold()
        if not self.domain:
            raise ValueError("domain must not be empty")
        self.event_time = _utc(self.event_time, "event_time")
        self.last_activity_at = _utc(self.last_activity_at, "last_activity_at")
        if self.last_activity_at < self.event_time:
            raise ValueError("last_activity_at must not precede event_time")
        self.member_ids = _member_ids(self.member_ids)
        self.tags = normalize_tags(self.tags)
        self.entities = normalize_tags(self.entities)
        if not isinstance(self.importance, ImportanceBreakdown):
            self.importance = ImportanceBreakdown.from_dict(self.importance)
        self.generator_version = normalize_text(self.generator_version) or "story-v1"
        self.metadata = _json_value(dict(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_time"] = self.event_time.isoformat()
        data["last_activity_at"] = self.last_activity_at.isoformat()
        return _json_value(data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Story:
        return cls(
            id=str(data.get("id", "")),
            identity_key=str(data.get("identity_key", "")),
            title=str(data.get("title", "")),
            summary=str(data.get("summary", "")),
            domain=str(data.get("domain", "")),
            event_time=_parse_time(data.get("event_time"), "event_time"),
            last_activity_at=_parse_time(
                data.get("last_activity_at"), "last_activity_at"
            ),
            member_ids=list(data.get("member_ids") or []),
            tags=list(data.get("tags") or []),
            entities=list(data.get("entities") or []),
            importance=ImportanceBreakdown.from_dict(data.get("importance")),
            generator_version=str(data.get("generator_version") or "story-v1"),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_json(cls, payload: str) -> Story:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("Story JSON must contain an object")
        return cls.from_dict(data)


__all__ = [
    "CLUSTER_ID_NAMESPACE",
    "STORY_ID_NAMESPACE",
    "Cluster",
    "ImportanceBreakdown",
    "Story",
    "deterministic_cluster_id",
    "deterministic_story_id",
]
