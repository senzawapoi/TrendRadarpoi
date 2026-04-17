"""GitHub Trending 数据源

GitHub 没有官方 Trending API，通过解析 https://github.com/trending/{lang}?since=daily 页面实现。
使用 BeautifulSoup 提取仓库信息（名称、描述、stars、语言）。
"""

from __future__ import annotations

import asyncio
import re

import aiohttp
from bs4 import BeautifulSoup

from trendradar.ai_frontier.sources.base import AIItem, AISource
from trendradar.utils.logging import log

TRENDING_URL = "https://github.com/trending"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class GitHubTrendingSource(AISource):
    """GitHub Trending 源"""

    source_type = "github"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        # languages: python 或 unknown（unknown=All languages）
        self.languages: list[str] = config.get("languages", ["python", "unknown"])
        self.since: str = config.get("since", "daily")  # daily/weekly/monthly
        self.min_stars: int = config.get("min_stars", 100)
        self.timeout: int = config.get("timeout", 20)
        # AI 相关关键词（用于筛选 All languages 榜单）
        self.ai_keywords: list[str] = config.get(
            "ai_keywords",
            ["ai", "llm", "gpt", "claude", "gemini", "anthropic", "openai",
             "agent", "rag", "transformer", "diffusion", "ml ", "neural",
             "pytorch", "tensorflow", "huggingface", "langchain"],
        )

    def _build_url(self, language: str) -> str:
        if language == "unknown":
            return f"{TRENDING_URL}?since={self.since}"
        return f"{TRENDING_URL}/{language}?since={self.since}"

    async def _fetch_language(
        self, session: aiohttp.ClientSession, language: str
    ) -> list[AIItem]:
        url = self._build_url(language)
        try:
            async with session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                if resp.status != 200:
                    log.warning(f"GitHub Trending [{language}] 状态异常", status=resp.status)
                    return []
                html = await resp.text()
        except asyncio.TimeoutError:
            log.warning(f"GitHub Trending [{language}] 超时")
            return []
        except Exception as e:
            log.warning(f"GitHub Trending [{language}] 异常", error=str(e))
            return []

        return self._parse_html(html, language)

    def _parse_stars(self, text: str) -> int:
        """从 '1,234 stars today' 或 '1.2k stars today' 中提取数字"""
        if not text:
            return 0
        s = text.strip().replace(",", "")
        m = re.match(r"([\d.]+)([kKmM]?)", s)
        if not m:
            return 0
        num = float(m.group(1))
        suffix = m.group(2).lower()
        if suffix == "k":
            num *= 1000
        elif suffix == "m":
            num *= 1_000_000
        return int(num)

    def _is_ai_related(self, title: str, summary: str) -> bool:
        text = f"{title} {summary}".lower()
        return any(kw.lower() in text for kw in self.ai_keywords)

    def _parse_html(self, html: str, language: str) -> list[AIItem]:
        items: list[AIItem] = []
        soup = BeautifulSoup(html, "html.parser")

        # 兼容 GitHub 不同时期的 selector
        articles = soup.select("article.Box-row") or soup.select("article")

        for article in articles:
            # 仓库链接与名称
            h2 = article.find(["h1", "h2"])
            if not h2:
                continue
            a_tag = h2.find("a")
            if not a_tag or not a_tag.get("href"):
                continue
            href = a_tag.get("href", "").strip()
            if not href.startswith("/"):
                continue
            repo_path = href.lstrip("/")
            if "/" not in repo_path:
                continue
            url = f"https://github.com{href}"
            title = repo_path  # owner/repo

            # 描述
            p = article.find("p")
            summary = (p.get_text(" ", strip=True) if p else "").strip()

            # Stars today（本期 trending 数）
            star_span = article.find(
                "span", class_=re.compile(r"d-inline-block float-sm-right")
            )
            stars_today = self._parse_stars(star_span.get_text(strip=True)) if star_span else 0

            # 主语言
            lang_span = article.find("span", itemprop="programmingLanguage")
            lang = lang_span.get_text(strip=True) if lang_span else ""

            # All languages 榜单需要关键词筛选
            if language == "unknown":
                if not self._is_ai_related(title, summary):
                    continue

            if stars_today > 0 and stars_today < self.min_stars:
                # 注意：trending 榜单 stars 字段是当期新增，不是总 stars
                # 这里依然保留阈值逻辑（供未来灵活调整）
                pass

            tags = [lang] if lang else []

            items.append(
                AIItem(
                    source="github",
                    source_name="GitHub Trending",
                    title=title,
                    url=url,
                    score=stars_today,
                    summary=summary,
                    tags=tags,
                )
            )
        return items

    async def fetch(self) -> list[AIItem]:
        if not self.enabled or not self.languages:
            return []

        log.info(f"抓取 GitHub Trending ({len(self.languages)} langs)")
        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch_language(session, lang) for lang in self.languages]
            results = await asyncio.gather(*tasks, return_exceptions=True)

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

        log.info(f"GitHub Trending 共 {len(merged)} 条（去重后）")
        return merged
