"""X / Nitter 数据源

通过 Nitter（Twitter 第三方镜像）RSS 抓取关键 AI 账号的推文。
Nitter 实例经常下线，配置多实例并自动回退。

优化：
- 启动时并发探测可用实例（避免逐个账号重试死实例）
- Semaphore 限流防反爬
- feedparser 移到线程池（不阻塞事件循环）
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

import aiohttp
import feedparser

from trendradar.ai_frontier._http import make_session, run_with_concurrency
from trendradar.ai_frontier.sources.base import AIItem, AISource
from trendradar.utils.logging import log

DEFAULT_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.cz",
]

# 预编译 nitter 域名替换正则（一次匹配所有实例）
_NITTER_HOST_RE: re.Pattern | None = None


def _build_nitter_re(instances: list[str]) -> re.Pattern:
    """构建一次性替换所有 nitter 实例域名的正则"""
    hosts = []
    for inst in instances:
        host = inst.replace("https://", "").replace("http://", "").rstrip("/")
        hosts.append(re.escape(host))
    if not hosts:
        hosts = ["nitter\\.net"]
    return re.compile("|".join(hosts))


class NitterSource(AISource):
    """X / Twitter via Nitter RSS"""

    source_type = "x"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.accounts: list[str] = config.get(
            "accounts",
            [
                "openai", "anthropicai", "googledeepmind", "sama", "karpathy",
                "ylecun", "demishassabis", "drjimfan", "_philschmid",
                "joshwoodward", "kevinweil", "petergyang", "thenanyu",
                "realmadhuguru", "AmandaAskell", "_catwu", "trq212",
                "GoogleLabs", "amasad", "rauchg", "alexalbert__",
                "levie", "ryolu_", "garrytan", "mattturck", "zarazhangrui",
                "nikunj", "steipete", "danshipper", "adityaag", "claudeai",
            ],
        )
        self.instances: list[str] = config.get("nitter_instances", DEFAULT_INSTANCES)
        self.max_per_account: int = config.get("max_per_account", 5)
        self.timeout: int = config.get("timeout", 8)
        self._nitter_re = _build_nitter_re(self.instances)
        self._working_instances: list[str] | None = None  # 预探测后缓存

    # ── 实例预探测 ──────────────────────────────────────
    async def _probe_instances(self, session: aiohttp.ClientSession) -> list[str]:
        """并发探测 nitter 实例可用性，只保留 200 响应的"""

        async def _probe_one(inst: str) -> str | None:
            try:
                url = f"{inst.rstrip('/')}/openai/rss"
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=6),
                ) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        if "<rss" in text[:500].lower() or "<feed" in text[:500].lower():
                            return inst
            except Exception:
                pass
            return None

        results = await asyncio.gather(
            *[_probe_one(i) for i in self.instances], return_exceptions=True
        )
        available = [r for r in results if isinstance(r, str)]
        log.info(f"Nitter 可用实例: {len(available)}/{len(self.instances)}")
        return available if available else self.instances[:1]

    # ── 单账号抓取 ──────────────────────────────────────
    async def _fetch_account(
        self, session: aiohttp.ClientSession, account: str, instances: list[str]
    ) -> list[AIItem]:
        """仅尝试已确认可用的实例"""
        for instance in instances:
            url = f"{instance.rstrip('/')}/{account}/rss"
            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()
                if not text or ("<rss" not in text[:500].lower() and "<feed" not in text[:500].lower()):
                    continue
                items = await asyncio.to_thread(self._parse_rss, account, text)
                if items:
                    return items
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue
        return []

    # ── RSS 解析（CPU 密集，在线程池运行）──────────────
    def _parse_rss(self, account: str, text: str) -> list[AIItem]:
        parsed = feedparser.parse(text)
        items: list[AIItem] = []
        valid_count = 0

        for entry in parsed.entries or []:
            title = (entry.get("title") or "").strip().replace("\n", " ")
            link = entry.get("link") or ""
            if not (title and link):
                continue

            # 用预编译正则一次性替换所有 nitter 域名
            if "nitter" in link:
                link = self._nitter_re.sub("twitter.com", link)

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
            valid_count += 1
            if valid_count >= self.max_per_account:
                break

        return items

    # ── 主入口 ──────────────────────────────────────────
    async def fetch(self) -> list[AIItem]:
        if not self.enabled or not self.accounts:
            return []

        log.info(f"抓取 X/Nitter ({len(self.accounts)} accounts)")
        session = make_session(
            total_timeout=self.timeout,
            max_connections=16,
            max_per_host=4,
        )
        async with session:
            # 1. 预探测可用实例（并发，~6s 内完成）
            working = await self._probe_instances(session)

            # 2. Semaphore 限流 + 并发抓取所有账号
            coros = [
                self._fetch_account(session, acc, working) for acc in self.accounts
            ]
            results = await run_with_concurrency(coros, limit=8)

        merged: list[AIItem] = []
        for r in results:
            if isinstance(r, list):
                merged.extend(r)
        log.info(f"X/Nitter 共 {len(merged)} 条")
        return merged
