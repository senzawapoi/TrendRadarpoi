"""OfficialBlogSource 测试（离线 HTML 解析）"""

from __future__ import annotations

from trendradar.ai_frontier.sources.official_blog import OfficialBlogSource

SAMPLE_HTML = """
<html>
  <body>
    <article>
      <a href="/engineering/building-claude">Building Claude</a>
      <time datetime="2026-04-17T10:00:00Z"></time>
      <p>Engineering notes.</p>
    </article>
    <article>
      <a href="https://www.anthropic.com/news/company">Company News</a>
    </article>
    <article>
      <a href="/engineering/building-claude">Duplicate</a>
    </article>
    <a href="/engineering">Engineering home</a>
    <a href="/">Home</a>
  </body>
</html>
"""


def test_parse_listing_extracts_matching_internal_articles():
    src = OfficialBlogSource({"max_items_per_site": 10})
    site = {
        "name": "Anthropic Engineering",
        "url": "https://www.anthropic.com/engineering",
        "include_patterns": ["anthropic.com/engineering"],
    }
    items = src._parse_listing(site, SAMPLE_HTML)
    assert len(items) == 1
    item = items[0]
    assert item.source == "blog"
    assert item.source_name == "Anthropic Engineering"
    assert item.title == "Building Claude"
    assert item.url == "https://www.anthropic.com/engineering/building-claude"
    assert item.published_at is not None
    assert item.summary == "Engineering notes."


def test_parse_listing_skips_listing_and_home_links():
    src = OfficialBlogSource({"max_items_per_site": 10})
    site = {
        "name": "Anthropic Engineering",
        "url": "https://www.anthropic.com/engineering",
        "include_patterns": ["anthropic.com/engineering"],
    }
    html = """
    <a href="/engineering">Engineering</a>
    <a href="/">Home</a>
    <a href="/engineering/new-infra?utm_source=x#top">New Infra</a>
    """
    items = src._parse_listing(site, html)
    assert len(items) == 1
    assert items[0].url == "https://www.anthropic.com/engineering/new-infra"


def test_parse_listing_respects_max_items():
    src = OfficialBlogSource({"max_items_per_site": 1})
    site = {
        "name": "Claude Blog",
        "url": "https://www.claude.com/blog",
        "include_patterns": ["claude.com/blog"],
    }
    html = """
    <a href="/blog/a">A</a>
    <a href="/blog/b">B</a>
    """
    items = src._parse_listing(site, html)
    assert len(items) == 1


def test_parse_listing_allows_missing_time():
    src = OfficialBlogSource({"max_items_per_site": 10})
    site = {
        "name": "Claude Blog",
        "url": "https://www.claude.com/blog",
        "include_patterns": ["claude.com/blog"],
    }
    items = src._parse_listing(site, '<a href="/blog/post">Post</a>')
    assert len(items) == 1
    assert items[0].published_at is None
