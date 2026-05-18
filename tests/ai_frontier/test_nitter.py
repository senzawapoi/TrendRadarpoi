"""NitterSource 测试（离线 RSS 解析）"""

from __future__ import annotations

from trendradar.ai_frontier.sources.nitter import NitterSource

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>OpenAI / @openai</title>
    <link>https://nitter.net/openai</link>
    <description>Twitter mirror</description>
    <item>
      <title>Introducing GPT-5, our most capable model yet.</title>
      <link>https://nitter.net/openai/status/1234567890</link>
      <pubDate>Thu, 17 Apr 2026 10:00:00 GMT</pubDate>
      <description>Detailed description of GPT-5 launch.</description>
    </item>
    <item>
      <title>We are hiring researchers.</title>
      <link>https://nitter.net/openai/status/9876543210</link>
      <pubDate>Thu, 17 Apr 2026 11:00:00 GMT</pubDate>
      <description>Job post</description>
    </item>
  </channel>
</rss>
"""


def test_parse_rss_extracts_tweets():
    src = NitterSource({"accounts": ["openai"], "max_per_account": 10})
    items = src._parse_rss("openai", SAMPLE_RSS)
    assert len(items) == 2

    first = items[0]
    assert first.source == "x"
    assert first.source_name == "@openai"
    assert first.author == "openai"
    assert "GPT-5" in first.title
    assert first.published_at is not None


def test_parse_rss_rewrites_link_to_twitter():
    src = NitterSource({})
    items = src._parse_rss("openai", SAMPLE_RSS)
    for item in items:
        assert "twitter.com" in item.url
        assert "nitter" not in item.url


def test_parse_rss_respects_max_per_account():
    src = NitterSource({"max_per_account": 1})
    items = src._parse_rss("openai", SAMPLE_RSS)
    assert len(items) == 1


def test_parse_rss_empty_feed_returns_empty():
    src = NitterSource({})
    empty = '<?xml version="1.0"?><rss><channel><title>x</title></channel></rss>'
    assert src._parse_rss("x", empty) == []


def test_disabled_returns_empty():
    import asyncio

    src = NitterSource({"enabled": False})

    async def run():
        return await src.fetch()

    assert asyncio.run(run()) == []


def test_default_accounts_exclude_elonmusk():
    src = NitterSource({})
    assert "elonmusk" not in src.accounts
    assert "karpathy" in src.accounts
    assert "sama" in src.accounts
