"""Tests for bounded local Story and ContentItem retrieval."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from trendradar.ai.models import TimeRange
from trendradar.ai.retrieval import (
    LocalRetriever,
    RetrievalLimits,
    content_item_citation,
)
from trendradar.core.models import ContentItem

NOW = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)


def test_retrieval_uses_ranked_stories_and_excludes_every_story_member(
    seeded_intelligence,
) -> None:
    retriever = LocalRetriever(
        seeded_intelligence.storage,
        limits=RetrievalLimits(max_members_per_story=1, max_items=20),
    )

    result = retriever.retrieve("AI", now=NOW)

    assert [bundle.story.id for bundle in result.stories] == [
        seeded_intelligence.story.id
    ]
    assert len(result.stories[0].members) == 1
    assert result.truncation.members is True
    standalone_ids = {item.id for item in result.items}
    assert seeded_intelligence.standalone.id in standalone_ids
    assert not standalone_ids.intersection(item.id for item in seeded_intelligence.members)


def test_retrieval_uses_exact_utc_half_open_edges(seeded_intelligence) -> None:
    start = NOW - timedelta(days=1)
    at_start = ContentItem.create(
        title="Boundary marker at start",
        url="https://example.com/boundary-start",
        source="rss:boundary",
        domain="general",
        published_time=start,
        collected_at=start,
        metadata={"source_content_id": "start"},
    )
    at_end = ContentItem.create(
        title="Boundary marker at end",
        url="https://example.com/boundary-end",
        source="rss:boundary",
        domain="general",
        published_time=NOW,
        collected_at=NOW,
        metadata={"source_content_id": "end"},
    )
    seeded_intelligence.storage.write_batch([at_start, at_end])

    result = LocalRetriever(seeded_intelligence.storage).retrieve(
        "Boundary marker",
        time_range=TimeRange(start, NOW),
        domain="general",
    )

    assert [item.id for item in result.items] == [at_start.id]
    with pytest.raises(ValueError, match="timezone-aware"):
        LocalRetriever(seeded_intelligence.storage).retrieve(
            start=datetime(2026, 9, 1),
            end=NOW,
        )


def test_like_metacharacters_are_escaped(seeded_intelligence) -> None:
    literal = ContentItem.create(
        title="Literal 100%_ready marker",
        url="https://example.com/literal",
        source="rss:literal",
        domain="general",
        published_time=NOW - timedelta(minutes=10),
        collected_at=NOW,
        metadata={"source_content_id": "literal"},
    )
    wildcard_only = ContentItem.create(
        title="Literal 100XYready marker",
        url="https://example.com/wildcard",
        source="rss:literal",
        domain="general",
        published_time=NOW - timedelta(minutes=9),
        collected_at=NOW,
        metadata={"source_content_id": "wildcard"},
    )
    seeded_intelligence.storage.write_batch([literal, wildcard_only])

    result = LocalRetriever(seeded_intelligence.storage).retrieve(
        "%_ready",
        now=NOW + timedelta(seconds=1),
        domain="general",
    )

    assert [item.id for item in result.items] == [literal.id]


def test_caps_truncation_and_immutable_observation_snapshots(
    seeded_intelligence,
) -> None:
    retriever = LocalRetriever(
        seeded_intelligence.storage,
        limits=RetrievalLimits(
            max_stories=1,
            max_members_per_story=1,
            max_observations_per_story=1,
            max_items=1,
            max_citations=2,
            max_context_chars=512,
        ),
    )

    result = retriever.retrieve("", now=NOW)

    assert len(result.stories) == 1
    assert len(result.stories[0].members) == 1
    assert len(result.stories[0].observations) == 1
    assert len(result.items) == 1
    assert len(result.citations) == 2
    assert result.truncation.members is True
    assert result.truncation.observations is True
    assert result.truncation.citations is True
    with pytest.raises(TypeError):
        result.stories[0].observations[0]["title"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        result.citations[0].snapshot["kind"] = "mutated"  # type: ignore[index]

    prompt = result.to_prompt()
    assert len(prompt) <= 512
    assert isinstance(json.loads(prompt), dict)
    with pytest.raises(ValueError, match="at least 2"):
        result.to_prompt(maximum=0)


def test_story_evidence_detail_is_bounded_and_range_scoped(
    seeded_intelligence,
) -> None:
    retriever = LocalRetriever(
        seeded_intelligence.storage,
        limits=RetrievalLimits(
            max_members_per_story=1,
            max_observations_per_story=1,
            max_citations=2,
        ),
    )
    interval = TimeRange.previous_days(NOW, 1)

    result = retriever.retrieve_story_evidence(
        seeded_intelligence.story.id,
        time_range=interval,
    )
    outside = retriever.retrieve_story_evidence(
        seeded_intelligence.story.id,
        time_range=TimeRange(NOW, NOW + timedelta(days=1)),
    )

    assert result.stories[0].story.id == seeded_intelligence.story.id
    assert len(result.stories[0].members) == 1
    assert len(result.stories[0].observations) == 1
    assert {citation.story_id for citation in result.citations} == {
        seeded_intelligence.story.id
    }
    assert outside.stories == ()


def test_borrowed_retriever_storage_is_not_closed(seeded_intelligence) -> None:
    retriever = LocalRetriever(seeded_intelligence.storage)
    retriever.close()
    assert seeded_intelligence.storage.count("stories") == 1


def test_content_item_citation_bounds_body_and_metadata() -> None:
    item = ContentItem.create(
        title="Large evidence",
        content="x" * 10_000,
        url="https://example.com/large",
        source="rss:large",
        domain="general",
        collected_at=NOW,
        metadata={"large": "y" * 10_000, "small": "kept"},
    )

    citation = content_item_citation(item)
    snapshot = citation.to_dict()["snapshot"]["item"]

    assert len(snapshot["content"]) == 2_000
    assert snapshot["metadata"] == {"small": "kept"}
