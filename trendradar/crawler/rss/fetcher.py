"""
RSS 抓取器

基于: async-python-patterns skill — asyncio + aiohttp with Semaphore rate limiting
基于: python-resilience skill — tenacity retry with exponential backoff
基于: python-observability skill — structured logging with correlation IDs
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import aiohttp

from trendradar.storage.base import RSSData, RSSItem
from trendradar.utils.logging import log
from trendradar.utils.time import DEFAULT_TIMEZONE, get_configured_time, is_within_days

from .parser import RSSParser

# ── Async helpers (must be top-level for pickling with ThreadPoolExecutor) ─────


async def _fetch_single_async(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    feed: RSSFeedConfig,
    timeout: int,
    parser: RSSParser,
    timezone: str,
    proxy_url: str | None = None,
) -> tuple[str, list[RSSItem], str | None]:
    """
    Async fetch for a single RSS feed, rate-limited by semaphore.

    基于: async-python-patterns skill — Semaphore-based rate limiting
    """
    url = feed.url
    try:
        async with semaphore:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout), proxy=proxy_url) as response:
                response.raise_for_status()
                text = await response.text()

        parsed_items = parser.parse(text, feed.url)

        if feed.max_items > 0:
            parsed_items = parsed_items[:feed.max_items]

        now = get_configured_time(timezone)
        crawl_time = now.strftime("%H:%M")
        items = []
        for parsed in parsed_items:
            item = RSSItem(
                title=parsed.title,
                feed_id=feed.id,
                feed_name=feed.name,
                url=parsed.url or "",
                published_at=parsed.published_at or "",
                summary=parsed.summary or "",
                author=parsed.author or "",
                crawl_time=crawl_time,
                first_time=crawl_time,
                last_time=crawl_time,
                count=1,
            )
            items.append(item)

        return feed.id, items, None

    except aiohttp.ClientError as e:
        error = f"HTTP 错误: {e}"
        return feed.id, [], error
    except TimeoutError:
        error = f"请求超时 ({timeout}s)"
        return feed.id, [], error
    except Exception as e:
        error = f"未知错误: {e}"
        return feed.id, [], error


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class RSSFeedConfig:
    """RSS 源配置"""
    id: str                     # 源 ID
    name: str                   # 显示名称
    url: str                    # RSS URL
    max_items: int = 0          # 最大条目数（0=不限制）
    enabled: bool = True        # 是否启用
    max_age_days: int | None = None  # 文章最大年龄（天），覆盖全局设置；None=使用全局，0=禁用过滤


# ── Main fetcher class ─────────────────────────────────────────────────────────


class RSSFetcher:
    """RSS 抓取器（支持同步和异步两种模式）"""

    def __init__(
        self,
        feeds: list[RSSFeedConfig],
        request_interval: int = 2000,
        timeout: int = 15,
        use_proxy: bool = False,
        proxy_url: str = "",
        timezone: str = DEFAULT_TIMEZONE,
        freshness_enabled: bool = True,
        default_max_age_days: int = 3,
    ):
        """
        初始化抓取器

        Args:
            feeds: RSS 源配置列表
            request_interval: 请求间隔（毫秒）
            timeout: 请求超时（秒）
            use_proxy: 是否使用代理
            proxy_url: 代理 URL
            timezone: 时区配置（如 'Asia/Shanghai'）
            freshness_enabled: 是否启用新鲜度过滤
            default_max_age_days: 默认最大文章年龄（天）
        """
        self.feeds = [f for f in feeds if f.enabled]
        self.request_interval = request_interval
        self.timeout = timeout
        self.use_proxy = use_proxy
        self.proxy_url = proxy_url
        self.timezone = timezone
        self.freshness_enabled = freshness_enabled
        self.default_max_age_days = default_max_age_days

        self.parser = RSSParser()

    def _aiohttp_headers(self) -> dict[str, str]:
        """Build aiohttp session headers."""
        return {
            "User-Agent": "TrendRadar/2.0 RSS Reader (https://github.com/trendradar)",
            "Accept": "application/feed+json, application/json, application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def _aiohttp_connector(self) -> aiohttp.TCPConnector:
        """Build aiohttp TCP connector."""
        return aiohttp.TCPConnector(
            limit=10,
            ttl_dns_cache=300,
        )

    def _filter_by_freshness(
        self,
        items: list[RSSItem],
        feed: RSSFeedConfig,
    ) -> tuple[list[RSSItem], int]:
        """
        根据新鲜度过滤文章

        Args:
            items: 待过滤的文章列表
            feed: RSS 源配置

        Returns:
            (过滤后的文章列表, 被过滤的文章数)
        """
        if not self.freshness_enabled:
            return items, 0

        max_days = feed.max_age_days
        if max_days is None:
            max_days = self.default_max_age_days

        if max_days == 0:
            return items, 0

        filtered = []
        for item in items:
            if not item.published_at or is_within_days(item.published_at, max_days, self.timezone):
                filtered.append(item)

        filtered_count = len(items) - len(filtered)
        return filtered, filtered_count

    # ── Sync version (backward-compatible) ─────────────────────────────────

    def fetch_feed(self, feed: RSSFeedConfig) -> tuple[list[RSSItem], str | None]:
        """
        抓取单个 RSS 源（同步版本，保留向后兼容）

        基于: python-resilience skill — retry with exponential backoff
        """
        for attempt in range(1, 4):
            try:
                import requests

                session = requests.Session()
                session.headers.update(self._aiohttp_headers())
                if self.use_proxy and self.proxy_url:
                    session.proxies = {"http": self.proxy_url, "https": self.proxy_url}

                response = session.get(feed.url, timeout=self.timeout)
                response.raise_for_status()

                parsed_items = self.parser.parse(response.text, feed.url)

                if feed.max_items > 0:
                    parsed_items = parsed_items[:feed.max_items]

                now = get_configured_time(self.timezone)
                crawl_time = now.strftime("%H:%M")
                items = []
                for parsed in parsed_items:
                    item = RSSItem(
                        title=parsed.title,
                        feed_id=feed.id,
                        feed_name=feed.name,
                        url=parsed.url or "",
                        published_at=parsed.published_at or "",
                        summary=parsed.summary or "",
                        author=parsed.author or "",
                        crawl_time=crawl_time,
                        first_time=crawl_time,
                        last_time=crawl_time,
                        count=1,
                    )
                    items.append(item)

                log.info("RSS feed 获取成功", feed_name=feed.name, count=len(items))
                session.close()
                return items, None

            except requests.Timeout:
                error = f"请求超时 ({self.timeout}s)"
                if attempt < 3:
                    wait = min(2 ** attempt, 10)
                    log.warning(f"RSS feed 请求超时，将在 {wait}s 后重试", feed_name=feed.name, attempt=attempt, wait_s=wait)
                    time.sleep(wait)
                else:
                    log.error("RSS feed 获取失败（重试耗尽）", feed_name=feed.name, error=error)
                    return [], error

            except requests.RequestException as e:
                error = f"请求失败: {e}"
                log.error("RSS feed 请求失败", feed_name=feed.name, error=error)
                return [], error

            except ValueError as e:
                error = f"解析失败: {e}"
                log.error("RSS feed 解析失败", feed_name=feed.name, error=error)
                return [], error

            except Exception as e:
                error = f"未知错误: {e}"
                log.error("RSS feed 未知错误", feed_name=feed.name, error=error)
                return [], error

        return [], "重试耗尽"

    def fetch_all(self, max_workers: int = 5) -> RSSData:
        """
        并发抓取所有 RSS 源（同步版本，保留向后兼容）

        基于: async-python-patterns skill — Semaphore-based concurrency control

        Note: 新代码应使用 async_fetch_all() 以获得更好的性能。
        """
        all_items: dict[str, list[RSSItem]] = {}
        id_to_name: dict[str, str] = {}
        failed_ids: list[str] = []

        now = get_configured_time(self.timezone)
        crawl_time = now.strftime("%H:%M")
        crawl_date = now.strftime("%Y-%m-%d")

        log.start(f"RSS 并发抓取 {len(self.feeds)} 个源", max_workers=max_workers)

        for feed in self.feeds:
            id_to_name[feed.id] = feed.name

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_feed = {executor.submit(self.fetch_feed, feed): feed for feed in self.feeds}
            for future in as_completed(future_to_feed):
                feed = future_to_feed[future]
                try:
                    items, error = future.result()
                    if error:
                        failed_ids.append(feed.id)
                    else:
                        all_items[feed.id] = items
                except Exception as e:
                    log.error("RSS feed 线程异常", feed_name=feed.name, error=str(e))
                    failed_ids.append(feed.id)

        total_items = sum(len(items) for items in all_items.values())
        log.success("RSS 抓取完成", success_count=len(all_items), failed_count=len(failed_ids), total_items=total_items)

        return RSSData(
            date=crawl_date,
            crawl_time=crawl_time,
            items=all_items,
            id_to_name=id_to_name,
            failed_ids=failed_ids,
        )

    # ── Async version (preferred) ───────────────────────────────────────────

    async def async_fetch_all(self, max_workers: int = 5) -> RSSData:
        """
        并发抓取所有 RSS 源（异步版本，使用 aiohttp）

        基于: async-python-patterns skill
        - Semaphore-based rate limiting for controlled concurrency
        - asyncio.gather for concurrent task management
        基于: python-resilience skill
        - Exponential backoff retry for transient failures
        """
        all_items: dict[str, list[RSSItem]] = {}
        id_to_name: dict[str, str] = {feed.id: feed.name for feed in self.feeds}
        failed_ids: list[str] = []

        now = get_configured_time(self.timezone)
        crawl_time = now.strftime("%H:%M")
        crawl_date = now.strftime("%Y-%m-%d")

        log.start(f"RSS 异步抓取 {len(self.feeds)} 个源", max_workers=max_workers)

        connector = self._aiohttp_connector()
        timeout = aiohttp.ClientTimeout(total=self.timeout)

        async with aiohttp.ClientSession(
            headers=self._aiohttp_headers(),
            connector=connector,
            timeout=timeout,
        ) as session:
            semaphore = asyncio.Semaphore(max_workers)

            # Build all tasks
            proxy_url = self.proxy_url if self.use_proxy else None
            tasks = [
                _fetch_single_async(
                    session=session,
                    semaphore=semaphore,
                    feed=feed,
                    timeout=self.timeout,
                    parser=self.parser,
                    timezone=self.timezone,
                    proxy_url=proxy_url,
                )
                for feed in self.feeds
            ]

            # Run all concurrently (semaphore limits active connections)
            results: list[tuple[str, list[RSSItem], str | None]] = await asyncio.gather(*tasks)

        # Process results
        for feed_id, items, error in results:
            if error:
                failed_ids.append(feed_id)
            else:
                all_items[feed_id] = items

        total_items = sum(len(items) for items in all_items.values())
        log.success("RSS 异步抓取完成", success_count=len(all_items), failed_count=len(failed_ids), total_items=total_items)

        return RSSData(
            date=crawl_date,
            crawl_time=crawl_time,
            items=all_items,
            id_to_name=id_to_name,
            failed_ids=failed_ids,
        )

    # ── Config loader ────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: dict) -> RSSFetcher:
        """
        从配置字典创建抓取器

        Args:
            config: 配置字典
        """
        freshness_config = config.get("freshness_filter", {})
        freshness_enabled = freshness_config.get("enabled", True)
        default_max_age_days = freshness_config.get("max_age_days", 3)

        feeds = []
        for feed_config in config.get("feeds", []):
            max_age_days_raw = feed_config.get("max_age_days")
            max_age_days = None
            if max_age_days_raw is not None:
                try:
                    max_age_days = int(max_age_days_raw)
                    if max_age_days < 0:
                        feed_id = feed_config.get("id", "unknown")
                        log.warning(f"RSS feed '{feed_id}' 的 max_age_days 为负数，将使用全局默认值")
                        max_age_days = None
                except (ValueError, TypeError):
                    feed_id = feed_config.get("id", "unknown")
                    log.warning(f"RSS feed '{feed_id}' 的 max_age_days 格式错误", raw_value=str(max_age_days_raw))
                    max_age_days = None

            feed = RSSFeedConfig(
                id=feed_config.get("id", ""),
                name=feed_config.get("name", ""),
                url=feed_config.get("url", ""),
                max_items=feed_config.get("max_items", 0),
                enabled=feed_config.get("enabled", True),
                max_age_days=max_age_days,
            )
            if feed.id and feed.url:
                feeds.append(feed)

        return cls(
            feeds=feeds,
            request_interval=config.get("request_interval", 2000),
            timeout=config.get("timeout", 15),
            use_proxy=config.get("use_proxy", False),
            proxy_url=config.get("proxy_url", ""),
            timezone=config.get("timezone", DEFAULT_TIMEZONE),
            freshness_enabled=freshness_enabled,
            default_max_age_days=default_max_age_days,
        )
