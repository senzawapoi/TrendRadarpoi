"""Translation publication boundaries, provenance and native Lark post regressions."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from trendradar.__main__ import _apply_translations_to_rss_items, _convert_rss_items_to_list
from trendradar.ai.translator import TRANSLATION_MODEL
from trendradar.ai_frontier import fetcher as ai_fetcher
from trendradar.ai_frontier.sources.base import AIItem
from trendradar.ai_frontier.translator import translate_items
from trendradar.core.models import ContentItem, content_from_ai_item, content_from_rss_item
from trendradar.integrations.feishu.config import FeishuConfig
from trendradar.integrations.feishu.delivery import StoryDelivery
from trendradar.integrations.feishu.post import POST_PREFIX
from trendradar.integrations.feishu.scheduler import DeliveryScheduler
from trendradar.intelligence import integration
from trendradar.intelligence.pipeline import persist_adapter_results_best_effort
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.intelligence.stories import StoryService
from trendradar.intelligence.translation import (
    CanonicalTitleTranslator,
    translate_news_items_canonically,
)
from trendradar.storage.base import NewsItem, RSSItem

NOW = datetime(2026, 10, 23, 5, tzinfo=timezone.utc)
STORIES = {"enabled": True, "report": {"enabled": False}}
TITLE = 'Median product "lifespan" has fallen from ~4y down to ~1.5y'
ZH = '\u4ea7\u54c1\u5bff\u547d\u4e2d\u4f4d\u6570\u4ece\u7ea64\u5e74\u964d\u81f3\u7ea61.5\u5e74'


def result_for(raw, collected_at=NOW):
    from trendradar.sources.base import AdapterResult

    convert = content_from_ai_item if isinstance(raw, AIItem) else content_from_rss_item
    content = convert(raw, collected_at=collected_at)
    return AdapterResult(adapter_id=content.source, items=[content],
                         raw_items=[raw], normalized_raw_items=[raw])


def rss(feed="hn", title=TITLE):
    return RSSItem(title=title, feed_id=feed, feed_name=feed, url="https://example.test/item")


def run_scheduler(storage, client):
    config = FeishuConfig(enabled=True, delivery_enabled=True, delivery_mode="instant",
                          delivery_target="test-chat")
    return DeliveryScheduler(config, storage.db_path, StoryDelivery(storage), client,
                             storage=storage, clock=lambda: NOW)


def test_rss_to_native_post_and_html_waits_for_translation(tmp_path, monkeypatch):
    path = tmp_path / "db"
    raw = rss()
    result = result_for(raw)
    client = Mock(send=Mock(return_value=True))
    cache = {}

    class Runner:
        def __init__(self, **kwargs):
            pass

        async def run(self, *args, **kwargs):
            return [result]

    monkeypatch.setattr(integration, "AdapterRunner", Runner)

    def translate(titles):
        assert titles == [TITLE]
        # A separate writer can acquire the outbox transaction during the provider call.
        with IntelligenceStorage.open_existing(path, story_config=STORIES) as reader:
            assert reader.get_item(result.items[0].id).metadata["title_translation"]["status"] == "pending"
            assert run_scheduler(reader, client).tick() == "empty"
            assert StoryService(reader).process([reader.get_item(result.items[0].id)]).stories == []
            assert reader.list_stories() == []
        client.send.assert_not_called()
        return [ZH]

    provider = Mock(side_effect=translate)
    with IntelligenceStorage(path, story_config=STORIES) as storage:
        projected = integration.fetch_rss_with_adapters(
            [], crawl_date="2026-10-23", crawl_time="13:00", storage=storage,
            title_translator=CanonicalTitleTranslator(provider, legacy_cache=cache),
        )
        assert projected.items["hn"][0].title == TITLE
        item = storage.get_item(result.items[0].id)
        assert item.title == TITLE
        assert item.metadata["title_translated"] == ZH
        record = item.metadata["title_translation"]
        assert record["original_title"] == TITLE and record["model"] == TRANSLATION_MODEL
        observation = storage.list_observations(item.id)[0]
        assert observation["title"] == TITLE
        assert json.loads(observation["metadata_json"])["title_translated"] == ZH
        story = storage.list_stories()[0]
        assert story.title == ZH

        ctx = SimpleNamespace(rss_config={"FRESHNESS_FILTER": {"ENABLED": False}},
                              rss_feeds=[], timezone="Asia/Shanghai")
        rows = _convert_rss_items_to_list(projected, ctx)
        legacy = NewsItem(title=TITLE, source_id="hn")
        legacy._canonical_content_id = rows[0]["_canonical_content_id"]
        forbidden = Mock(side_effect=AssertionError("duplicate translation"))
        translate_news_items_canonically([legacy], forbidden, cache=cache)
        _apply_translations_to_rss_items(rows, [legacy])
        assert rows[0]["title"] == ZH
        forbidden.assert_not_called()
        assert run_scheduler(storage, client).tick() == "sent"
        chunk = client.send.call_args.args[1]
        post = json.loads(chunk.removeprefix(POST_PREFIX))["zh_cn"]
        links = [node for line in post["content"] for node in line if node["tag"] == "a"]
        assert links == [{"tag": "a", "text": ZH, "href": raw.url}]
        assert run_scheduler(storage, client).tick() == "empty"
    provider.assert_called_once()


def test_success_survives_restart_and_new_source_without_changing_sightings(tmp_path):
    path = tmp_path / "db"
    with IntelligenceStorage(path, story_config=STORIES) as storage:
        first = result_for(rss())
        persist_adapter_results_best_effort([first], storage,
                                           title_translator=CanonicalTitleTranslator(lambda _: [ZH]))
        canonical_id = first.items[0].id
        original_observation = dict(storage.list_observations(canonical_id)[0])
        story_id = storage.list_stories()[0].id
    with IntelligenceStorage.open_existing(path, story_config=STORIES) as storage:
        provider = Mock(side_effect=AssertionError("persisted translation was ignored"))
        duplicate = rss(feed="other", title="A syndicated variant")
        result = persist_adapter_results_best_effort(
            [result_for(duplicate, NOW + timedelta(minutes=10))], storage,
            title_translator=CanonicalTitleTranslator(provider),
        )
        assert result.canonical_items == [] and result.canonical_ids == [canonical_id]
        assert duplicate.title_translated == ZH
        assert duplicate.title == "A syndicated variant"
        provider.assert_not_called()
        observations = storage.list_observations(canonical_id)
        assert len(observations) == 2
        assert dict(observations[0]) == original_observation
        assert all(json.loads(row["metadata_json"])["title_translated"] == ZH for row in observations)
        assert storage.list_stories()[0].id == story_id


@pytest.mark.parametrize("outcome", [[""], RuntimeError("provider unavailable"), None])
def test_terminal_fallback_publishes_original_without_legacy_retry(tmp_path, outcome):
    provider = None if outcome is None else Mock(
        side_effect=outcome if isinstance(outcome, Exception) else None,
        return_value=outcome,
    )
    with IntelligenceStorage(tmp_path / "db", story_config=STORIES) as storage:
        item = AIItem(source="hackernews", source_name="HN", title=TITLE, url="https://example.test/a")
        result = result_for(item)
        translator = CanonicalTitleTranslator(provider)
        persist_adapter_results_best_effort([result], storage, title_translator=translator)
        assert storage.list_stories()[0].title == TITLE
        record = storage.get_item(result.items[0].id).metadata["title_translation"]
        assert record["status"] == ("disabled" if outcome is None else "fallback")
        legacy_service = Mock(batch_translate_titles=Mock(side_effect=AssertionError("retried")))
        assert translate_items([item], translation_service=legacy_service) == 0
        legacy_service.batch_translate_titles.assert_not_called()
        if provider:
            provider.assert_called_once()


def test_metadata_write_failure_defers_story_but_preserves_report_and_recovers(tmp_path, monkeypatch):
    with IntelligenceStorage(tmp_path / "db", story_config=STORIES) as storage:
        result = result_for(rss())
        original = storage.update_title_translations
        monkeypatch.setattr(storage, "update_title_translations", Mock(side_effect=OSError("disk")))
        provider = Mock(return_value=[ZH])
        translator = CanonicalTitleTranslator(provider)
        persist_adapter_results_best_effort([result], storage, title_translator=translator)
        assert storage.list_stories() == []
        assert result.raw_items[0].title_translated == ZH
        assert storage.get_item(result.items[0].id).metadata["title_translation"]["status"] == "pending"
        monkeypatch.setattr(storage, "update_title_translations", original)
        persist_adapter_results_best_effort([result_for(rss())], storage, title_translator=translator)
        assert storage.list_stories()[0].title == ZH
        provider.assert_called_once()


def test_interrupted_translation_is_not_publishable_and_recovers_on_next_poll(tmp_path):
    path = tmp_path / "db"
    with IntelligenceStorage(path, story_config=STORIES) as storage:
        with pytest.raises(KeyboardInterrupt):
            persist_adapter_results_best_effort(
                [result_for(rss())], storage,
                title_translator=CanonicalTitleTranslator(Mock(side_effect=KeyboardInterrupt)),
            )
        assert run_scheduler(storage, Mock()).tick() == "empty"
    with IntelligenceStorage.open_existing(path, story_config=STORIES) as storage:
        persist_adapter_results_best_effort(
            [result_for(rss())], storage, title_translator=CanonicalTitleTranslator(lambda _: [ZH]),
        )
        assert storage.list_stories()[0].title == ZH


def test_metadata_update_is_atomic_and_does_not_change_observation_times(tmp_path):
    with IntelligenceStorage(tmp_path / "db") as storage:
        first = result_for(rss()).items[0]
        second = ContentItem.create(title="Other", source="rss:other", domain="general", collected_at=NOW)
        storage.write_batch([first, second])
        outcomes = CanonicalTitleTranslator(lambda titles: [ZH] * len(titles)).resolve([first, second])
        outcomes[second.id]["original_title"] = "stale title"
        before = [dict(row) for row in storage.list_observations()]
        with pytest.raises(ValueError, match="changed"):
            storage.update_title_translations(outcomes)
        assert [dict(row) for row in storage.list_observations()] == before
        assert "title_translation" not in storage.get_item(first.id).metadata


def test_unified_database_failure_reuses_translation_for_legacy(tmp_path, monkeypatch):
    cache = {}
    provider = Mock(return_value=[ZH])
    with IntelligenceStorage(tmp_path / "db") as storage:
        monkeypatch.setattr(storage, "write_batch", Mock(side_effect=OSError("disk")))
        raw = rss()
        outcome = persist_adapter_results_best_effort(
            [result_for(raw)], storage,
            title_translator=CanonicalTitleTranslator(provider, legacy_cache=cache),
        )
        assert outcome.persistence_succeeded is False
        assert raw.title == TITLE and raw.title_translated == ZH
        assert cache[raw._canonical_content_id]["title_translated"] == ZH
        provider.assert_called_once()


def test_wording_cannot_replace_localized_title_and_retry_remains_frozen(tmp_path):
    with IntelligenceStorage(tmp_path / "db", story_config=STORIES) as storage:
        wording = Mock(enhance=Mock(return_value={"title": "English rewrite", "summary": "Summary"}))
        result = result_for(rss())
        persist_adapter_results_best_effort(
            [result], storage, title_translator=CanonicalTitleTranslator(lambda _: [ZH]),
            wording_client=wording,
        )
        assert storage.list_stories()[0].title == ZH
        client = Mock(send=Mock(return_value=False))
        run = run_scheduler(storage, client)
        assert run.tick() == "send_failed"
        original_call = client.send.call_args
        story = storage.list_stories()[0]
        story.title = "An edited display title"
        storage.upsert_story_batch([], [story])
        client.send.return_value = True
        assert run.tick() == "sent"
        assert client.send.call_args == original_call
        assert run.tick() == "empty"


def test_ai_frontier_translates_all_fresh_candidates_before_legacy_push_limit(tmp_path, monkeypatch):
    items = [AIItem(source="hackernews", source_name="HN", title=f"Release {i}",
                    url=f"https://example.test/{i}", published_at=NOW) for i in range(35)]
    items.append(AIItem(source="hackernews", source_name="HN", title="Too old",
                        url="https://example.test/old", published_at=NOW - timedelta(days=3)))

    class Runner:
        def __init__(self, **kwargs):
            pass

        async def run(self, *args):
            return [result_for(item) for item in items]

    monkeypatch.setattr(ai_fetcher, "AdapterRunner", Runner)
    monkeypatch.setattr(ai_fetcher, "build_ai_adapters", lambda _: [])
    provider = Mock(side_effect=lambda titles: [ZH] * len(titles))
    with IntelligenceStorage(tmp_path / "db", story_config=STORIES) as storage:
        fresh = asyncio.run(ai_fetcher.fetch_and_process(
            {"freshness_hours": 24, "push": {"max_items_per_push": 30}}, now=NOW,
            intelligence_storage=storage, title_translator=CanonicalTitleTranslator(provider),
        ))
        assert len(fresh) == 35
        assert len(provider.call_args.args[0]) == 35
        assert all(item.title_translated == ZH for item in fresh)
        assert all(story.title == ZH for story in storage.list_stories())
        assert not items[-1].title_translated


def test_cache_binding_partial_success_and_fallback_retry_on_new_run():
    first = result_for(rss()).items[0]
    second = ContentItem.create(title="Another title", source="rss:second", domain="general", collected_at=NOW)
    translator = CanonicalTitleTranslator(lambda _: [ZH, ""])
    records = translator.resolve([first, second])
    for item in (first, second):
        item.metadata["title_translation"] = records[item.id]
    provider = Mock(return_value=[ZH])
    CanonicalTitleTranslator(provider).resolve([first, second])
    provider.assert_called_once_with([second.title])
    first.title = "Changed canonical title"
    provider.reset_mock()
    CanonicalTitleTranslator(provider).resolve([first])
    provider.assert_called_once_with([first.title])
    provider.reset_mock()
    first.title = TITLE
    CanonicalTitleTranslator(provider, model="new-model").resolve([first])
    provider.assert_called_once_with([TITLE])


def test_pending_context_cannot_be_published_by_another_collector(tmp_path):
    with IntelligenceStorage(tmp_path / "db", story_config=STORIES) as storage:
        pending = result_for(rss()).items[0]
        pending.metadata["title_translation"] = {"status": "pending"}
        other = ContentItem.create(title=TITLE, source="rss:other", domain="general",
                                   collected_at=NOW, url="https://example.test/other")
        storage.write_batch([pending, other])
        stories = StoryService(storage).process([other]).stories
        assert stories
        assert all(pending.id not in story.member_ids for story in stories)


def test_translation_changes_display_not_story_identity_or_interest_ranking(tmp_path):
    from trendradar.intelligence.ranking import RankingEvidence, score_story

    with IntelligenceStorage(tmp_path / "db", story_config=STORIES) as storage:
        item = result_for(rss()).items[0]
        storage.write_batch([item])
        original = StoryService(storage).process([item]).stories[0]
        records = CanonicalTitleTranslator(lambda _: [ZH]).resolve([item])
        storage.update_title_translations(records)
        localized = StoryService(storage).process([storage.get_item(item.id)]).stories[0]
        assert localized.id == original.id
        assert localized.member_ids == original.member_ids
        assert localized.title == ZH and original.title == TITLE
        config = {"user_interests": ["median", "lifespan"]}
        evidence = RankingEvidence(items=(item,))
        assert score_story(original, evidence, config, now=NOW) == score_story(
            localized, evidence, config, now=NOW,
        )


def test_newsnow_entry_publishes_translated_story_and_keeps_raw_news(tmp_path, monkeypatch):
    from trendradar.core.models import content_from_news_item
    from trendradar.sources.base import AdapterResult

    raw = NewsItem(title=TITLE, source_id="hn", url="https://example.test/news")
    content = content_from_news_item(raw, collected_at=NOW)

    async def runner(*args, **kwargs):
        return [AdapterResult(adapter_id="newsnow:hn", items=[content], raw_items=[raw],
                              normalized_raw_items=[raw])]

    monkeypatch.setattr(integration, "run_newsnow_adapters", runner)
    with IntelligenceStorage(tmp_path / "db", story_config=STORIES) as storage:
        news = integration.fetch_newsnow_with_adapters(
            [{"id": "hn", "name": "HN"}], fetcher=Mock(), request_interval_ms=0,
            crawl_date="2026-10-23", crawl_time="13:00", storage=storage,
            title_translator=CanonicalTitleTranslator(lambda _: [ZH]),
        )
        assert news.items["hn"][0].title == TITLE
        assert news.items["hn"][0].title_translated == ZH
        assert storage.list_stories()[0].title == ZH


def test_legacy_ai_translation_metadata_is_respected_without_optional_wording(tmp_path):
    with IntelligenceStorage(tmp_path / "db", story_config=STORIES) as storage:
        raw = AIItem(source="blog", source_name="Blog", title=TITLE, url="https://example.test/ai",
                     title_translated=ZH)
        result = result_for(raw)
        persist_adapter_results_best_effort([result], storage)
        assert storage.list_stories()[0].title == ZH
