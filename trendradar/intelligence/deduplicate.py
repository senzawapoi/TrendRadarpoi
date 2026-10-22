"""Conservative canonical content de-duplication with provenance retention."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from trendradar.core.models import ContentItem, normalize_identity_title
from trendradar.intelligence.storage import ContentObservation, IntelligenceStorage


def event_time(item: ContentItem) -> datetime:
    return item.published_time or item.collected_at


@dataclass
class DeduplicationResult:
    canonical_items: list[ContentItem] = field(default_factory=list)
    observations: list[ContentObservation] = field(default_factory=list)
    canonical_ids: list[str] = field(default_factory=list)
    persistence_succeeded: bool | None = None

    @property
    def duplicate_count(self) -> int:
        return len(self.observations) - len(self.canonical_items)


class Deduplicator:
    """Apply deterministic URL and same-source title rules in contract order."""

    def __init__(
        self,
        storage: IntelligenceStorage | None = None,
        *,
        title_window_hours: int = 24,
        fuzzy_threshold: float = 0.92,
        fuzzy_min_length: int = 12,
    ) -> None:
        self.storage = storage
        self.title_window = timedelta(hours=title_window_hours)
        self.fuzzy_threshold = fuzzy_threshold
        self.fuzzy_min_length = fuzzy_min_length

    def process(self, items: list[ContentItem]) -> DeduplicationResult:
        result = DeduplicationResult()
        canonical_by_id: dict[str, ContentItem] = {}
        canonical_by_url: dict[str, ContentItem] = {}
        canonical_by_source: dict[str, list[ContentItem]] = {}
        indexed_items = sorted(
            enumerate(items),
            key=lambda pair: (event_time(pair[1]), pair[1].id, pair[0]),
        )
        canonical_ids_by_input = ["" for _ in items]

        for input_index, item in indexed_items:
            observation = ContentObservation.from_item(item)
            canonical = self._existing_observation(observation)
            if canonical is None:
                canonical = self._url_match(item, canonical_by_url)
            if canonical is None:
                candidates = list(canonical_by_source.get(item.source, []))
                candidates.extend(self._stored_title_candidates(item))
                candidates = self._unique_candidates(candidates)
                canonical = self._title_match(item, candidates)
            if canonical is None:
                canonical = item
                result.canonical_items.append(item)
                canonical_by_id[item.id] = item
                if item.url:
                    canonical_by_url[item.url] = item
                canonical_by_source.setdefault(item.source, []).append(item)
            else:
                canonical_by_id.setdefault(canonical.id, canonical)
                if canonical.url:
                    canonical_by_url.setdefault(canonical.url, canonical)
                canonical_by_source.setdefault(canonical.source, []).append(canonical)

            observation.content_item_id = canonical.id
            result.observations.append(observation)
            canonical_ids_by_input[input_index] = canonical.id

        result.canonical_ids = canonical_ids_by_input
        return result

    def _existing_observation(self, observation: ContentObservation) -> ContentItem | None:
        if self.storage is None:
            return None
        item_id = self.storage.find_observation_item_id(
            observation.source,
            observation.source_content_id,
        )
        return self.storage.get_item(item_id) if item_id else None

    def _url_match(
        self,
        item: ContentItem,
        canonical_by_url: dict[str, ContentItem],
    ) -> ContentItem | None:
        if not item.url:
            return None
        candidate = canonical_by_url.get(item.url)
        if candidate is not None:
            return candidate
        return self.storage.find_by_url(item.url) if self.storage is not None else None

    def _stored_title_candidates(self, item: ContentItem) -> list[ContentItem]:
        if self.storage is None:
            return []
        return self.storage.find_source_items_in_window(
            item.source,
            event_time(item),
            hours=round(self.title_window.total_seconds() / 3600),
        )

    @staticmethod
    def _unique_candidates(candidates: list[ContentItem]) -> list[ContentItem]:
        unique: dict[str, ContentItem] = {}
        for candidate in candidates:
            unique.setdefault(candidate.id, candidate)
        return sorted(unique.values(), key=lambda item: (event_time(item), item.id))

    def _title_match(
        self,
        item: ContentItem,
        candidates: list[ContentItem],
    ) -> ContentItem | None:
        title = normalize_identity_title(item.title)
        item_time = event_time(item)
        eligible = [
            candidate
            for candidate in candidates
            if candidate.source == item.source
            and abs(event_time(candidate) - item_time) <= self.title_window
        ]
        for candidate in eligible:
            if normalize_identity_title(candidate.title) == title:
                return candidate
        if len(title) < self.fuzzy_min_length:
            return None
        for candidate in eligible:
            candidate_title = normalize_identity_title(candidate.title)
            if len(candidate_title) < self.fuzzy_min_length:
                continue
            if SequenceMatcher(None, title, candidate_title).ratio() >= self.fuzzy_threshold:
                return candidate
        return None


__all__ = ["DeduplicationResult", "Deduplicator", "event_time"]
