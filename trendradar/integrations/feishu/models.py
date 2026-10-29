"""Bounded, provider-neutral DTOs used by the Feishu adapter."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

_SAFE_ID = re.compile(r"[A-Za-z0-9_.:@-]+")


def _text(value: Any, name: str, *, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    result = value.strip()
    if required and not result:
        raise ValueError(f"{name} must not be empty")
    if len(result) > maximum:
        raise ValueError(f"{name} exceeds its limit")
    return result


def sanitize_id(value: str, *, name: str = "identifier", maximum: int = 256) -> str:
    value = _text(value, name, maximum=maximum)
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{name} contains invalid characters")
    return value


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True, repr=False)
class FeishuMediaPart:
    """A bounded image reference; raw bytes are intentionally not persisted."""

    kind: str = "image"
    resource_key: str = ""
    mime_type: str = "image/*"
    data: bytes = b""

    def __post_init__(self) -> None:
        kind = _text(self.kind, "kind", maximum=16).lower()
        if kind != "image":
            raise ValueError("only image media is supported")
        object.__setattr__(self, "kind", kind)
        if self.resource_key:
            object.__setattr__(self, "resource_key", sanitize_id(self.resource_key, maximum=512))
        object.__setattr__(self, "mime_type", _text(self.mime_type, "mime_type", maximum=128))
        if not isinstance(self.data, bytes) or len(self.data) > 4 * 1024 * 1024:
            raise ValueError("image data exceeds its limit")

    @property
    def has_data(self) -> bool:
        return bool(self.data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "resource_key": self.resource_key,
            "mime_type": self.mime_type,
            "size": len(self.data),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FeishuMediaPart:
        """Restore only the durable media reference; raw image bytes are never stored."""
        return cls(
            kind=value.get("kind", "image"),
            resource_key=value.get("resource_key", ""),
            mime_type=value.get("mime_type", "image/*"),
        )


@dataclass(frozen=True, slots=True, repr=False)
class FeishuInbound:
    """Normalized event envelope after the transport boundary."""

    event_id: str
    event_type: str
    identity: Mapping[str, str]
    chat_type: str
    chat_id: str
    message_id: str
    text: str = ""
    media: tuple[FeishuMediaPart, ...] = ()
    mentioned: bool = False
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload_version: int = 1
    created_at: datetime | None = None
    parent_message_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", sanitize_id(self.event_id, maximum=256))
        object.__setattr__(self, "event_type", _text(self.event_type, "event_type", maximum=128))
        normalized_identity = {
            sanitize_id(key, name="identity field", maximum=64): sanitize_id(
                value, name="identity value", maximum=256
            )
            for key, value in dict(self.identity).items()
            if value
        }
        object.__setattr__(self, "identity", MappingProxyType(normalized_identity))
        chat_type = _text(self.chat_type, "chat_type", maximum=32).lower()
        if chat_type not in {"p2p", "group"}:
            raise ValueError("unsupported chat_type")
        object.__setattr__(self, "chat_type", chat_type)
        object.__setattr__(self, "chat_id", sanitize_id(self.chat_id, name="chat_id"))
        object.__setattr__(self, "message_id", sanitize_id(self.message_id, name="message_id"))
        parent = _text(self.parent_message_id, "parent_message_id", maximum=256, required=False)
        if parent:
            parent = sanitize_id(parent, name="parent_message_id")
            if parent == self.message_id:
                raise ValueError("message cannot reply to itself")
        object.__setattr__(self, "parent_message_id", parent)
        object.__setattr__(self, "text", _text(self.text, "text", maximum=50_000, required=False))
        if len(self.media) > 4 or any(not isinstance(item, FeishuMediaPart) for item in self.media):
            raise ValueError("media exceeds its limit")
        object.__setattr__(self, "media", tuple(self.media))
        object.__setattr__(self, "received_at", _utc(self.received_at, "received_at"))
        if self.created_at is not None:
            object.__setattr__(self, "created_at", _utc(self.created_at, "created_at"))
        if (
            isinstance(self.payload_version, bool)
            or not isinstance(self.payload_version, int)
            or self.payload_version != 1
        ):
            raise ValueError("unsupported durable payload version")

    @property
    def request_id(self) -> str:
        return self.event_id

    @property
    def has_content(self) -> bool:
        return bool(self.text or self.media)

    def to_dict(self) -> dict[str, Any]:
        """Serialize a prepared event without persisting downloaded media bytes."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "identity": dict(self.identity),
            "chat_type": self.chat_type,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "text": self.text,
            "media": [part.to_dict() for part in self.media],
            "mentioned": self.mentioned,
            "received_at": self.received_at.isoformat(),
            "payload_version": self.payload_version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "parent_message_id": self.parent_message_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FeishuInbound:
        try:
            received_at = datetime.fromisoformat(str(value.get("received_at", "")))
            raw_media = value.get("media", ())
            if not isinstance(raw_media, list | tuple):
                raise ValueError("invalid media")
            media = tuple(FeishuMediaPart.from_dict(item) for item in raw_media)
            identity = value.get("identity", {})
            if not isinstance(identity, Mapping):
                raise ValueError("invalid identity")
            mentioned = value.get("mentioned", False)
            if not isinstance(mentioned, bool):
                raise ValueError("invalid mentioned flag")
            return cls(
                event_id=value.get("event_id", ""),
                event_type=value.get("event_type", ""),
                identity=identity,
                chat_type=value.get("chat_type", ""),
                chat_id=value.get("chat_id", ""),
                message_id=value.get("message_id", ""),
                text=value.get("text", ""),
                media=media,
                mentioned=mentioned,
                received_at=received_at,
                payload_version=value.get("payload_version", 1),
                created_at=(
                    datetime.fromisoformat(str(value["created_at"]))
                    if value.get("created_at") else None
                ),
                parent_message_id=value.get("parent_message_id", ""),
            )
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("invalid durable event") from exc


@dataclass(frozen=True, slots=True, repr=False)
class FeishuReply:
    """Replayable text response; rendered citations are part of the text."""

    event_id: str
    text: str
    session_id: str = ""
    degraded: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", sanitize_id(self.event_id, maximum=256))
        object.__setattr__(self, "text", _text(self.text, "text", maximum=50_000))
        if self.session_id:
            object.__setattr__(self, "session_id", sanitize_id(self.session_id, name="session_id"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "text": self.text,
            "session_id": self.session_id,
            "degraded": self.degraded,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FeishuReply:
        return cls(
            event_id=value.get("event_id", ""),
            text=value.get("text", ""),
            session_id=value.get("session_id", ""),
            degraded=bool(value.get("degraded", False)),
        )


def stable_digest(*parts: str) -> str:
    """Return a compact stable identifier without exposing raw identity values."""
    joined = "\x1f".join(_text(part, "identifier part", maximum=512) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


__all__ = ["FeishuInbound", "FeishuMediaPart", "FeishuReply", "sanitize_id", "stable_digest"]
