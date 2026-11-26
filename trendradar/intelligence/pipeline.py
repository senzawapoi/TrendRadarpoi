"""Application helpers for best-effort unified intelligence persistence."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trendradar.core.models import ContentItem, Story
from trendradar.intelligence.clustering import ClusteringConfig
from trendradar.intelligence.deduplicate import DeduplicationResult, Deduplicator, event_time
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.intelligence.stories import StoryBatchResult, StoryService
from trendradar.intelligence.translation import (
    CANONICAL_ID_ATTRIBUTE,
    CanonicalTitleTranslator,
    title_translation_pending,
)
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


def _refresh_settled_stories(
    storage: IntelligenceStorage,
    settled_items: list[ContentItem],
) -> list[Story]:
    """Refresh existing Stories for settled (> window) items in O(1) without full-history clustering."""
    from trendradar.intelligence.story_generator import _fallback_summary

    by_domain: dict[str, list[str]] = {}
    for item in settled_items:
        by_domain.setdefault(item.domain, []).append(item.id)
    story_ids: set[str] = set()
    for domain, member_ids in by_domain.items():
        story_ids |= storage.story_ids_for_members(member_ids, domain=domain)

    refreshed: list[Story] = []
    for story_id in sorted(story_ids):
        story = storage.get_story(story_id)
        if story is None:
            continue
        member_items = storage.list_story_items(story_id)
        obs_sources: set[str] = set()
        obs_source_names: set[str] = set()
        for member_id in story.member_ids:
            for row in storage.list_observations(member_id):
                obs_sources.add(str(row["source"]))
                try:
                    metadata = json.loads(row["metadata_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    metadata = {}
                if isinstance(metadata, Mapping):
                    obs_source_names.add(str(metadata.get("source_name") or row["source"]))
        story.metadata["source_count"] = len(
            obs_sources or {member.source for member in member_items}
        )
        if member_items and not story.metadata.get("wording_enhanced"):
            ordered = sorted(member_items, key=lambda member: (event_time(member), member.id))
            cluster_meta = (
                SimpleNamespace(
                    metadata={"observation_source_names": sorted(obs_source_names, key=str.casefold)}
                )
                if obs_source_names
                else None
            )
            story.summary = _fallback_summary(ordered, cluster_meta)  # type: ignore[arg-type]
        refreshed.append(story)
    return refreshed


def _latest_observation_time(
    storage: IntelligenceStorage,
    item_ids: Iterable[str],
) -> datetime | None:
    latest: datetime | None = None
    for item_id in item_ids:
        for row in storage.list_observations(item_id):
            stamp = datetime.fromisoformat(str(row["last_observed_at"])).astimezone(timezone.utc)
            latest = stamp if latest is None else max(latest, stamp)
    return latest


def _derive_and_persist_stories(
    affected_ids: Iterable[str],
    storage: IntelligenceStorage,
    *,
    save_report: bool,
    timestamp: datetime,
    reference_time: datetime,
    story_domain: str | None,
    wording_client: object | None,
    digest_analyzer: object | None,
) -> StoryBatchResult:
    resolver = storage.get_security_item_view if story_domain == "security" else storage.get_item
    affected = [
        item for item_id in sorted(set(affected_ids)) if (item := resolver(item_id)) is not None
    ]
    if story_domain is not None:
        affected = [item for item in affected if item.domain == story_domain]
    publishable = [item for item in affected if not title_translation_pending(item)]
    if not publishable:
        return StoryBatchResult(stories=[])

    try:
        from trendradar.intelligence.ranking import rank_stories
        from trendradar.intelligence.story_report import save_story_report

        story_config = storage.story_config
        clustering_cfg = ClusteringConfig.from_mapping(story_config.get("clustering"))
        settled_cutoff = reference_time - timedelta(hours=clustering_cfg.time_window_hours)

        active_items: list[ContentItem] = []
        settled_items: list[ContentItem] = []
        for item in publishable:
            if (
                item.domain != "security"
                and event_time(item) < settled_cutoff
                and storage.has_story_membership(item.id, domain=item.domain)
            ):
                settled_items.append(item)
            else:
                active_items.append(item)

        stories_by_id: dict[str, Story] = {}
        derived_clusters = []
        if active_items:
            derived = StoryService(
                storage,
                clustering_config=clustering_cfg,
                wording_client=wording_client,
            ).process(active_items, persist=False)
            derived_clusters = derived.clusters
            for story in derived.stories:
                stories_by_id[story.id] = story

        if settled_items:
            for settled_story in _refresh_settled_stories(storage, settled_items):
                stories_by_id.setdefault(settled_story.id, settled_story)

        if not stories_by_id:
            return StoryBatchResult(stories=[])

        candidate_stories = list(stories_by_id.values())
        ranked = rank_stories(
            candidate_stories,
            _story_evidence(storage, candidate_stories),
            story_config.get("ranking"),
            now=timestamp,
        )
        cluster_count, story_count, member_count = storage.upsert_story_batch(
            derived_clusters, ranked
        )
        output = StoryBatchResult(
            stories=ranked,
            clusters=derived_clusters,
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
    timestamp = timestamp.astimezone(timezone.utc)
    affected_ids = set(
        dict.fromkeys([*result.canonical_ids, *(i.id for i in result.canonical_items)])
    )
    if story_content_ids is not None:
        affected_ids &= {str(item_id) for item_id in story_content_ids}
    if not affected_ids:
        return StoryBatchResult(stories=[])
    batch_observed = max(
        (obs.observed_at.astimezone(timezone.utc) for obs in result.observations),
        default=None,
    )
    reference_time = (
        now.astimezone(timezone.utc)
        if now is not None
        else (batch_observed or _latest_observation_time(storage, affected_ids) or timestamp)
    )
    return _derive_and_persist_stories(
        affected_ids,
        storage,
        save_report=save_report,
        timestamp=timestamp,
        reference_time=reference_time,
        story_domain=story_domain,
        wording_client=wording_client,
        digest_analyzer=digest_analyzer,
    )


def finalize_stories_best_effort(
    content_ids: Iterable[str],
    storage: IntelligenceStorage | None,
    *,
    save_report: bool = True,
    now: datetime | None = None,
    story_domain: str | None = None,
    wording_client: object | None = None,
    digest_analyzer: object | None = None,
) -> StoryBatchResult:
    """Single-pass Story derivation across accumulated canonical IDs from multiple adapters."""
    if storage is None or not storage.story_config.get("enabled", False):
        return StoryBatchResult(stories=[])
    timestamp = now or datetime.now(tz=timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)
    affected_ids = [str(item_id) for item_id in dict.fromkeys(content_ids) if str(item_id)]
    if not affected_ids:
        return StoryBatchResult(stories=[])
    reference_time = (
        now.astimezone(timezone.utc)
        if now is not None
        else (_latest_observation_time(storage, affected_ids) or timestamp)
    )
    return _derive_and_persist_stories(
        affected_ids,
        storage,
        save_report=save_report,
        timestamp=timestamp,
        reference_time=reference_time,
        story_domain=story_domain,
        wording_client=wording_client,
        digest_analyzer=digest_analyzer,
    )


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
    pending_story_ids: set[str] | None = None,
) -> DeduplicationResult:
    """Write normalized adapter output; failures never affect legacy projections."""
    items = [item for result in adapter_results for item in result.items]
    if not items:
        return DeduplicationResult(persistence_succeeded=storage is not None)
    if title_translator is not None:
        for item in items:
            item.metadata["title_translation"] = {
                "status": "pending",
                "original_title": item.title,
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
        canonical_id
        for item, canonical_id in zip(items, result.canonical_ids, strict=False)
        if selected_ids is None or item.id in selected_ids
    }
    translation_ready = True
    if title_translator is not None:
        try:
            canonical = {item.id: item for item in result.canonical_items}
            if persisted:
                canonical.update(
                    {
                        item_id: item
                        for item_id in sorted(eligible_ids)
                        if (item := storage.get_item(item_id)) is not None
                    }
                )
            outcomes = title_translator.resolve(
                [item for item_id, item in canonical.items() if item_id in eligible_ids]
            )
            if persisted:
                storage.update_title_translations(outcomes)
        except Exception as exc:
            translation_ready = False
            log.error(
                "Title metadata persistence failed; Story publication deferred",
                error_type=type(exc).__name__,
            )
    if persisted and translation_ready and pending_story_ids is not None:
        pending_story_ids.update(eligible_ids)
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
            log.error(
                "Story intelligence failed unexpectedly; legacy path continues",
                error=str(exc),
            )
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
    "finalize_stories_best_effort",
    "persist_adapter_results_best_effort",
    "process_content_items",
    "process_stories_after_persist_best_effort",
]
