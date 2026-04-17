"""AIFrontierStorage 测试"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from trendradar.ai_frontier.sources.base import AIItem
from trendradar.ai_frontier.storage import AIFrontierStorage


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "ai.db"


def _item(source="arxiv", url="https://u1", title="t", score=0, title_translated=""):
    return AIItem(
        source=source,
        source_name=f"src-{source}",
        title=title,
        url=url,
        score=score,
        title_translated=title_translated,
    )


def test_storage_creates_schema_and_empty(tmp_db):
    with AIFrontierStorage(tmp_db) as s:
        assert s.count() == 0


def test_upsert_inserts_new_items(tmp_db):
    with AIFrontierStorage(tmp_db) as s:
        items = [_item(url="https://a"), _item(url="https://b")]
        new, updated = s.upsert_items(items)
        assert len(new) == 2
        assert len(updated) == 0
        assert all(i.is_new for i in new)
        assert s.count() == 2


def test_upsert_updates_existing_items(tmp_db):
    with AIFrontierStorage(tmp_db) as s:
        s.upsert_items([_item(url="https://a", score=10)])
        new, updated = s.upsert_items([_item(url="https://a", score=50)])
        assert len(new) == 0
        assert len(updated) == 1
        assert updated[0].is_new is False

        # 验证 score 已更新
        rows = s.get_recent()
        assert rows[0].score == 50


def test_upsert_preserves_translation_when_empty(tmp_db):
    with AIFrontierStorage(tmp_db) as s:
        s.upsert_items([_item(url="https://a", title_translated="中文翻译")])
        # 再次插入不带翻译，应保留原翻译
        s.upsert_items([_item(url="https://a", title_translated="")])
        rows = s.get_recent()
        assert rows[0].title_translated == "中文翻译"


def test_get_new_since_returns_only_new(tmp_db):
    with AIFrontierStorage(tmp_db) as s:
        checkpoint = datetime.now(tz=timezone.utc).isoformat()
        s.upsert_items([_item(url="https://a"), _item(url="https://b")])
        new = s.get_new_since(checkpoint)
        assert len(new) == 2
        assert all(i.is_new for i in new)


def test_source_url_uniqueness(tmp_db):
    """同 source+url 视为同一条；不同 source 视为独立条"""
    with AIFrontierStorage(tmp_db) as s:
        s.upsert_items([_item(source="arxiv", url="https://u")])
        s.upsert_items([_item(source="reddit", url="https://u")])
        assert s.count() == 2


def test_roundtrip_preserves_metadata(tmp_db):
    with AIFrontierStorage(tmp_db) as s:
        item = AIItem(
            source="hackernews",
            source_name="HN",
            title="hello",
            url="https://x",
            published_at=datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc),
            score=99,
            author="alice",
            summary="s",
            tags=["ai", "llm"],
            title_translated="你好",
        )
        s.upsert_items([item])
        rows = s.get_recent()
        assert len(rows) == 1
        r = rows[0]
        assert r.source == "hackernews"
        assert r.score == 99
        assert r.tags == ["ai", "llm"]
        assert r.title_translated == "你好"
        assert r.published_at is not None
