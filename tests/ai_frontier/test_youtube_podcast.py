"""YouTubePodcastSource 测试（离线解析）"""

from __future__ import annotations

import asyncio

import pytest

from trendradar.ai_frontier.sources.youtube_podcast import YouTubePodcastSource

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>New AI Podcast Episode</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abc123"/>
    <published>2026-04-17T10:00:00+00:00</published>
    <summary>Episode summary</summary>
  </entry>
  <entry>
    <title>Second Episode</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=def456"/>
    <published>2026-04-18T10:00:00+00:00</published>
    <summary>Second summary</summary>
  </entry>
</feed>
"""


def test_playlist_url_converts_to_rss():
    src = YouTubePodcastSource({})
    url = "https://www.youtube.com/playlist?list=PLabc123"
    assert src._rss_url_for_id(url) == (
        "https://www.youtube.com/feeds/videos.xml?playlist_id=PLabc123"
    )


def test_channel_url_converts_to_rss():
    src = YouTubePodcastSource({})
    url = "https://www.youtube.com/channel/UCabc123"
    assert src._rss_url_for_id(url) == (
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCabc123"
    )


def test_parse_channel_id_from_handle_page():
    src = YouTubePodcastSource({})
    html = '<script>{"channelId":"UCxyz789","title":"Example"}</script>'
    assert src._parse_channel_id(html) == "UCxyz789"


def test_parse_rss_extracts_podcast_items():
    src = YouTubePodcastSource({"max_items_per_feed": 10})
    items = src._parse_rss("Latent Space", SAMPLE_RSS)
    assert len(items) == 2
    item = items[0]
    assert item.source == "podcast"
    assert item.source_name == "Latent Space"
    assert item.author == "Latent Space"
    assert item.title == "New AI Podcast Episode"
    assert item.url == "https://www.youtube.com/watch?v=abc123"
    assert item.published_at is not None


def test_parse_rss_respects_max_items():
    src = YouTubePodcastSource({"max_items_per_feed": 1})
    assert len(src._parse_rss("Latent Space", SAMPLE_RSS)) == 1


@pytest.mark.parametrize("metadata", [
    '<link href="https://www.youtube.com/channel/UCexpected123" rel="canonical">',
    '<meta content="https://www.youtube.com/channel/UCexpected123" property="og:url">',
    '<link type="application/rss+xml" href="https://www.youtube.com/feeds/videos.xml?channel_id=UCexpected123">',
    '<script>{"channelMetadataRenderer":{"externalId":"UCexpected123"}}</script>',
])
def test_page_metadata_wins_over_recommended_video_channels(metadata):
    html = '<script>{"channelId":"UCunrelated123"}</script>' + metadata
    assert YouTubePodcastSource({})._parse_channel_id(html) == "UCexpected123"


def test_does_not_select_arbitrary_browse_ids_or_foreign_canonical_url():
    html = ('<link rel="canonical" href="https://example.com/channel/UCwrong123">'
            '<script>{"recommendation":{"browseId":"UCwrong123","channelId":"UCwrong123"}}</script>')
    assert YouTubePodcastSource({})._parse_channel_id(html) == ""


@pytest.mark.parametrize("feed,expected", [
    ({"channel_id": "UCexpected123"}, "https://www.youtube.com/feeds/videos.xml?channel_id=UCexpected123"),
    ({"rss_url": "https://publisher.example/podcast.xml", "channel_id": "UCexpected123"},
     "https://publisher.example/podcast.xml"),
])
def test_explicit_identity_does_not_fetch_handle_page(feed, expected):
    assert asyncio.run(YouTubePodcastSource({})._resolve_rss_url(None, feed)) == expected


def test_successful_html_response_is_not_an_empty_podcast_feed():
    from trendradar.ai_frontier.sources.base import SourceFetchError

    with pytest.raises(SourceFetchError, match="invalid_feed"):
        YouTubePodcastSource({})._parse_rss("podcast", "<html>Consent</html>")
