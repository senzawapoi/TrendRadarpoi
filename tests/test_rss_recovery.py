"""Source-specific recovery keeps the existing feed and adapter contracts."""

import asyncio
import json
import threading
import time
from unittest.mock import AsyncMock, Mock

import pytest
import requests

from trendradar.crawler.rss.fetcher import RSSFeedConfig, RSSFetcher
from trendradar.crawler.rss.yahoo import YahooFinanceParser
from trendradar.intelligence.runner import AdapterRunner
from trendradar.sources.base import HealthStatus
from trendradar.sources.rss import RSSAdapter


def test_feed_options_default_and_validate():
    feed = RSSFeedConfig("default", "Default", "https://example.test/feed")
    assert feed.transport == "aiohttp" and feed.format == "feed"
    fetcher = RSSFetcher.from_config({"feeds": [{
        "id": "custom", "name": "Custom", "url": "https://finance.yahoo.com/news/",
        "transport": "requests", "format": "yahoo_news",
    }]})
    assert fetcher.feeds[0].transport == "requests"
    assert fetcher.feeds[0].format == "yahoo_news"
    for extra in ({"transport": "typo"}, {"format": "typo"}):
        with pytest.raises(ValueError):
            RSSFeedConfig("bad", "Bad", "https://example.test", **extra)


def test_requests_feeds_are_bounded_off_loop_and_keep_order(monkeypatch):
    feeds = [RSSFeedConfig(str(i), str(i), "https://example.test", transport="requests")
             for i in range(6)]
    fetcher = RSSFetcher(feeds)
    active = peak = 0
    lock = threading.Lock()
    main_thread = threading.get_ident()

    def fetch(feed):
        nonlocal active, peak
        assert threading.get_ident() != main_thread
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return [], "failed" if feed.id == "2" else None

    monkeypatch.setattr(fetcher, "fetch_feed", fetch)
    result = asyncio.run(fetcher.async_fetch_all(max_workers=2))
    assert peak == 2
    assert result.failed_ids == ["2"]
    assert list(result.items) == ["0", "1", "3", "4", "5"]


def test_default_async_client_keeps_proxy_timeout_and_parser(monkeypatch):
    operation = AsyncMock(return_value=("default", [], None))
    monkeypatch.setattr("trendradar.crawler.rss.fetcher._fetch_single_async", operation)
    feed = RSSFeedConfig("default", "Default", "https://example.test")
    fetcher = RSSFetcher([feed], timeout=7, use_proxy=True, proxy_url="http://proxy.test")
    asyncio.run(fetcher.async_fetch_all())
    assert operation.call_args.kwargs["timeout"] == 7
    assert operation.call_args.kwargs["proxy_url"] == "http://proxy.test"
    assert operation.call_args.kwargs["parser"] is fetcher.parser


@pytest.mark.parametrize("failure", [requests.HTTPError(), ValueError()])
def test_requests_error_closes_session_and_is_unhealthy(monkeypatch, failure):
    session = Mock()
    session.get.return_value.raise_for_status.side_effect = failure
    monkeypatch.setattr(requests, "Session", lambda: session)
    adapter = RSSAdapter(RSSFeedConfig(
        "test", "Test", "https://example.test/feed", transport="requests",
    ), timeout=7, use_proxy=True, proxy_url="http://proxy.test")
    result = asyncio.run(AdapterRunner().run([adapter]))[0]
    assert result.health.status == HealthStatus.UNHEALTHY
    session.close.assert_called_once()
    session.get.assert_called_once_with("https://example.test/feed", timeout=7)
    assert session.proxies == {"http": "http://proxy.test", "https": "http://proxy.test"}


def card(title="Markets advance", href="/news/markets-advance-123.html", extra="", attrs="{}"):
    return (f'<section data-testid="storyitem"><a href="{href}" data-yga=\'{attrs}\'>'
            f'<h3>{title}</h3></a>{extra}</section>')


def test_yahoo_listing_uses_articles_only_and_preserves_provenance():
    attrs = json.dumps({"yContentPartner": "Yahoo Finance", "yDestinationContentUUID": "id-1"})
    html = card(attrs=attrs, extra='<time datetime="2026-10-23T04:00:00Z"></time><p>Summary</p>')
    html += card(href="/news/markets-advance-123.html?tracking=1")
    html += card(title="External", href="https://ads.example.test/news.html")
    html += '<div data-testid="ad-container"><h3>Advertisement</h3></div>'
    html += card(title="Second", href="/personal-finance/credit-cards/article/second.html",
                 attrs="[]", extra='<div class="publishing">2d ago</div>')
    result = YahooFinanceParser().parse(html, "https://finance.yahoo.com/news/")
    assert [item.title for item in result] == ["Markets advance", "Second"]
    assert result[0].url == "https://finance.yahoo.com/news/markets-advance-123.html"
    assert result[0].guid == "id-1" and result[0].author == "Yahoo Finance"
    assert result[0].summary == "Summary"
    assert result[0].published_at == "2026-10-23T04:00:00+00:00"
    assert result[1].published_at is None and result[1].guid == result[1].url


@pytest.mark.parametrize("html", ["<title>Access Denied</title>", "<html></html>",
                                    card(href="https://finance.yahoo.com@evil.test/a.html")])
def test_yahoo_unrecognized_page_is_a_failure_not_empty_success(html):
    with pytest.raises(ValueError, match="no recognized"):
        YahooFinanceParser().parse(html, "https://finance.yahoo.com/news/")


def test_yahoo_requests_parser_keeps_rss_item_contract(monkeypatch):
    session = Mock()
    session.get.return_value.text = card()
    monkeypatch.setattr(requests, "Session", lambda: session)
    feed = RSSFeedConfig("yahoo-finance", "Yahoo Finance", "https://finance.yahoo.com/news/",
                         transport="requests", format="yahoo_news", max_items=1)
    result = asyncio.run(RSSAdapter(feed).fetch())
    assert len(result) == 1
    assert result[0].feed_id == "yahoo-finance"
    assert result[0].title == "Markets advance"
    assert result[0].published_at == ""
    session.close.assert_called_once()
