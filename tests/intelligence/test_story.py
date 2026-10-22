import json
from datetime import datetime, timezone

import pytest

from trendradar.core.models import (
    Cluster,
    ImportanceBreakdown,
    Story,
    deterministic_cluster_id,
    deterministic_story_id,
)

NOW = datetime(2026, 9, 4, 6, tzinfo=timezone.utc)
FIRST = "0c92f2bf-3ed6-506f-8824-f6c259bf47fd"
SECOND = "f6609347-7273-5388-b3d7-f0a407d21ef9"


def test_cluster_identity_is_member_order_independent_and_round_trips():
    cluster = Cluster(
        id=deterministic_cluster_id([SECOND, FIRST]),
        member_ids=[SECOND, FIRST],
        domain="ai",
        event_time=NOW,
        last_activity_at=NOW,
        tags=["Models", "models"],
        entities=["OpenAI"],
        metadata={"seen": NOW},
    )

    assert cluster.id == deterministic_cluster_id([FIRST, SECOND])
    assert cluster.member_ids == sorted([FIRST, SECOND])
    assert cluster.tags == ["Models"]
    assert Cluster.from_json(cluster.to_json()) == cluster


def test_story_and_importance_round_trip_with_stable_identity():
    identity_key = "ai:openai:gpt-5:2026-09-04"
    story = Story(
        id=deterministic_story_id(identity_key),
        identity_key=identity_key,
        title="OpenAI releases GPT-5",
        summary="Two sources reported the release.",
        domain="ai",
        event_time=NOW,
        last_activity_at=NOW,
        member_ids=[SECOND, FIRST],
        tags=["models"],
        entities=["openai", "gpt-5"],
        importance=ImportanceBreakdown(
            score=82.5,
            components={"recency": 0.8, "diversity": 0.7},
            reasons=["Multiple sources"],
        ),
    )

    restored = Story.from_json(story.to_json())
    assert restored == story
    assert story.id == deterministic_story_id(identity_key.upper())
    assert json.loads(story.to_json())["importance"]["score"] == 82.5


@pytest.mark.parametrize("model", ["cluster", "story"])
def test_story_models_reject_naive_times(model):
    naive = datetime(2026, 9, 4, 6)
    if model == "cluster":
        with pytest.raises(ValueError, match="event_time must be timezone-aware"):
            Cluster(
                id=deterministic_cluster_id([FIRST]),
                member_ids=[FIRST],
                domain="ai",
                event_time=naive,
                last_activity_at=NOW,
            )
    else:
        with pytest.raises(ValueError, match="event_time must be timezone-aware"):
            Story(
                id=deterministic_story_id("event"),
                identity_key="event",
                title="Event",
                summary="",
                domain="ai",
                event_time=naive,
                last_activity_at=NOW,
                member_ids=[FIRST],
            )
