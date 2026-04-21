"""ArXiv 数据源

使用 ArXiv API（Atom feed），无需 API Key。
查询格式：http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import aiohttp
import feedparser

from trendradar.ai_frontier._http import make_session, request_with_retry
from trendradar.ai_frontier.sources.base import AIItem, AISource
from trendradar.utils.logging import log

ARXIV_API_URL = "http://export.arxiv.org/api/query"


class ArXivSource(AISource):
    """ArXiv Atom feed 源"""

    source_type = "arxiv"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.categories: list[str] = config.get("categories", ["cs.AI", "cs.LG", "cs.CL"])
        self.max_results: int = config.get("max_results", 30)
        self.timeout: int = config.get("timeout", 20)

    def _build_query(self) -> str:
        """构造搜索 query：cat:cs.AI OR cat:cs.LG"""
        return "+OR+".join(f"cat:{c}" for c in self.categories)

    def _build_url(self) -> str:
        query = self._build_query()
        return (
            f"{ARXIV_API_URL}"
            f"?search_query={query}"
            f"&sortBy=submittedDate&sortOrder=descending"
            f"&max_results={self.max_results}"
        )

    async def fetch(self) -> list[AIItem]:
        if not self.enabled:
            return []

        url = self._build_url()
        log.info("抓取 ArXiv", url=url)

        async with make_session(total_timeout=self.timeout) as session:
            resp = await request_with_retry(
                session, "GET", url, label="ArXiv", max_attempts=2,
                timeout=self.timeout,
            )
            if resp is None:
                return []
            if resp.status != 200:
                log.warning("ArXiv 抓取失败", status=resp.status)
                await resp.release()
                return []
            text = await resp.text()
            await resp.release()

        # feedparser 是 CPU 密集操作，移到线程池避免阻塞事件循环
        return await asyncio.to_thread(self._parse_feed, text)

    def _parse_feed(self, text: str) -> list[AIItem]:
        parsed = feedparser.parse(text)
        items: list[AIItem] = []

        for entry in parsed.entries:
            title = (entry.get("title") or "").strip().replace("\n", " ").replace("  ", " ")
            url = entry.get("id") or entry.get("link") or ""
            if not (title and url):
                continue

            # 发布时间
            pub_dt: datetime | None = None
            if getattr(entry, "published_parsed", None):
                pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            # 作者
            authors = entry.get("authors", [])
            author = ", ".join(a.get("name", "") for a in authors if a.get("name"))

            # 摘要
            summary = (entry.get("summary") or "").strip().replace("\n", " ")
            if len(summary) > 500:
                summary = summary[:497] + "..."

            # 分类标签
            tags = []
            for t in entry.get("tags", []) or []:
                term = t.get("term") or ""
                if term:
                    tags.append(term)

            # 源名称：取第一个分类
            source_name = f"ArXiv {tags[0]}" if tags else "ArXiv"

            items.append(
                AIItem(
                    source="arxiv",
                    source_name=source_name,
                    title=title,
                    url=url,
                    published_at=pub_dt,
                    author=author,
                    summary=summary,
                    tags=tags,
                )
            )

        log.info(f"ArXiv 解析 {len(items)} 条")
        return items
