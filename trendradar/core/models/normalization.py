"""Normalization helpers for unified intelligence content."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_WHITESPACE_RE = re.compile(r"\s+")
_TRACKING_PARAMETERS = {
    "_",
    "_t",
    "campaign",
    "channel",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "random",
    "ref",
    "referrer",
    "share_from",
    "share_id",
    "share_token",
    "source",
    "timestamp",
}


def normalize_text(value: Any) -> str:
    """Apply Unicode NFKC and collapse whitespace to one ASCII space."""
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFKC", str(value))).strip()


def normalize_identity_title(value: Any) -> str:
    """Return the stable case-insensitive title representation used for identity."""
    return normalize_text(value).casefold()


def normalize_tags(values: Iterable[Any] | None) -> list[str]:
    """Normalize and de-duplicate tags while preserving their first spelling."""
    output: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        tag = normalize_text(value)
        key = tag.casefold()
        if not tag or key in seen:
            continue
        seen.add(key)
        output.append(tag)
    return output


def normalize_datetime(value: Any) -> datetime | None:
    """Parse a date-like value and return an aware UTC datetime, or ``None``."""
    if value is None or value == "":
        return None
    parsed: datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonicalize_url(value: Any) -> str:
    """Canonicalize an HTTP(S) URL for identity and cross-source de-duplication."""
    raw = normalize_text(value)
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = f"https:{raw}"
    elif "://" not in raw and "." in raw.split("/", 1)[0]:
        raw = f"https://{raw}"

    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.hostname:
            return ""

        hostname = parsed.hostname.lower().rstrip(".")
        try:
            port = parsed.port
        except ValueError:
            return ""
        if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            hostname = f"{hostname}:{port}"

        userinfo = ""
        if parsed.username:
            userinfo = parsed.username
            if parsed.password:
                userinfo = f"{userinfo}:{parsed.password}"
            userinfo = f"{userinfo}@"
        netloc = f"{userinfo}{hostname}"

        query = []
        for key, item in parse_qsl(parsed.query, keep_blank_values=True):
            lowered = key.casefold()
            if lowered.startswith("utm_") or lowered in _TRACKING_PARAMETERS:
                continue
            query.append((key, item))
        query.sort(key=lambda pair: (pair[0].casefold(), pair[0], pair[1]))

        return urlunsplit((scheme, netloc, parsed.path or "/", urlencode(query), ""))
    except (TypeError, ValueError, UnicodeError):
        return ""


__all__ = [
    "canonicalize_url",
    "normalize_datetime",
    "normalize_identity_title",
    "normalize_tags",
    "normalize_text",
]
