"""Bounded text delivery of persisted ranked Stories using the existing report evidence."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from trendradar.core.models import Story
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.intelligence.story_report import prepare_story_report

from .post import POST_PREFIX, encode_post, safe_link


def safe_text(value: str) -> str:
    # Feishu recognizes <at ...> even in text messages; never allow evidence/model
    # strings to introduce transport markup or notification mentions.
    return str(value).replace("<", "&lt;").replace(">", "&gt;")


def text_chunks(text: str, *, max_bytes: int = 12_000) -> tuple[str, ...]:
    """Leave room for JSON escaping inside Feishu's message payload limit."""
    if not 256 <= max_bytes <= 12000:
        raise ValueError("invalid chunk byte limit")
    parts, current, size = [], [], 0
    for char in text:
        length = len(json.dumps(char, ensure_ascii=False).encode("utf-8")) - 2
        if size + length > max_bytes:
            parts.append("".join(current))
            current, size = [], 0
        current.append(char)
        size += length
    if current:
        parts.append("".join(current))
    return tuple(parts)


class StoryDelivery:
    def __init__(
        self, storage: IntelligenceStorage, *, max_stories: int = 20, digest_analyzer=None
    ):
        self.storage = storage
        self.max_stories = max(1, min(100, max_stories))
        self.digest_analyzer = digest_analyzer

    def prepare(self, now: datetime) -> tuple[str, ...]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("delivery time must be aware")
        local = now.astimezone(ZoneInfo("Asia/Shanghai"))
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        stories = self.storage.list_stories(
            start=start.astimezone(timezone.utc),
            end=(start + timedelta(days=1)).astimezone(timezone.utc),
            limit=self.max_stories,
        )
        if not stories:
            return ()
        return self._render(stories, local, daily=True)

    def prepare_stories(self, now: datetime, stories: list[Story]) -> tuple[str, ...]:
        """Render an explicit instant batch locally, without date filtering or a provider."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("delivery time must be aware")
        if not 1 <= len(stories) <= 20:
            raise ValueError("instant batch must contain 1 to 20 Stories")
        return self._render_instant(stories, now.astimezone(ZoneInfo("Asia/Shanghai")))

    def _render_instant(self, stories: list[Story], local: datetime) -> tuple[str, ...]:
        groups: dict[str, list[tuple[str, str]]] = {}
        for entry in prepare_story_report(stories, self.storage, evidence_limit=16):
            story = entry["story"]
            evidence = next(
                (row for row in entry["evidence"] if safe_link(row["url"])),
                entry["evidence"][0] if entry["evidence"] else {},
            )
            source = _compact_text(evidence.get("source_name") or story.domain, 80)
            groups.setdefault(source, []).append((
                _compact_text(story.title, 240), safe_link(evidence.get("url", "")),
            ))

        heading = f"Story Intelligence | {local:%m-%d %H:%M}"
        total = [{"tag": "text", "text": f"\u672c\u6b21\u65b0\u589e\uff1a{len(stories)} \u6761"}]
        chunks: list[str] = []
        lines = [total]
        number = 0
        for group_index, (source, items) in enumerate(groups.items(), 1):
            group = [{"tag": "text", "text": (
                f"[{group_index}/{len(groups)}] {source} \u00b7 {len(items)} \u6761"
            )}]
            for item_index, (title, url) in enumerate(items):
                number += 1
                row = [{"tag": "text", "text": f"{number}. "}]
                row.append({"tag": "a", "text": title, "href": url} if url else {
                    "tag": "text", "text": title,
                })
                additions = [group, row] if item_index == 0 else [row]
                candidate = encode_post(heading, lines + additions)
                if len(candidate.removeprefix(POST_PREFIX).encode("utf-8")) > 12_000:
                    chunks.append(encode_post(heading, lines))
                    lines = [total, group, row]
                else:
                    lines.extend(additions)
        chunks.append(encode_post(heading, lines))
        if len(chunks) > 1:
            # Each saved part is a complete post; never split a link or JSON element.
            for index, chunk in enumerate(chunks, 1):
                body = json.loads(chunk.removeprefix(POST_PREFIX))["zh_cn"]
                chunks[index - 1] = encode_post(
                    f"{heading} ({index}/{len(chunks)})", body["content"]
                )
        return tuple(chunks)

    def _render(self, stories: list[Story], local: datetime, *, daily: bool) -> tuple[str, ...]:
        lines = [f"Story Intelligence | {local:%Y-%m-%d %H:%M} Asia/Shanghai"]
        if daily and self.digest_analyzer is not None:
            try:
                digest = self.digest_analyzer.analyze(stories)
            except Exception:
                digest = None
            if isinstance(digest, str) and digest.strip():
                lines.extend(["Daily digest", safe_text(digest[:4000])])
        for index, entry in enumerate(
            prepare_story_report(stories, self.storage, evidence_limit=16), 1
        ):
            story = entry["story"]
            entry_lines = [
                "---",
                f"{index}. {safe_text(story.title[:1000])}",
                f"Importance: {story.importance.score:.1f}",
                safe_text(story.summary[:2000]),
            ]
            entry_lines.extend(safe_text(reason[:500]) for reason in story.importance.reasons[:5])
            seen = set()
            for evidence in entry["evidence"]:
                url = evidence["url"]
                if url and url not in seen:
                    entry_lines.append(
                        f"{safe_text(str(evidence['source_name'])[:120])}: {safe_text(url[:2000])}"
                    )
                    seen.add(url)
                    if len(seen) == 8:
                        break
            # Bound each instant entry so all registered Stories survive chunking.
            entry_text = "\n\n".join(entry_lines)
            lines.append(entry_text if daily else entry_text[:8000])
        text = "\n\n".join(lines)
        return text_chunks(text[:100_000] if daily else text)


def _compact_text(value: str, limit: int) -> str:
    value = " ".join(str(value).split())
    return safe_text(value if len(value) <= limit else value[:limit - 3] + "...")
