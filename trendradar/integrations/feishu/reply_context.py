"""Bounded visible quote material; never media, fetched web evidence, or a verified Story."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

MAX_QUOTE_CHARS = 4000
MAX_CONTENT_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
MAX_POST_ROWS = 100
MAX_POST_ELEMENTS = 500
MAX_POST_LOCALES = 16

ReplyStatus = Literal[
    "absent", "available", "unavailable", "permission_denied", "not_found", "timeout",
    "invalid_response", "unsupported", "cross_chat", "mismatched_message", "too_large",
    "input_limit",
]


@dataclass(frozen=True)
class ReplyContext:
    """Only available text is usable; callers must mark all other quotes unavailable.

    Text is excluded from repr to keep message bodies and URL queries out of logs.
    The caller owns authorization and treats this text as untrusted quoted material.
    """

    status: ReplyStatus
    text: str = field(default="", repr=False)
    message_type: str = ""
    truncated: bool = False

    def __post_init__(self) -> None:
        if self.status != "available":
            object.__setattr__(self, "text", "")
        elif len(self.text) > MAX_QUOTE_CHARS:
            object.__setattr__(self, "text", self.text[:MAX_QUOTE_CHARS])
            object.__setattr__(self, "truncated", True)


def quote_limit(max_chars: int) -> int:
    if type(max_chars) is not int or max_chars <= 0:
        return 0
    return min(max_chars, MAX_QUOTE_CHARS)


def _http_link(value: object) -> str:
    if not isinstance(value, str) or any(char.isspace() or ord(char) < 32 for char in value):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return ""
        if parsed.username is not None or parsed.password is not None:
            return ""
        _ = parsed.port  # urlsplit defers port validation until this property is read.
    except ValueError:
        return ""
    return value


class _TextBudget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.parts: list[str] = []
        self.size = 0
        self.truncated = False
        self.visible = False

    def add(self, value: str, *, atomic: bool = False, visible: bool = True) -> None:
        remaining = self.limit - self.size
        if len(value) > remaining:
            self.truncated = True
            value = "" if atomic else value[:remaining]
        self.parts.append(value)
        self.size += len(value)
        self.visible = self.visible or (visible and bool(value.strip()))


def _post_body(value: dict) -> dict | None:
    if "post" in value:
        value = value["post"]
        if not isinstance(value, dict):
            return None
    # GetMessage returns the direct title/content body; event/sending fixtures may be localized.
    if "content" in value:
        return value
    if len(value) > MAX_POST_LOCALES:
        return None
    locales = [key for key in value if re.fullmatch(r"[a-z]{2}_[a-z]{2}", key)]
    locales.sort(key=lambda key: (key != "zh_cn", key != "en_us", key))
    if not locales:
        return None
    body = value[locales[0]]
    return body if isinstance(body, dict) else None


def _parse_post(value: dict, limit: int) -> ReplyContext:
    body = _post_body(value)
    if body is None:
        return ReplyContext("invalid_response", message_type="post")
    title, rows = body.get("title", ""), body.get("content")
    if not isinstance(title, str) or not isinstance(rows, list):
        return ReplyContext("invalid_response", message_type="post")
    budget = _TextBudget(limit)
    budget.add(title)
    budget.truncated = budget.truncated or len(rows) > MAX_POST_ROWS
    elements = 0
    unsupported = False
    for row in rows[:MAX_POST_ROWS]:
        if not isinstance(row, list):
            return ReplyContext("invalid_response", message_type="post")
        if elements >= MAX_POST_ELEMENTS or budget.size >= limit:
            budget.truncated = True
            break
        if budget.size and row:
            budget.add("\n", visible=False)
        remaining = MAX_POST_ELEMENTS - elements
        if len(row) > remaining:
            budget.truncated = True
        for element in row[:remaining]:
            elements += 1
            if not isinstance(element, dict) or not isinstance(element.get("tag"), str):
                return ReplyContext("invalid_response", message_type="post")
            tag = element["tag"]
            if tag in {"text", "a", "at", "md", "code_block"}:
                key = "user_name" if tag == "at" else "text"
                text = element.get(key, "")
                if not isinstance(text, str):
                    return ReplyContext("invalid_response", message_type="post")
                budget.add(text)
                if tag == "a":
                    href = _http_link(element.get("href"))
                    if href and href != text:
                        budget.add(f" ({href})" if text else href, atomic=True)
            else:
                unsupported = True
                marker = "[image not inspected]" if tag == "img" else "[unsupported content]"
                budget.add(marker, visible=False)
    text = "".join(budget.parts).strip()
    if not budget.visible:
        return ReplyContext(
            "unsupported" if unsupported else "invalid_response",
            message_type="post", truncated=budget.truncated,
        )
    return ReplyContext("available", text, "post", budget.truncated)


def parse_reply_content(
    message_type: str, content: str, *, max_chars: int = 4000,
) -> ReplyContext:
    """Parse one already identity-checked message, without any network or media access."""
    limit = quote_limit(max_chars)
    if not limit:
        return ReplyContext("input_limit")
    if not isinstance(message_type, str) or not re.fullmatch(r"[a-z_]{1,32}", message_type):
        return ReplyContext("invalid_response")
    if message_type not in {"text", "post"}:
        return ReplyContext("unsupported", message_type=message_type)
    if not isinstance(content, str):
        return ReplyContext("invalid_response", message_type=message_type)
    if len(content) > MAX_CONTENT_BYTES:
        return ReplyContext("too_large", message_type=message_type, truncated=True)
    try:
        if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
            return ReplyContext("too_large", message_type=message_type, truncated=True)
        value = json.loads(content)
    except (ValueError, UnicodeError, RecursionError):
        return ReplyContext("invalid_response", message_type=message_type)
    if not isinstance(value, dict):
        return ReplyContext("invalid_response", message_type=message_type)
    if message_type == "post":
        return _parse_post(value, limit)
    text = value.get("text")
    if not isinstance(text, str) or not text.strip():
        return ReplyContext("invalid_response", message_type=message_type)
    return ReplyContext("available", text[:limit], "text", len(text) > limit)
