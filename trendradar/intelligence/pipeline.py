"""Application helpers for best-effort unified intelligence persistence."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trendradar.core.models import ContentItem
from trendradar.intelligence.deduplicate import DeduplicationResult, Deduplicator
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.intelligence.stories import StoryBatchResult, StoryService
from trendradar.intelligence.translation import CANONICAL_ID_ATTRIBUTE, CanonicalTitleTranslator
from trendradar.sources.base import AdapterResult
from trendradar.utils.logging import log


def _positive_int(value: Any, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _story_evidence(storage: IntelligenceStorage, stories) -> dict:
    from trendradar.intelligence.ranking import RankingEvidence

    evidence = {}
    for story in stories:
        resolver = (
            storage.get_security_item_view if story.domain == "security" else storage.get_item
        )
        items = tuple(
            item
            for item_id in story.member_ids
            if (item := resolver(item_id)) is not None
        )
        observation_sources: list[str] = []
        observation_count = 0
        first_observed = None
        last_observed = None
        for item_id in story.member_ids:
            rows = storage.list_observations(item_id)
            for row in rows:
                observation_sources.append(str(row["source"]))
                try:
                    metadata = json.loads(row["metadata_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    metadata = {}
                try:
                    observation_count += max(
                        1,
                        int(metadata.get("_observation_count", 1))
                        if isinstance(metadata, Mapping)
                        else 1,
                    )
                except (TypeError, ValueError):
                    observation_count += 1
                first = datetime.fromisoformat(str(row["first_observed_at"])).astimezone(
                    timezone.utc
                )
                last = datetime.fromisoformat(str(row["last_observed_at"])).astimezone(
                    timezone.utc
                )
                first_observed = first if first_observed is None else min(first_observed, first)
                last_observed = last if last_observed is None else max(last_observed, last)
        evidence[story.id] = RankingEvidence(
            items=items,
            observation_sources=tuple(observation_sources),
            observation_count=observation_count,
            first_observed_at=first_observed,
            last_observed_at=last_observed,
        )
    return evidence


def _story_report_period(timestamp: datetime, timezone_name: str) -> tuple[datetime, datetime]:
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_timezone = timezone.utc
    local = timestamp.astimezone(local_timezone)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def process_stories_after_persist_best_effort(
    result: DeduplicationResult,
    storage: IntelligenceStorage | None,
    *,
    save_report: bool = True,
    now: datetime | None = None,
    story_content_ids: Iterable[str] | None = None,
    story_domain: str | None = None,
    wording_client: object | None = None,
    digest_analyzer: object | None = None,
) -> StoryBatchResult:
    """Derive ranked Stories from persisted canonical IDs without fetching again."""
    if storage is None or not storage.story_config.get("enabled", False):
        return StoryBatchResult(stories=[])
    timestamp = now or datetime.now(tz=timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    affected_ids = set(
        dict.fromkeys([*result.canonical_ids, *(i.id for i in result.canonical_items)])
    )
    if story_content_ids is not None:
        affected_ids &= {str(item_id) for item_id in story_content_ids}
    resolver = storage.get_security_item_view if story_domain == "security" else storage.get_item
    affected = [
        item for item_id in sorted(affected_ids) if (item := resolver(item_id)) is not None
    ]
    if story_domain is not None:
        affected = [item for item in affected if item.domain == story_domain]
    if not affected:
        return StoryBatchResult(stories=[])

    try:
        from trendradar.intelligence.ranking import rank_stories
        from trendradar.intelligence.story_report import save_story_report

        story_config = storage.story_config
        derived = StoryService(
            storage,
            clustering_config=story_config.get("clustering"),
            wording_client=wording_client,
        ).process(affected, persist=False)
        ranked = rank_stories(
            derived.stories,
            _story_evidence(storage, derived.stories),
            story_config.get("ranking"),
            now=timestamp,
        )
        cluster_count, story_count, member_count = storage.upsert_story_batch(
            derived.clusters, ranked
        )
        output = StoryBatchResult(
            stories=ranked,
            clusters=derived.clusters,
            clusters_created=cluster_count,
            stories_created=story_count,
            memberships_created=member_count,
        )

    except Exception as exc:
        log.error("Story intelligence processing failed; legacy path continues", error=str(exc))
        return StoryBatchResult(stories=[], processing_succeeded=False)

    report_value = storage.story_config.get("report") or {}
    report_config = report_value if isinstance(report_value, dict) else {}
    if save_report and report_config.get("enabled", True):
        try:
            timezone_name = str(storage.story_config.get("timezone") or "Asia/Shanghai")
            start, end = _story_report_period(timestamp, timezone_name)
            stories = storage.list_stories(
                start=start,
                end=end,
                limit=_positive_int(report_config.get("max_stories", 100), 100),
            )
            report_path = save_story_report(
                stories,
                storage,
                output_dir=storage.story_config.get("output_dir") or "output/stories",
                generated_at=timestamp,
                timezone_name=timezone_name,
                digest_analyzer=digest_analyzer,
            )
            log.info("Story report generated", path=str(report_path), stories=len(stories))
        except Exception as exc:
            log.error("Story report generation failed; legacy path continues", error=str(exc))
    return output


def attach_canonical_ids(
    adapter_results: list[AdapterResult[Any]],
    result: DeduplicationResult,
) -> None:
    """Attach runtime-only canonical IDs to successfully normalized legacy records."""
    legacy_items = [
        raw
        for adapter_result in adapter_results
        for raw in adapter_result.normalized_raw_items
    ]
    for legacy_item, canonical_id in zip(legacy_items, result.canonical_ids, strict=False):
        try:
            setattr(legacy_item, CANONICAL_ID_ATTRIBUTE, canonical_id)
        except (AttributeError, TypeError):
            continue


def process_content_items(
    items: list[ContentItem],
    *,
    storage: IntelligenceStorage | None = None,
    persist: bool = True,
) -> DeduplicationResult:
    """Deduplicate a batch and optionally persist it without hiding storage errors."""
    result = Deduplicator(storage).process(items)
    if storage is not None and persist:
        storage.write_batch(result.canonical_items, result.observations)
        result.persistence_succeeded = True
    return result


def persist_adapter_results_best_effort(
    adapter_results: list[AdapterResult[Any]],
    storage: IntelligenceStorage | None,
    *,
    story_content_ids: Iterable[str] | None = None,
    wording_client: object | None = None,
    digest_analyzer: object | None = None,
    save_story_report: bool = True,
    process_stories: bool = True,
    story_domain: str | None = None,
    title_translator: CanonicalTitleTranslator | None = None,
) -> DeduplicationResult:
    """Write normalized adapter output; failures never affect legacy projections."""
    items = [item for result in adapter_results for item in result.items]
    if not items:
        return DeduplicationResult(persistence_succeeded=storage is not None)
    if title_translator is not None:
        for item in items:
            item.metadata["title_translation"] = {
                "status": "pending", "original_title": item.title,
            }
    persisted = False
    try:
        result = process_content_items(items, storage=storage)
        persisted = storage is not None
        result.persistence_succeeded = persisted
    except Exception as exc:
        log.error("统一情报库写入失败，旧链路继续", error=str(exc))
        result = Deduplicator().process(items)
        result.persistence_succeeded = False
    # Freshness filters arrive as input IDs; deduplication can map them to older canonical IDs.
    selected_ids = set(story_content_ids) if story_content_ids is not None else None
    eligible_ids = {
        canonical_id for item, canonical_id in zip(items, result.canonical_ids, strict=False)
        if selected_ids is None or item.id in selected_ids
    }
    translation_ready = True
    if title_translator is not None:
        try:
            canonical = {item.id: item for item in result.canonical_items}
            if persisted:
                canonical.update({
                    item_id: item for item_id in sorted(eligible_ids)
                    if (item := storage.get_item(item_id)) is not None
                })
            outcomes = title_translator.resolve([
                item for item_id, item in canonical.items() if item_id in eligible_ids
            ])
            if persisted:
                storage.update_title_translations(outcomes)
        except Exception as exc:
            translation_ready = False
            log.error("Title metadata persistence failed; Story publication deferred",
                      error_type=type(exc).__name__)
    if persisted and process_stories and translation_ready:
        try:
            process_stories_after_persist_best_effort(
                result,
                storage,
                save_report=save_story_report,
                story_content_ids=eligible_ids,
                story_domain=story_domain,
                wording_client=wording_client,
                digest_analyzer=digest_analyzer,
            )
        except Exception as exc:
            log.error("Story intelligence failed unexpectedly; legacy path continues", error=str(exc))
    attach_canonical_ids(adapter_results, result)
    if title_translator is not None:
        for adapter_result in adapter_results:
            for raw in adapter_result.normalized_raw_items:
                try:
                    title_translator.project(raw, getattr(raw, CANONICAL_ID_ATTRIBUTE, ""))
                except (AttributeError, TypeError):
                    continue
    return result


__all__ = [
    "CANONICAL_ID_ATTRIBUTE",
    "attach_canonical_ids",
    "persist_adapter_results_best_effort",
    "process_content_items",
    "process_stories_after_persist_best_effort",
]
