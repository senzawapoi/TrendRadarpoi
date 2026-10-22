"""Characterization tests for the existing SQLite storage contracts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from trendradar.ai_frontier.sources.base import AIItem
from trendradar.ai_frontier.storage import AIFrontierStorage
from trendradar.storage.local import LocalStorageBackend

NEWS_TABLES = {
    "platforms",
    "news_items",
    "title_changes",
    "rank_history",
    "crawl_records",
    "crawl_source_status",
    "push_records",
}
RSS_TABLES = {
    "rss_feeds",
    "rss_items",
    "rss_crawl_records",
    "rss_crawl_status",
    "rss_push_records",
}


def _tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _unique_indexes(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND sql LIKE 'CREATE UNIQUE INDEX%'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def test_core_storage_keeps_news_and_rss_schemas(tmp_path: Path) -> None:
    storage = LocalStorageBackend(data_dir=str(tmp_path))

    try:
        news = storage._get_connection("2026-08-21", db_type="news")
        rss = storage._get_connection("2026-08-21", db_type="rss")

        assert _tables(news) >= NEWS_TABLES
        assert _tables(rss) >= RSS_TABLES
        assert "idx_news_url_platform" in _unique_indexes(news)
        assert "idx_rss_url_feed" in _unique_indexes(rss)
        assert (tmp_path / "news" / "2026-08-21.db").is_file()
        assert (tmp_path / "rss" / "2026-08-21.db").is_file()
    finally:
        storage.cleanup()


def test_ai_frontier_upsert_remains_idempotent(tmp_path: Path) -> None:
    item = AIItem(
        source="arxiv",
        source_name="ArXiv cs.AI",
        title="Compatibility baseline",
        url="https://example.invalid/paper",
        score=10,
    )

    with AIFrontierStorage(tmp_path / "ai_frontier.db") as storage:
        new_items, updated_items = storage.upsert_items([item])
        second_new, second_updated = storage.upsert_items([item])

        assert new_items == [item]
        assert updated_items == []
        assert second_new == []
        assert second_updated == [item]
        assert storage.count() == 1
