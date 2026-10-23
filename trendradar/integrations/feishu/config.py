"""Bounded, fail-closed Lark configuration with legacy Feishu names."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trendradar.core.settings import RuntimeSettings

from .models import sanitize_id

IDENTITY_FIELDS = ("open_id", "user_id", "union_id")
LARK_API_DOMAIN = "https://open.larksuite.com"


def _bounded(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if not isinstance(value, bool) else default
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bool(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.lower() in {"true", "1", "yes"})


def _ids(values: Any) -> tuple[str, ...]:
    if isinstance(values, str):
        values = values.split(",")
    if not isinstance(values, list | tuple) or len(values) > 100:
        return ()
    try:
        return tuple(sorted({sanitize_id(value) for value in values}))
    except ValueError:
        return ()


def _time(value: Any, default: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,2}:\d{2}", value):
        return default
    hour, minute = map(int, value.split(":"))
    return f"{hour:02}:{minute:02}" if hour < 24 and minute < 60 else default


@dataclass(frozen=True, slots=True)
class FeishuConfig:
    """Compatibility name for the Lark international transport settings."""

    enabled: bool = False
    app_id: str = field(default="", repr=False)
    app_secret: str = field(default="", repr=False)
    identity_fields: tuple[tuple[str, tuple[str, ...]], ...] = field(default=(), repr=False)
    allowed_chat_types: tuple[str, ...] = ("p2p", "group")
    bot_id: str = field(default="", repr=False)
    reconnect_attempts: int = 5
    cooldown_seconds: int = 300
    event_lease_seconds: int = 120
    delivery_retry_base_seconds: int = 5
    delivery_retry_max_seconds: int = 300
    max_message_chars: int = 8_000
    request_timeout_seconds: int = 30
    delivery_enabled: bool = False
    delivery_mode: str = "daily"
    delivery_time: str = "00:00"
    delivery_end: str = "23:59"
    timezone: str = "Asia/Shanghai"
    delivery_target: str = field(default="", repr=False)
    delivery_max_stories: int = 20
    api_domain: str = field(default=LARK_API_DOMAIN, init=False)

    def __post_init__(self) -> None:
        for name, default, minimum, maximum in (
            ("reconnect_attempts", 5, 1, 20),
            ("cooldown_seconds", 300, 1, 86400),
            ("event_lease_seconds", 120, 10, 3600),
            ("delivery_retry_base_seconds", 5, 0, 300),
            ("delivery_retry_max_seconds", 300, 0, 3600),
            ("max_message_chars", 8000, 256, 50000),
            ("request_timeout_seconds", 30, 1, 120),
            ("delivery_max_stories", 20, 1, 100),
        ):
            object.__setattr__(self, name, _bounded(getattr(self, name), default, minimum, maximum))
        object.__setattr__(
            self,
            "delivery_retry_max_seconds",
            max(self.delivery_retry_base_seconds, self.delivery_retry_max_seconds),
        )
        normalized = []
        for key, values in self.identity_fields:
            accepted = _ids(values)
            if key in IDENTITY_FIELDS and accepted:
                normalized.append((key, accepted))
        object.__setattr__(self, "identity_fields", tuple(sorted(normalized)))
        object.__setattr__(
            self,
            "allowed_chat_types",
            tuple(item for item in self.allowed_chat_types if item in {"p2p", "group"}),
        )
        object.__setattr__(self, "enabled", _bool(self.enabled))
        object.__setattr__(self, "delivery_enabled", _bool(self.delivery_enabled))
        mode = str(self.delivery_mode).strip().lower()
        object.__setattr__(self, "delivery_mode", mode)
        if mode not in {"instant", "daily"}:
            object.__setattr__(self, "delivery_enabled", False)
        object.__setattr__(self, "delivery_time", _time(self.delivery_time, "00:00"))
        object.__setattr__(self, "delivery_end", _time(self.delivery_end, "23:59"))
        object.__setattr__(self, "timezone", "Asia/Shanghai")

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
        *,
        app_id: str = "",
        app_secret: str = "",
        legacy_allowed_users: tuple[str, ...] = (),
    ) -> FeishuConfig:
        raw = value if isinstance(value, Mapping) else {}
        fields = raw.get("identity_fields")
        if fields is None:
            fields = {"open_id": legacy_allowed_users or raw.get("allowed_users", ())}
        normalized = tuple(fields.items()) if isinstance(fields, Mapping) else ()
        chats = raw.get("allowed_chat_types", ("p2p", "group"))
        if isinstance(chats, str):
            chats = chats.split(",")
        if not isinstance(chats, list | tuple):
            chats = ()
        values = {
            name: raw[name]
            for name in (
                "enabled",
                "bot_id",
                "reconnect_attempts",
                "cooldown_seconds",
                "event_lease_seconds",
                "delivery_retry_base_seconds",
                "delivery_retry_max_seconds",
                "max_message_chars",
                "request_timeout_seconds",
                "delivery_enabled",
                "delivery_mode",
                "delivery_time",
                "delivery_end",
                "delivery_target",
                "delivery_max_stories",
            )
            if name in raw
        }
        return cls(
            app_id=app_id,
            app_secret=app_secret,
            identity_fields=normalized,
            allowed_chat_types=tuple(chats),
            **values,
        )

    @classmethod
    def from_settings(cls, settings: RuntimeSettings) -> FeishuConfig:
        return cls.from_mapping(
            settings.lark_config,
            app_id=settings.lark_app_id,
            app_secret=settings.lark_app_secret,
        )


LarkConfig = FeishuConfig

__all__ = ["FeishuConfig", "LarkConfig", "LARK_API_DOMAIN"]
