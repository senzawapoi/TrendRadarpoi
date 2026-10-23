"""Versioned rich-text snapshots stored in the existing string outbox."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

POST_PREFIX = "trendradar:story-post:v1\n"
MAX_MESSAGE_BYTES = 20_000


def safe_link(value: str) -> str:
    """Keep complete public HTTP links; never truncate a URL into another target."""
    if not isinstance(value, str) or len(value) > 2000:
        return ""
    if any(char.isspace() or ord(char) < 32 or char in '<>"\\' for char in value):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return ""


def encode_post(title: str, lines: list[list[dict]]) -> str:
    return POST_PREFIX + json.dumps(
        {"zh_cn": {"title": title, "content": lines}}, ensure_ascii=False, separators=(",", ":")
    )


def message_content(snapshot: str) -> tuple[str, str]:
    """Decode new posts or retain legacy text payloads byte-for-byte on retry."""
    if not isinstance(snapshot, str) or not snapshot:
        raise ValueError("empty message snapshot")
    if snapshot.startswith(POST_PREFIX):
        content = snapshot[len(POST_PREFIX):]
        if len(content.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ValueError("post payload exceeds message limit")
        post = json.loads(content)
        if not isinstance(post, dict) or set(post) != {"zh_cn"}:
            raise ValueError("invalid post language")
        body = post["zh_cn"]
        if not isinstance(body, dict) or set(body) != {"title", "content"}:
            raise ValueError("invalid post body")
        if not isinstance(body["title"], str) or not body["title"]:
            raise ValueError("invalid post title")
        lines = body["content"]
        if not isinstance(lines, list) or not lines:
            raise ValueError("invalid post lines")
        for line in lines:
            if not isinstance(line, list) or not line:
                raise ValueError("invalid post line")
            for element in line:
                if not isinstance(element, dict) or element.get("tag") not in {"text", "a"}:
                    raise ValueError("unsupported post element")
                allowed = {"tag", "text"} if element["tag"] == "text" else {"tag", "text", "href"}
                if set(element) != allowed or not isinstance(element["text"], str):
                    raise ValueError("invalid post element")
                if element["tag"] == "a" and not safe_link(element["href"]):
                    raise ValueError("invalid post link")
        return "post", content
    content = json.dumps({"text": snapshot}, ensure_ascii=False)
    if len(content.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ValueError("text payload exceeds message limit")
    return "text", content
