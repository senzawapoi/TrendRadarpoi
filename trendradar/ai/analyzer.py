"""Bounded Gemini narrative adapters over deterministic Story projections."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from trendradar.ai.client import GeminiClient
from trendradar.ai.errors import GeminiError
from trendradar.core.models import Story
from trendradar.utils.logging import log

DEFAULT_MAX_STORIES = 20
DEFAULT_MAX_PROMPT_CHARS = 12_000
DEFAULT_MAX_DIGEST_CHARS = 4_000
DEFAULT_MAX_SECURITY_NARRATIVE_CHARS = 4_000


def _bounded_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _values(value: Any) -> list[Any]:
    if isinstance(value, list | tuple | set | frozenset):
        return list(value)
    return [] if value is None or value == "" else [value]


def _clean_output(value: Any, maximum: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:maximum].rstrip() or None


def _bounded_json(values: list[dict[str, Any]], maximum: int) -> str:
    """Serialize a deterministic prefix without cutting JSON mid-token."""
    selected: list[dict[str, Any]] = []
    for value in values:
        candidate = json.dumps([*selected, value], ensure_ascii=False, separators=(",", ":"))
        if len(candidate) > maximum:
            break
        selected.append(value)
    if selected:
        return json.dumps(selected, ensure_ascii=False, separators=(",", ":"))
    return "[]"


def _story_projection(story: Story) -> dict[str, Any]:
    return {
        "title": story.title[:500],
        "summary": story.summary[:1_500],
        "domain": story.domain,
        "event_time": story.event_time.isoformat(),
        "importance": round(story.importance.score, 3),
        "reasons": [str(value)[:500] for value in story.importance.reasons[:8]],
        "tags": [str(value)[:100] for value in story.tags[:20]],
    }


def _security_projection(story: Story) -> dict[str, Any]:
    security = _mapping(story.metadata.get("security"))
    return {
        **_story_projection(story),
        "security": {
            "cve_ids": [str(value)[:50] for value in _values(security.get("cve_ids"))[:20]],
            "severity": str(security.get("severity") or "")[:50],
            "cvss_score": security.get("cvss_score"),
            "known_exploited": bool(security.get("known_exploited")),
            "due_date": str(security.get("due_date") or "")[:50],
            "required_actions": [
                str(value)[:500] for value in _values(security.get("required_actions"))[:10]
            ],
        },
    }


@dataclass(frozen=True, slots=True)
class NarrativeLimits:
    max_stories: int = DEFAULT_MAX_STORIES
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS
    max_output_chars: int = DEFAULT_MAX_DIGEST_CHARS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_stories",
            _bounded_int(self.max_stories, DEFAULT_MAX_STORIES, minimum=1, maximum=100),
        )
        object.__setattr__(
            self,
            "max_prompt_chars",
            _bounded_int(
                self.max_prompt_chars,
                DEFAULT_MAX_PROMPT_CHARS,
                minimum=1_000,
                maximum=32_000,
            ),
        )
        object.__setattr__(
            self,
            "max_output_chars",
            _bounded_int(
                self.max_output_chars,
                DEFAULT_MAX_DIGEST_CHARS,
                minimum=200,
                maximum=12_000,
            ),
        )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
        *,
        default_output_chars: int = DEFAULT_MAX_DIGEST_CHARS,
    ) -> NarrativeLimits:
        config = value if isinstance(value, Mapping) else {}
        return cls(
            max_stories=_bounded_int(
                config.get("max_stories"), DEFAULT_MAX_STORIES, minimum=1, maximum=100
            ),
            max_prompt_chars=_bounded_int(
                config.get("max_prompt_chars"),
                DEFAULT_MAX_PROMPT_CHARS,
                minimum=1_000,
                maximum=32_000,
            ),
            max_output_chars=_bounded_int(
                config.get("max_output_chars"),
                default_output_chars,
                minimum=200,
                maximum=12_000,
            ),
        )


class DailyDigestAnalyzer:
    """Create one optional digest from an already-ranked Story prefix."""

    def __init__(
        self,
        client: GeminiClient,
        *,
        limits: NarrativeLimits | None = None,
    ) -> None:
        self.client = client
        self.limits = limits or NarrativeLimits()

    def analyze(self, stories: Sequence[Story]) -> str | None:
        ranked = [story for story in stories if isinstance(story, Story)][: self.limits.max_stories]
        if not ranked:
            return None
        payload = _bounded_json(
            [_story_projection(story) for story in ranked],
            self.limits.max_prompt_chars,
        )
        if payload == "[]":
            return None
        try:
            result = self.client.summary(
                payload,
                instruction=(
                    "Write a concise daily personal intelligence digest using only the ranked "
                    "Story facts supplied as JSON. Preserve uncertainty and do not invent facts, "
                    "sources, scores, or actions. Return plain text only."
                ),
            )
        except GeminiError as exc:
            log.warning("Daily digest unavailable", error_code=exc.code)
            return None
        except Exception as exc:
            log.warning("Daily digest failed", error_type=type(exc).__name__)
            return None
        return _clean_output(result.text, self.limits.max_output_chars)


class SecurityNarrativeAnalyzer:
    """Create one optional explanation without modifying deterministic security facts."""

    def __init__(
        self,
        client: GeminiClient,
        *,
        limits: NarrativeLimits | None = None,
    ) -> None:
        self.client = client
        self.limits = limits or NarrativeLimits(
            max_output_chars=DEFAULT_MAX_SECURITY_NARRATIVE_CHARS
        )

    def analyze(self, stories: Sequence[Story]) -> str | None:
        ranked = [
            story for story in stories if isinstance(story, Story) and story.domain == "security"
        ][: self.limits.max_stories]
        if not ranked:
            return None
        payload = _bounded_json(
            [_security_projection(story) for story in ranked],
            self.limits.max_prompt_chars,
        )
        if payload == "[]":
            return None
        try:
            result = self.client.analyze(
                payload,
                instruction=(
                    "Explain the supplied ranked security Stories for a personal operator. Use "
                    "only the JSON facts. Do not alter CVE identifiers, CVSS values, KEV status, "
                    "due dates, required actions, ranking, or freshness. Return plain text only."
                ),
            )
        except GeminiError as exc:
            log.warning("Security narrative unavailable", error_code=exc.code)
            return None
        except Exception as exc:
            log.warning("Security narrative failed", error_type=type(exc).__name__)
            return None
        return _clean_output(result.text, self.limits.max_output_chars)


__all__ = [
    "DailyDigestAnalyzer",
    "NarrativeLimits",
    "SecurityNarrativeAnalyzer",
]
