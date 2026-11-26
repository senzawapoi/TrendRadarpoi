"""TDD tests for Component 2 & 3:
1. Settled (> time_window_hours) already-clustered items refresh Story activity/importance without triggering full-history StoryService._context_items clustering.
2. Deferred/unclustered old items (e.g. pending translation resolved later) STILL enter StoryService.process.
3. Single-pass general-domain Story finalization merges Hotboard + RSS canonical IDs into one clustering & report pass.
4. --scope CLI on trendradar.__main__ isolates general, hotboard, rss, and security execution while keeping default 'all'.
5. IntelligenceStorage.upsert_story_batch skips redundant SQLite writes (preserving updated_at) when cluster/story fields are unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trendradar.core.models import ContentItem
from trendradar.intelligence.pipeline import persist_adapter_results_best_effort
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.intelligence.stories import StoryService
from trendradar.intelligence.translation import CanonicalTitleTranslator
from trendradar.sources.base import AdapterResult


def test_settled_resighting_refreshes_story_without_loading_ancient_clustering_context(
    tmp_path, monkeypatch
):
    t0 = datetime(2026, 10, 23, 4, 0, tzinfo=timezone.utc)
    now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    story_cfg = {
        "enabled": True,
        "clustering": {"time_window_hours": 24},
        "report": {"enabled": False},
    }

    with IntelligenceStorage(tmp_path / "intelligence.db", story_config=story_cfg) as storage:
        ancient_sticky = ContentItem.create(
            title="Pinned GitHub Repository",
            url="https://github.com/org/pinned-repo",
            source="newsnow:github",
            domain="general",
            collected_at=t0,
        )
        bystanders = [
            ContentItem.create(
                title=f"Ancient October News {idx}",
                url=f"https://news.example/oct-{idx}",
                source="newsnow:jin10",
                domain="general",
                published_time=t0 + timedelta(minutes=idx),
                collected_at=t0 + timedelta(minutes=idx),
            )
            for idx in range(20)
        ]
        persist_adapter_results_best_effort(
            [AdapterResult(adapter_id="newsnow:github", items=[ancient_sticky, *bystanders])],
            storage,
        )
        original_story = storage.get_story(
            next(iter(storage.story_ids_for_members([ancient_sticky.id], domain="general")))
        )
        assert original_story is not None

        resighted = ContentItem.create(
            title="Pinned GitHub Repository",
            url="https://github.com/org/pinned-repo",
            source="rss:hacker-news",
            domain="general",
            collected_at=now,
        )
        fresh_today = ContentItem.create(
            title="Fresh November Release",
            url="https://news.example/nov-25",
            source="rss:hacker-news",
            domain="general",
            published_time=now - timedelta(minutes=15),
            collected_at=now,
        )

        clustered_inputs: list[list[str]] = []
        orig_context = StoryService._context_items

        def spy_context(self, items):
            ctx = orig_context(self, items)
            clustered_inputs.append([i.id for i in ctx])
            return ctx

        monkeypatch.setattr(StoryService, "_context_items", spy_context)

        persist_adapter_results_best_effort(
            [AdapterResult(adapter_id="rss:hacker-news", items=[resighted, fresh_today])],
            storage,
        )

        assert len(clustered_inputs) == 1
        loaded_ids = set(clustered_inputs[0])
        assert fresh_today.id in loaded_ids
        assert ancient_sticky.id not in loaded_ids
        assert loaded_ids.isdisjoint({b.id for b in bystanders})

        refreshed = storage.get_story(original_story.id)
        assert refreshed is not None
        assert refreshed.last_activity_at == now
        assert "2 independent source(s)" in refreshed.importance.reasons


def test_old_unclustered_item_still_enters_clustering_when_resolved(tmp_path):
    old_time = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    story_cfg = {"enabled": True, "report": {"enabled": False}}

    with IntelligenceStorage(tmp_path / "intelligence.db", story_config=story_cfg) as storage:
        deferred = ContentItem.create(
            title="Deferred English Headline",
            url="https://example.com/deferred",
            source="rss:ars",
            domain="general",
            published_time=old_time,
            collected_at=old_time,
            metadata={"title_translation": {"status": "pending", "original_title": "Deferred English Headline"}},
        )
        storage.write_batch([deferred])
        assert storage.list_stories() == []

        retry_item = ContentItem.create(
            title="Deferred English Headline",
            url="https://example.com/deferred",
            source="rss:ars",
            domain="general",
            published_time=old_time,
            collected_at=now,
        )
        persist_adapter_results_best_effort(
            [AdapterResult(adapter_id="rss:ars", items=[retry_item])],
            storage,
            title_translator=CanonicalTitleTranslator(lambda _: ["延迟标题中文"]),
        )
        stories = storage.list_stories()
        assert len(stories) == 1
        assert stories[0].title == "延迟标题中文"


def test_single_pass_general_finalization_clusters_hotboard_and_rss_together_once(
    tmp_path, monkeypatch
):
    from trendradar.intelligence import pipeline

    assert hasattr(pipeline, "finalize_stories_best_effort"), "missing finalize_stories_best_effort"
    finalize_stories_best_effort = pipeline.finalize_stories_best_effort

    now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    story_cfg = {"enabled": True, "report": {"enabled": False}}

    with IntelligenceStorage(tmp_path / "intelligence.db", story_config=story_cfg) as storage:
        hot_item = ContentItem.create(
            title="OpenAI unveils new hardware chip",
            url="https://example.com/openai-chip",
            source="newsnow:ithome",
            domain="general",
            collected_at=now,
        )
        rss_item = ContentItem.create(
            title="OpenAI unveils new hardware chip",
            url="https://example.com/openai-chip",
            source="rss:techcrunch",
            domain="general",
            published_time=now - timedelta(minutes=10),
            collected_at=now,
        )

        process_calls = []
        orig_process = StoryService.process

        def spy_process(self, items, **kwargs):
            process_calls.append([i.id for i in items])
            return orig_process(self, items, **kwargs)

        monkeypatch.setattr(StoryService, "process", spy_process)

        pending_ids: set[str] = set()
        persist_adapter_results_best_effort(
            [AdapterResult(adapter_id="newsnow:ithome", items=[hot_item])],
            storage,
            process_stories=False,
            pending_story_ids=pending_ids,
        )
        persist_adapter_results_best_effort(
            [AdapterResult(adapter_id="rss:techcrunch", items=[rss_item])],
            storage,
            process_stories=False,
            pending_story_ids=pending_ids,
        )
        assert process_calls == []
        assert len(pending_ids) == 1

        batch_res = finalize_stories_best_effort(
            pending_ids,
            storage,
            now=now,
            story_domain="general",
        )
        assert len(process_calls) == 1
        assert len(batch_res.stories) == 1
        assert "2 independent source(s)" in batch_res.stories[0].importance.reasons


def test_upsert_story_batch_skips_noop_writes_when_unchanged(tmp_path):
    now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    story_cfg = {"enabled": True, "report": {"enabled": False}}

    with IntelligenceStorage(tmp_path / "intelligence.db", story_config=story_cfg) as storage:
        item = ContentItem.create(
            title="Unchanged Singleton Event",
            url="https://example.com/singleton",
            source="rss:bbc_news",
            domain="general",
            published_time=now,
            collected_at=now,
        )
        persist_adapter_results_best_effort(
            [AdapterResult(adapter_id="rss:bbc_news", items=[item])],
            storage,
        )
        story_row_1 = dict(
            storage.connection.execute("SELECT * FROM stories").fetchone()
        )
        member_row_1 = dict(
            storage.connection.execute("SELECT * FROM story_members").fetchone()
        )

        story_obj = storage.list_stories()[0]
        import time
        time.sleep(0.01)
        storage.upsert_story_batch([], [story_obj])

        story_row_2 = dict(
            storage.connection.execute("SELECT * FROM stories").fetchone()
        )
        member_row_2 = dict(
            storage.connection.execute("SELECT * FROM story_members").fetchone()
        )
        assert story_row_2["updated_at"] == story_row_1["updated_at"]
        assert member_row_2["last_seen_at"] == member_row_1["last_seen_at"]


def test_main_cli_parse_scope_defaults_and_isolates_security(monkeypatch, tmp_path):
    import trendradar.__main__ as main_mod

    assert hasattr(main_mod, "_parse_cli_args"), "missing _parse_cli_args"
    assert main_mod._parse_cli_args([]).scope == "all"
    assert main_mod._parse_cli_args(["--scope", "general"]).scope == "general"
    assert main_mod._parse_cli_args(["--scope", "security"]).scope == "security"
    with pytest.raises(SystemExit):
        main_mod._parse_cli_args(["--scope", "invalid"])
def test_run_main_scope_isolation_and_single_pass_general_clustering(monkeypatch, tmp_path):
    import trendradar.__main__ as main_mod
    from trendradar.intelligence import integration, pipeline
    from trendradar.storage.base import NewsData, NewsItem, RSSData, RSSItem

    calls: list[str] = []

    class DummyStorageManager:
        def save_news_data(self, data):
            calls.append("save_news")
            return True

        def save_rss_data(self, data):
            calls.append("save_rss")
            return True

        def detect_new_rss_items(self, data):
            return {}

        def is_first_crawl_today(self):
            return True

    class DummyCtx:
        rss_enabled = True
        timezone = "Asia/Shanghai"
        rank_threshold = 10

        def __init__(self, config):
            self.config = config
            self.platforms = [{"id": "ithome", "name": "IT之家"}]
            self.rss_feeds = [
                {"id": "hn", "name": "HN", "url": "https://hn.example/rss", "enabled": True}
            ]
            self.rss_config = {"FRESHNESS_FILTER": {"ENABLED": True, "MAX_AGE_DAYS": 3}}
            self.weight_config = {}

        def get_storage_manager(self):
            return DummyStorageManager()

        def get_time_display(self):
            return "12:00"

        def format_date(self):
            return "2026-11-25"

        def get_time(self):
            return datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)

        def save_titles(self, *a, **k):
            pass

        def detect_new_titles(self, *a, **k):
            return {}

        def load_frequency_words(self):
            raise FileNotFoundError("skip freq")

        def generate_html(self, **kwargs):
            calls.append("generate_html")
            return str(tmp_path / "index.html")

        def cleanup(self):
            calls.append("cleanup")

    db_path = tmp_path / "intelligence.db"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INTELLIGENCE_DB_PATH", str(db_path))
    monkeypatch.setenv("GEMINI_ENABLED", "false")

    import trendradar.context as ctx_mod
    import trendradar.core as core_mod

    monkeypatch.setattr(ctx_mod, "AppContext", DummyCtx)
    monkeypatch.setattr(
        core_mod,
        "load_config",
        lambda: {
            "INTELLIGENCE": {
                "ENABLED": True,
                "STORY": {"enabled": True, "report": {"enabled": False}},
                "SECURITY": {"enabled": True},
            },
            "STORAGE": {"FORMATS": {"TXT": False}},
            "REPORT_MODE": "current",
        },
    )

    def fake_newsnow(*args, **kwargs):
        assert kwargs.get("process_stories") is False
        calls.append("newsnow")
        if kwargs.get("pending_story_ids") is not None:
            kwargs["pending_story_ids"].add("cid-hot")
        return NewsData(
            date="2026-11-25",
            crawl_time="12:00",
            items={"ithome": [NewsItem(title="Hot 1", source_id="ithome", source_name="IT之家", rank=1, url="https://e.com/1", crawl_time="12:00")]},
            id_to_name={"ithome": "IT之家"},
            failed_ids=[],
        )

    def fake_rss(*args, **kwargs):
        assert kwargs.get("process_stories") is False
        calls.append("rss")
        if kwargs.get("pending_story_ids") is not None:
            kwargs["pending_story_ids"].add("cid-rss")
        return RSSData(
            date="2026-11-25",
            crawl_time="12:00",
            items={"hn": [RSSItem(title="RSS 1", feed_id="hn", feed_name="HN", url="https://e.com/2", published_at="2026-11-25T11:00:00Z", crawl_time="12:00")]},
            id_to_name={"hn": "HN"},
            failed_ids=[],
        )

    def fake_finalize(ids, storage, **kwargs):
        calls.append(f"finalize:{sorted(ids)}:{kwargs.get('story_domain')}")
        from trendradar.intelligence.stories import StoryBatchResult
        return StoryBatchResult(stories=[])

    monkeypatch.setattr(integration, "fetch_newsnow_with_adapters", fake_newsnow)
    monkeypatch.setattr(integration, "fetch_rss_with_adapters", fake_rss)
    monkeypatch.setattr(pipeline, "finalize_stories_best_effort", fake_finalize, raising=False)
    monkeypatch.setattr(
        main_mod,
        "_run_security_best_effort",
        lambda **kw: calls.append("security"),
    )

    assert main_mod._run_main(scope="general") is True
    assert calls == [
        "newsnow",
        "save_news",
        "rss",
        "save_rss",
        "finalize:['cid-hot', 'cid-rss']:general",
        "generate_html",
        "cleanup",
    ]

    calls.clear()
    assert main_mod._run_main(scope="security") is True
    assert calls == ["security", "cleanup"]
