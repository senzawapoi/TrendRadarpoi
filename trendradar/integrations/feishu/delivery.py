"""Bounded text delivery of persisted ranked Stories using the existing report evidence."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from trendradar.core.models import Story
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.intelligence.story_report import prepare_story_report


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
        return self._render(stories, now.astimezone(ZoneInfo("Asia/Shanghai")), daily=False)

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
