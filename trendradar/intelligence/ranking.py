"""Deterministic, explainable Story importance scoring."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from trendradar.core.models import ContentItem, ImportanceBreakdown, Story, normalize_identity_title
from trendradar.intelligence.clustering import title_tokens

_COMPONENT_NAMES = ("diversity", "reliability", "activity", "recency", "interest")
_DEFAULT_WEIGHTS = {
    "diversity": 0.25,
    "reliability": 0.20,
    "activity": 0.20,
    "recency": 0.20,
    "interest": 0.15,
}
_DEFAULT_RELIABILITY = {
    "ai_frontier": 0.75,
    "ai_frontier:arxiv": 0.90,
    "ai_frontier:official_blog": 0.90,
    "newsnow": 0.65,
    "rss": 0.70,
}


def _unit(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _positive_float(value: Any, default: float) -> float:
    try:
        return max(1.0, float(value))
    except (TypeError, ValueError):
        return default


def _positive_int(value: Any, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RankingConfig:
    weights: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_WEIGHTS))
    source_reliability: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_RELIABILITY)
    )
    user_interests: tuple[str, ...] = ()
    recency_half_life_hours: float = 24.0
    diversity_target: int = 4
    activity_target: int = 6
    version: str = "importance-v1"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> RankingConfig:
        values = data if isinstance(data, Mapping) else {}
        raw_weights = values.get("weights") or {}
        if not isinstance(raw_weights, Mapping):
            raw_weights = {}
        weights = {
            name: _unit(raw_weights.get(name), default)
            for name, default in _DEFAULT_WEIGHTS.items()
        }
        total = sum(weights.values())
        if total <= 0:
            weights = dict(_DEFAULT_WEIGHTS)
            total = sum(weights.values())
        weights = {name: value / total for name, value in weights.items()}

        reliability = dict(_DEFAULT_RELIABILITY)
        raw_reliability = values.get("source_reliability") or {}
        if isinstance(raw_reliability, Mapping):
            reliability.update(
                {
                    normalize_identity_title(key): _unit(value, 0.5)
                    for key, value in raw_reliability.items()
                    if normalize_identity_title(key)
                }
            )
        interests = values.get("user_interests") or []
        if isinstance(interests, str):
            interests = [part.strip() for part in interests.split(",")]
        elif not isinstance(interests, list | tuple | set | frozenset):
            interests = []
        normalized_interests = tuple(
            dict.fromkeys(
                interest
                for interest in (normalize_identity_title(value) for value in interests)
                if interest
            )
        )
        return cls(
            weights=weights,
            source_reliability=reliability,
            user_interests=normalized_interests,
            recency_half_life_hours=_positive_float(
                values.get("recency_half_life_hours", 24), 24.0
            ),
            diversity_target=_positive_int(values.get("diversity_target", 4), 4),
            activity_target=_positive_int(values.get("activity_target", 6), 6),
            version=str(values.get("version") or "importance-v1"),
        )


@dataclass(frozen=True)
class RankingEvidence:
    items: tuple[ContentItem, ...]
    observation_sources: tuple[str, ...] = ()
    observation_count: int = 0
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None


def _source_reliability(source: str, config: RankingConfig) -> float:
    normalized = normalize_identity_title(source)
    if normalized in config.source_reliability:
        return config.source_reliability[normalized]
    namespace = normalized.split(":", 1)[0]
    return config.source_reliability.get(namespace, 0.5)


def score_story(
    story: Story,
    evidence: RankingEvidence,
    config: RankingConfig | Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> ImportanceBreakdown:
    """Score a Story from explicit evidence and retain every component and reason."""
    resolved = config if isinstance(config, RankingConfig) else RankingConfig.from_mapping(config)
    timestamp = now or datetime.now(tz=timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)

    sources = set(evidence.observation_sources)
    sources.update(item.source for item in evidence.items)
    diversity = min(1.0, len(sources) / resolved.diversity_target)
    reliabilities = [_source_reliability(source, resolved) for source in sources]
    reliability = sum(reliabilities) / len(reliabilities) if reliabilities else 0.0

    evidence_count = max(len(evidence.items), evidence.observation_count)
    volume = min(1.0, evidence_count / resolved.activity_target)
    first_activity = evidence.first_observed_at or story.event_time
    last_activity = evidence.last_observed_at or story.last_activity_at
    span_hours = max(
        1.0,
        (last_activity - first_activity).total_seconds() / 3600,
    )
    velocity = min(1.0, evidence_count / span_hours)
    activity = (volume + velocity) / 2

    age_hours = max(0.0, (timestamp - last_activity).total_seconds() / 3600)
    recency = math.pow(0.5, age_hours / resolved.recency_half_life_hours)

    searchable = " ".join(
        [
            normalize_identity_title(story.title),
            normalize_identity_title(story.summary),
            *(normalize_identity_title(tag) for tag in story.tags),
            *(normalize_identity_title(entity) for entity in story.entities),
        ]
    )
    searchable_tokens = title_tokens(searchable)
    matched_interests = [
        interest
        for interest in resolved.user_interests
        if interest in searchable or interest in searchable_tokens
    ]
    interest = (
        min(1.0, len(matched_interests) / len(resolved.user_interests))
        if resolved.user_interests
        else 0.0
    )

    components = {
        "diversity": diversity,
        "reliability": reliability,
        "activity": activity,
        "recency": recency,
        "interest": interest,
    }
    score = 100 * sum(
        components[name] * resolved.weights[name] for name in _COMPONENT_NAMES
    )
    reasons = [f"{len(sources)} independent source(s)"]
    if reliabilities:
        reasons.append(f"Source reliability {reliability:.2f}")
    reasons.append(f"{evidence_count} evidence observation(s) over {span_hours:.1f}h")
    reasons.append(f"Last activity {age_hours:.1f}h ago")
    if matched_interests:
        reasons.append(f"Interest matches: {', '.join(matched_interests)}")
    return ImportanceBreakdown(
        score=score,
        components=components,
        reasons=reasons,
        version=resolved.version,
    )


def rank_stories(
    stories: list[Story],
    evidence: dict[str, RankingEvidence],
    config: RankingConfig | Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> list[Story]:
    """Apply Importance and return a fully deterministic total ordering."""
    resolved = config if isinstance(config, RankingConfig) else RankingConfig.from_mapping(config)
    for story in stories:
        story_evidence = evidence.get(story.id, RankingEvidence(items=()))
        if story_evidence.last_observed_at is not None:
            story.last_activity_at = max(
                story.last_activity_at,
                story_evidence.last_observed_at,
            )
        story.importance = score_story(
            story,
            story_evidence,
            resolved,
            now=now,
        )
    return sorted(
        stories,
        key=lambda story: (-story.importance.score, -story.event_time.timestamp(), story.id),
    )


__all__ = ["RankingConfig", "RankingEvidence", "rank_stories", "score_story"]
