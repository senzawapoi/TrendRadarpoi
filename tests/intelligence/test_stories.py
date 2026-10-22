from datetime import datetime, timedelta, timezone

from trendradar.core.models import ContentItem
from trendradar.intelligence.clustering import ClusteringConfig, cluster_items
from trendradar.intelligence.pipeline import (
    process_content_items,
    process_stories_after_persist_best_effort,
)
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.intelligence.stories import StoryService
from trendradar.intelligence.story_generator import generate_story

NOW = datetime(2026, 9, 4, 6, tzinfo=timezone.utc)
CONFIG = ClusteringConfig.from_mapping(
    {"entity_keywords": {"openai": ["OpenAI"], "gpt-5": ["GPT-5", "GPT 5"]}}
)


def _item(title: str, source: str, hours: int = 0) -> ContentItem:
    return ContentItem.create(
        title=title,
        content=f"Details: {title}",
        url=f"https://example.com/{source.replace(':', '-')}/{hours}",
        source=source,
        domain="ai",
        published_time=NOW + timedelta(hours=hours),
        collected_at=NOW + timedelta(hours=hours),
        metadata={"source_content_id": f"{source}-{hours}"},
    )


def _security_item(title: str, source: str, cve_id: str, hours: int = 0) -> ContentItem:
    return ContentItem.create(
        title=title,
        content=f"Details: {title}",
        url=f"https://example.com/{source.replace(':', '-')}/{hours}/{cve_id}",
        source=source,
        domain="security",
        published_time=NOW + timedelta(hours=hours),
        collected_at=NOW + timedelta(hours=hours),
        tags=[cve_id],
        metadata={
            "source_content_id": f"{source}-{hours}",
            "cve_ids": [cve_id],
            "entities": [cve_id],
        },
    )


def test_story_service_is_idempotent_and_input_order_independent(tmp_path):
    first = _item("OpenAI launches the new GPT-5 model", "rss:first")
    second = _item("OpenAI launches GPT 5 model worldwide", "ai_frontier:blog", 1)

    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        storage.write_batch([first, second])
        service = StoryService(storage, clustering_config=CONFIG)
        forward = service.process([first, second])
        reverse = service.process([second, first])

        assert len(forward.stories) == 1
        assert forward.stories == reverse.stories
        assert forward.stories_created == 1
        assert reverse.stories_created == 0
        assert reverse.memberships_created == 0
        assert storage.count("stories") == 1
        assert storage.count("story_members") == 2


def test_later_source_extends_existing_story_without_changing_id(tmp_path):
    first = _item("OpenAI launches the new GPT-5 model", "rss:first")
    second = _item("OpenAI launches GPT 5 model worldwide", "ai_frontier:blog", 1)

    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        storage.write_batch([first])
        service = StoryService(storage, clustering_config=CONFIG)
        initial = service.process([first]).stories[0]

        storage.write_batch([second])
        updated = service.process([second]).stories[0]

        assert updated.id == initial.id
        assert updated.identity_key == initial.identity_key
        assert updated.member_ids == sorted([first.id, second.id])
        assert storage.count("stories") == 1
        assert storage.count("story_members") == 2


def test_unmatched_item_forms_single_story(tmp_path):
    item = _item("Independent database maintenance window", "rss:first")
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        storage.write_batch([item])
        result = StoryService(storage, clustering_config=CONFIG).process([item])
        assert len(result.stories) == 1
        assert result.stories[0].member_ids == [item.id]


def test_ambiguous_existing_story_overlap_is_never_merged(tmp_path):
    first = _item("OpenAI launches the new GPT-5 model", "rss:first")
    second = _item("OpenAI launches GPT 5 model worldwide", "rss:second", 1)
    later = _item("OpenAI launches the GPT-5 model globally", "rss:later", 2)
    singleton_clusters = [cluster_items([item], CONFIG)[0] for item in (first, second)]
    existing = [
        generate_story(cluster, [item])
        for cluster, item in zip(singleton_clusters, (first, second), strict=True)
    ]

    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        storage.write_batch([first, second, later])
        storage.upsert_story_batch(singleton_clusters, existing)

        result = StoryService(storage, clustering_config=CONFIG).process([later])

        assert {story.id for story in existing} <= {story.id for story in result.stories}
        assert any(story.member_ids == [later.id] for story in result.stories)
        assert storage.count("stories") == 3
        assert storage.count("story_members") == 3


def test_separate_same_day_events_get_distinct_story_identities(tmp_path):
    config = ClusteringConfig.from_mapping(
        {
            "time_window_hours": 1,
            "entity_keywords": {"openai": ["OpenAI"], "gpt-5": ["GPT-5", "GPT 5"]},
        }
    )
    first = _item("OpenAI launches the new GPT-5 model", "rss:first")
    second = _item("OpenAI launches the new GPT-5 model", "rss:second", 2)

    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        storage.write_batch([first, second])
        result = StoryService(storage, clustering_config=config).process([first, second])

        assert len(result.stories) == 2
        assert len({story.id for story in result.stories}) == 2
        assert len({story.identity_key for story in result.stories}) == 2
        assert storage.count("stories") == 2


def test_later_same_cve_evidence_extends_story_across_time_without_changing_id(tmp_path):
    official = _security_item(
        "NVD publishes a remote execution vulnerability",
        "security:nvd",
        "CVE-2026-12345",
    )
    later = _security_item(
        "CISA adds the vulnerability to KEV",
        "security:rss:cisa",
        "CVE-2026-12345",
        24 * 45,
    )

    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        storage.write_batch([official])
        service = StoryService(storage, clustering_config=CONFIG)
        initial = service.process([official]).stories[0]

        storage.write_batch([later])
        updated = service.process([later]).stories[0]

        assert initial.identity_key == "security:cve:cve-2026-12345"
        assert updated.id == initial.id
        assert updated.identity_key == initial.identity_key
        assert updated.member_ids == sorted([official.id, later.id])
        assert storage.count("stories") == 1
        assert storage.count("story_members") == 2


def test_security_story_can_share_general_canonical_member_without_domain_collision(tmp_path):
    url = "https://nvd.nist.gov/vuln/detail/CVE-2026-12345"
    general = ContentItem.create(
        title="Vendor publishes an advisory",
        content="General feed evidence",
        url=url,
        source="rss:vendor",
        domain="general",
        published_time=NOW,
        collected_at=NOW,
        metadata={"source_content_id": "vendor-advisory"},
    )
    security = ContentItem.create(
        title="CVE-2026-12345: remote execution",
        content="NVD security evidence",
        url=url,
        source="security:nvd",
        domain="security",
        published_time=NOW,
        collected_at=NOW + timedelta(hours=1),
        tags=["CVE-2026-12345"],
        metadata={
            "source_content_id": "CVE-2026-12345",
            "source_name": "NVD",
            "cve_ids": ["CVE-2026-12345"],
            "entities": ["CVE-2026-12345"],
        },
    )
    story_config = {"enabled": True, "report": {"enabled": False}}

    with IntelligenceStorage(
        tmp_path / "intelligence.db",
        story_config=story_config,
    ) as storage:
        storage.write_batch([general])
        StoryService(storage, clustering_config=CONFIG).process([general])
        deduplicated = process_content_items([security], storage=storage)
        derived = process_stories_after_persist_best_effort(
            deduplicated,
            storage,
            save_report=False,
            now=NOW + timedelta(hours=1),
            story_content_ids={general.id},
            story_domain="security",
        )

        stories = storage.list_stories()
        security_story = next(story for story in stories if story.domain == "security")
        security_items = storage.list_story_items(security_story.id)

        assert deduplicated.canonical_ids == [general.id]
        assert derived.processing_succeeded is True
        assert {story.domain for story in stories} == {"general", "security"}
        assert storage.count("clusters") == 2
        assert storage.count("story_members") == 2
        assert security_story.identity_key == "security:cve:cve-2026-12345"
        assert security_story.member_ids == [general.id]
        assert security_items[0].domain == "security"
        assert security_items[0].metadata["cve_ids"] == ["CVE-2026-12345"]
