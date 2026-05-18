"""官方博客数据源

抓取 follow-builders 默认官方博客列表页，提取站内文章链接。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from trendradar.ai_frontier._http import make_session, request_with_retry, run_with_concurrency
from trendradar.ai_frontier.sources.base import AIItem, AISource
from trendradar.utils.logging import log


class OfficialBlogSource(AISource):
    """官方博客 HTML 列表源"""

    source_type = "blog"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.sites: list[dict] = config.get("sites", [])
        self.max_items_per_site: int = int(config.get("max_items_per_site", 10) or 10)
        self.timeout: int = int(config.get("timeout", 15) or 15)

    async def _fetch_site(self, session: aiohttp.ClientSession, site: dict) -> list[AIItem]:
        name = (site.get("name") or "Official Blog").strip()
        url = (site.get("url") or "").strip()
        if not url:
            return []

        resp = await request_with_retry(
            session,
            "GET",
            url,
            label=f"Official blog [{name}]",
            max_attempts=2,
            timeout=self.timeout,
        )
        if resp is None:
            return []
        if resp.status != 200:
            log.warning("官方博客状态异常", site_name=name, status=resp.status)
            await resp.release()
            return []
        html_text = await resp.text()
        await resp.release()

        return await asyncio.to_thread(self._parse_listing, site, html_text)

    def _parse_listing(self, site: dict, html_text: str) -> list[AIItem]:
        """从博客列表页提取文章链接。"""
        name = (site.get("name") or "Official Blog").strip()
        base_url = (site.get("url") or "").strip()
        include_patterns = site.get("include_patterns") or []
        base_host = urlparse(base_url).netloc
        base_parsed = urlparse(base_url)
        base_path = base_parsed.path.rstrip("/") or "/"
        listing_url = base_parsed._replace(query="", fragment="").geturl().rstrip("/")
        soup = BeautifulSoup(html_text, "html.parser")

        seen: set[str] = set()
        items: list[AIItem] = []
        for link in soup.find_all("a", href=True):
            href = (link.get("href") or "").strip()
            url = urljoin(base_url, href)
            parsed = urlparse(url)
            if parsed.netloc and parsed.netloc != base_host:
                continue
            clean_url = parsed._replace(query="", fragment="").geturl().rstrip("/")
            if clean_url == listing_url:
                continue
            if (parsed.path.rstrip("/") or "/") in {"/", base_path}:
                continue
            if clean_url in seen:
                continue
            if include_patterns and not any(pattern in clean_url for pattern in include_patterns):
                continue

            title = link.get_text(" ", strip=True)
            if not title:
                title = self._nearby_title(link)
            if not title:
                continue

            pub_dt = self._nearby_time(link)
            summary = self._nearby_summary(link)
            seen.add(clean_url)
            items.append(
                AIItem(
                    source="blog",
                    source_name=name,
                    title=title,
                    url=clean_url,
                    published_at=pub_dt,
                    author=name,
                    summary=summary,
                )
            )
            if len(items) >= self.max_items_per_site:
                break

        return items

    def _nearby_title(self, link) -> str:
        """从链接附近的标题元素兜底提取标题。"""
        container = link.find_parent(["article", "li", "div", "section"])
        if not container:
            return ""
        heading = container.find(["h1", "h2", "h3"])
        return heading.get_text(" ", strip=True) if heading else ""

    def _nearby_summary(self, link) -> str:
        """从链接附近提取短摘要。"""
        container = link.find_parent(["article", "li", "div", "section"])
        if not container:
            return ""
        paragraph = container.find("p")
        if not paragraph:
            return ""
        summary = paragraph.get_text(" ", strip=True)
        return summary[:397] + "..." if len(summary) > 400 else summary

    def _nearby_time(self, link) -> datetime | None:
        """从链接附近的 time 标签解析发布时间。"""
        container = link.find_parent(["article", "li", "div", "section"]) or link
        time_tag = container.find("time") if hasattr(container, "find") else None
        raw = ""
        if time_tag:
            raw = (time_tag.get("datetime") or time_tag.get_text(" ", strip=True) or "").strip()
        if not raw:
            return None
        return self._parse_datetime(raw)

    def _parse_datetime(self, raw: str) -> datetime | None:
        """解析常见 ISO 日期字符串。"""
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    async def fetch(self) -> list[AIItem]:
        if not self.enabled or not self.sites:
            return []

        log.info(f"抓取 Official Blogs ({len(self.sites)} sites)")
        async with make_session(total_timeout=self.timeout, max_per_host=4) as session:
            coros = [self._fetch_site(session, site) for site in self.sites]
            results = await run_with_concurrency(coros, limit=4)

        merged: list[AIItem] = []
        for result in results:
            if isinstance(result, list):
                merged.extend(result)
        log.info(f"Official Blogs 共 {len(merged)} 条")
        return merged
