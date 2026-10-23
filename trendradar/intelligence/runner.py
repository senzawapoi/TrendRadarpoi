"""Failure-isolated, bounded asynchronous source adapter execution."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from trendradar.intelligence.storage import IntelligenceStorage, SourceRunRecord
from trendradar.sources.base import (
    AdapterResult,
    HealthStatus,
    SourceAdapter,
    SourceHealth,
)
from trendradar.utils.logging import log


class AdapterRunner:
    """Run independent adapters with a hard concurrency ceiling."""

    def __init__(
        self,
        max_concurrency: int = 5,
        *,
        storage: IntelligenceStorage | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self.max_concurrency = max_concurrency
        self.storage = storage

    async def run(
        self,
        adapters: list[SourceAdapter[Any]],
        *,
        collected_at: datetime | None = None,
    ) -> list[AdapterResult[Any]]:
        timestamp = collected_at or datetime.now(tz=timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("collected_at must be timezone-aware")
        timestamp = timestamp.astimezone(timezone.utc)
        semaphore = asyncio.Semaphore(self.max_concurrency)
        tasks = [self._run_one(adapter, semaphore, timestamp) for adapter in adapters]
        return list(await asyncio.gather(*tasks))

    async def _run_one(
        self,
        adapter: SourceAdapter[Any],
        semaphore: asyncio.Semaphore,
        collected_at: datetime,
    ) -> AdapterResult[Any]:
        started_at = datetime.now(tz=timezone.utc)
        timer = monotonic()
        raw_items: list[Any] = []
        items = []
        normalized_raw_items: list[Any] = []
        normalize_errors: list[str] = []
        fetch_error = ""
        partial_errors: tuple[str, ...] = ()

        try:
            async with semaphore:
                fetched = await adapter.fetch()
                if not isinstance(fetched, list):
                    raise TypeError("adapter.fetch() must return a list")
                raw_items = fetched
                partial_errors = adapter.fetch_errors
        except Exception as exc:
            fetch_error = str(exc) or type(exc).__name__
        else:
            for index, raw in enumerate(raw_items):
                try:
                    items.append(adapter.normalize(raw, collected_at=collected_at))
                    normalized_raw_items.append(raw)
                except Exception as exc:
                    normalize_errors.append(f"item {index}: {exc}")

        finished_at = datetime.now(tz=timezone.utc)
        duration_ms = max(0, round((monotonic() - timer) * 1000))
        if fetch_error or ((raw_items or partial_errors) and not items):
            status = HealthStatus.UNHEALTHY
        elif not raw_items or normalize_errors or partial_errors:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.HEALTHY
        errors = [*partial_errors, *normalize_errors]
        error_summary = fetch_error or "; ".join(errors[:5])
        health = SourceHealth(
            adapter_id=adapter.adapter_id,
            status=status,
            checked_at=finished_at,
            fetched_count=len(raw_items),
            normalized_count=len(items),
            error_count=(1 if fetch_error else len(errors)),
            error_summary=error_summary,
        )
        adapter._set_health(health)
        result = AdapterResult(
            adapter_id=adapter.adapter_id,
            items=items,
            raw_items=raw_items,
            normalized_raw_items=normalized_raw_items,
            health=health,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            normalize_errors=normalize_errors,
            fetch_error=fetch_error,
        )
        self._record_run(result)
        return result

    def _record_run(self, result: AdapterResult[Any]) -> None:
        if self.storage is None or result.health is None:
            return
        try:
            self.storage.record_source_run(
                SourceRunRecord(
                    adapter_id=result.adapter_id,
                    status=result.health.status.value,
                    started_at=result.started_at or result.health.checked_at,
                    finished_at=result.finished_at or result.health.checked_at,
                    duration_ms=result.duration_ms,
                    fetched_count=result.health.fetched_count,
                    normalized_count=result.health.normalized_count,
                    error_count=result.health.error_count,
                    error_summary=result.health.error_summary,
                )
            )
        except Exception as exc:
            log.warning(
                "统一情报源运行记录写入失败",
                adapter_id=result.adapter_id,
                error=str(exc),
            )


async def run_newsnow_adapters(
    adapters: list[SourceAdapter[Any]],
    *,
    request_interval_ms: int = 100,
    collected_at: datetime | None = None,
    storage: IntelligenceStorage | None = None,
) -> list[AdapterResult[Any]]:
    """Run NewsNow adapters serially and preserve the configured inter-request delay."""
    results: list[AdapterResult[Any]] = []
    runner = AdapterRunner(max_concurrency=1, storage=storage)
    for index, adapter in enumerate(adapters):
        results.extend(await runner.run([adapter], collected_at=collected_at))
        if index < len(adapters) - 1 and request_interval_ms > 0:
            await asyncio.sleep(request_interval_ms / 1000)
    return results


__all__ = ["AdapterRunner", "run_newsnow_adapters"]
