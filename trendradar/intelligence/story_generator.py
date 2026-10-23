"""Deterministic Story generation with an optional wording-only enhancement boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from trendradar.core.models import (
    Cluster,
    ContentItem,
    Story,
    deterministic_story_id,
    normalize_text,
)
from trendradar.intelligence.deduplicate import event_time
from trendradar.intelligence.stories import story_identity_key
from trendradar.intelligence.translation import localized_title
from trendradar.utils.logging import log

GENERATOR_VERSION = "story-generator-v1"
MAX_TITLE_LENGTH = 240
MAX_SUMMARY_LENGTH = 1200
_BRACKETED_PREFIX_RE = re.compile(r"^(?:\[[^\]]+\]|【[^】]+】)\s*[-:：]?\s*")


@dataclass(frozen=True)
class WordingResult:
    title: str
    summary: str


class StoryWordingClient(Protocol):
    """Narrow protocol implemented by an optional external wording provider."""

    def enhance(self, *, title: str, summary: str) -> WordingResult | Mapping[str, Any]: ...


def _source_name(item: ContentItem) -> str:
    return normalize_text(item.metadata.get("source_name") or item.source)


def _clean_title(item: ContentItem) -> str:
    title = _BRACKETED_PREFIX_RE.sub("", normalize_text(item.title))
    source_name = _source_name(item)
    for separator in (":", "：", " - "):
        prefix = f"{source_name}{separator}"
        if source_name and title.casefold().startswith(prefix.casefold()):
            title = title[len(prefix) :].strip()
            break
    return title or normalize_text(item.title)


def _fallback_summary(items: list[ContentItem], cluster: Cluster | None = None) -> str:
    content = next((normalize_text(item.content) for item in items if item.content), "")
    configured_names = cluster.metadata.get("observation_source_names") if cluster else None
    if isinstance(configured_names, list | tuple | set):
        source_names = sorted(
            {normalize_text(value) for value in configured_names if normalize_text(value)},
            key=str.casefold,
        )
    else:
        source_names = sorted(
            {_source_name(item) for item in items if _source_name(item)},
            key=str.casefold,
        )
    context = (
        f"Sources: {len(source_names)}"
        + (f" ({', '.join(source_names)})" if source_names else "")
        + f". Evidence items: {len(items)}."
    )
    if not content:
        return context[:MAX_SUMMARY_LENGTH]
    available = max(0, MAX_SUMMARY_LENGTH - len(context) - 1)
    return f"{content[:available].rstrip()} {context}".strip()


def _parse_wording(value: Any) -> WordingResult | None:
    if isinstance(value, WordingResult):
        title, summary = value.title, value.summary
    elif isinstance(value, Mapping):
        title, summary = value.get("title"), value.get("summary")
    else:
        return None
    title = normalize_text(title)
    summary = normalize_text(summary)
    if not title or not summary:
        return None
    return WordingResult(
        title=title[:MAX_TITLE_LENGTH].rstrip(),
        summary=summary[:MAX_SUMMARY_LENGTH].rstrip(),
    )


def generate_story(
    cluster: Cluster,
    items: list[ContentItem],
    wording_client: StoryWordingClient | None = None,
) -> Story:
    """Generate one usable Story; provider failures only affect optional wording."""
    members = {item.id: item for item in items}
    if set(cluster.member_ids) != set(members):
        raise ValueError("cluster members and ContentItems must match")
    ordered = sorted(members.values(), key=lambda item: (event_time(item), item.id))
    representative = ordered[0]
    translated_title = localized_title(representative)
    original_title = _clean_title(representative)[:MAX_TITLE_LENGTH].rstrip()
    identity_key = story_identity_key(cluster, ordered)
    story = Story(
        id=deterministic_story_id(identity_key),
        identity_key=identity_key,
        title=(translated_title or original_title)[:MAX_TITLE_LENGTH].rstrip(),
        summary=_fallback_summary(ordered, cluster),
        domain=cluster.domain,
        event_time=cluster.event_time,
        last_activity_at=cluster.last_activity_at,
        member_ids=cluster.member_ids,
        tags=cluster.tags,
        entities=cluster.entities,
        generator_version=GENERATOR_VERSION,
        metadata={
            "cluster_id": cluster.id,
            "source_count": len(
                cluster.metadata.get("observation_sources")
                or {item.source for item in ordered}
            ),
        },
    )
    title_resolution = representative.metadata.get("title_translation")
    if isinstance(title_resolution, dict):
        story.metadata["title_translation"] = dict(title_resolution)
        story.metadata["title_content_id"] = representative.id
    if translated_title or isinstance(title_resolution, dict):
        story.metadata["ranking_title"] = original_title
    if wording_client is None:
        return story

    try:
        wording = _parse_wording(
            wording_client.enhance(title=original_title, summary=story.summary)
        )
    except Exception as exc:
        log.warning("Story wording enhancement failed; using deterministic fallback", error=str(exc))
        return story
    if wording is None:
        log.warning("Story wording enhancement returned invalid content; using fallback")
        return story
    # Optional wording must not overwrite the resolved display title or fallback decision.
    if not translated_title and not isinstance(title_resolution, dict):
        story.title = wording.title
    else:
        story.metadata["ranking_title"] = wording.title
    story.summary = wording.summary
    story.metadata["wording_enhanced"] = True
    return story


__all__ = [
    "GENERATOR_VERSION",
    "MAX_SUMMARY_LENGTH",
    "MAX_TITLE_LENGTH",
    "StoryWordingClient",
    "WordingResult",
    "generate_story",
]
