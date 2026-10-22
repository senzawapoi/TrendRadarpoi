from datetime import date, datetime, timezone

from trendradar.ai_frontier.sources.base import AIItem
from trendradar.ai_frontier.storage import AIFrontierStorage
from trendradar.core.settings import load_settings
from trendradar.intelligence import backfill as backfill_module
from trendradar.intelligence.backfill import run_backfill
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.storage.base import NewsData, NewsItem, RSSData, RSSItem
from trendradar.storage.local import LocalStorageBackend


def _settings(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "app:\n  timezone: Asia/Shanghai\n"
        f"storage:\n  local:\n    data_dir: {tmp_path.as_posix()}/output\n"
        f"ai_frontier:\n  database_path: {tmp_path.as_posix()}/ai.db\n"
        "intelligence:\n"
        f"  database_path: {tmp_path.as_posix()}/intelligence.db\n",
        encoding="utf-8",
    )
    return load_settings(config, environ={})


def _seed_legacy(settings):
    storage = LocalStorageBackend(
        data_dir=str(settings.database_path),
        enable_txt=False,
        enable_html=False,
    )
    try:
        storage.save_news_data(
            NewsData(
                date="2026-08-20",
                crawl_time="10:00",
                items={
                    "hot": [
                        NewsItem(
                            title="Hot",
                            source_id="hot",
                            source_name="Hot List",
                            rank=1,
                            url="https://example.com/hot",
                            crawl_time="10:00",
                            first_time="10:00",
                            last_time="10:00",
                            ranks=[1],
                        )
                    ]
                },
                id_to_name={"hot": "Hot List"},
            )
        )
        storage.save_rss_data(
            RSSData(
                date="2026-08-20",
                crawl_time="11:00",
                items={
                    "feed": [
                        RSSItem(
                            title="Feed",
                            feed_id="feed",
                            feed_name="Feed",
                            url="https://example.com/feed",
                            published_at="2026-08-20T02:00:00+00:00",
                            crawl_time="11:00",
                            first_time="11:00",
                            last_time="11:00",
                        )
                    ]
                },
                id_to_name={"feed": "Feed"},
            )
        )
    finally:
        storage.cleanup()
    with AIFrontierStorage(settings.ai_frontier_database_path) as storage:
        storage.upsert_items(
            [
                AIItem(
                    source="arxiv",
                    source_name="ArXiv",
                    title="AI",
                    url="https://example.com/ai",
                    published_at=datetime(2026, 8, 20, 3, tzinfo=timezone.utc),
                ),
                AIItem(
                    source="arxiv",
                    source_name="ArXiv",
                    title="Old",
                    url="https://example.com/old",
                    published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                ),
            ]
        )


def test_backfill_filters_dates_and_is_idempotent(tmp_path):
    settings = _settings(tmp_path)
    _seed_legacy(settings)
    first = run_backfill(
        start=date(2026, 8, 20),
        end=date(2026, 8, 20),
        settings=settings,
    )
    second = run_backfill(
        start=date(2026, 8, 20),
        end=date(2026, 8, 20),
        settings=settings,
    )
    assert first.scanned == 3
    assert first.content_items_created == 3
    assert first.observations_created == 3
    assert first.stories_created == 3
    assert first.story_memberships_created == 3
    assert second.content_items_created == 0
    assert second.observations_created == 0
    assert second.stories_created == 0
    assert second.story_memberships_created == 0
    with IntelligenceStorage(settings.intelligence_database_path) as storage:
        assert storage.count() == 3
        assert storage.count("stories") == 3
        assert storage.count("story_members") == 3


def test_backfill_orders_source_batches_by_event_time(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _seed_legacy(settings)
    captured: list[list[str]] = []

    def capture_batch(items, _storage, _summary):
        captured.append([item.title for item in items])

    monkeypatch.setattr(backfill_module, "_persist_batch", capture_batch)

    run_backfill(
        start=date(2026, 8, 1),
        end=date(2026, 8, 20),
        settings=settings,
    )

    assert captured == [["Old"], ["Hot"], ["Feed"], ["AI"]]


def test_backfill_include_and_dry_run_do_not_create_target(tmp_path):
    settings = _settings(tmp_path)
    _seed_legacy(settings)
    summary = run_backfill(
        start=date(2026, 8, 20),
        end=date(2026, 8, 20),
        include={"rss"},
        dry_run=True,
        settings=settings,
    )
    assert summary.scanned == 1
    assert summary.content_items_created == 1
    assert not settings.intelligence_database_path.exists()


def test_backfill_skips_missing_and_corrupt_legacy_database(tmp_path):
    settings = _settings(tmp_path)
    corrupt = settings.database_path / "news" / "2026-08-20.db"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("not sqlite", encoding="utf-8")
    summary = run_backfill(
        start=date(2026, 8, 20),
        end=date(2026, 8, 21),
        include={"news", "rss"},
        dry_run=True,
        settings=settings,
    )
    assert summary.scanned == 0
    assert summary.skipped_databases == [str(corrupt)]


def test_disabled_intelligence_backfill_does_not_open_or_create_target(tmp_path):
    config = tmp_path / "disabled.yaml"
    target = tmp_path / "disabled-intelligence.db"
    config.write_text(
        "intelligence:\n"
        "  enabled: false\n"
        f"  database_path: {target.as_posix()}\n",
        encoding="utf-8",
    )
    settings = load_settings(config, environ={})

    summary = run_backfill(
        start=date(2026, 8, 20),
        end=date(2026, 8, 20),
        settings=settings,
    )

    assert summary.scanned == 0
    assert summary.content_items_created == 0
    assert not target.exists()
