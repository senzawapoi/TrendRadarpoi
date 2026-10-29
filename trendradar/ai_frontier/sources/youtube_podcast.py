"""YouTube podcast 数据源

通过 YouTube 官方 RSS 抓取 follow-builders 默认播客节目。
支持 playlist URL 直接转换，也支持 handle/channel 页面解析 channelId 后转 RSS。
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import aiohttp
import feedparser

from trendradar.ai_frontier._http import make_session, request_with_retry
from trendradar.ai_frontier.sources.base import AIItem, AISource, SourceFetchError
from trendradar.utils.logging import log

YOUTUBE_PLAYLIST_RSS = "https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}"
YOUTUBE_CHANNEL_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
CHANNEL_ID_RE = re.compile(r"UC[A-Za-z0-9_-]{1,62}\Z")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}


class _ChannelMetadata(HTMLParser):
    """Only retain page-level metadata, never suggested-video browse IDs."""

    def __init__(self) -> None:
        super().__init__()
        self.canonical: list[str] = []
        self.alternate: list[str] = []
        self.open_graph: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "link":
            relations = (values.get("rel") or "").lower().split()
            if "canonical" in relations:
                self.canonical.append(values.get("href") or "")
            elif values.get("type") == "application/rss+xml":
                self.alternate.append(values.get("href") or "")
        elif tag == "meta" and values.get("property") == "og:url":
            self.open_graph.append(values.get("content") or "")


class YouTubePodcastSource(AISource):
    """YouTube podcast RSS 源"""

    source_type = "podcast"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.feeds: list[dict] = config.get("feeds", [])
        self.max_items_per_feed: int = int(config.get("max_items_per_feed", 5) or 5)
        self.timeout: int = int(config.get("timeout", 15) or 15)

    def _playlist_id_from_url(self, url: str) -> str:
        """从 YouTube playlist URL 提取 list 参数。"""
        parsed = urlparse(url)
        return parse_qs(parsed.query).get("list", [""])[0]

    def _channel_id_from_url(self, url: str) -> str:
        """从 /channel/<id> URL 提取 channel id。"""
        parsed = urlparse(url)
        if parsed.hostname not in YOUTUBE_HOSTS:
            return ""
        match = re.fullmatch(r"/channel/(UC[A-Za-z0-9_-]+)/?", parsed.path)
        candidate = match.group(1) if match else ""
        return candidate if CHANNEL_ID_RE.fullmatch(candidate) else ""

    def _rss_url_for_id(self, url: str) -> str:
        """若 URL 已含 playlist/channel id，则直接生成 RSS URL。"""
        if urlparse(url).hostname not in YOUTUBE_HOSTS:
            return ""
        playlist_id = self._playlist_id_from_url(url)
        if playlist_id:
            return YOUTUBE_PLAYLIST_RSS.format(playlist_id=playlist_id)

        channel_id = self._channel_id_from_url(url)
        if channel_id:
            return YOUTUBE_CHANNEL_RSS.format(channel_id=channel_id)

        return ""

    def _parse_channel_id(self, html: str) -> str:
        """Prefer canonical page identity to unrelated recommended channels."""
        parser = _ChannelMetadata()
        head_end = html.lower().find("</head>")
        parser.feed(html[:head_end + 7] if head_end >= 0 else html)
        for url in [*parser.canonical, *parser.open_graph]:
            channel_id = self._channel_id_from_url(url)
            if channel_id:
                return channel_id
        for url in parser.alternate:
            parsed = urlparse(url)
            channel_id = parse_qs(parsed.query).get("channel_id", [""])[0]
            if (parsed.hostname in YOUTUBE_HOSTS and parsed.path == "/feeds/videos.xml"
                    and CHANNEL_ID_RE.fullmatch(channel_id)):
                return channel_id
        match = re.search(
            r'"channelMetadataRenderer"\s*:\s*\{[^{}]{0,20000}?'
            r'"externalId"\s*:\s*"(UC[A-Za-z0-9_-]+)"', html,
        )
        if match and CHANNEL_ID_RE.fullmatch(match.group(1)):
            return match.group(1)
        # Retain the old standalone JSON contract without scanning nested video data.
        for match in re.finditer(r"<script[^>]*>\s*(\{[^<>]{1,2048}\})\s*</script>", html):
            try:
                candidate = json.loads(match.group(1)).get("channelId", "")
            except (ValueError, AttributeError):
                continue
            if isinstance(candidate, str) and CHANNEL_ID_RE.fullmatch(candidate):
                return candidate
        return ""

    async def _resolve_rss_url(self, session: aiohttp.ClientSession, feed: dict) -> str:
        """把配置 URL 解析为 YouTube RSS URL。"""
        name = (feed.get("name") or "YouTube Podcast").strip()
        explicit_rss = (feed.get("rss_url") or "").strip()
        if explicit_rss:
            if urlparse(explicit_rss).scheme not in {"http", "https"}:
                raise SourceFetchError("invalid_rss_url")
            return explicit_rss
        channel_id = (feed.get("channel_id") or "").strip()
        if channel_id:
            if not CHANNEL_ID_RE.fullmatch(channel_id):
                raise SourceFetchError("invalid_channel_id")
            return YOUTUBE_CHANNEL_RSS.format(channel_id=channel_id)
        raw_url = (feed.get("url") or "").strip()
        if not raw_url:
            raise SourceFetchError("missing_url")
        parsed_url = urlparse(raw_url)
        if parsed_url.hostname not in YOUTUBE_HOSTS:
            raise SourceFetchError("invalid_youtube_url")
        if parsed_url.path == "/feeds/videos.xml":
            return raw_url

        rss_url = self._rss_url_for_id(raw_url)
        if rss_url:
            return rss_url

        resp = await request_with_retry(
            session,
            "GET",
            raw_url,
            label=f"YouTube podcast page [{name}]",
            max_attempts=2,
            timeout=self.timeout,
        )
        if resp is None:
            raise SourceFetchError("page_request_failed")
        # YouTube 未登录常 302 到 consent.youtube.com（最终 status 仍可能 200）
        # 检测最终 URL 是否还在 youtube.com 主域，consent 页解析不到 channelId
        final_host = urlparse(str(resp.url)).hostname or ""
        if resp.status != 200:
            log.warning(
                "YouTube podcast 页面状态异常",
                feed_name=name,
                url=raw_url,
                status=resp.status,
            )
            resp.release()
            raise SourceFetchError(f"page_http_{resp.status}")
        try:
            if final_host not in YOUTUBE_HOSTS:
                raise SourceFetchError("unexpected_page_host")
            html_text = await resp.text()
        finally:
            resp.release()

        channel_id = self._parse_channel_id(html_text)
        if not channel_id:
            log.warning(
                "YouTube podcast 解析 channelId 失败（可能是 consent 页），"
                "建议在配置中直接填 channel_id 或 playlist URL",
                feed_name=name,
                url=raw_url,
                final_host=final_host,
            )
            raise SourceFetchError("channel_metadata_missing")
        return YOUTUBE_CHANNEL_RSS.format(channel_id=channel_id)

    async def _fetch_one(self, session: aiohttp.ClientSession, feed: dict) -> list[AIItem]:
        name = (feed.get("name") or "YouTube Podcast").strip()
        rss_url = await self._resolve_rss_url(session, feed)
        if not rss_url:
            log.warning("YouTube podcast 无法解析 RSS", feed_name=name)
            raise SourceFetchError("rss_resolution_failed")

        resp = await request_with_retry(
            session,
            "GET",
            rss_url,
            label=f"YouTube podcast RSS [{name}]",
            max_attempts=2,
            timeout=self.timeout,
        )
        if resp is None:
            raise SourceFetchError("rss_request_failed")
        if resp.status != 200:
            log.warning("YouTube podcast RSS 状态异常", feed_name=name, status=resp.status)
            resp.release()
            raise SourceFetchError(f"rss_http_{resp.status}")
        try:
            text = await resp.text()
        finally:
            resp.release()
        return await asyncio.to_thread(self._parse_rss, name, text)

    def _parse_rss(self, name: str, text: str) -> list[AIItem]:
        """解析 YouTube RSS 为 AIItem。"""
        parsed = feedparser.parse(text)
        if not parsed.version or (parsed.bozo and not parsed.entries):
            raise SourceFetchError("invalid_feed")
        items: list[AIItem] = []

        for entry in parsed.entries or []:
            title = (entry.get("title") or "").strip()
            link = entry.get("link") or ""
            if not title or not link:
                continue

            pub_dt: datetime | None = None
            if getattr(entry, "published_parsed", None):
                pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            elif getattr(entry, "updated_parsed", None):
                pub_dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

            summary = (entry.get("summary") or "").strip()
            if len(summary) > 400:
                summary = summary[:397] + "..."

            items.append(
                AIItem(
                    source="podcast",
                    source_name=name,
                    title=title,
                    url=link,
                    published_at=pub_dt,
                    author=name,
                    summary=summary,
                )
            )
            if len(items) >= self.max_items_per_feed:
                break

        return items

    async def fetch(self) -> list[AIItem]:
        self._fetch_errors.clear()
        if not self.enabled or not self.feeds:
            return []

        log.info(f"抓取 YouTube Podcasts ({len(self.feeds)} feeds)")
        async with make_session(total_timeout=self.timeout, max_per_host=4) as session:
            coros = [self._fetch_one(session, feed) for feed in self.feeds]
            results = await self._gather(
                coros, [feed.get("name", "podcast") for feed in self.feeds], limit=4,
            )

        merged: list[AIItem] = []
        for result in results:
            if isinstance(result, list):
                merged.extend(result)
        log.info(f"YouTube Podcasts 共 {len(merged)} 条")
        return merged
