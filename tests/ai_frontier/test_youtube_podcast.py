"""YouTubePodcastSource 测试（离线解析）"""

from __future__ import annotations

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
