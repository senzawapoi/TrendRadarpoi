"""X / Nitter 数据源

通过 Nitter（Twitter 第三方镜像）RSS 抓取关键 AI 账号的推文。
Nitter 实例经常下线，配置多实例并自动回退。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import aiohttp
import feedparser

from trendradar.ai_frontier.sources.base import AIItem, AISource
from trendradar.utils.logging import log

DEFAULT_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.cz",
]


class NitterSource(AISource):
    """X / Twitter via Nitter RSS"""

    source_type = "x"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.accounts: list[str] = config.get(
            "accounts",
            [
                "openai", "anthropicai", "googledeepmind", "sama", "elonmusk",
                "karpathy", "ylecun", "demishassabis", "jimfan0", "_philschmid",
            ],
        )
        self.instances: list[str] = config.get("nitter_instances", DEFAULT_INSTANCES)
        self.max_per_account: int = config.get("max_per_account", 5)
        self.timeout: int = config.get("timeout", 12)

    async def _fetch_account(
        self, session: aiohttp.ClientSession, account: str
    ) -> list[AIItem]:
        """尝试多个 nitter 实例，取首个成功的"""
        for instance in self.instances:
            url = f"{instance.rstrip('/')}/{account}/rss"
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    headers={"User-Agent": "TrendRadar-AIFrontier/1.0"},
                ) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()
                if not text or "<rss" not in text[:500].lower() and "<feed" not in text[:500].lower():
                    continue
                items = self._parse_rss(account, text)
                if items:
                    return items
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue
        log.warning(f"Nitter @{account} 所有实例均失败")
        return []

    def _parse_rss(self, account: str, text: str) -> list[AIItem]:
        parsed = feedparser.parse(text)
        items: list[AIItem] = []

        for entry in (parsed.entries or [])[: self.max_per_account]:
            title = (entry.get("title") or "").strip().replace("\n", " ")
            link = entry.get("link") or ""
            if not (title and link):
                continue

            # 清理 nitter 的链接（指回 twitter.com）
            if "nitter" in link:
                link = link.replace("nitter.net", "twitter.com")
                for inst in self.instances:
                    host = inst.replace("https://", "").replace("http://", "").rstrip("/")
                    link = link.replace(host, "twitter.com")

            # 发布时间
            pub_dt: datetime | None = None
            if getattr(entry, "published_parsed", None):
                pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            summary = (entry.get("summary") or "").strip()
            if len(summary) > 400:
                summary = summary[:397] + "..."

            items.append(
                AIItem(
                    source="x",
                    source_name=f"@{account}",
                    title=title,
                    url=link,
                    published_at=pub_dt,
                    author=account,
                    summary=summary,
                )
            )
        return items

    async def fetch(self) -> list[AIItem]:
        if not self.enabled or not self.accounts:
            return []

        log.info(f"抓取 X/Nitter ({len(self.accounts)} accounts)")
        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch_account(session, acc) for acc in self.accounts]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: list[AIItem] = []
        for r in results:
            if isinstance(r, list):
                merged.extend(r)
        log.info(f"X/Nitter 共 {len(merged)} 条")
        return merged
