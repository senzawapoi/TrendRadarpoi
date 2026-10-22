"""Small, transport-neutral contracts for optional external research."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

CAPABILITIES = frozenset({
    "search_web", "search_github", "search_reddit", "read_webpage", "get_video_transcript",
})
SEARCH_CAPABILITIES = frozenset({"search_web", "search_github", "search_reddit"})
ERROR_CODES = frozenset({
    "disabled", "permission_denied", "invalid_arguments", "unavailable", "timeout",
    "upstream_error", "invalid_response", "output_limit", "busy",
    "authentication", "rate_limited",
})


def public_url(value: str) -> str:
    """Accept public HTTP(S) names only; no credentials, local targets or odd ports.

    This is input validation, not a DNS rebinding defense. Adapters may only contact
    fixed providers; they must never connect directly to this user-supplied URL.
    """
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise ValueError("invalid URL")
    if any(ord(char) <= 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise ValueError("invalid URL")
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parts.port
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid URL") from exc
    if (parts.scheme not in {"http", "https"} or not host
            or parts.username is not None or parts.password is not None
            or port not in {None, 80, 443}):
        raise ValueError("invalid URL")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if ("." not in host or not re.fullmatch(r"[a-z0-9.-]+", host)
                or host.endswith((".localhost", ".local", ".internal", ".home", ".lan"))
                or all(part.isdigit() or part.startswith("0x") for part in host.split("."))
                or any(not label or len(label) > 63 or label.startswith("-")
                       or label.endswith("-") for label in host.split("."))):
            raise ValueError("URL host is not public") from None
    else:
        if not address.is_global:
            raise ValueError("URL host is not public")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc += f":{port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


@dataclass(frozen=True, slots=True)
class ResearchRequest:
    capability: str
    query: str = ""
    url: str = ""
    limit: int = 5

    def validated(self, *, max_results: int = 5) -> ResearchRequest:
        if not isinstance(self.capability, str) or self.capability not in CAPABILITIES:
            raise ValueError("unknown capability")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise ValueError("invalid limit")
        if not 1 <= self.limit <= 10:
            raise ValueError("invalid limit")
        if not isinstance(self.query, str) or not isinstance(self.url, str):
            raise ValueError("invalid argument type")
        if self.capability in SEARCH_CAPABILITIES:
            query = self.query.strip()
            if (not 1 <= len(query) <= 500 or query.startswith("-") or self.url
                    or any(ord(char) < 32 or ord(char) == 127 for char in query)):
                raise ValueError("invalid search")
            return ResearchRequest(self.capability, query=query,
                                   limit=min(self.limit, max_results))
        if self.query:
            raise ValueError("fetch does not accept query")
        url = public_url(self.url)
        if self.capability == "get_video_transcript":
            parts = urlsplit(url)
            if parts.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com",
                                      "youtu.be"}:
                raise ValueError("unsupported video host")
        return ResearchRequest(self.capability, url=url, limit=1)


@dataclass(frozen=True, slots=True)
class ResearchDocument:
    title: str
    url: str
    content: str
    source: str


@dataclass(frozen=True, slots=True)
class ResearchResult:
    capability: str
    items: tuple[ResearchDocument, ...] = ()
    success: bool = True
    error_code: str = ""
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.success and not self.error_code


@dataclass(frozen=True, slots=True)
class ResearchPolicy:
    enabled: bool = False
    capabilities: frozenset[str] = frozenset()
    timeout_seconds: int = 15
    max_results: int = 5
    max_result_chars: int = 3000
    max_response_bytes: int = 262_144
    max_concurrency: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be boolean")
        capabilities = frozenset(self.capabilities)
        if not capabilities <= CAPABILITIES:
            raise ValueError("unknown capability")
        object.__setattr__(self, "capabilities", capabilities)
        for name, minimum, maximum in (
            ("timeout_seconds", 1, 30), ("max_results", 1, 10),
            ("max_result_chars", 256, 4000), ("max_response_bytes", 1024, 1_048_576),
            ("max_concurrency", 1, 4),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise ValueError(f"invalid {name}")
