from datetime import datetime, timedelta, timezone

import pytest

from trendradar.core.models import ContentItem
from trendradar.intelligence.clustering import ClusteringConfig, cluster_items
from trendradar.intelligence.story_generator import (
    MAX_SUMMARY_LENGTH,
    WordingResult,
    generate_story,
)

NOW = datetime(2026, 9, 4, 6, tzinfo=timezone.utc)


def _item(
    title: str,
    source: str,
    *,
    hours: int = 0,
    content: str = "",
    source_name: str = "",
) -> ContentItem:
    return ContentItem.create(
        title=title,
        content=content,
        url=f"https://example.com/{source.replace(':', '-')}/{hours}",
        source=source,
        domain="ai",
        published_time=NOW + timedelta(hours=hours),
        collected_at=NOW + timedelta(hours=hours),
        tags=["models"],
        metadata={"source_name": source_name},
    )


def _cluster(items):
    config = ClusteringConfig.from_mapping(
        {"entity_keywords": {"openai": ["OpenAI"], "gpt-5": ["GPT-5", "GPT 5"]}}
    )
    return cluster_items(items, config)[0]


def test_fallback_generation_is_readable_offline_and_order_independent():
    first = _item(
        "[ArXiv] OpenAI launches the GPT-5 model",
        "rss:first",
        content="The model adds stronger reasoning.",
        source_name="ArXiv",
    )
    second = _item(
        "OpenAI launches GPT 5 model worldwide",
        "ai_frontier:blog",
        hours=1,
        source_name="Official Blog",
    )
    cluster = _cluster([first, second])

    forward = generate_story(cluster, [first, second])
    reverse = generate_story(cluster, [second, first])

    assert forward == reverse
    assert forward.title == "OpenAI launches the GPT-5 model"
    assert "The model adds stronger reasoning." in forward.summary
    assert "Sources: 2" in forward.summary
    assert forward.metadata["source_count"] == 2


def test_empty_content_still_generates_singleton_summary():
    item = _item("Independent AI release", "rss:first")
    story = generate_story(_cluster([item]), [item])
    assert story.title == item.title
    assert story.summary == "Sources: 1 (rss:first). Evidence items: 1."
    assert len(story.summary) <= MAX_SUMMARY_LENGTH


def test_wording_client_can_change_only_title_and_summary():
    item = _item("OpenAI launches GPT-5 model", "rss:first", content="Details")
    cluster = _cluster([item])
    fallback = generate_story(cluster, [item])

    class Client:
        def enhance(self, *, title, summary):
            assert title == fallback.title
            assert summary == fallback.summary
            return WordingResult("Enhanced title", "Enhanced summary")

    enhanced = generate_story(cluster, [item], Client())
    assert enhanced.title == "Enhanced title"
    assert enhanced.summary == "Enhanced summary"
    assert enhanced.id == fallback.id
    assert enhanced.identity_key == fallback.identity_key
    assert enhanced.member_ids == fallback.member_ids
    assert enhanced.importance == fallback.importance


@pytest.mark.parametrize("response", [{}, {"title": "", "summary": "bad"}, None])
def test_invalid_wording_uses_exact_fallback(response):
    item = _item("OpenAI launches GPT-5 model", "rss:first")
    cluster = _cluster([item])

    class Client:
        def enhance(self, **_kwargs):
            return response

    assert generate_story(cluster, [item], Client()) == generate_story(cluster, [item])


def test_wording_exception_uses_exact_fallback():
    item = _item("OpenAI launches GPT-5 model", "rss:first")
    cluster = _cluster([item])

    class Client:
        def enhance(self, **_kwargs):
            raise TimeoutError("provider timeout")

    assert generate_story(cluster, [item], Client()) == generate_story(cluster, [item])


def test_generator_rejects_cluster_item_mismatch():
    item = _item("OpenAI launches GPT-5 model", "rss:first")
    with pytest.raises(ValueError, match="must match"):
        generate_story(_cluster([item]), [])
