"""TDD tests for AI Frontier acquisition hygiene: HN date search, freshness before DB write, domain isolation, blog feed fallback, and podcast feed toggle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from importlib import import_module
from types import SimpleNamespace

from trendradar.ai_frontier.fetcher import fetch_and_process
from trendradar.ai_frontier.sources.base import AIItem, AISource
from trendradar.ai_frontier.sources.hackernews import HackerNewsSource
from trendradar.ai_frontier.sources.official_blog import OfficialBlogSource
from trendradar.ai_frontier.sources.youtube_podcast import YouTubePodcastSource
from trendradar.core.models import ContentItem
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.intelligence.stories import StoryService


class _DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def _json_response(payload: dict, status: int = 200):
    async def _json():
        return payload

    return SimpleNamespace(status=status, json=_json, release=lambda: None)


def _text_response(text: str, url: str, status: int = 200):
    async def _text():
        return text

    return SimpleNamespace(status=status, text=_text, url=url, release=lambda: None)


def test_hackernews_queries_search_by_date_with_cutoff_filter(monkeypatch):
    hn_mod = import_module("trendradar.ai_frontier.sources.hackernews")
    monkeypatch.setattr(hn_mod, "make_session", lambda **kwargs: _DummySession())
    captured: list[tuple[str, dict]] = []
    fixed_now = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)

    async def fake_request(session, method, url, *, params=None, **kwargs):
        captured.append((url, dict(params or {})))
        return _json_response({"hits": []})

    monkeypatch.setattr(hn_mod, "request_with_retry", fake_request)
    src = HackerNewsSource(
        {"keywords": ["Claude"], "min_score": 50, "lookback_hours": 48},
        now_fn=lambda: fixed_now,
    )
    asyncio.run(src.fetch())

    assert len(captured) == 1
    url, params = captured[0]
    assert url == "https://hn.algolia.com/api/v1/search_by_date"
    expected_cutoff = int((fixed_now - timedelta(hours=48)).timestamp())
    assert "points>50" in params["numericFilters"]
    assert f"created_at_i>{expected_cutoff}" in params["numericFilters"]


def test_hackernews_disables_cutoff_when_lookback_hours_zero(monkeypatch):
    hn_mod = import_module("trendradar.ai_frontier.sources.hackernews")
    monkeypatch.setattr(hn_mod, "make_session", lambda **kwargs: _DummySession())
    captured: list[tuple[str, dict]] = []

    async def fake_request(session, method, url, *, params=None, **kwargs):
        captured.append((url, dict(params or {})))
        return _json_response({"hits": []})

    monkeypatch.setattr(hn_mod, "request_with_retry", fake_request)
    src = HackerNewsSource({"keywords": ["AI"], "min_score": 30, "lookback_hours": 0})
    asyncio.run(src.fetch())

    assert captured[0][0] == "https://hn.algolia.com/api/v1/search_by_date"
    assert captured[0][1]["numericFilters"] == "points>30"


def test_fetch_and_process_excludes_stale_items_from_db_and_isolates_ai_domain(
    tmp_path, monkeypatch
):
    now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    five_days_ago = now - timedelta(days=5)
    db_path = tmp_path / "intelligence.db"
    story_cfg = {"enabled": True, "report": {"enabled": False}}

    with IntelligenceStorage(db_path, story_config=story_cfg) as storage:
        existing_general = ContentItem.create(
            title="Shared Popular Repo",
            url="https://github.com/org/shared-repo",
            source="newsnow:github",
            domain="general",
            collected_at=five_days_ago,
        )
        bystander_general = ContentItem.create(
            title="Old General News",
            url="https://news.example/old",
            source="rss:bbc_news",
            domain="general",
            published_time=five_days_ago,
            collected_at=five_days_ago,
        )
        storage.write_batch([existing_general, bystander_general])

        class MixedAISource(AISource):
            source_type = "hackernews"

            async def fetch(self):
                return [
                    AIItem(
                        source="hackernews",
                        source_name="HN",
                        title="2015 Relic",
                        url="https://example.com/2015-relic",
                        published_at=datetime(2015, 1, 1, tzinfo=timezone.utc),
                    ),
                    AIItem(
                        source="hackernews",
                        source_name="HN",
                        title="Shared Popular Repo",
                        url="https://github.com/org/shared-repo",
                        published_at=now - timedelta(hours=2),
                    ),
                    AIItem(
                        source="hackernews",
                        source_name="HN",
                        title="Fresh AI Breakthrough",
                        url="https://arxiv.org/abs/2611.99999",
                        published_at=now - timedelta(hours=1),
                    ),
                ]

        from trendradar.sources.ai_frontier import AIFrontierAdapter

        monkeypatch.setattr(
            "trendradar.ai_frontier.fetcher.build_ai_adapters",
            lambda cfg: [AIFrontierAdapter("hackernews", MixedAISource({}))],
        )

        processed_domains: list[set[str]] = []
        orig_process = StoryService.process

        def spy_process(self, items, **kwargs):
            processed_domains.append({item.domain for item in items})
            return orig_process(self, items, **kwargs)

        monkeypatch.setattr(StoryService, "process", spy_process)

        fresh = asyncio.run(
            fetch_and_process(
                {"freshness_hours": 24, "sources": {"hackernews": {"enabled": True}}},
                use_adapters=True,
                intelligence_storage=storage,
                now=now,
            )
        )

        assert len(fresh) == 2
        assert storage.find_by_url("https://example.com/2015-relic") is None
        assert storage.find_by_url("https://arxiv.org/abs/2611.99999") is not None
        assert processed_domains == [{"ai"}]


def test_official_blog_supports_rss_or_atom_feed_fallback(monkeypatch):
    blog_mod = import_module("trendradar.ai_frontier.sources.official_blog")
    monkeypatch.setattr(blog_mod, "make_session", lambda **kwargs: _DummySession())

    atom_xml = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Claude Agent Architecture</title>
        <link href="https://www.anthropic.com/engineering/claude-agents"/>
        <published>2026-11-24T15:00:00Z</published>
        <summary>Deep dive into tool execution.</summary>
      </entry>
      <entry>
        <title>General Press Release</title>
        <link href="https://www.anthropic.com/news/press"/>
        <published>2026-11-24T12:00:00Z</published>
      </entry>
    </feed>
    """

    async def fake_request(session, method, url, **kwargs):
        return _text_response(atom_xml, url)

    monkeypatch.setattr(blog_mod, "request_with_retry", fake_request)
    src = OfficialBlogSource(
        {
            "sites": [
                {
                    "name": "Anthropic Engineering",
                    "url": "https://www.anthropic.com/engineering",
                    "feed_url": "https://www.anthropic.com/rss.xml",
                    "include_patterns": ["anthropic.com/engineering"],
                }
            ]
        }
    )
    items = asyncio.run(src.fetch())
    assert len(items) == 1
    assert items[0].title == "Claude Agent Architecture"
    assert items[0].url == "https://www.anthropic.com/engineering/claude-agents"
    assert items[0].published_at == datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc)


def test_youtube_podcast_skips_disabled_feed_entries_without_error(monkeypatch):
    yt_mod = import_module("trendradar.ai_frontier.sources.youtube_podcast")
    monkeypatch.setattr(yt_mod, "make_session", lambda **kwargs: _DummySession())
    called_urls: list[str] = []

    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Active Podcast</title>
        <link rel="alternate" href="https://www.youtube.com/watch?v=ok123"/>
        <published>2026-11-24T10:00:00+00:00</published>
      </entry>
    </feed>
    """

    async def fake_request(session, method, url, **kwargs):
        called_urls.append(url)
        return _text_response(rss_xml, url)

    monkeypatch.setattr(yt_mod, "request_with_retry", fake_request)
    src = YouTubePodcastSource(
        {
            "feeds": [
                {
                    "name": "Dead Feed",
                    "url": "https://www.youtube.com/@DataDrivenNYC",
                    "enabled": False,
                },
                {
                    "name": "Live Feed",
                    "channel_id": "UCactive123456",
                    "enabled": True,
                },
            ]
        }
    )
    items = asyncio.run(src.fetch())
    assert len(items) == 1
    assert src.fetch_errors == ()
    assert all("DataDrivenNYC" not in u for u in called_urls)
