"""AI 前沿聚合 fetcher

并发调用所有启用的数据源，统一异常隔离，合并去重结果。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from trendradar.ai_frontier.sources.arxiv import ArXivSource
from trendradar.ai_frontier.sources.base import AIItem, AISource
from trendradar.ai_frontier.sources.github_trending import GitHubTrendingSource
from trendradar.ai_frontier.sources.hackernews import HackerNewsSource
from trendradar.ai_frontier.sources.nitter import NitterSource
from trendradar.ai_frontier.sources.official_blog import OfficialBlogSource
from trendradar.ai_frontier.sources.reddit import RedditSource
from trendradar.ai_frontier.sources.youtube_podcast import YouTubePodcastSource
from trendradar.utils.logging import log

SOURCE_CLASSES: dict[str, type[AISource]] = {
    "arxiv": ArXivSource,
    "reddit": RedditSource,
    "hackernews": HackerNewsSource,
    "github_trending": GitHubTrendingSource,
    "x_nitter": NitterSource,
    "youtube_podcast": YouTubePodcastSource,
    "official_blog": OfficialBlogSource,
}


def build_sources(config: dict) -> list[AISource]:
    """根据 config.ai_frontier.sources 构造启用的 source 实例"""
    sources_cfg = (config or {}).get("sources", {}) or {}
    built: list[AISource] = []
    for key, cls in SOURCE_CLASSES.items():
        sub_cfg = sources_cfg.get(key) or {}
        if sub_cfg.get("enabled", True):
            built.append(cls(sub_cfg))
    return built


def filter_by_freshness(items: list[AIItem], hours: int) -> list[AIItem]:
    """过滤发布时间超过 hours 小时的旧条目；无发布时间的条目保留"""
    if hours <= 0:
        return items
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    out: list[AIItem] = []
    for item in items:
        if item.published_at is None:
            out.append(item)
            continue
        pub = item.published_at
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if pub >= cutoff:
            out.append(item)
    return out


def dedupe_items(items: list[AIItem]) -> list[AIItem]:
    """按 (source, url) 去重，保留先出现的"""
    seen: set[tuple[str, str]] = set()
    out: list[AIItem] = []
    for item in items:
        key = item.unique_key()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


async def fetch_all(sources: list[AISource]) -> list[AIItem]:
    """并发抓取所有 source，单 source 失败不影响其他"""
    if not sources:
        return []

    log.info(f"AI 前沿并发抓取 {len(sources)} 个源...")
    tasks = [src.fetch() for src in sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    merged: list[AIItem] = []
    for src, r in zip(sources, results, strict=False):
        if isinstance(r, Exception):
            log.warning(f"源 {src.name} 抛出异常", error=str(r))
            continue
        if isinstance(r, list):
            merged.extend(r)
    log.info(f"合并原始条目 {len(merged)} 条")
    return merged


async def fetch_and_process(config: dict) -> list[AIItem]:
    """一站式：构造 sources → 并发 fetch → 去重 → 新鲜度过滤"""
    sources = build_sources(config)
    raw = await fetch_all(sources)
    deduped = dedupe_items(raw)
    freshness_hours = int(config.get("freshness_hours", 24) or 0)
    fresh = filter_by_freshness(deduped, freshness_hours)
    log.info(f"去重+过滤后 {len(fresh)} 条")
    return fresh
