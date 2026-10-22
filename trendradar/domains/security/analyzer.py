"""Deterministic security assessment, importance, and source freshness."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from trendradar.core.models import ImportanceBreakdown, Story, normalize_tags, normalize_text
from trendradar.domains.security.collector import extract_cve_ids
from trendradar.intelligence.storage import IntelligenceStorage

_DEFAULT_WEIGHTS = {
    "base": 0.15,
    "severity": 0.35,
    "known_exploited": 0.30,
    "action": 0.20,
}
_SEVERITY_UNITS = {
    "CRITICAL": 1.0,
    "HIGH": 0.8,
    "MEDIUM": 0.5,
    "MODERATE": 0.5,
    "LOW": 0.2,
    "NONE": 0.0,
    "UNKNOWN": 0.0,
}
_CVSS_VERSION_PRIORITY = {
    "4": 4,
    "4.0": 4,
    "3.1": 3,
    "3.0": 2,
    "3": 2,
    "2.0": 1,
    "2": 1,
}


def _unit(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= 10 else None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return normalize_text(value).casefold() in {"1", "true", "yes", "known"}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _values(value: Any) -> list[Any]:
    if isinstance(value, list | tuple | set | frozenset):
        return list(value)
    return [] if value is None or value == "" else [value]


def _valid_date(value: Any) -> str:
    raw = normalize_text(value)
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return ""


@dataclass(frozen=True)
class SecurityRankingConfig:
    weights: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_WEIGHTS))
    version: str = "security-importance-v1"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> SecurityRankingConfig:
        values = data if isinstance(data, Mapping) else {}
        raw_weights = values.get("weights")
        raw_weights = raw_weights if isinstance(raw_weights, Mapping) else {}
        weights = {
            name: _unit(raw_weights.get(name), default)
            for name, default in _DEFAULT_WEIGHTS.items()
        }
        total = sum(weights.values())
        if total <= 0:
            weights = dict(_DEFAULT_WEIGHTS)
            total = sum(weights.values())
        return cls(
            weights={name: value / total for name, value in weights.items()},
            version=normalize_text(values.get("version")) or "security-importance-v1",
        )


@dataclass(frozen=True)
class SourceFreshness:
    adapter_id: str
    status: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    age_hours: float | None
    stale: bool
    fetched_count: int = 0
    normalized_count: int = 0
    error_count: int = 0
    error_summary: str = ""


def _story_metadata(story: Story, storage: IntelligenceStorage) -> list[Mapping[str, Any]]:
    metadata: list[Mapping[str, Any]] = [
        _mapping(item.metadata) for item in storage.list_story_items(story.id)
    ]
    for row in storage.list_story_evidence(story.id):
        try:
            parsed = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            parsed = {}
        metadata.append(_mapping(parsed))
    return metadata


def _security_evidence(metadata: list[Mapping[str, Any]]) -> dict[str, Any]:
    cve_ids = extract_cve_ids(*(entry.get("cve_ids", []) for entry in metadata))
    cvss_entries: list[tuple[float, str, str, str]] = []
    severities: set[str] = set()
    actions: set[str] = set()
    due_dates: set[str] = set()
    vendors: set[str] = set()
    products: set[str] = set()
    references: set[str] = set()
    known_exploited = False
    action_required = False

    for entry in metadata:
        severity = normalize_text(entry.get("severity")).upper()
        if severity:
            severities.add(severity)
        score = _float_or_none(entry.get("cvss_score"))
        if score is not None:
            cvss_entries.append(
                (
                    score,
                    severity,
                    normalize_text(entry.get("cvss_version")),
                    normalize_text(entry.get("cvss_vector")),
                )
            )
        known_exploited |= _truthy(entry.get("known_exploited"))
        action_required |= _truthy(entry.get("action_required"))
        action = normalize_text(entry.get("required_action"))
        if action:
            actions.add(action)
            action_required = True
        due_date = _valid_date(entry.get("due_date"))
        if due_date:
            due_dates.add(due_date)
            action_required = True
        vendor = normalize_text(entry.get("vendor"))
        product = normalize_text(entry.get("product"))
        if vendor:
            vendors.add(vendor)
        if product:
            products.add(product)
        references.update(
            normalize_text(value)
            for value in _values(entry.get("references"))
            if normalize_text(value)
        )

    best_cvss = max(
        cvss_entries,
        default=(0.0, "", "", ""),
        key=lambda value: (
            _CVSS_VERSION_PRIORITY.get(value[2].casefold().removeprefix("cvss:"), 0),
            value[0],
            value[2],
            value[3],
        ),
    )
    fallback_severity = max(
        severities,
        default="",
        key=lambda value: (_SEVERITY_UNITS.get(value, 0.0), value),
    )
    severity = best_cvss[1] or fallback_severity
    return {
        "cve_ids": cve_ids,
        "severity": severity,
        "cvss_score": best_cvss[0] or None,
        "cvss_version": best_cvss[2],
        "cvss_vector": best_cvss[3],
        "known_exploited": known_exploited,
        "action_required": action_required,
        "required_actions": sorted(actions, key=str.casefold),
        "due_date": min(due_dates) if due_dates else "",
        "vendors": sorted(vendors, key=str.casefold),
        "products": sorted(products, key=str.casefold),
        "references": sorted(references),
        "evidence_records": len(metadata),
    }


def analyze_security_stories(
    stories: list[Story],
    storage: IntelligenceStorage,
    config: Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> list[Story]:
    """Apply explainable security Importance and aggregate all persisted evidence."""
    timestamp = now or datetime.now(tz=timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)
    resolved = SecurityRankingConfig.from_mapping(config)
    analyzed: list[Story] = []

    for story in stories:
        if story.domain != "security":
            continue
        prior_security = _mapping(story.metadata.get("security"))
        base_score = _unit(
            prior_security.get("base_importance_score"),
            _unit(story.importance.score / 100),
        )
        evidence = _security_evidence(_story_metadata(story, storage))
        severity = max(
            _unit((evidence.get("cvss_score") or 0) / 10),
            _SEVERITY_UNITS.get(str(evidence.get("severity") or ""), 0.0),
        )
        exploited = 1.0 if evidence["known_exploited"] else 0.0
        action = 0.0
        if evidence["action_required"]:
            action = 0.5
        if evidence["required_actions"]:
            action = max(action, 0.7)
        if evidence["due_date"]:
            action = min(1.0, action + 0.3)
        components = {
            "base": base_score,
            "severity": severity,
            "known_exploited": exploited,
            "action": action,
        }
        score = 100 * sum(
            components[name] * resolved.weights[name] for name in _DEFAULT_WEIGHTS
        )
        reasons: list[str] = []
        if evidence["cvss_score"] is not None:
            label = f" {evidence['severity']}" if evidence["severity"] else ""
            reasons.append(f"CVSS {evidence['cvss_score']:.1f}{label}")
        elif evidence["severity"]:
            reasons.append(f"Severity {evidence['severity']}")
        if evidence["known_exploited"]:
            reasons.append("Known exploited (CISA KEV)")
        reasons.extend(f"Required action: {value}" for value in evidence["required_actions"])
        if evidence["due_date"]:
            due = date.fromisoformat(evidence["due_date"])
            delta = (due - timestamp.date()).days
            timing = "overdue" if delta < 0 else f"in {delta} day(s)"
            reasons.append(f"Action due {evidence['due_date']} ({timing})")
        reasons.append(f"Base intelligence score {base_score * 100:.1f}")

        evidence["base_importance_score"] = base_score
        story.importance = ImportanceBreakdown(
            score=score,
            components=components,
            reasons=reasons,
            version=resolved.version,
        )
        story.metadata = {**story.metadata, "security": evidence}
        story.tags = normalize_tags(
            [*story.tags, *evidence["cve_ids"], evidence["severity"], "KEV" if exploited else ""]
        )
        story.entities = normalize_tags([*story.entities, *evidence["cve_ids"]])
        analyzed.append(story)

    return sorted(
        analyzed,
        key=lambda story: (-story.importance.score, -story.event_time.timestamp(), story.id),
    )


def build_source_freshness(
    storage: IntelligenceStorage,
    adapter_ids: list[str],
    *,
    now: datetime | None = None,
    stale_after_hours: int = 48,
) -> list[SourceFreshness]:
    """Summarize current source state without performing health-check I/O."""
    timestamp = now or datetime.now(tz=timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)
    threshold = max(1, int(stale_after_hours))
    freshness: list[SourceFreshness] = []
    for adapter_id in sorted(set(adapter_ids)):
        latest = storage.latest_source_run(adapter_id)
        success = storage.latest_source_run(adapter_id, successful_only=True)
        age_hours = (
            max(0.0, (timestamp - success.finished_at).total_seconds() / 3600)
            if success is not None
            else None
        )
        freshness.append(
            SourceFreshness(
                adapter_id=adapter_id,
                status=latest.status if latest is not None else "unknown",
                last_attempt_at=latest.finished_at if latest is not None else None,
                last_success_at=success.finished_at if success is not None else None,
                age_hours=round(age_hours, 3) if age_hours is not None else None,
                stale=age_hours is None or age_hours > threshold,
                fetched_count=latest.fetched_count if latest is not None else 0,
                normalized_count=latest.normalized_count if latest is not None else 0,
                error_count=latest.error_count if latest is not None else 0,
                error_summary=(latest.error_summary[:500] if latest is not None else ""),
            )
        )
    return freshness


__all__ = [
    "SecurityRankingConfig",
    "SourceFreshness",
    "analyze_security_stories",
    "build_source_freshness",
]
