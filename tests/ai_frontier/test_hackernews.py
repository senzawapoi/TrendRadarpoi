"""HackerNewsSource 测试（离线解析）"""

from __future__ import annotations

from trendradar.ai_frontier.sources.hackernews import HackerNewsSource


def _make_sample():
    return {
        "hits": [
            {
                "title": "Claude 4 Opus Released",
                "url": "https://www.anthropic.com/news/claude-4",
                "points": 800,
                "author": "someuser",
                "objectID": "12345",
                "created_at_i": 1713350000,
            },
            {
                "title": "Show HN: LLM Playground",
                "url": "",
                "points": 120,
                "author": "dev",
                "objectID": "67890",
                "created_at_i": 1713350100,
            },
            {
                "title": "",
                "url": "https://empty",
                "points": 200,
                "objectID": "99999",
            },
        ]
    }


def test_parse_hits_uses_external_url_when_available():
    src = HackerNewsSource({})
    items = src._parse_hits("Claude", _make_sample())
    anthropic_item = [i for i in items if "anthropic" in i.url][0]
    assert anthropic_item.source == "hackernews"
    assert anthropic_item.score == 800
    assert anthropic_item.tags == ["Claude"]


def test_parse_hits_falls_back_to_discussion():
    src = HackerNewsSource({})
    items = src._parse_hits("LLM", _make_sample())
    show_hn = [i for i in items if "ycombinator" in i.url][0]
    assert "item?id=67890" in show_hn.url
    assert show_hn.score == 120


def test_parse_hits_skips_empty_title():
    src = HackerNewsSource({})
    items = src._parse_hits("x", _make_sample())
    assert all(i.title for i in items)


def test_parse_hits_empty_data():
    src = HackerNewsSource({})
    assert src._parse_hits("x", {}) == []
    assert src._parse_hits("x", {"hits": []}) == []


def test_disabled_returns_empty():
    import asyncio

    src = HackerNewsSource({"enabled": False})

    async def run():
        return await src.fetch()

    assert asyncio.run(run()) == []
