"""Incremental Story derivation over persisted canonical content."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta, timezone

from trendradar.core.models import (
    Cluster,
    ContentItem,
    Story,
    normalize_identity_title,
    normalize_tags,
)
from trendradar.intelligence.clustering import (
    ClusteringConfig,
    cluster_items,
    security_cve_ids,
    title_tokens,
)
from trendradar.intelligence.deduplicate import event_time
from trendradar.intelligence.storage import IntelligenceStorage

StoryGenerator = Callable[[Cluster, list[ContentItem]], Story]


@dataclass(frozen=True)
class StoryBatchResult:
    stories: list[Story]
    clusters: list[Cluster] = field(default_factory=list)
    clusters_created: int = 0
    stories_created: int = 0
    memberships_created: int = 0
    processing_succeeded: bool = True


def story_identity_key(cluster: Cluster, items: list[ContentItem]) -> str:
    """Build a logical key that does not contain the current member-set UUID.

    Entity/tag anchors are stable when a second source arrives. Title-only
    stories include an hourly event bucket to avoid collapsing clearly separate
    same-day events with identical headlines; an existing Story ID is always
    retained when a later item joins it.
    """
    if not items:
        raise ValueError("at least one item is required for Story identity")
    cve_ids = sorted({cve_id for item in items for cve_id in security_cve_ids(item)})
    if cluster.domain == "security" and cve_ids:
        return f"security:cve:{','.join(cve_ids)}"
    common_tokens = set(title_tokens(items[0].title))
    for item in items[1:]:
        common_tokens &= set(title_tokens(item.title))
    if not common_tokens:
        representative = min(items, key=lambda item: (event_time(item), item.id))
        common_tokens = set(title_tokens(representative.title))
    topic = " ".join(sorted(common_tokens))
    date_key = cluster.event_time.astimezone(timezone.utc).date().isoformat()
    entities = ",".join(sorted(entity.casefold() for entity in cluster.entities))
    tags = ",".join(sorted(tag.casefold() for tag in cluster.tags))
    representative = min(items, key=lambda item: (event_time(item), item.id))
    topic = topic or normalize_identity_title(representative.title)
    bucket = event_time(representative).astimezone(timezone.utc).strftime("%H")
    if cluster.entities:
        anchor = f"entities:{entities}"
        if tags:
            anchor += f":tags:{tags}"
    elif cluster.tags:
        anchor = f"tags:{tags}"
    else:
        anchor = "title"
    anchor += f":topic:{topic}:hour:{bucket}"
    return f"{cluster.domain}:{date_key}:{anchor}"


class StoryService:
    """Derive and atomically persist stable Stories without fetching upstream data."""

    def __init__(
        self,
        storage: IntelligenceStorage,
        *,
        clustering_config: ClusteringConfig | Mapping[str, object] | None = None,
        generator: StoryGenerator | None = None,
        wording_client: object | None = None,
    ) -> None:
        self.storage = storage
        self.clustering_config = (
            clustering_config
            if isinstance(clustering_config, ClusteringConfig)
            else ClusteringConfig.from_mapping(clustering_config)
        )
        self.wording_client = wording_client
        self._uses_default_generator = generator is None
        if generator is None:
            from trendradar.intelligence.story_generator import generate_story

            generator = generate_story
        self.generator = generator

    def process(
        self,
        items: list[ContentItem],
        *,
        persist: bool = True,
    ) -> StoryBatchResult:
        from trendradar.intelligence.translation import title_translation_pending

        items = [item for item in items if not title_translation_pending(item)]
        if not items:
            return StoryBatchResult(stories=[])
        incoming_ids = {item.id for item in items}
        context_items = self._context_items(items)
        items_by_id = {item.id: item for item in context_items}
        clusters = cluster_items(context_items, self.clustering_config)
        clusters_to_persist: dict[str, Cluster] = {}
        stories_by_id: dict[str, Story] = {}

        for cluster in clusters:
            if not incoming_ids.intersection(cluster.member_ids):
                continue
            cluster_items_list = [items_by_id[item_id] for item_id in cluster.member_ids]
            existing_ids = self.storage.story_ids_for_members(
                cluster.member_ids,
                domain=cluster.domain,
            )
            if len(existing_ids) > 1:
                for existing in self._preserve_ambiguous(existing_ids):
                    stories_by_id[existing.id] = existing
                known_members = {
                    member_id
                    for story in stories_by_id.values()
                    for member_id in story.member_ids
                }
                self._add_new_item_stories(
                    [item for item in cluster_items_list if item.id not in known_members],
                    clusters_to_persist,
                    stories_by_id,
                )
                continue

            existing = self.storage.get_story(next(iter(existing_ids))) if existing_ids else None
            if existing is not None:
                existing_items = self.storage.list_story_items(existing.id)
                if self._can_extend(existing_items, cluster_items_list):
                    combined_items = self._unique_items([*existing_items, *cluster_items_list])
                    combined_cluster = self._cluster_for_items(combined_items)
                    generated = self._generate(combined_cluster, combined_items)
                    generated.id = existing.id
                    generated.identity_key = existing.identity_key
                    generated.member_ids = sorted(
                        set(existing.member_ids) | set(generated.member_ids)
                    )
                    generated.event_time = min(existing.event_time, generated.event_time)
                    generated.last_activity_at = max(
                        existing.last_activity_at, generated.last_activity_at
                    )
                    generated.tags = normalize_tags([*existing.tags, *generated.tags])
                    generated.entities = normalize_tags([*existing.entities, *generated.entities])
                    clusters_to_persist[combined_cluster.id] = combined_cluster
                    stories_by_id[generated.id] = generated
                else:
                    stories_by_id[existing.id] = existing
                    new_items = [
                        item for item in cluster_items_list if item.id not in existing.member_ids
                    ]
                    self._add_new_item_stories(
                        new_items,
                        clusters_to_persist,
                        stories_by_id,
                    )
                continue

            generated = self._generate(cluster, cluster_items_list)
            self._ensure_unique_identity(generated, stories_by_id)
            clusters_to_persist[cluster.id] = cluster
            stories_by_id[generated.id] = generated

        stories = sorted(stories_by_id.values(), key=lambda story: (story.event_time, story.id))
        derived_clusters = sorted(
            clusters_to_persist.values(), key=lambda cluster: (cluster.event_time, cluster.id)
        )
        if not persist:
            return StoryBatchResult(stories=stories, clusters=derived_clusters)
        cluster_count, story_count, member_count = self.storage.upsert_story_batch(
            derived_clusters, stories
        )
        return StoryBatchResult(
            stories=stories,
            clusters=derived_clusters,
            clusters_created=cluster_count,
            stories_created=story_count,
            memberships_created=member_count,
        )

    def _context_items(self, items: list[ContentItem]) -> list[ContentItem]:
        from trendradar.intelligence.translation import title_translation_pending

        by_id = {item.id: item for item in items}
        window = timedelta(hours=self.clustering_config.time_window_hours)
        for domain in sorted({item.domain for item in items}):
            domain_items = [item for item in items if item.domain == domain]
            start = min(event_time(item) for item in domain_items) - window
            end = max(event_time(item) for item in domain_items) + window
            for stored in self.storage.list_items_in_window(domain, start, end):
                by_id[stored.id] = stored
        cve_ids = {cve_id for item in items for cve_id in security_cve_ids(item)}
        for stored in self.storage.list_security_items_by_cves(cve_ids):
            by_id[stored.id] = stored
        return sorted(
            (item for item in by_id.values() if not title_translation_pending(item)),
            key=lambda item: (event_time(item), item.id),
        )

    def _generate(self, cluster: Cluster, items: list[ContentItem]) -> Story:
        self._add_observation_context(cluster)
        if self._uses_default_generator:
            return self.generator(  # type: ignore[operator]
                cluster,
                items,
                wording_client=self.wording_client,
            )
        return self.generator(cluster, items)  # type: ignore[misc]

    def _add_observation_context(self, cluster: Cluster) -> None:
        sources: set[str] = set()
        source_names: set[str] = set()
        for member_id in cluster.member_ids:
            for row in self.storage.list_observations(member_id):
                sources.add(str(row["source"]))
                try:
                    metadata = json.loads(row["metadata_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    metadata = {}
                if isinstance(metadata, Mapping):
                    source_names.add(str(metadata.get("source_name") or row["source"]))
        if sources:
            cluster.metadata["observation_sources"] = sorted(sources)
        if source_names:
            cluster.metadata["observation_source_names"] = sorted(
                source_names,
                key=str.casefold,
            )

    def _cluster_for_items(self, items: list[ContentItem]) -> Cluster:
        clusters = cluster_items(items, self.clustering_config)
        if len(clusters) != 1 or set(clusters[0].member_ids) != {item.id for item in items}:
            raise ValueError("Story members do not form one compatible cluster")
        return clusters[0]

    def _can_extend(
        self,
        existing_items: list[ContentItem],
        candidate_items: list[ContentItem],
    ) -> bool:
        combined = self._unique_items([*existing_items, *candidate_items])
        if not combined or len({item.domain for item in combined}) != 1:
            return False
        try:
            self._cluster_for_items(combined)
        except ValueError:
            return False
        return True

    def _add_new_item_stories(
        self,
        items: list[ContentItem],
        clusters_to_persist: dict[str, Cluster],
        stories_by_id: dict[str, Story],
    ) -> None:
        if not items:
            return
        for cluster in cluster_items(items, self.clustering_config):
            cluster_items_list = [
                item for item in items if item.id in set(cluster.member_ids)
            ]
            generated = self._generate(cluster, cluster_items_list)
            self._ensure_unique_identity(generated, stories_by_id)
            clusters_to_persist[cluster.id] = cluster
            stories_by_id[generated.id] = generated

    def _ensure_unique_identity(self, story: Story, stories_by_id: dict[str, Story]) -> None:
        identity_key = story.identity_key
        existing = self.storage.get_story_by_identity_key(identity_key)
        if existing is None and not any(
            candidate.identity_key == identity_key for candidate in stories_by_id.values()
        ):
            return
        suffix = ":event:" + story.event_time.astimezone(timezone.utc).isoformat()
        suffix += ":members:" + ",".join(story.member_ids)
        candidate_key = identity_key + suffix
        story.identity_key = candidate_key
        from trendradar.core.models.story import deterministic_story_id

        story.id = deterministic_story_id(candidate_key)
        while story.id in stories_by_id:
            candidate_key += ":duplicate"
            story.identity_key = candidate_key
            story.id = deterministic_story_id(candidate_key)

    @staticmethod
    def _unique_items(items: list[ContentItem]) -> list[ContentItem]:
        return sorted(
            {item.id: item for item in items}.values(),
            key=lambda item: (event_time(item), item.id),
        )

    def _preserve_ambiguous(
        self,
        story_ids: set[str],
    ) -> list[Story]:
        preserved: list[Story] = []
        for story_id in sorted(story_ids):
            existing = self.storage.get_story(story_id)
            if existing is not None:
                preserved.append(existing)
        return preserved

__all__ = ["StoryBatchResult", "StoryGenerator", "StoryService", "story_identity_key"]
