"""Security source records, parsing, and bounded collection orchestration."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trendradar.core.models import ContentItem, normalize_datetime, normalize_tags, normalize_text
from trendradar.utils.logging import log

if TYPE_CHECKING:
    from trendradar.intelligence.deduplicate import DeduplicationResult
    from trendradar.sources.base import AdapterResult

CISA_KEV_URL = (
    "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
)
NVD_CVE_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_DETAIL_URL = "https://nvd.nist.gov/vuln/detail/{cve_id}"
CVE_PATTERN = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE)


def extract_cve_ids(*values: Any) -> list[str]:
    """Return stable, uppercase CVE identifiers found in arbitrary text values."""
    found: set[str] = set()
    for value in values:
        if isinstance(value, Mapping):
            candidates = value.values()
        elif isinstance(value, list | tuple | set | frozenset):
            candidates = value
        else:
            candidates = (value,)
        for candidate in candidates:
            found.update(match.upper() for match in CVE_PATTERN.findall(str(candidate or "")))
    return sorted(found)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded_text(value: Any, limit: int) -> str:
    text = normalize_text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _date_string(value: Any) -> str:
    parsed = normalize_datetime(value)
    if parsed is not None:
        return parsed.date().isoformat()
    raw = normalize_text(value)
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return ""


@dataclass(frozen=True)
class SecurityRecord:
    """Provider-neutral security evidence before canonical normalization."""

    source_key: str
    source_name: str
    external_id: str
    title: str
    summary: str = ""
    url: str = ""
    published_at: datetime | None = None
    modified_at: datetime | None = None
    cve_ids: tuple[str, ...] = ()
    severity: str = ""
    cvss_score: float | None = None
    cvss_version: str = ""
    cvss_vector: str = ""
    known_exploited: bool = False
    required_action: str = ""
    due_date: str = ""
    vendor: str = ""
    product: str = ""
    references: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_content_item(self, *, collected_at: datetime) -> ContentItem:
        source_key = normalize_text(self.source_key).casefold().replace("_", "-")
        if not source_key:
            raise ValueError("security source_key is required")
        cve_ids = extract_cve_ids(self.external_id, self.cve_ids, self.title, self.summary)
        external_id = normalize_text(self.external_id) or (cve_ids[0] if cve_ids else "")
        if not external_id:
            raise ValueError("security external_id is required")
        title = normalize_text(self.title)
        if not title:
            raise ValueError("security title is required")

        raw_url = normalize_text(self.url)
        canonical_url = raw_url
        if cve_ids and source_key in {"cisa-kev", "nvd"}:
            canonical_url = NVD_DETAIL_URL.format(cve_id=cve_ids[0])
        severity = normalize_text(self.severity).upper()
        due_date = _date_string(self.due_date)
        metadata = {
            **dict(self.metadata),
            "source_content_id": external_id,
            "source_name": normalize_text(self.source_name) or source_key,
            "raw_url": raw_url,
            "cve_ids": cve_ids,
            "entities": cve_ids,
            "severity": severity,
            "cvss_score": self.cvss_score,
            "cvss_version": normalize_text(self.cvss_version),
            "cvss_vector": normalize_text(self.cvss_vector),
            "known_exploited": bool(self.known_exploited),
            "required_action": normalize_text(self.required_action),
            "action_required": bool(self.known_exploited or self.required_action or due_date),
            "due_date": due_date,
            "vendor": normalize_text(self.vendor),
            "product": normalize_text(self.product),
            "references": list(dict.fromkeys(str(url) for url in self.references if str(url))),
            "published_time": self.published_at.isoformat() if self.published_at else None,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
        }
        tags = normalize_tags(
            [
                *self.tags,
                *cve_ids,
                severity,
                "KEV" if self.known_exploited else "",
                self.vendor,
                self.product,
            ]
        )
        return ContentItem.create(
            title=title,
            content=self.summary,
            url=canonical_url,
            source=f"security:{source_key}",
            domain="security",
            published_time=self.published_at,
            collected_at=collected_at,
            tags=tags,
            metadata=metadata,
        )


def parse_cisa_catalog(
    payload: Mapping[str, Any],
    *,
    source_url: str = CISA_KEV_URL,
) -> list[SecurityRecord]:
    """Parse a CISA KEV catalog while leaving bad entries for normalize isolation."""
    if not isinstance(payload, Mapping):
        raise ValueError("CISA KEV response must be an object")
    vulnerabilities = payload.get("vulnerabilities")
    if not isinstance(vulnerabilities, list):
        raise ValueError("CISA KEV vulnerabilities must be a list")
    catalog_metadata = {
        "catalog_version": normalize_text(payload.get("catalogVersion")),
        "catalog_released_at": normalize_text(payload.get("dateReleased")),
        "catalog_count": payload.get("count"),
    }
    records: list[SecurityRecord] = []
    for raw in vulnerabilities:
        if not isinstance(raw, Mapping):
            continue
        cve_id = normalize_text(raw.get("cveID")).upper()
        title = normalize_text(raw.get("vulnerabilityName"))
        display_title = f"{cve_id}: {title}" if cve_id and title else cve_id or title
        records.append(
            SecurityRecord(
                source_key="cisa-kev",
                source_name="CISA KEV",
                external_id=cve_id,
                title=display_title,
                summary=_bounded_text(raw.get("shortDescription"), 1200),
                url=source_url,
                published_at=normalize_datetime(raw.get("dateAdded")),
                cve_ids=tuple(extract_cve_ids(cve_id)),
                known_exploited=True,
                required_action=normalize_text(raw.get("requiredAction")),
                due_date=_date_string(raw.get("dueDate")),
                vendor=normalize_text(raw.get("vendorProject")),
                product=normalize_text(raw.get("product")),
                tags=tuple(str(value) for value in (raw.get("cwes") or []) if value),
                metadata={
                    **catalog_metadata,
                    "known_ransomware_campaign_use": normalize_text(
                        raw.get("knownRansomwareCampaignUse")
                    ),
                    "notes": normalize_text(raw.get("notes")),
                },
            )
        )
    return records


_CVSS_FAMILIES = ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2")


def _extract_cvss(metrics: Any) -> tuple[str, float | None, str, str]:
    if not isinstance(metrics, Mapping):
        return "", None, "", ""
    for family in _CVSS_FAMILIES:
        raw_candidates = metrics.get(family)
        if not isinstance(raw_candidates, list) or not raw_candidates:
            continue
        candidates = [candidate for candidate in raw_candidates if isinstance(candidate, Mapping)]
        candidates.sort(key=lambda candidate: str(candidate.get("type", "")).upper() != "PRIMARY")
        for candidate in candidates:
            cvss = candidate.get("cvssData")
            if not isinstance(cvss, Mapping):
                continue
            score = _float_or_none(cvss.get("baseScore"))
            severity = normalize_text(
                cvss.get("baseSeverity") or candidate.get("baseSeverity")
            ).upper()
            version = normalize_text(cvss.get("version"))
            vector = normalize_text(cvss.get("vectorString"))
            if score is not None or severity or vector:
                return severity, score, version, vector
    return "", None, "", ""


def _english_description(descriptions: Any) -> str:
    if not isinstance(descriptions, list):
        return ""
    candidates = [entry for entry in descriptions if isinstance(entry, Mapping)]
    selected = next(
        (entry for entry in candidates if str(entry.get("lang", "")).casefold() == "en"),
        candidates[0] if candidates else {},
    )
    return _bounded_text(selected.get("value"), 1600)


def parse_nvd_page(payload: Mapping[str, Any]) -> tuple[list[SecurityRecord], int, int, int]:
    """Parse one NVD CVE API 2.0 page and its pagination contract."""
    if not isinstance(payload, Mapping):
        raise ValueError("NVD response must be an object")
    vulnerabilities = payload.get("vulnerabilities")
    if not isinstance(vulnerabilities, list):
        raise ValueError("NVD vulnerabilities must be a list")
    records: list[SecurityRecord] = []
    for wrapper in vulnerabilities:
        if not isinstance(wrapper, Mapping) or not isinstance(wrapper.get("cve"), Mapping):
            continue
        raw = wrapper["cve"]
        cve_id = normalize_text(raw.get("id")).upper()
        summary = _english_description(raw.get("descriptions"))
        title_summary = summary.split(". ", 1)[0].rstrip(".")
        title = f"{cve_id}: {_bounded_text(title_summary, 200)}" if title_summary else cve_id
        severity, score, version, vector = _extract_cvss(raw.get("metrics"))
        references = tuple(
            normalize_text(entry.get("url"))
            for entry in (raw.get("references") or [])
            if isinstance(entry, Mapping) and normalize_text(entry.get("url"))
        )
        weaknesses: list[str] = []
        for weakness in raw.get("weaknesses") or []:
            if not isinstance(weakness, Mapping):
                continue
            weaknesses.extend(
                normalize_text(description.get("value"))
                for description in weakness.get("description") or []
                if isinstance(description, Mapping) and normalize_text(description.get("value"))
            )
        records.append(
            SecurityRecord(
                source_key="nvd",
                source_name="NVD",
                external_id=cve_id,
                title=title,
                summary=summary,
                url=NVD_DETAIL_URL.format(cve_id=cve_id) if cve_id else "",
                published_at=normalize_datetime(raw.get("published")),
                modified_at=normalize_datetime(raw.get("lastModified")),
                cve_ids=tuple(extract_cve_ids(cve_id)),
                severity=severity,
                cvss_score=score,
                cvss_version=version,
                cvss_vector=vector,
                references=references,
                tags=tuple(weaknesses),
                metadata={
                    "source_identifier": normalize_text(raw.get("sourceIdentifier")),
                    "vulnerability_status": normalize_text(raw.get("vulnStatus")),
                },
            )
        )
    try:
        total = max(0, int(payload.get("totalResults", len(records))))
        start = max(0, int(payload.get("startIndex", 0)))
        per_page = max(0, int(payload.get("resultsPerPage", len(records))))
    except (TypeError, ValueError) as exc:
        raise ValueError("NVD pagination fields must be integers") from exc
    return records, total, start, per_page


def security_record_from_rss(item: Any) -> SecurityRecord:
    cve_ids = extract_cve_ids(item.title, item.summary)
    source_id = normalize_text(item.feed_id)
    return SecurityRecord(
        source_key=f"rss:{source_id}",
        source_name=normalize_text(item.feed_name) or source_id,
        external_id=(
            normalize_text(getattr(item, "guid", ""))
            or normalize_text(item.url)
            or f"{source_id}:{normalize_text(item.title)}"
        ),
        title=item.title,
        summary=item.summary,
        url=item.url,
        published_at=normalize_datetime(item.published_at),
        cve_ids=tuple(cve_ids),
        tags=("security-news",),
        metadata={
            "author": normalize_text(item.author),
            "guid": normalize_text(getattr(item, "guid", "")),
        },
    )


def _empty_deduplication() -> DeduplicationResult:
    from trendradar.intelligence.deduplicate import DeduplicationResult

    return DeduplicationResult()


@dataclass(frozen=True)
class SecurityRunSummary:
    enabled: bool
    adapter_results: tuple[AdapterResult[Any], ...] = ()
    deduplication: DeduplicationResult = field(default_factory=_empty_deduplication)
    stories_analyzed: int = 0
    report_path: Path | None = None
    collection_succeeded: bool = True
    persistence_succeeded: bool = False
    story_processing_succeeded: bool = True
    analysis_succeeded: bool = True
    freshness_succeeded: bool = True
    report_succeeded: bool | None = None
    errors: tuple[str, ...] = ()

    @property
    def data_refreshed(self) -> bool:
        return self.persistence_succeeded and any(result.items for result in self.adapter_results)


def _positive_int(value: Any, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _bounded_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = normalize_text(value).casefold()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return default


def configured_security_adapter_ids(config: Mapping[str, Any] | None) -> list[str]:
    """Return every enabled logical source without constructing network clients."""
    values = config if isinstance(config, Mapping) else {}
    sources = values.get("sources") if isinstance(values.get("sources"), Mapping) else {}
    adapter_ids: list[str] = []
    for key, adapter_id in (("cisa_kev", "security:cisa-kev"), ("nvd", "security:nvd")):
        source = sources.get(key) if isinstance(sources.get(key), Mapping) else {}
        if _as_bool(source.get("enabled"), True):
            adapter_ids.append(adapter_id)
    rss = sources.get("rss") if isinstance(sources.get("rss"), Mapping) else {}
    if _as_bool(rss.get("enabled"), True):
        for raw_feed in rss.get("feeds") or []:
            if not isinstance(raw_feed, Mapping) or not _as_bool(raw_feed.get("enabled"), True):
                continue
            feed_id = normalize_text(raw_feed.get("id"))
            if feed_id:
                adapter_ids.append(f"security:rss:{feed_id}")
    return list(dict.fromkeys(adapter_ids))


def build_security_adapters(
    config: Mapping[str, Any] | None,
    *,
    now: datetime,
    nvd_api_key: str = "",
) -> list[Any]:
    """Build enabled security adapters from one frozen runtime timestamp."""
    from trendradar.crawler.rss.fetcher import RSSFeedConfig
    from trendradar.sources.security import CisaKevAdapter, NvdCveAdapter, SecurityRSSAdapter

    values = config if isinstance(config, Mapping) else {}
    sources = values.get("sources") if isinstance(values.get("sources"), Mapping) else {}
    adapters: list[Any] = []

    cisa = sources.get("cisa_kev") if isinstance(sources.get("cisa_kev"), Mapping) else {}
    if _as_bool(cisa.get("enabled"), True):
        try:
            adapters.append(CisaKevAdapter(dict(cisa)))
        except Exception as exc:
            log.error("CISA KEV adapter configuration failed", error=str(exc))

    nvd = sources.get("nvd") if isinstance(sources.get("nvd"), Mapping) else {}
    if _as_bool(nvd.get("enabled"), True):
        try:
            adapters.append(NvdCveAdapter(dict(nvd), now=now, api_key=nvd_api_key))
        except Exception as exc:
            log.error("NVD adapter configuration failed", error=str(exc))

    rss = sources.get("rss") if isinstance(sources.get("rss"), Mapping) else {}
    if _as_bool(rss.get("enabled"), True):
        fetcher_options = {
            "timeout": _bounded_int(rss.get("timeout"), 20, minimum=1, maximum=120),
            "use_proxy": _as_bool(rss.get("use_proxy"), False),
            "proxy_url": normalize_text(rss.get("proxy_url")),
            "timezone": normalize_text(values.get("timezone")) or "Asia/Shanghai",
            "freshness_enabled": True,
            "default_max_age_days": _bounded_int(
                rss.get("max_age_days"), 3, minimum=1, maximum=3650
            ),
        }
        seen_feed_ids: set[str] = set()
        for raw_feed in rss.get("feeds") or []:
            if not isinstance(raw_feed, Mapping) or not _as_bool(raw_feed.get("enabled"), True):
                continue
            feed_id = normalize_text(raw_feed.get("id"))
            feed_url = normalize_text(raw_feed.get("url"))
            if not feed_id or not feed_url or feed_id in seen_feed_ids:
                continue
            seen_feed_ids.add(feed_id)
            try:
                feed = RSSFeedConfig(
                    id=feed_id,
                    name=normalize_text(raw_feed.get("name")) or feed_id,
                    url=feed_url,
                    max_items=_bounded_int(
                        raw_feed.get("max_items"), 25, minimum=1, maximum=500
                    ),
                    enabled=True,
                    max_age_days=_bounded_int(
                        raw_feed.get("max_age_days"), 3, minimum=1, maximum=3650
                    ),
                )
                adapters.append(SecurityRSSAdapter(feed, **fetcher_options))
            except Exception as exc:
                log.error(
                    "Security RSS adapter configuration failed",
                    adapter_id=f"security:rss:{feed_id}",
                    error=str(exc),
                )
    return adapters


async def collect_security(
    config: Mapping[str, Any] | None,
    *,
    storage: Any,
    collected_at: datetime,
    nvd_api_key: str = "",
) -> list[AdapterResult[Any]]:
    """Fetch all enabled security sources once through the shared runner."""
    from trendradar.intelligence.runner import AdapterRunner

    values = config if isinstance(config, Mapping) else {}
    if not _as_bool(values.get("enabled"), True) or storage is None:
        return []
    if collected_at.tzinfo is None or collected_at.utcoffset() is None:
        raise ValueError("collected_at must be timezone-aware")
    timestamp = collected_at.astimezone(timezone.utc)
    adapters = build_security_adapters(values, now=timestamp, nvd_api_key=nvd_api_key)
    return await AdapterRunner(
        max_concurrency=_bounded_int(
            values.get("max_concurrency"), 4, minimum=1, maximum=16
        ),
        storage=storage,
    ).run(adapters, collected_at=timestamp)


def _story_candidate_ids(
    results: list[AdapterResult[Any]],
    config: Mapping[str, Any],
    now: datetime,
) -> set[str]:
    sources = config.get("sources") if isinstance(config.get("sources"), Mapping) else {}
    cisa = sources.get("cisa_kev") if isinstance(sources.get("cisa_kev"), Mapping) else {}
    cutoff = now - timedelta(
        days=_bounded_int(cisa.get("story_lookback_days"), 30, minimum=1, maximum=3650)
    )
    candidates: set[str] = set()
    for result in results:
        for item in result.items:
            if result.adapter_id == "security:cisa-kev":
                if item.published_time is None or item.published_time < cutoff:
                    continue
            candidates.add(item.id)
    return candidates


def run_security_pipeline(
    config: Mapping[str, Any] | None,
    *,
    storage: Any,
    collected_at: datetime | None = None,
    nvd_api_key: str = "",
    wording_client: object | None = None,
    narrative_analyzer: object | None = None,
) -> SecurityRunSummary:
    """Collect, persist, analyze, and report security data without touching legacy output."""
    values = config if isinstance(config, Mapping) else {}
    if not _as_bool(values.get("enabled"), True) or storage is None:
        return SecurityRunSummary(enabled=False)
    timestamp = collected_at or datetime.now(tz=timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("collected_at must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)

    errors: list[str] = []
    results: list[AdapterResult[Any]] = []
    collection_succeeded = True
    try:
        results = asyncio.run(
            collect_security(
                values,
                storage=storage,
                collected_at=timestamp,
                nvd_api_key=nvd_api_key,
            )
        )
    except Exception as exc:
        collection_succeeded = False
        errors.append(f"collection: {exc}")
        log.error("Security collection orchestration failed", error=str(exc))

    from trendradar.intelligence.pipeline import (
        persist_adapter_results_best_effort,
        process_stories_after_persist_best_effort,
    )

    try:
        if not collection_succeeded:
            raise RuntimeError("collection did not produce a persistable batch")
        deduplicated = persist_adapter_results_best_effort(
            results,
            storage,
            wording_client=wording_client,
            save_story_report=False,
            process_stories=False,
        )
    except Exception as exc:
        deduplicated = _empty_deduplication()
        deduplicated.persistence_succeeded = False
        errors.append(f"persistence: {exc}")
        log.error("Security canonical persistence failed", error=str(exc))
    persistence_succeeded = deduplicated.persistence_succeeded is True
    if not persistence_succeeded and not any(error.startswith("persistence:") for error in errors):
        errors.append("persistence: canonical batch was not written")

    story_processing_succeeded = persistence_succeeded
    if persistence_succeeded:
        eligible_item_ids = _story_candidate_ids(results, values, timestamp)
        flattened_items = [item for result in results for item in result.items]
        canonical_story_ids = {
            canonical_id
            for item, canonical_id in zip(
                flattened_items,
                deduplicated.canonical_ids,
                strict=False,
            )
            if item.id in eligible_item_ids
        }
        try:
            story_result = process_stories_after_persist_best_effort(
                deduplicated,
                storage,
                save_report=False,
                now=timestamp,
                story_content_ids=canonical_story_ids,
                story_domain="security",
                wording_client=wording_client,
            )
            story_processing_succeeded = story_result.processing_succeeded
            if not story_processing_succeeded:
                errors.append("story: security Story processing failed")
        except Exception as exc:
            story_processing_succeeded = False
            errors.append(f"story: {exc}")
            log.error("Security Story processing failed", error=str(exc))

    from trendradar.domains.security.analyzer import (
        analyze_security_stories,
        build_source_freshness,
    )
    from trendradar.domains.security.report import save_security_report

    report = values.get("report") if isinstance(values.get("report"), Mapping) else {}
    lookback_days = _bounded_int(
        report.get("lookback_days"), 30, minimum=1, maximum=3650
    )
    max_stories = _bounded_int(report.get("max_stories"), 100, minimum=1, maximum=500)
    default_candidates = min(2000, max(500, max_stories * 5))
    max_candidates = max(
        max_stories,
        _bounded_int(
            report.get("max_candidates"),
            default_candidates,
            minimum=1,
            maximum=2000,
        ),
    )
    analysis_succeeded = True
    analyzed = []
    try:
        stories = storage.list_stories(
            domain="security",
            start=timestamp - timedelta(days=lookback_days),
            limit=max_candidates,
        )
        analyzed = analyze_security_stories(
            stories,
            storage,
            values.get("ranking"),
            now=timestamp,
        )
        if analyzed:
            storage.upsert_story_batch([], analyzed)
    except Exception as exc:
        analysis_succeeded = False
        errors.append(f"analysis: {exc}")
        log.error("Security analysis failed", error=str(exc))

    adapter_ids = configured_security_adapter_ids(values)
    freshness_succeeded = True
    try:
        freshness = build_source_freshness(
            storage,
            adapter_ids,
            now=timestamp,
            stale_after_hours=_bounded_int(
                values.get("stale_after_hours"), 48, minimum=1, maximum=8760
            ),
        )
    except Exception as exc:
        from trendradar.domains.security.analyzer import SourceFreshness

        freshness_succeeded = False
        errors.append(f"freshness: {exc}")
        log.error("Security freshness lookup failed", error=str(exc))
        freshness = [
            SourceFreshness(
                adapter_id=adapter_id,
                status="unknown",
                last_attempt_at=None,
                last_success_at=None,
                age_hours=None,
                stale=True,
            )
            for adapter_id in adapter_ids
        ]
    report_path = None
    report_succeeded: bool | None = None
    if _as_bool(report.get("enabled"), True):
        try:
            report_path = save_security_report(
                analyzed[:max_stories],
                storage,
                freshness=freshness,
                output_dir=values.get("output_dir") or "output/security",
                generated_at=timestamp,
                timezone_name=values.get("timezone") or "Asia/Shanghai",
                narrative_analyzer=narrative_analyzer,
            )
            report_succeeded = True
        except Exception as exc:
            report_succeeded = False
            errors.append(f"report: {exc}")
            log.error("Security report generation failed", error=str(exc))
    return SecurityRunSummary(
        enabled=True,
        adapter_results=tuple(results),
        deduplication=deduplicated,
        stories_analyzed=len(analyzed),
        report_path=report_path,
        collection_succeeded=collection_succeeded,
        persistence_succeeded=persistence_succeeded,
        story_processing_succeeded=story_processing_succeeded,
        analysis_succeeded=analysis_succeeded,
        freshness_succeeded=freshness_succeeded,
        report_succeeded=report_succeeded,
        errors=tuple(errors),
    )


__all__ = [
    "CISA_KEV_URL",
    "CVE_PATTERN",
    "NVD_CVE_API_URL",
    "NVD_DETAIL_URL",
    "SecurityRecord",
    "SecurityRunSummary",
    "build_security_adapters",
    "collect_security",
    "configured_security_adapter_ids",
    "extract_cve_ids",
    "parse_cisa_catalog",
    "parse_nvd_page",
    "run_security_pipeline",
    "security_record_from_rss",
]
