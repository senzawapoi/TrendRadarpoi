"""Canonical-first translation with propagation to legacy compatibility records."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from trendradar.ai.translator import TRANSLATION_MODEL, is_english_title
from trendradar.core.models import ContentItem
from trendradar.storage.base import NewsItem
from trendradar.utils.logging import log

CANONICAL_ID_ATTRIBUTE = "_canonical_content_id"
TRANSLATION_POLICY = "canonical-title-v1"

_TRANSLATION_FIELDS = (
    "title_translated",
    "title_english",
    "summary_translated",
    "summary_english",
    "is_english",
)


def localized_title(item: ContentItem) -> str:
    """Read a display title without changing identity or clustering inputs."""
    record = item.metadata.get("title_translation")
    if isinstance(record, dict):
        if record.get("original_title") == item.title and record.get("status") == "translated":
            return str(record.get("text") or "")
        return ""
    return str(item.metadata.get("title_translated") or "")


def title_translation_pending(item: ContentItem) -> bool:
    record = item.metadata.get("title_translation")
    return isinstance(record, dict) and record.get("status") == "pending"


class CanonicalTitleTranslator:
    """Resolve titles before Story publication; providers never run in a DB transaction."""

    def __init__(
        self,
        translate: Callable[[list[str]], list[str]] | None,
        *,
        model: str = TRANSLATION_MODEL,
        legacy_cache: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.translate = translate
        self.model = model
        self.legacy_cache = legacy_cache if legacy_cache is not None else {}
        self._outcomes: dict[str, dict[str, Any]] = {}

    def _matches(self, record: Any, title: str) -> bool:
        return (
            isinstance(record, dict)
            and record.get("original_title") == title
            and record.get("model") == self.model
            and record.get("policy") == TRANSLATION_POLICY
            and record.get("target_lang") == "zh"
        )

    def resolve(self, items: list[ContentItem]) -> dict[str, dict[str, Any]]:
        outcomes: dict[str, dict[str, Any]] = {}
        pending: list[ContentItem] = []
        for item in items:
            cached = self._outcomes.get(item.id)
            stored = item.metadata.get("title_translation")
            if self._matches(cached, item.title):
                outcomes[item.id] = dict(cached)
                continue
            if (
                self._matches(stored, item.title)
                and stored.get("status") == "translated"
                and stored.get("text")
                and self.translate is not None
            ):
                outcomes[item.id] = dict(stored)
                continue
            needs_translation = is_english_title(item.title)
            outcomes[item.id] = {
                "original_title": item.title,
                "text": "",
                "status": "fallback" if needs_translation else "original",
                "model": self.model,
                "policy": TRANSLATION_POLICY,
                "target_lang": "zh",
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            }
            if needs_translation and self.translate is not None:
                pending.append(item)
            elif needs_translation:
                outcomes[item.id]["status"] = "disabled"
        if pending:
            try:
                values = self.translate([item.title for item in pending])
                if not isinstance(values, list | tuple):
                    raise ValueError("invalid translation batch")
                for item, text in zip(pending, values, strict=False):
                    if isinstance(text, str) and text.strip():
                        outcomes[item.id].update(status="translated", text=text.strip())
            except Exception as exc:
                log.warning("Canonical title translation failed; originals retained",
                            error_type=type(exc).__name__)
        for item in items:
            record = outcomes[item.id]
            self._outcomes[item.id] = dict(record)
            self.legacy_cache[item.id] = {
                "title_translated": record["text"],
                "is_english": is_english_title(item.title),
            }
        log.info(
            "Canonical titles resolved before Story publication",
            translated=sum(r["status"] == "translated" for r in outcomes.values()),
            fallback=sum(r["status"] == "fallback" for r in outcomes.values()),
            requested=len(pending), model=self.model,
        )
        return outcomes

    def project(self, raw: Any, canonical_id: str) -> None:
        values = self.legacy_cache.get(canonical_id)
        if values is not None:
            for field, value in values.items():
                setattr(raw, field, value)
            raw._canonical_translation_resolved = True


def translate_news_items_canonically(
    items: list[NewsItem],
    translate: Callable[[list[NewsItem]], int],
    *,
    cache: dict[str, dict[str, Any]] | None = None,
) -> int:
    """Translate one representative per canonical ID and propagate compatible fields."""
    translation_cache = cache if cache is not None else {}
    groups: dict[str, list[NewsItem]] = {}
    for item in items:
        canonical_id = str(getattr(item, CANONICAL_ID_ATTRIBUTE, f"legacy:{id(item)}"))
        groups.setdefault(canonical_id, []).append(item)

    representatives: list[NewsItem] = []
    representative_keys: list[str] = []
    for canonical_id, group in groups.items():
        cached = translation_cache.get(canonical_id)
        if cached is not None:
            for item in group:
                for field_name, value in cached.items():
                    setattr(item, field_name, value)
            continue
        representative = group[0]
        existing = next((item for item in group if item.title_translated), None)
        if existing is not None:
            representative.title_translated = existing.title_translated
        representatives.append(representative)
        representative_keys.append(canonical_id)

    translated_count = translate(representatives) if representatives else 0
    for canonical_id, representative in zip(representative_keys, representatives, strict=False):
        values = {field_name: getattr(representative, field_name) for field_name in _TRANSLATION_FIELDS}
        translation_cache[canonical_id] = values
        for item in groups[canonical_id]:
            for field_name, value in values.items():
                setattr(item, field_name, value)
    return translated_count


__all__ = ["CanonicalTitleTranslator", "localized_title", "translate_news_items_canonically"]
