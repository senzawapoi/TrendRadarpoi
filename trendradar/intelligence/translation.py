"""Canonical-first translation with propagation to legacy compatibility records."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from trendradar.intelligence.pipeline import CANONICAL_ID_ATTRIBUTE
from trendradar.storage.base import NewsItem

_TRANSLATION_FIELDS = (
    "title_translated",
    "title_english",
    "summary_translated",
    "summary_english",
    "is_english",
)


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


__all__ = ["translate_news_items_canonically"]
