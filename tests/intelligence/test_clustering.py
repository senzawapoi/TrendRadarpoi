from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from itertools import combinations

from trendradar.core.models import ContentItem
from trendradar.intelligence import clustering
from trendradar.intelligence.clustering import (
    ClusteringConfig,
    are_related,
    cluster_items,
    item_signals,
)

NOW = datetime(2026, 9, 4, 6, tzinfo=timezone.utc)
CONFIG = ClusteringConfig.from_mapping(
    {
        "entity_keywords": {
            "openai": ["OpenAI"],
            "gpt-5": ["GPT-5", "GPT 5"],
            "anthropic": ["Anthropic"],
        }
    }
)


def _item(title, source, *, hours=0, tags=None, entities=None):
    return ContentItem.create(
        title=title,
        url=f"https://{source.replace(':', '-')}.example/{abs(hash(title))}",
        source=source,
        domain="ai",
        published_time=NOW + timedelta(hours=hours),
        collected_at=NOW + timedelta(hours=hours),
        tags=tags or [],
        metadata={"entities": entities or []},
    )


def _security_item(title, source, cve_ids, *, hours=0):
    return ContentItem.create(
        title=title,
        url=f"https://{source.replace(':', '-')}.example/{hours}/{cve_ids[0]}",
        source=source,
        domain="security",
        published_time=NOW + timedelta(hours=hours),
        collected_at=NOW + timedelta(hours=hours),
        tags=cve_ids,
        metadata={"cve_ids": cve_ids, "entities": cve_ids},
    )


def test_related_cross_source_items_cluster_and_order_is_stable():
    first = _item("OpenAI launches the new GPT-5 model", "rss:one")
    second = _item("OpenAI launches GPT 5 model worldwide", "ai_frontier:blog", hours=1)

    forward = cluster_items([first, second], CONFIG)
    reverse = cluster_items([second, first], CONFIG)

    assert len(forward) == 1
    assert forward == reverse
    assert forward[0].member_ids == sorted([first.id, second.id])
    assert forward[0].entities == ["gpt-5", "openai"]


def test_conflicting_entities_do_not_merge_similar_titles():
    first = _item(
        "Company releases a new flagship reasoning model",
        "rss:one",
        entities=["OpenAI"],
    )
    second = _item(
        "Company releases a new flagship reasoning model",
        "rss:two",
        entities=["Anthropic"],
    )

    assert len(cluster_items([first, second], CONFIG)) == 2


def test_tags_contribute_but_time_window_and_singletons_are_preserved():
    first = _item(
        "Open source agents improve coding workflows",
        "rss:one",
        tags=["agents"],
    )
    related = _item(
        "Open source agents improve coding tools",
        "rss:two",
        hours=2,
        tags=["agents"],
    )
    old = _item(
        "Open source agents improve coding workflows",
        "rss:three",
        hours=30,
        tags=["agents"],
    )
    unrelated = _item("Database maintenance window", "rss:four", hours=1)

    clusters = cluster_items([unrelated, old, related, first], CONFIG)

    assert sorted(len(cluster.member_ids) for cluster in clusters) == [1, 1, 2]
    assert any(cluster.member_ids == [unrelated.id] for cluster in clusters)


def test_transitive_match_cannot_bridge_conflicting_entities():
    openai = _item(
        "Company launches a flagship reasoning model",
        "rss:openai",
        entities=["OpenAI"],
    )
    bridge = _item(
        "Company launches flagship reasoning model",
        "rss:bridge",
        hours=1,
    )
    anthropic = _item(
        "Company launches a flagship reasoning model",
        "rss:anthropic",
        hours=2,
        entities=["Anthropic"],
    )

    clusters = cluster_items([anthropic, bridge, openai], CONFIG)

    assert sorted(len(cluster.member_ids) for cluster in clusters) == [1, 2]
    assert not any(
        openai.id in cluster.member_ids and anthropic.id in cluster.member_ids
        for cluster in clusters
    )


def test_transitive_match_cannot_extend_component_past_time_window():
    first = _item("Open source agent improves coding workflow", "rss:first")
    middle = _item(
        "Open source agent improves coding workflows",
        "rss:middle",
        hours=15,
    )
    last = _item(
        "Open source agent improves coding workflow",
        "rss:last",
        hours=30,
    )

    clusters = cluster_items([last, middle, first], CONFIG)

    assert sorted(len(cluster.member_ids) for cluster in clusters) == [1, 2]
    assert not any(
        first.id in cluster.member_ids and last.id in cluster.member_ids
        for cluster in clusters
    )


def test_title_similarity_is_computed_only_when_shared_tokens_allow_a_match(monkeypatch):
    built = []

    class RecordingMatcher(SequenceMatcher):
        def __init__(self, *args, **kwargs):
            built.append(args)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(clustering, "SequenceMatcher", RecordingMatcher)
    unrelated = [_item("Database maintenance window", "rss:one"),
                 _item("Quarterly earnings beat forecasts", "rss:two", hours=1)]
    related = [_item("Open source agents improve coding workflows", "rss:three"),
               _item("Open source agents improve coding tools", "rss:four", hours=2)]

    assert len(cluster_items(unrelated, CONFIG)) == 2
    assert built == []
    assert len(cluster_items(related, CONFIG)) == 1
    assert len(built) == 1


def test_lazy_title_similarity_matches_eager_decision():
    titles = ["OpenAI launches the new GPT-5 model", "OpenAI launches GPT 5 model worldwide",
              "Open source agents improve coding workflows", "Open source agents improve tools",
              "Database maintenance window", "Database maintenance window tonight",
              "Company launches a flagship reasoning model", "数据库维护窗口今晚开始",
              "数据库维护窗口明晚开始", "Quarterly earnings beat forecasts"]
    items = [_item(title, f"rss:{index}", hours=index % 3, tags=["agents"] if index % 2 else [])
             for index, title in enumerate(titles)]
    signals = [item_signals(item, CONFIG) for item in items]

    def eager(first, second):
        if (first.cve_ids or second.cve_ids
                or (first.entities and second.entities and not first.entities & second.entities)
                or first.title == second.title):
            return are_related(first, second, CONFIG)
        shared = first.tokens & second.tokens
        if (first.entities & second.entities or first.tags & second.tags) and (
                clustering.token_jaccard(first.tokens, second.tokens)
                >= CONFIG.token_jaccard_threshold):
            return True
        ratio = SequenceMatcher(None, first.title, second.title).ratio()
        return len(shared) >= CONFIG.min_shared_tokens and ratio >= CONFIG.title_similarity_threshold

    for first, second in combinations(signals, 2):
        assert are_related(first, second, CONFIG) == eager(first, second), (
            first.title, second.title)


def test_malformed_clustering_config_uses_defaults():
    config = ClusteringConfig.from_mapping("invalid")  # type: ignore[arg-type]
    partial = ClusteringConfig.from_mapping(
        {"time_window_hours": "bad", "min_shared_tokens": object()}
    )

    assert config == ClusteringConfig()
    assert partial.time_window_hours == 24
    assert partial.min_shared_tokens == 2


def test_exact_cve_clusters_security_evidence_across_sources_and_time_windows():
    official = _security_item(
        "NVD record for remote execution",
        "security:nvd",
        ["CVE-2026-12345"],
    )
    news = _security_item(
        "Vendor confirms active exploitation",
        "security:rss:cisa",
        ["CVE-2026-12345"],
        hours=24 * 45,
    )

    clusters = cluster_items([news, official], CONFIG)

    assert len(clusters) == 1
    assert clusters[0].member_ids == sorted([official.id, news.id])


def test_different_explicit_cves_do_not_merge_similar_security_headlines():
    first = _security_item(
        "Critical remote execution in Example Server",
        "security:nvd",
        ["CVE-2026-10001"],
    )
    second = _security_item(
        "Critical remote execution in Example Server",
        "security:rss:cisa",
        ["CVE-2026-10002"],
        hours=1,
    )

    assert len(cluster_items([first, second], CONFIG)) == 2


def test_multi_cve_record_cannot_bridge_distinct_vulnerability_stories():
    first = _security_item(
        "Example Server vulnerability A",
        "security:nvd",
        ["CVE-2026-10001"],
    )
    bridge = _security_item(
        "Example Server combined advisory",
        "security:rss:vendor",
        ["CVE-2026-10001", "CVE-2026-10002"],
        hours=1,
    )
    second = _security_item(
        "Example Server vulnerability B",
        "security:nvd",
        ["CVE-2026-10002"],
        hours=2,
    )

    clusters = cluster_items([first, bridge, second], CONFIG)

    assert len(clusters) == 3
    assert {tuple(cluster.member_ids) for cluster in clusters} == {
        (first.id,),
        (bridge.id,),
        (second.id,),
    }
