import asyncio
from datetime import datetime, timedelta, timezone

from trendradar.ai_frontier import fetcher as ai_fetcher
from trendradar.ai_frontier.sources.base import AIItem
from trendradar.core.models import content_from_ai_item
from trendradar.intelligence.integration import (
    _project_news,
    _project_rss,
    open_intelligence_storage,
)
from trendradar.intelligence.pipeline import persist_adapter_results_best_effort
from trendradar.intelligence.storage import ContentObservation, IntelligenceStorage
from trendradar.sources.base import AdapterResult
from trendradar.storage.base import NewsItem, RSSItem

NOW = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)


def test_news_projection_preserves_group_order_names_and_failed_ids():
    first = NewsItem(title="A", source_id="a", source_name="A", rank=1, ranks=[1])
    results = [
        AdapterResult(adapter_id="newsnow:a", raw_items=[first]),
        AdapterResult(adapter_id="newsnow:b", fetch_error="failed"),
    ]
    projected = _project_news(
        results,
        crawl_date="2026-08-21",
        crawl_time="20:00",
        platform_names={"a": "A", "b": "B"},
    )
    assert projected.items == {"a": [first]}
    assert projected.id_to_name == {"a": "A", "b": "B"}
    assert projected.failed_ids == ["b"]


def test_rss_projection_preserves_empty_success_and_failure():
    item = RSSItem(title="Post", feed_id="a", feed_name="A")
    results = [
        AdapterResult(adapter_id="rss:a", raw_items=[item]),
        AdapterResult(adapter_id="rss:empty", raw_items=[]),
        AdapterResult(adapter_id="rss:failed", fetch_error="failed"),
    ]
    projected = _project_rss(
        results,
        crawl_date="2026-08-21",
        crawl_time="20:00",
        feed_names={"a": "A", "empty": "Empty", "failed": "Failed"},
    )
    assert projected.items == {"a": [item], "empty": []}
    assert projected.failed_ids == ["failed"]


def test_open_intelligence_storage_respects_disabled_and_degrades(tmp_path):
    assert open_intelligence_storage(False, tmp_path / "disabled.db") is None
    assert not (tmp_path / "disabled.db").exists()
    directory = tmp_path / "directory"
    directory.mkdir()
    assert open_intelligence_storage(True, directory) is None


def test_ai_fetch_and_process_defaults_to_adapter_path(monkeypatch):
    item = AIItem(source="arxiv", source_name="ArXiv", title="A", url="https://a")
    normalized = content_from_ai_item(item, collected_at=NOW)
    captured = {}

    class FakeRunner:
        def __init__(self, max_concurrency, storage):
            captured["concurrency"] = max_concurrency
            captured["storage"] = storage

        async def run(self, adapters):
            captured["adapters"] = adapters
            return [
                AdapterResult(
                    adapter_id="ai_frontier:arxiv",
                    raw_items=[item],
                    normalized_raw_items=[item],
                    items=[normalized],
                )
            ]

    monkeypatch.setattr(ai_fetcher, "build_ai_adapters", lambda _config: ["adapter"])
    monkeypatch.setattr(ai_fetcher, "AdapterRunner", FakeRunner)
    monkeypatch.setattr(
        ai_fetcher,
        "persist_adapter_results_best_effort",
        lambda results, storage, **kwargs: captured.update(
            results=results,
            persisted=storage,
            persist_options=kwargs,
        ),
    )
    monkeypatch.setattr(
        ai_fetcher,
        "build_sources",
        lambda _config: (_ for _ in ()).throw(AssertionError("legacy path used")),
    )

    output = asyncio.run(ai_fetcher.fetch_and_process({"freshness_hours": 0}))
    assert output == [item]
    assert captured["adapters"] == ["adapter"]
    assert "results" in captured
    assert captured["persist_options"]["story_content_ids"] == {normalized.id}


def test_ai_fetch_and_process_can_fully_roll_back_to_legacy(monkeypatch):
    item = AIItem(source="arxiv", source_name="ArXiv", title="A", url="https://a")
    captured = {}

    monkeypatch.setattr(ai_fetcher, "build_sources", lambda _config: ["legacy"])

    async def fake_fetch_all(sources):
        captured["sources"] = sources
        return [item]

    monkeypatch.setattr(ai_fetcher, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(
        ai_fetcher,
        "build_ai_adapters",
        lambda _config: (_ for _ in ()).throw(AssertionError("adapter path used")),
    )
    output = asyncio.run(
        ai_fetcher.fetch_and_process({"freshness_hours": 0}, use_adapters=False)
    )
    assert output == [item]
    assert captured["sources"] == ["legacy"]


def test_unified_write_failure_returns_results_without_refetch(tmp_path, monkeypatch):
    item = AIItem(source="arxiv", source_name="ArXiv", title="A", url="https://a")
    content = content_from_ai_item(item, collected_at=NOW)
    result = AdapterResult(
        adapter_id="ai_frontier:arxiv",
        raw_items=[item],
        normalized_raw_items=[item],
        items=[content],
    )
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        calls = {"writes": 0}

        def fail_write(*_args, **_kwargs):
            calls["writes"] += 1
            raise OSError("disk unavailable")

        monkeypatch.setattr(storage, "write_batch", fail_write)
        deduped = persist_adapter_results_best_effort([result], storage)
    assert calls["writes"] == 1
    assert deduped.canonical_items == [content]
    assert item._canonical_content_id == content.id


def test_successful_persistence_builds_ranked_story_without_changing_projection(tmp_path):
    item = AIItem(
        source="arxiv",
        source_name="ArXiv",
        title="OpenAI releases a new reasoning model",
        url="https://example.com/model",
        published_at=NOW,
    )
    content = content_from_ai_item(item, collected_at=NOW)
    result = AdapterResult(
        adapter_id="ai_frontier:arxiv",
        raw_items=[item],
        normalized_raw_items=[item],
        items=[content],
    )
    config = {"enabled": True, "report": {"enabled": False}}
    with IntelligenceStorage(tmp_path / "intelligence.db", story_config=config) as storage:
        deduped = persist_adapter_results_best_effort([result], storage)
        stories = storage.list_stories()

        assert deduped.canonical_items == [content]
        assert len(stories) == 1
        assert stories[0].member_ids == [content.id]
        assert stories[0].importance.score > 0


def test_duplicate_observation_reranks_existing_story_without_new_member(tmp_path):
    url = "https://example.com/shared"
    first = AIItem(source="arxiv", source_name="ArXiv", title="Shared event", url=url)
    second = AIItem(source="blog", source_name="Official Blog", title="Shared event", url=url)
    config = {"enabled": True, "report": {"enabled": False}}
    with IntelligenceStorage(tmp_path / "intelligence.db", story_config=config) as storage:
        for source_key, item in (("arxiv", first), ("official_blog", second)):
            content = content_from_ai_item(item, collected_at=NOW)
            result = AdapterResult(
                adapter_id=f"ai_frontier:{source_key}",
                raw_items=[item],
                normalized_raw_items=[item],
                items=[content],
            )
            persist_adapter_results_best_effort([result], storage)

        story = storage.list_stories()[0]
        assert storage.count("stories") == 1
        assert storage.count("story_members") == 1
        assert len(storage.list_story_evidence(story.id)) == 2
        assert "2 independent source(s)" in story.importance.reasons


def test_disabled_story_config_keeps_phase_one_only(tmp_path):
    item = AIItem(source="arxiv", source_name="ArXiv", title="A", url="https://a")
    content = content_from_ai_item(item, collected_at=NOW)
    result = AdapterResult(adapter_id="ai_frontier:arxiv", items=[content])
    with IntelligenceStorage(
        tmp_path / "intelligence.db", story_config={"enabled": False}
    ) as storage:
        persist_adapter_results_best_effort([result], storage)
        assert storage.count() == 1
        assert storage.count("stories") == 0


def test_unexpected_story_failure_does_not_escape_or_repeat_canonical_write(
    tmp_path, monkeypatch
):
    from trendradar.intelligence import pipeline

    item = AIItem(source="arxiv", source_name="ArXiv", title="A", url="https://a")
    content = content_from_ai_item(item, collected_at=NOW)
    result = AdapterResult(adapter_id="ai_frontier:arxiv", items=[content])
    with IntelligenceStorage(
        tmp_path / "intelligence.db", story_config={"enabled": True}
    ) as storage:
        calls = {"stories": 0}

        def fail_story(*_args, **_kwargs):
            calls["stories"] += 1
            raise RuntimeError("derived failure")

        monkeypatch.setattr(pipeline, "process_stories_after_persist_best_effort", fail_story)
        deduped = pipeline.persist_adapter_results_best_effort([result], storage)
        assert calls["stories"] == 1
        assert deduped.canonical_items == [content]
        assert storage.count() == 1
        assert storage.count("stories") == 0


def test_later_observation_updates_persisted_story_activity(tmp_path):
    item = AIItem(
        source="arxiv",
        source_name="ArXiv",
        title="OpenAI releases a new reasoning model",
        url="https://example.com/activity",
        published_at=NOW,
    )
    content = content_from_ai_item(item, collected_at=NOW)
    adapter_result = AdapterResult(adapter_id="ai_frontier:arxiv", items=[content])
    config = {"enabled": True, "report": {"enabled": False}}

    with IntelligenceStorage(tmp_path / "intelligence.db", story_config=config) as storage:
        persist_adapter_results_best_effort([adapter_result], storage)
        initial = storage.list_stories()[0]
        later = NOW + timedelta(hours=3)
        observation = ContentObservation.from_item(content)
        observation.observed_at = later
        storage.write_batch([], [observation])

        persist_adapter_results_best_effort([adapter_result], storage)
        updated = storage.get_story(initial.id)

        assert updated is not None
        assert updated.last_activity_at == later


def test_report_failure_preserves_story_result_counts(tmp_path, monkeypatch):
    from trendradar.intelligence import pipeline, story_report

    item = AIItem(
        source="arxiv",
        source_name="ArXiv",
        title="OpenAI releases another reasoning model",
        url="https://example.com/report-failure",
        published_at=NOW,
    )
    content = content_from_ai_item(item, collected_at=NOW)
    config = {
        "enabled": True,
        "output_dir": str(tmp_path / "stories"),
        "report": {"enabled": True, "max_stories": "invalid"},
    }

    with IntelligenceStorage(tmp_path / "intelligence.db", story_config=config) as storage:
        deduplicated = pipeline.process_content_items([content], storage=storage)
        captured = {}
        list_stories = storage.list_stories

        def capture_list_stories(**kwargs):
            captured["limit"] = kwargs.get("limit")
            return list_stories(**kwargs)

        monkeypatch.setattr(storage, "list_stories", capture_list_stories)
        monkeypatch.setattr(
            story_report,
            "save_story_report",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("report unavailable")),
        )

        result = pipeline.process_stories_after_persist_best_effort(
            deduplicated,
            storage,
            now=NOW,
        )

        assert result.stories_created == 1
        assert result.memberships_created == 1
        assert captured["limit"] == 100
        assert storage.count("stories") == 1
