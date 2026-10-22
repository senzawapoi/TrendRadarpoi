"""Explicit idempotent backfill from legacy TrendRadar SQLite databases."""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytz

from trendradar.ai_frontier.storage import AIFrontierStorage
from trendradar.core.models import (
    ContentItem,
    content_from_ai_item,
    content_from_news_item,
    content_from_rss_item,
    normalize_datetime,
)
from trendradar.core.settings import RuntimeSettings, load_settings
from trendradar.intelligence.deduplicate import Deduplicator, event_time
from trendradar.intelligence.pipeline import process_stories_after_persist_best_effort
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.storage.local import LocalStorageBackend
from trendradar.utils.logging import log

SUPPORTED_SOURCES = frozenset({"news", "rss", "ai"})


@dataclass
class BackfillSummary:
    scanned: int = 0
    content_items_created: int = 0
    observations_created: int = 0
    stories_created: int = 0
    story_memberships_created: int = 0
    skipped_databases: list[str] = field(default_factory=list)
    dry_run: bool = False


@dataclass
class _BackfillBatch:
    """One chronological legacy-source batch awaiting unified persistence."""

    sort_time: datetime
    source_key: str
    items: list[ContentItem]


def _queue_or_persist_batch(
    items: list[ContentItem],
    *,
    source_key: str,
    pending: list[_BackfillBatch] | None,
    storage: IntelligenceStorage | None,
    summary: BackfillSummary,
) -> None:
    if not items:
        return
    ordered = sorted(items, key=lambda item: (event_time(item), item.id))
    if pending is None:
        _persist_batch(ordered, storage, summary)
        return
    pending.append(
        _BackfillBatch(
            sort_time=event_time(ordered[0]),
            source_key=source_key,
            items=ordered,
        )
    )


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date: {value}") from exc


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _timezone(name: str):
    try:
        return pytz.timezone(name)
    except pytz.UnknownTimeZoneError:
        return pytz.timezone("Asia/Shanghai")


def _collected_at(day: date, clock: str, timezone_name: str) -> datetime:
    try:
        parsed_time = time.fromisoformat((clock or "00:00").replace("-", ":"))
    except ValueError:
        parsed_time = time.min
    local_time = _timezone(timezone_name).localize(datetime.combine(day, parsed_time))
    return local_time.astimezone(timezone.utc)


def _validate_sqlite(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise sqlite3.DatabaseError(f"quick_check failed: {result[0] if result else 'empty'}")
    finally:
        connection.close()


def _persist_batch(
    items: list[ContentItem],
    storage: IntelligenceStorage | None,
    summary: BackfillSummary,
) -> None:
    summary.scanned += len(items)
    result = Deduplicator(storage).process(items)
    if storage is None:
        summary.content_items_created += len(result.canonical_items)
        summary.observations_created += len(result.observations)
        return
    content_count, observation_count = storage.write_batch(
        result.canonical_items,
        result.observations,
    )
    summary.content_items_created += content_count
    summary.observations_created += observation_count
    try:
        story_result = process_stories_after_persist_best_effort(
            result,
            storage,
            save_report=False,
        )
    except Exception as exc:
        log.error("Story backfill failed; canonical backfill continues", error=str(exc))
    else:
        summary.stories_created += story_result.stories_created
        summary.story_memberships_created += story_result.memberships_created


def _backfill_news_and_rss(
    settings: RuntimeSettings,
    start: date,
    end: date,
    include: set[str],
    storage: IntelligenceStorage | None,
    summary: BackfillSummary,
    *,
    pending: list[_BackfillBatch] | None = None,
) -> None:
    backend = LocalStorageBackend(
        data_dir=str(settings.database_path),
        enable_txt=False,
        enable_html=False,
        timezone=settings.timezone,
    )
    try:
        for day in _date_range(start, end):
            day_text = day.isoformat()
            if "news" in include:
                path = settings.database_path / "news" / f"{day_text}.db"
                if path.exists():
                    try:
                        _validate_sqlite(path)
                        data = backend.get_today_all_data(day_text)
                        items = []
                        if data is not None:
                            for source_items in data.items.values():
                                for item in source_items:
                                    timestamp = _collected_at(
                                        day,
                                        item.first_time or item.crawl_time,
                                        settings.timezone,
                                    )
                                    items.append(
                                        content_from_news_item(item, collected_at=timestamp)
                                    )
                        _queue_or_persist_batch(
                            items,
                            source_key=f"news:{day_text}",
                            pending=pending,
                            storage=storage,
                            summary=summary,
                        )
                    except (OSError, sqlite3.DatabaseError) as exc:
                        summary.skipped_databases.append(str(path))
                        log.warning("跳过损坏的历史热榜库", path=str(path), error=str(exc))
            if "rss" in include:
                path = settings.database_path / "rss" / f"{day_text}.db"
                if path.exists():
                    try:
                        _validate_sqlite(path)
                        data = backend.get_rss_data(day_text)
                        items = []
                        if data is not None:
                            for feed_items in data.items.values():
                                for item in feed_items:
                                    timestamp = _collected_at(
                                        day,
                                        item.first_time or item.crawl_time,
                                        settings.timezone,
                                    )
                                    items.append(content_from_rss_item(item, collected_at=timestamp))
                        _queue_or_persist_batch(
                            items,
                            source_key=f"rss:{day_text}",
                            pending=pending,
                            storage=storage,
                            summary=summary,
                        )
                    except (OSError, sqlite3.DatabaseError) as exc:
                        summary.skipped_databases.append(str(path))
                        log.warning("跳过损坏的历史 RSS 库", path=str(path), error=str(exc))
    finally:
        backend.cleanup()


def _backfill_ai(
    settings: RuntimeSettings,
    start: date,
    end: date,
    storage: IntelligenceStorage | None,
    summary: BackfillSummary,
    *,
    pending: list[_BackfillBatch] | None = None,
) -> None:
    path = settings.ai_frontier_database_path
    if not path.exists():
        return
    try:
        with sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT source, source_name, title, title_translated, url,
                       published_at, score, author, summary, tags, first_seen, last_seen
                FROM ai_items
                ORDER BY COALESCE(published_at, first_seen), id
                """
            ).fetchall()
    except (OSError, sqlite3.DatabaseError) as exc:
        summary.skipped_databases.append(str(path))
        log.warning("跳过损坏的 AI Frontier 历史库", path=str(path), error=str(exc))
        return

    items_by_date: dict[date, list[ContentItem]] = {}
    local_timezone = _timezone(settings.timezone)
    for row in rows:
        item = AIFrontierStorage._row_to_item(row)
        first_seen = normalize_datetime(row["first_seen"])
        event = normalize_datetime(item.published_at) or first_seen
        if event is None:
            continue
        event_date = event.astimezone(local_timezone).date()
        if not start <= event_date <= end:
            continue
        converted = content_from_ai_item(item, collected_at=first_seen or event)
        items_by_date.setdefault(event_date, []).append(converted)

    for event_date in sorted(items_by_date):
        _queue_or_persist_batch(
            items_by_date[event_date],
            source_key=f"ai:{event_date.isoformat()}",
            pending=pending,
            storage=storage,
            summary=summary,
        )


def run_backfill(
    *,
    start: date,
    end: date,
    include: set[str] | None = None,
    dry_run: bool = False,
    settings: RuntimeSettings | None = None,
) -> BackfillSummary:
    """Backfill selected legacy stores in chronological order."""
    if start > end:
        raise ValueError("start date must not be after end date")
    selected = set(include or SUPPORTED_SOURCES)
    unsupported = selected - SUPPORTED_SOURCES
    if unsupported:
        raise ValueError(f"unsupported sources: {', '.join(sorted(unsupported))}")
    runtime = settings or load_settings()
    summary = BackfillSummary(dry_run=dry_run)
    if not runtime.intelligence_enabled:
        log.info("统一情报回填已禁用，跳过数据库创建")
        return summary
    storage = (
        IntelligenceStorage(":memory:", story_config=runtime.intelligence_story_config)
        if dry_run
        else IntelligenceStorage(
            runtime.intelligence_database_path,
            story_config=runtime.intelligence_story_config,
            synchronous=runtime.intelligence_sqlite_synchronous,
            allow_create=not runtime.intelligence_require_existing,
            allow_migrate=not runtime.intelligence_require_existing,
        )
    )
    pending: list[_BackfillBatch] = []
    try:
        _backfill_news_and_rss(
            runtime,
            start,
            end,
            selected,
            storage,
            summary,
            pending=pending,
        )
        if "ai" in selected:
            _backfill_ai(runtime, start, end, storage, summary, pending=pending)
        for batch in sorted(
            pending,
            key=lambda value: (
                value.sort_time,
                value.source_key,
                tuple(item.id for item in value.items),
            ),
        ):
            _persist_batch(batch.items, storage, summary)
    finally:
        if storage is not None:
            storage.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill the unified intelligence database")
    parser.add_argument("--from", dest="start", required=True, type=_parse_date)
    parser.add_argument("--to", dest="end", required=True, type=_parse_date)
    parser.add_argument(
        "--include",
        default="news,rss,ai",
        help="Comma-separated sources: news,rss,ai",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    include = {value.strip() for value in args.include.split(",") if value.strip()}
    try:
        summary = run_backfill(
            start=args.start,
            end=args.end,
            include=include,
            dry_run=args.dry_run,
            settings=load_settings(args.config) if args.config else None,
        )
    except (OSError, ValueError, sqlite3.DatabaseError) as exc:
        log.error("历史数据回填失败", error=str(exc))
        return 1
    log.info(
        "历史数据回填完成",
        dry_run=summary.dry_run,
        scanned=summary.scanned,
        content_items_created=summary.content_items_created,
        observations_created=summary.observations_created,
        stories_created=summary.stories_created,
        story_memberships_created=summary.story_memberships_created,
        skipped_databases=len(summary.skipped_databases),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
