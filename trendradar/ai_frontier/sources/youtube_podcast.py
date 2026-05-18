"""YouTube podcast 数据源

通过 YouTube 官方 RSS 抓取 follow-builders 默认播客节目。
支持 playlist URL 直接转换，也支持 handle/channel 页面解析 channelId 后转 RSS。
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import aiohttp
import feedparser

from trendradar.ai_frontier._http import make_session, request_with_retry, run_with_concurrency
from trendradar.ai_frontier.sources.base import AIItem, AISource
from trendradar.utils.logging import log

YOUTUBE_PLAYLIST_RSS = "https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}"
YOUTUBE_CHANNEL_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
CHANNEL_ID_RE = re.compile(r'"channelId"\s*:\s*"([^"]+)"')


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
        match = re.search(r"/channel/([^/?#]+)", url)
        return match.group(1) if match else ""

    def _rss_url_for_id(self, url: str) -> str:
        """若 URL 已含 playlist/channel id，则直接生成 RSS URL。"""
        playlist_id = self._playlist_id_from_url(url)
        if playlist_id:
            return YOUTUBE_PLAYLIST_RSS.format(playlist_id=playlist_id)

        channel_id = self._channel_id_from_url(url)
        if channel_id:
            return YOUTUBE_CHANNEL_RSS.format(channel_id=channel_id)

        return ""

    def _parse_channel_id(self, html: str) -> str:
        """从 YouTube 页面 HTML 中解析 channelId。"""
        match = CHANNEL_ID_RE.search(html or "")
        return match.group(1) if match else ""

    async def _resolve_rss_url(self, session: aiohttp.ClientSession, feed: dict) -> str:
        """把配置 URL 解析为 YouTube RSS URL。"""
        raw_url = (feed.get("rss_url") or feed.get("url") or "").strip()
        if not raw_url:
            return ""
        if "feeds/videos.xml" in raw_url:
            return raw_url

        rss_url = self._rss_url_for_id(raw_url)
        if rss_url:
            return rss_url

        resp = await request_with_retry(
            session,
            "GET",
            raw_url,
            label=f"YouTube podcast page [{feed.get('name', raw_url)}]",
            max_attempts=2,
            timeout=self.timeout,
        )
        if resp is None:
            return ""
        if resp.status != 200:
            await resp.release()
            return ""
        html_text = await resp.text()
        await resp.release()

        channel_id = self._parse_channel_id(html_text)
        if not channel_id:
            return ""
        return YOUTUBE_CHANNEL_RSS.format(channel_id=channel_id)

    async def _fetch_one(self, session: aiohttp.ClientSession, feed: dict) -> list[AIItem]:
        name = (feed.get("name") or "YouTube Podcast").strip()
        rss_url = await self._resolve_rss_url(session, feed)
        if not rss_url:
            log.warning("YouTube podcast 无法解析 RSS", feed_name=name)
            return []

        resp = await request_with_retry(
            session,
            "GET",
            rss_url,
            label=f"YouTube podcast RSS [{name}]",
            max_attempts=2,
            timeout=self.timeout,
        )
        if resp is None:
            return []
        if resp.status != 200:
            log.warning("YouTube podcast RSS 状态异常", feed_name=name, status=resp.status)
            await resp.release()
            return []
        text = await resp.text()
        await resp.release()
        return await asyncio.to_thread(self._parse_rss, name, text)

    def _parse_rss(self, name: str, text: str) -> list[AIItem]:
        """解析 YouTube RSS 为 AIItem。"""
        parsed = feedparser.parse(text)
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
        if not self.enabled or not self.feeds:
            return []

        log.info(f"抓取 YouTube Podcasts ({len(self.feeds)} feeds)")
        async with make_session(total_timeout=self.timeout, max_per_host=4) as session:
            coros = [self._fetch_one(session, feed) for feed in self.feeds]
            results = await run_with_concurrency(coros, limit=4)

        merged: list[AIItem] = []
        for result in results:
            if isinstance(result, list):
                merged.extend(result)
        log.info(f"YouTube Podcasts 共 {len(merged)} 条")
        return merged
