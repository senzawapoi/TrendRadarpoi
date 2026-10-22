from datetime import datetime, timedelta, timezone

import pytest

from trendradar.core.models import ContentItem, Story, deterministic_story_id
from trendradar.intelligence.ranking import (
    RankingConfig,
    RankingEvidence,
    rank_stories,
    score_story,
)

NOW = datetime(2026, 9, 4, 6, tzinfo=timezone.utc)


def _item(title: str, source: str, index: int) -> ContentItem:
    return ContentItem.create(
        title=title,
        url=f"https://example.com/{index}",
        source=source,
        domain="ai",
        published_time=NOW - timedelta(hours=24),
        collected_at=NOW - timedelta(hours=24),
    )


def _story(items: list[ContentItem], *, event_time=None, key="story") -> Story:
    timestamp = event_time or NOW - timedelta(hours=24)
    return Story(
        id=deterministic_story_id(key),
        identity_key=key,
        title="OpenAI ships a coding model",
        summary="The release improves agent workflows.",
        domain="ai",
        event_time=timestamp,
        last_activity_at=timestamp,
        member_ids=[item.id for item in items],
        tags=["coding"],
        entities=["openai"],
    )


def test_importance_contains_all_components_and_readable_reasons():
    first = _item("One", "rss:trusted", 1)
    second = _item("Two", "ai_frontier:arxiv", 2)
    story = _story([first, second])
    config = RankingConfig.from_mapping(
        {
            "source_reliability": {"rss:trusted": 1.0},
            "user_interests": ["openai", "security"],
        }
    )
    evidence = RankingEvidence(
        items=(first, second),
        observation_sources=("rss:trusted", "ai_frontier:arxiv"),
        observation_count=3,
    )

    importance = score_story(story, evidence, config, now=NOW)

    assert set(importance.components) == {
        "diversity",
        "reliability",
        "activity",
        "recency",
        "interest",
    }
    assert importance.components["diversity"] == 0.5
    assert importance.components["reliability"] == 0.95
    assert importance.components["recency"] == pytest.approx(0.5)
    assert importance.components["interest"] == 0.5
    assert any("independent source" in reason for reason in importance.reasons)
    assert any("Interest matches: openai" in reason for reason in importance.reasons)


def test_ranking_has_complete_deterministic_tie_breakers():
    item = _item("One", "rss:one", 1)
    older = _story([item], event_time=NOW - timedelta(hours=2), key="older")
    newer_b = _story([item], event_time=NOW - timedelta(hours=1), key="newer-b")
    newer_a = _story([item], event_time=NOW - timedelta(hours=1), key="newer-a")
    evidence = {
        story.id: RankingEvidence(items=(item,), observation_sources=(item.source,), observation_count=1)
        for story in (older, newer_b, newer_a)
    }
    config = {"weights": {"diversity": 1, "reliability": 0, "activity": 0,
                           "recency": 0, "interest": 0}}

    ranked = rank_stories([older, newer_b, newer_a], evidence, config, now=NOW)

    expected_newer = sorted([newer_a.id, newer_b.id])
    assert [story.id for story in ranked] == [*expected_newer, older.id]


def test_malformed_ranking_config_uses_safe_defaults():
    config = RankingConfig.from_mapping(
        {
            "recency_half_life_hours": "bad",
            "activity_target": "bad",
            "diversity_target": None,
            "weights": {"recency": "bad"},
        }
    )
    assert config.recency_half_life_hours == 24.0
    assert config.activity_target == 6
    assert config.diversity_target == 4
    assert sum(config.weights.values()) == pytest.approx(1.0)


def test_scalar_ranking_sections_use_safe_defaults():
    config = RankingConfig.from_mapping(
        {"weights": "bad", "source_reliability": 7, "user_interests": 42}
    )
    non_mapping = RankingConfig.from_mapping("bad")  # type: ignore[arg-type]

    assert config.weights == non_mapping.weights
    assert config.source_reliability == non_mapping.source_reliability
    assert config.user_interests == ()


def test_score_rejects_naive_reference_time():
    item = _item("One", "rss:one", 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        score_story(
            _story([item]),
            RankingEvidence(items=(item,)),
            now=datetime(2026, 9, 4, 6),
        )
