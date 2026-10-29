"""Deterministic offline clustering for canonical intelligence content."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from difflib import SequenceMatcher
from typing import Any

from trendradar.core.models import ContentItem, normalize_identity_title, normalize_tags
from trendradar.core.models.story import Cluster, deterministic_cluster_id
from trendradar.intelligence.deduplicate import event_time

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)

# Conservative high-signal defaults. Deployments can add project-specific
# aliases through ``entity_keywords``.
DEFAULT_ENTITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "amazon": ("amazon", "aws"),
    "anthropic": ("anthropic", "claude"),
    "apple": ("apple",),
    "deepmind": ("deepmind",),
    "google": ("google", "gemini"),
    "meta": ("meta", "llama"),
    "microsoft": ("microsoft", "copilot"),
    "mistral": ("mistral",),
    "nvidia": ("nvidia",),
    "openai": ("openai", "gpt"),
    "xai": ("xai", "grok"),
}


def _is_cjk(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3040 <= codepoint <= 0x30FF  # Hiragana/Katakana
        or 0x3400 <= codepoint <= 0x4DBF  # CJK Extension A
        or 0x4E00 <= codepoint <= 0x9FFF  # CJK Unified Ideographs
        or 0xAC00 <= codepoint <= 0xD7AF  # Hangul
    )


def _script_chunks(value: str) -> list[tuple[bool, str]]:
    chunks: list[tuple[bool, str]] = []
    current: list[str] = []
    current_is_cjk: bool | None = None
    for character in value:
        is_cjk = _is_cjk(character)
        is_word = is_cjk or character.isalnum()
        if not is_word:
            if current:
                chunks.append((bool(current_is_cjk), "".join(current)))
                current = []
                current_is_cjk = None
            continue
        if current and is_cjk != current_is_cjk:
            chunks.append((bool(current_is_cjk), "".join(current)))
            current = []
        current.append(character)
        current_is_cjk = is_cjk
    if current:
        chunks.append((bool(current_is_cjk), "".join(current)))
    return chunks


@dataclass(frozen=True)
class ClusteringConfig:
    time_window_hours: int = 24
    token_jaccard_threshold: float = 0.35
    title_similarity_threshold: float = 0.70
    min_shared_tokens: int = 2
    entity_keywords: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_ENTITY_KEYWORDS)
    )
    algorithm_version: str = "cluster-v1"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> ClusteringConfig:
        values = data if isinstance(data, Mapping) else {}
        raw_keywords = values.get("entity_keywords")
        keywords: dict[str, tuple[str, ...]] = dict(DEFAULT_ENTITY_KEYWORDS)
        if raw_keywords is None:
            raw_keywords = {}
        if isinstance(raw_keywords, Mapping):
            for name, aliases in raw_keywords.items():
                raw_aliases = aliases if isinstance(aliases, list | tuple | set) else [aliases]
                normalized = tuple(
                    value
                    for value in (
                        normalize_identity_title(alias) for alias in [name, *raw_aliases]
                    )
                    if value
                )
                if normalized:
                    keywords[normalize_identity_title(name)] = normalized
        elif isinstance(raw_keywords, list | tuple | set):
            for keyword in raw_keywords:
                normalized = normalize_identity_title(keyword)
                if normalized:
                    keywords[normalized] = (normalized,)
        return cls(
            time_window_hours=_positive_int(values.get("time_window_hours", 24), 24),
            token_jaccard_threshold=_ratio(
                values.get("token_jaccard_threshold", 0.35), 0.35
            ),
            title_similarity_threshold=_ratio(
                values.get("title_similarity_threshold", 0.70), 0.70
            ),
            min_shared_tokens=_positive_int(values.get("min_shared_tokens", 2), 2),
            entity_keywords=keywords,
            algorithm_version=str(values.get("algorithm_version") or "cluster-v1"),
        )


@dataclass(frozen=True)
class ItemSignals:
    item: ContentItem
    title: str
    tokens: frozenset[str]
    tags: frozenset[str]
    entities: frozenset[str]
    cve_ids: frozenset[str]


def _ratio(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _positive_int(value: Any, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def title_tokens(title: str) -> frozenset[str]:
    normalized = normalize_identity_title(title)
    tokens: set[str] = set()
    for is_cjk, chunk in _script_chunks(normalized):
        if not is_cjk:
            tokens.update(token for token in _TOKEN_RE.findall(chunk) if len(token) >= 2)
            continue
        # Bigrams retain useful structure in unspaced CJK headlines. Short
        # chunks also expose individual characters for two-character titles.
        if len(chunk) <= 2:
            tokens.update(chunk)
        else:
            tokens.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return frozenset(tokens)


def extract_entities(
    item: ContentItem,
    keywords: dict[str, tuple[str, ...]] | None = None,
) -> frozenset[str]:
    entities: set[str] = set()
    raw_entities = item.metadata.get("entities", [])
    if isinstance(raw_entities, str):
        raw_entities = [raw_entities]
    if isinstance(raw_entities, list | tuple | set):
        entities.update(
            normalized
            for normalized in (normalize_identity_title(value) for value in raw_entities)
            if normalized
        )
    title = normalize_identity_title(item.title)
    for canonical, aliases in (keywords or {}).items():
        if any(alias and alias in title for alias in aliases):
            entities.add(canonical)
    return frozenset(entities)


def security_cve_ids(item: ContentItem) -> frozenset[str]:
    """Return exact normalized CVE metadata for security-domain strong matching."""
    if item.domain != "security":
        return frozenset()
    raw_values = item.metadata.get("cve_ids", [])
    if isinstance(raw_values, str):
        raw_values = [raw_values]
    if not isinstance(raw_values, list | tuple | set | frozenset):
        return frozenset()
    return frozenset(
        normalized
        for normalized in (str(value).strip().upper() for value in raw_values)
        if _CVE_RE.fullmatch(normalized)
    )


def item_signals(item: ContentItem, config: ClusteringConfig) -> ItemSignals:
    return ItemSignals(
        item=item,
        title=normalize_identity_title(item.title),
        tokens=title_tokens(item.title),
        tags=frozenset(tag.casefold() for tag in normalize_tags(item.tags)),
        entities=extract_entities(item, config.entity_keywords),
        cve_ids=security_cve_ids(item),
    )


def token_jaccard(first: frozenset[str], second: frozenset[str]) -> float:
    union = first | second
    return len(first & second) / len(union) if union else 0.0


def are_related(
    first: ItemSignals,
    second: ItemSignals,
    config: ClusteringConfig,
) -> bool:
    if first.item.domain != second.item.domain:
        return False
    shared_cves = first.cve_ids & second.cve_ids
    if shared_cves:
        if len(first.cve_ids) > 1 or len(second.cve_ids) > 1:
            return first.cve_ids == second.cve_ids
        return True
    if first.cve_ids and second.cve_ids:
        return False
    if abs(event_time(first.item) - event_time(second.item)) > timedelta(
        hours=config.time_window_hours
    ):
        return False

    shared_entities = first.entities & second.entities
    if first.entities and second.entities and not shared_entities:
        return False

    # Exact headlines remain a strong signal even when a CJK headline has only
    # one generated token. Explicit entity conflicts still take precedence.
    if first.title == second.title:
        return True

    # Similarity scores are computed only where they can decide the result.
    has_context_signal = bool(shared_entities or first.tags & second.tags)
    if (
        has_context_signal
        and token_jaccard(first.tokens, second.tokens) >= config.token_jaccard_threshold
    ):
        return True
    if len(first.tokens & second.tokens) < config.min_shared_tokens:
        return False
    # Same decision as ratio() >= threshold; the documented upper bounds skip
    # the quadratic matcher for pairs that cannot reach it.
    threshold = config.title_similarity_threshold
    matcher = SequenceMatcher(None, first.title, second.title)
    return (
        matcher.real_quick_ratio() >= threshold
        and matcher.quick_ratio() >= threshold
        and matcher.ratio() >= threshold
    )


def _find(parents: list[int], index: int) -> int:
    while parents[index] != index:
        parents[index] = parents[parents[index]]
        index = parents[index]
    return index


def _union(parents: list[int], first: int, second: int) -> int:
    first_root = _find(parents, first)
    second_root = _find(parents, second)
    if first_root == second_root:
        return first_root
    if first_root < second_root:
        parents[second_root] = first_root
        return first_root
    else:
        parents[first_root] = second_root
        return second_root


def cluster_items(
    items: list[ContentItem],
    config: ClusteringConfig | Mapping[str, Any] | None = None,
) -> list[Cluster]:
    """Group related items into stable connected components, including singletons."""
    resolved = (
        config if isinstance(config, ClusteringConfig) else ClusteringConfig.from_mapping(config)
    )
    ordered = sorted(items, key=lambda item: (event_time(item), item.id))
    signals = [item_signals(item, resolved) for item in ordered]
    parents = list(range(len(signals)))
    component_entity_sets = [[signal.entities] for signal in signals]
    component_start = [event_time(signal.item) for signal in signals]
    component_end = list(component_start)
    window = timedelta(hours=resolved.time_window_hours)

    for right, candidate in enumerate(signals):
        for left in range(right - 1, -1, -1):
            prior = signals[left]
            outside_window = event_time(candidate.item) - event_time(prior.item) > window
            if outside_window and not candidate.cve_ids:
                break
            if outside_window and not (candidate.cve_ids & prior.cve_ids):
                continue
            if are_related(prior, candidate, resolved):
                left_root = _find(parents, left)
                right_root = _find(parents, right)
                if left_root == right_root:
                    continue
                if any(
                    left_member_entities
                    and right_member_entities
                    and not left_member_entities & right_member_entities
                    for left_member_entities in component_entity_sets[left_root]
                    for right_member_entities in component_entity_sets[right_root]
                ):
                    continue
                combined_start = min(component_start[left_root], component_start[right_root])
                combined_end = max(component_end[left_root], component_end[right_root])
                if (
                    combined_end - combined_start > window
                    and not candidate.cve_ids & prior.cve_ids
                ):
                    continue
                root = _union(parents, left_root, right_root)
                other = right_root if root == left_root else left_root
                component_entity_sets[root].extend(component_entity_sets[other])
                component_entity_sets[other] = []
                component_start[root] = combined_start
                component_end[root] = combined_end

    components: dict[int, list[ItemSignals]] = {}
    for index, signal in enumerate(signals):
        components.setdefault(_find(parents, index), []).append(signal)

    clusters: list[Cluster] = []
    for members in components.values():
        member_ids = [signal.item.id for signal in members]
        times = [event_time(signal.item) for signal in members]
        activity_times = [
            max(event_time(signal.item), signal.item.collected_at) for signal in members
        ]
        tags = normalize_tags(
            sorted(
                {tag for signal in members for tag in signal.item.tags},
                key=lambda value: (str(value).casefold(), str(value)),
            )
        )
        entities = normalize_tags(
            sorted(
                {entity for signal in members for entity in signal.entities},
                key=lambda value: (str(value).casefold(), str(value)),
            )
        )
        signature = "|".join(
            [resolved.algorithm_version, *sorted(member_ids)]
        )
        clusters.append(
            Cluster(
                id=deterministic_cluster_id(
                    member_ids,
                    scope="security" if members[0].item.domain == "security" else "",
                ),
                member_ids=member_ids,
                domain=members[0].item.domain,
                event_time=min(times),
                last_activity_at=max(activity_times),
                tags=tags,
                entities=entities,
                signature=signature,
                metadata={
                    "algorithm_version": resolved.algorithm_version,
                    "time_window_hours": resolved.time_window_hours,
                    "token_jaccard_threshold": resolved.token_jaccard_threshold,
                    "title_similarity_threshold": resolved.title_similarity_threshold,
                },
            )
        )
    return sorted(clusters, key=lambda cluster: (cluster.event_time, cluster.id))


__all__ = [
    "ClusteringConfig",
    "DEFAULT_ENTITY_KEYWORDS",
    "ItemSignals",
    "are_related",
    "cluster_items",
    "extract_entities",
    "item_signals",
    "security_cve_ids",
    "title_tokens",
    "token_jaccard",
]
