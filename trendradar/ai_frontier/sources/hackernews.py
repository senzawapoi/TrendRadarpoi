"""HackerNews 数据源

使用 Algolia HN Search API（无需 API Key）搜索 AI 相关热帖。
接口：https://hn.algolia.com/api/v1/search?query=...&tags=story&numericFilters=points>50
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import aiohttp

from trendradar.ai_frontier._http import make_session, request_with_retry, run_with_concurrency
from trendradar.ai_frontier.sources.base import AIItem, AISource
from trendradar.utils.logging import log

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"


class HackerNewsSource(AISource):
    """HackerNews (Algolia) 源"""

    source_type = "hackernews"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.keywords: list[str] = config.get(
            "keywords", ["AI", "LLM", "GPT", "Claude", "Gemini", "Anthropic", "OpenAI"]
        )
        self.min_score: int = config.get("min_score", 50)
        self.hits_per_keyword: int = config.get("hits_per_keyword", 20)
        self.timeout: int = config.get("timeout", 15)

    async def _fetch_keyword(
        self, session: aiohttp.ClientSession, keyword: str
    ) -> list[AIItem]:
        params = {
            "query": keyword,
            "tags": "story",
            "hitsPerPage": self.hits_per_keyword,
            "numericFilters": f"points>{self.min_score}",
        }
        resp = await request_with_retry(
            session, "GET", HN_SEARCH_URL, params=params,
            label=f"HN '{keyword}'", max_attempts=2, timeout=self.timeout,
        )
        if resp is None:
            return []
        if resp.status != 200:
            log.warning(f"HN 搜索 '{keyword}' 状态异常", status=resp.status)
            await resp.release()
            return []
        try:
            data = await resp.json()
        except Exception as e:
            log.warning(f"HN '{keyword}' JSON 解析失败", error=str(e))
            return []

        return self._parse_hits(keyword, data)

    def _parse_hits(self, keyword: str, data: dict) -> list[AIItem]:
        items: list[AIItem] = []
        hits = (data or {}).get("hits", []) or []

        for hit in hits:
            title = (hit.get("title") or hit.get("story_title") or "").strip()
            if not title:
                continue

            hn_url = hit.get("url") or ""
            object_id = hit.get("objectID") or ""
            discussion = f"https://news.ycombinator.com/item?id={object_id}" if object_id else ""

            url = hn_url or discussion
            if not url:
                continue

            points = int(hit.get("points") or 0)
            author = hit.get("author") or ""

            # 时间
            created_at = hit.get("created_at_i")
            pub_dt: datetime | None = None
            if created_at:
                try:
                    pub_dt = datetime.fromtimestamp(float(created_at), tz=timezone.utc)
                except (ValueError, OSError):
                    pub_dt = None

            items.append(
                AIItem(
                    source="hackernews",
                    source_name="Hacker News",
                    title=title,
                    url=url,
                    published_at=pub_dt,
                    score=points,
                    author=author,
                    tags=[keyword],
                )
            )
        return items

    async def fetch(self) -> list[AIItem]:
        if not self.enabled or not self.keywords:
            return []

        log.info(f"抓取 HackerNews ({len(self.keywords)} keywords)")
        async with make_session(
            total_timeout=self.timeout, max_per_host=4,
        ) as session:
            coros = [self._fetch_keyword(session, kw) for kw in self.keywords]
            results = await run_with_concurrency(coros, limit=5)

        seen: set[str] = set()
        merged: list[AIItem] = []
        for r in results:
            if not isinstance(r, list):
                continue
            for item in r:
                if item.url in seen:
                    continue
                seen.add(item.url)
                merged.append(item)

        log.info(f"HackerNews 共 {len(merged)} 条（去重后）")
        return merged
