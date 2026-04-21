"""AI 前沿模块的共享 HTTP 基础设施

职责：
- 提供统一的 aiohttp.ClientSession 工厂（复用连接池，降低握手开销）
- 提供带指数退避的重试工具（针对 429/5xx/超时）
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable

import aiohttp

from trendradar.utils.logging import log

# 合理的浏览器 UA，减少被反爬的概率
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 需要重试的 HTTP 状态码
_RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


def make_session(
    *,
    total_timeout: float = 15.0,
    connect_timeout: float = 5.0,
    max_connections: int = 32,
    max_per_host: int = 8,
    user_agent: str = DEFAULT_UA,
) -> aiohttp.ClientSession:
    """构造一个配置合理的共享 aiohttp 会话。

    - 连接池大小受限，避免同域名打爆
    - 同时设置 total 与 connect 超时
    - 默认带浏览器 UA
    """
    connector = aiohttp.TCPConnector(
        limit=max_connections,
        limit_per_host=max_per_host,
        ttl_dns_cache=300,
        enable_cleanup_closed=True,
    )
    timeout = aiohttp.ClientTimeout(total=total_timeout, connect=connect_timeout)
    return aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={"User-Agent": user_agent},
    )


async def request_with_retry(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    max_attempts: int = 3,
    base_delay: float = 0.6,
    max_delay: float = 4.0,
    timeout: float | None = None,
    label: str = "",
    **kwargs: Any,
) -> aiohttp.ClientResponse | None:
    """对指定请求做指数退避重试。

    返回：
        成功时返回已进入上下文的响应（调用方负责 `await resp.text()`）；
        所有重试失败则返回 None（调用方按 None 处理）。

    注意：我们不在此处 `async with`，让调用方灵活使用；若传入 timeout，将覆盖 session 默认。
    """
    timeout_obj = aiohttp.ClientTimeout(total=timeout) if timeout else None

    for attempt in range(1, max_attempts + 1):
        try:
            resp = await session.request(
                method, url, timeout=timeout_obj, **kwargs
            ) if timeout_obj else await session.request(method, url, **kwargs)

            if resp.status in _RETRY_STATUS and attempt < max_attempts:
                # 读到内存再关闭，便于 server 迅速释放
                await resp.release()
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                delay += random.uniform(0, 0.3)  # 加抖动
                log.info(
                    f"HTTP 重试 [{label or url}] status={resp.status} "
                    f"attempt={attempt}/{max_attempts} sleep={delay:.1f}s"
                )
                await asyncio.sleep(delay)
                continue
            return resp
        except asyncio.TimeoutError:
            if attempt < max_attempts:
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                log.info(
                    f"HTTP 超时重试 [{label or url}] "
                    f"attempt={attempt}/{max_attempts} sleep={delay:.1f}s"
                )
                await asyncio.sleep(delay)
                continue
            log.warning(f"HTTP 最终超时 [{label or url}]")
            return None
        except aiohttp.ClientError as e:
            if attempt < max_attempts:
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                log.info(
                    f"HTTP 异常重试 [{label or url}] err={e!s} "
                    f"attempt={attempt}/{max_attempts} sleep={delay:.1f}s"
                )
                await asyncio.sleep(delay)
                continue
            log.warning(f"HTTP 最终失败 [{label or url}]", error=str(e))
            return None
    return None


async def run_with_concurrency(
    coros: list[Awaitable[Any]],
    limit: int,
) -> list[Any]:
    """用 Semaphore 控制最大并发执行一批协程，返回顺序一致的结果（含异常）。"""
    if not coros:
        return []
    sem = asyncio.Semaphore(max(1, int(limit)))

    async def _wrapped(coro: Awaitable[Any]) -> Any:
        async with sem:
            return await coro

    return await asyncio.gather(*(_wrapped(c) for c in coros), return_exceptions=True)


__all__ = [
    "DEFAULT_UA",
    "make_session",
    "request_with_retry",
    "run_with_concurrency",
]
