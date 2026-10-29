"""Provider-neutral models for the local intelligence Assistant."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any

from .media import ImagePart, validate_images


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _text(value: Any, field_name: str, *, maximum: int = 12_000, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} exceeds its limit")
    return normalized


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


@dataclass(frozen=True, slots=True)
class TimeRange:
    """An aware UTC half-open interval ``[start, end)``."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start = _utc(self.start, "start")
        end = _utc(self.end, "end")
        if end <= start:
            raise ValueError("end must be after start")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    @classmethod
    def previous_days(cls, now: datetime, days: int = 7) -> TimeRange:
        timestamp = _utc(now, "now")
        return cls(timestamp - timedelta(days=max(1, int(days))), timestamp)

    def contains(self, value: datetime) -> bool:
        timestamp = _utc(value, "value")
        return self.start <= timestamp < self.end

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True, slots=True)
class TruncationState:
    """Layer-specific result truncation flags."""

    history: bool = False
    stories: bool = False
    members: bool = False
    items: bool = False
    observations: bool = False
    citations: bool = False
    context: bool = False
    tool_calls: bool = False

    @property
    def any(self) -> bool:
        return any(
            (
                self.history,
                self.stories,
                self.members,
                self.items,
                self.observations,
                self.citations,
                self.context,
                self.tool_calls,
            )
        )

    def to_dict(self) -> dict[str, bool]:
        return {
            "history": self.history,
            "stories": self.stories,
            "members": self.members,
            "items": self.items,
            "observations": self.observations,
            "citations": self.citations,
            "context": self.context,
            "tool_calls": self.tool_calls,
        }


@dataclass(frozen=True, slots=True)
class Citation:
    """Immutable server-built evidence snapshot."""

    ref: str
    title: str
    source: str
    url: str = ""
    story_id: str | None = None
    content_item_id: str | None = None
    observation_id: int | None = None
    event_time: datetime | None = None
    observed_at: datetime | None = None
    snapshot: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref", _text(self.ref, "ref", maximum=64))
        object.__setattr__(self, "title", _text(self.title, "title", maximum=2_000))
        object.__setattr__(self, "source", _text(self.source, "source", maximum=256))
        object.__setattr__(self, "url", _text(self.url, "url", maximum=4_000, required=False))
        if self.event_time is not None:
            object.__setattr__(self, "event_time", _utc(self.event_time, "event_time"))
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", _utc(self.observed_at, "observed_at"))
        object.__setattr__(self, "snapshot", _freeze(dict(self.snapshot)))

    def to_dict(self) -> dict[str, Any]:
        def value(item: datetime | None) -> str | None:
            return item.isoformat() if item is not None else None

        return {
            "ref": self.ref,
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "story_id": self.story_id,
            "content_item_id": self.content_item_id,
            "observation_id": self.observation_id,
            "event_time": value(self.event_time),
            "observed_at": value(self.observed_at),
            "snapshot": _thaw(self.snapshot),
        }


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    """A persisted conversation message."""

    role: str
    content: str
    created_at: datetime
    sequence: int = 0
    request_id: str = ""

    def __post_init__(self) -> None:
        role = _text(self.role, "role", maximum=32).casefold()
        if role not in {"user", "assistant", "tool"}:
            raise ValueError("unsupported message role")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "content", _text(self.content, "content", maximum=50_000))
        object.__setattr__(self, "created_at", _utc(self.created_at, "created_at"))
        if self.sequence < 0:
            raise ValueError("sequence must not be negative")
        if self.request_id:
            object.__setattr__(self, "request_id", _text(self.request_id, "request_id", maximum=256))


@dataclass(frozen=True, slots=True)
class ToolCallSummary:
    name: str
    allowed: bool
    result: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "name", maximum=128))
        object.__setattr__(self, "result", _text(self.result, "result", maximum=4_000, required=False))
        object.__setattr__(self, "error", _text(self.error, "error", maximum=512, required=False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "allowed": self.allowed,
            "result": self.result,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True, repr=False)
class QuotedMessageContext:
    """Bounded untrusted material, separate from instructions and local citations."""

    status: str
    text: str = ""
    message_type: str = ""
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or self.status not in {
            "available", "unavailable", "permission_denied", "not_found", "timeout",
            "invalid_response", "unsupported", "cross_chat", "mismatched_message",
            "too_large", "input_limit",
        }:
            raise ValueError("invalid quoted message status")
        text = _text(self.text, "quoted text", maximum=4000, required=False)
        if self.status != "available" and text:
            raise ValueError("unavailable quoted message cannot contain text")
        if self.status == "available" and not text:
            raise ValueError("available quoted message must contain text")
        if not isinstance(self.truncated, bool):
            raise ValueError("invalid quoted message truncation flag")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "message_type", _text(
            self.message_type, "quoted message type", maximum=32, required=False,
        ))

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "text": self.text,
                "message_type": self.message_type, "truncated": self.truncated}


@dataclass(frozen=True, slots=True, init=False)
class AssistantRequest:
    """Validated user input accepted by the core Assistant."""

    request_id: str
    principal_id: str
    text: str
    session_id: str | None
    requested_at: datetime
    images: tuple[ImagePart, ...]
    quoted_context: QuotedMessageContext | None

    def __init__(
        self,
        request_id: str,
        principal_id: str,
        text: str,
        session_id: str | None = None,
        requested_at: datetime | None = None,
        *,
        now: datetime | None = None,
        images: tuple[ImagePart, ...] = (),
        quoted_context: QuotedMessageContext | None = None,
    ) -> None:
        if requested_at is not None and now is not None and requested_at != now:
            raise ValueError("requested_at and now disagree")
        timestamp = requested_at or now or datetime.now(tz=timezone.utc)
        object.__setattr__(self, "request_id", _text(request_id, "request_id", maximum=256))
        object.__setattr__(self, "principal_id", _text(principal_id, "principal_id", maximum=256))
        normalized_images = validate_images(images)
        object.__setattr__(self, "images", normalized_images)
        normalized_text = _text(text, "text", maximum=50_000, required=not normalized_images)
        object.__setattr__(self, "text", normalized_text or "[Image attachment]")
        if session_id is not None:
            session_id = _text(session_id, "session_id", maximum=256)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "requested_at", _utc(timestamp, "requested_at"))
        if quoted_context is not None and not isinstance(quoted_context, QuotedMessageContext):
            raise ValueError("quoted_context must be a QuotedMessageContext")
        object.__setattr__(self, "quoted_context", quoted_context)

    @property
    def now(self) -> datetime:
        return self.requested_at


@dataclass(frozen=True, slots=True, init=False)
class AssistantReply:
    """Bounded Assistant output and the evidence/range used to produce it."""

    request_id: str
    session_id: str
    text: str
    time_range: TimeRange
    citations: tuple[Citation, ...]
    degraded: bool
    degraded_reason: str
    truncation: TruncationState
    tool_calls: tuple[ToolCallSummary, ...]
    created_at: datetime

    def __init__(
        self,
        request_id: str,
        session_id: str,
        text: str,
        time_range: TimeRange | None = None,
        citations: tuple[Citation, ...] | list[Citation] = (),
        degraded: bool = False,
        degraded_reason: str = "",
        truncation: TruncationState | None = None,
        tool_calls: tuple[ToolCallSummary, ...] | list[ToolCallSummary] = (),
        created_at: datetime | None = None,
        *,
        effective_range: TimeRange | None = None,
    ) -> None:
        interval = time_range or effective_range
        if interval is None:
            raise ValueError("time_range is required")
        if time_range is not None and effective_range is not None and time_range != effective_range:
            raise ValueError("time_range and effective_range disagree")
        object.__setattr__(self, "request_id", _text(request_id, "request_id", maximum=256))
        object.__setattr__(self, "session_id", _text(session_id, "session_id", maximum=256))
        object.__setattr__(self, "text", _text(text, "text", maximum=50_000))
        object.__setattr__(self, "time_range", interval)
        normalized_citations = tuple(citations)
        if any(not isinstance(item, Citation) for item in normalized_citations):
            raise ValueError("citations must contain Citation values")
        object.__setattr__(self, "citations", normalized_citations)
        object.__setattr__(self, "degraded", bool(degraded))
        object.__setattr__(
            self,
            "degraded_reason",
            _text(degraded_reason, "degraded_reason", maximum=512, required=False),
        )
        object.__setattr__(self, "truncation", truncation or TruncationState())
        normalized_tools = tuple(tool_calls)
        if any(not isinstance(item, ToolCallSummary) for item in normalized_tools):
            raise ValueError("tool_calls must contain ToolCallSummary values")
        object.__setattr__(self, "tool_calls", normalized_tools)
        object.__setattr__(
            self,
            "created_at",
            _utc(created_at or datetime.now(tz=timezone.utc), "created_at"),
        )

    @property
    def effective_range(self) -> TimeRange:
        return self.time_range

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "text": self.text,
            "time_range": self.time_range.to_dict(),
            "citations": [item.to_dict() for item in self.citations],
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "truncation": self.truncation.to_dict(),
            "tool_calls": [item.to_dict() for item in self.tool_calls],
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AssistantReply:
        raw_range = data.get("time_range") or data.get("effective_range") or {}
        interval = TimeRange(
            datetime.fromisoformat(str(raw_range["start"])),
            datetime.fromisoformat(str(raw_range["end"])),
        )
        citations = tuple(
            Citation(
                ref=str(item.get("ref", "")),
                title=str(item.get("title", "")),
                source=str(item.get("source", "")),
                url=str(item.get("url", "")),
                story_id=item.get("story_id"),
                content_item_id=item.get("content_item_id"),
                observation_id=item.get("observation_id"),
                event_time=(
                    datetime.fromisoformat(str(item["event_time"]))
                    if item.get("event_time")
                    else None
                ),
                observed_at=(
                    datetime.fromisoformat(str(item["observed_at"]))
                    if item.get("observed_at")
                    else None
                ),
                snapshot=item.get("snapshot") or {},
            )
            for item in data.get("citations", [])
            if isinstance(item, Mapping)
        )
        raw_truncation = data.get("truncation") or {}
        truncation = TruncationState(
            **{
                name: bool(raw_truncation.get(name, False))
                for name in (
                    "history",
                    "stories",
                    "members",
                    "items",
                    "observations",
                    "citations",
                    "context",
                    "tool_calls",
                )
            }
        )
        tool_calls = tuple(
            ToolCallSummary(
                name=str(item.get("name", "")),
                allowed=bool(item.get("allowed", False)),
                result=str(item.get("result", "")),
                error=str(item.get("error", "")),
            )
            for item in data.get("tool_calls", [])
            if isinstance(item, Mapping)
        )
        created_at = datetime.fromisoformat(str(data["created_at"]))
        return cls(
            request_id=str(data.get("request_id", "")),
            session_id=str(data.get("session_id", "")),
            text=str(data.get("text", "")),
            time_range=interval,
            citations=citations,
            degraded=bool(data.get("degraded", False)),
            degraded_reason=str(data.get("degraded_reason", "")),
            truncation=truncation,
            tool_calls=tool_calls,
            created_at=created_at,
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, default=str)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


__all__ = [
    "AssistantMessage",
    "AssistantReply",
    "AssistantRequest",
    "Citation",
    "QuotedMessageContext",
    "TimeRange",
    "ToolCallSummary",
    "TruncationState",
]
