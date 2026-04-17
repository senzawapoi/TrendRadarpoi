"""ArXivSource 测试"""

from __future__ import annotations

from trendradar.ai_frontier.sources.arxiv import ArXivSource

SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2601.00001</id>
    <title>Scaling Laws for LLM Alignment</title>
    <summary>We study scaling laws for alignment.</summary>
    <published>2026-04-17T10:00:00Z</published>
    <updated>2026-04-17T10:00:00Z</updated>
    <author><name>Alice</name></author>
    <author><name>Bob</name></author>
    <category term="cs.AI"/>
    <category term="cs.LG"/>
    <link href="http://arxiv.org/abs/2601.00001"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2601.00002</id>
    <title>  Multi-line
    Title Example  </title>
    <summary>short</summary>
    <published>2026-04-17T11:00:00Z</published>
    <author><name>Carol</name></author>
    <category term="cs.CL"/>
    <link href="http://arxiv.org/abs/2601.00002"/>
  </entry>
</feed>
"""


def test_build_url_contains_categories():
    src = ArXivSource({"categories": ["cs.AI", "cs.LG"], "max_results": 10})
    url = src._build_url()
    assert "cat:cs.AI" in url
    assert "cat:cs.LG" in url
    assert "max_results=10" in url


def test_parse_feed_extracts_items():
    src = ArXivSource({"categories": ["cs.AI"]})
    items = src._parse_feed(SAMPLE_ATOM)
    assert len(items) == 2

    first = items[0]
    assert first.source == "arxiv"
    assert "Scaling Laws" in first.title
    assert first.url == "http://arxiv.org/abs/2601.00001"
    assert "Alice" in first.author and "Bob" in first.author
    assert "cs.AI" in first.tags and "cs.LG" in first.tags
    assert first.source_name == "ArXiv cs.AI"
    assert first.published_at is not None


def test_parse_feed_cleans_multiline_title():
    src = ArXivSource({"categories": ["cs.AI"]})
    items = src._parse_feed(SAMPLE_ATOM)
    second = items[1]
    assert "\n" not in second.title
    assert "Multi-line" in second.title


def test_disabled_source_returns_empty(monkeypatch):
    import asyncio

    src = ArXivSource({"enabled": False})

    async def run():
        return await src.fetch()

    assert asyncio.run(run()) == []
