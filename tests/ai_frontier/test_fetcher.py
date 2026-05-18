"""fetcher 聚合器测试"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from trendradar.ai_frontier.fetcher import (
    build_sources,
    dedupe_items,
    fetch_all,
    filter_by_freshness,
)
from trendradar.ai_frontier.sources.base import AIItem, AISource


class DummySource(AISource):
    source_type = "arxiv"

    def __init__(self, config):
        super().__init__(config)
        self.items = config.get("items", [])
        self.should_raise = config.get("should_raise", False)

    async def fetch(self):
        if self.should_raise:
            raise RuntimeError("boom")
        return self.items


def _item(source, url, pub=None):
    return AIItem(source=source, source_name=source, title="t", url=url, published_at=pub)


def test_build_sources_respects_enabled_flag():
    cfg = {
        "sources": {
            "arxiv": {"enabled": True},
            "reddit": {"enabled": False},
            "hackernews": {"enabled": True},
            "github_trending": {"enabled": False},
            "x_nitter": {"enabled": True},
            "youtube_podcast": {"enabled": True},
            "official_blog": {"enabled": False},
        }
    }
    sources = build_sources(cfg)
    assert len(sources) == 4
    types = {s.source_type for s in sources}
    assert types == {"arxiv", "hackernews", "x", "podcast"}


def test_build_sources_defaults_enabled_true():
    cfg = {"sources": {}}
    sources = build_sources(cfg)
    assert len(sources) == 7  # 全部启用


def test_dedupe_items_by_source_and_url():
    items = [
        _item("arxiv", "https://u1"),
        _item("arxiv", "https://u1"),  # 重复
        _item("reddit", "https://u1"),  # source 不同，保留
        _item("arxiv", "https://u2"),
    ]
    out = dedupe_items(items)
    assert len(out) == 3


def test_filter_by_freshness_keeps_recent_and_unknown():
    now = datetime.now(tz=timezone.utc)
    items = [
        _item("arxiv", "https://u1", pub=now - timedelta(hours=2)),
        _item("arxiv", "https://u2", pub=now - timedelta(hours=100)),  # 超过 24h
        _item("arxiv", "https://u3", pub=None),  # 无时间，保留
    ]
    out = filter_by_freshness(items, hours=24)
    urls = {i.url for i in out}
    assert "https://u1" in urls
    assert "https://u3" in urls
    assert "https://u2" not in urls


def test_filter_by_freshness_disabled_when_hours_zero():
    now = datetime.now(tz=timezone.utc)
    items = [_item("arxiv", "https://u", pub=now - timedelta(days=1000))]
    assert filter_by_freshness(items, 0) == items


def test_fetch_all_isolates_source_failures():
    items_a = [_item("arxiv", "https://a")]
    ok = DummySource({"items": items_a, "enabled": True})
    bad = DummySource({"enabled": True, "should_raise": True})

    async def run():
        return await fetch_all([ok, bad])

    out = asyncio.run(run())
    assert len(out) == 1
    assert out[0].url == "https://a"


def test_fetch_all_empty():
    async def run():
        return await fetch_all([])

    assert asyncio.run(run()) == []
