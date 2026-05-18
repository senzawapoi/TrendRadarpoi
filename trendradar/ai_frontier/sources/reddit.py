"""Reddit 数据源

使用 Reddit 公开 .json 接口（无需 API Key），
抓取 r/MachineLearning / r/LocalLLaMA / r/singularity / r/OpenAI 热门帖子。
"""

from __future__ import annotations

from datetime import datetime, timezone

import aiohttp

from trendradar.ai_frontier._http import make_session, request_with_retry, run_with_concurrency
from trendradar.ai_frontier.sources.base import AIItem, AISource
from trendradar.utils.logging import log

USER_AGENT = "TrendRadar-AIFrontier/1.0 (by u/trendradar_bot)"


class RedditSource(AISource):
    """Reddit hot 帖源"""

    source_type = "reddit"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.subreddits: list[str] = config.get(
            "subreddits", ["MachineLearning", "LocalLLaMA", "singularity", "OpenAI"]
        )
        self.limit_per_sub: int = config.get("limit_per_sub", 25)
        self.min_score: int = config.get("min_score", 30)
        self.timeout: int = config.get("timeout", 15)

    async def _fetch_one(self, session: aiohttp.ClientSession, sub: str) -> list[AIItem]:
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit={self.limit_per_sub}"
        resp = await request_with_retry(
            session, "GET", url, label=f"Reddit r/{sub}",
            max_attempts=2, timeout=self.timeout,
        )
        if resp is None:
            return []
        if resp.status != 200:
            log.warning(f"Reddit r/{sub} 状态码异常", status=resp.status)
            await resp.release()
            return []
        try:
            data = await resp.json()
        except Exception as e:
            log.warning(f"Reddit r/{sub} JSON 解析失败", error=str(e))
            return []

        return self._parse_sub(sub, data)

    def _parse_sub(self, sub: str, data: dict) -> list[AIItem]:
        items: list[AIItem] = []
        children = (data or {}).get("data", {}).get("children", []) or []

        for child in children:
            d = (child or {}).get("data") or {}
            title = (d.get("title") or "").strip()
            score = int(d.get("score") or 0)
            if not title or score < self.min_score:
                continue

            # 外链优先，否则用 reddit 讨论链接
            permalink = d.get("permalink") or ""
            external_url = d.get("url_overridden_by_dest") or d.get("url") or ""
            is_self = bool(d.get("is_self"))

            if is_self or not external_url:
                url = f"https://www.reddit.com{permalink}"
            else:
                url = external_url

            # 时间
            created_utc = d.get("created_utc")
            pub_dt: datetime | None = None
            if created_utc:
                try:
                    pub_dt = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
                except (ValueError, OSError):
                    pub_dt = None

            summary = (d.get("selftext") or "").strip()
            if len(summary) > 400:
                summary = summary[:397] + "..."

            author = d.get("author") or ""
            flair = d.get("link_flair_text") or ""
            tags = [flair] if flair else []

            items.append(
                AIItem(
                    source="reddit",
                    source_name=f"r/{sub}",
                    title=title,
                    url=url,
                    published_at=pub_dt,
                    score=score,
                    author=author,
                    summary=summary,
                    tags=tags,
                )
            )
        return items

    async def fetch(self) -> list[AIItem]:
        if not self.enabled or not self.subreddits:
            return []

        log.info(f"抓取 Reddit ({len(self.subreddits)} subs)")
        async with make_session(
            total_timeout=self.timeout,
            user_agent=USER_AGENT,
            max_per_host=3,
        ) as session:
            coros = [self._fetch_one(session, sub) for sub in self.subreddits]
            results = await run_with_concurrency(coros, limit=4)

        merged: list[AIItem] = []
        for r in results:
            if isinstance(r, list):
                merged.extend(r)
        log.info(f"Reddit 共 {len(merged)} 条")
        return merged
