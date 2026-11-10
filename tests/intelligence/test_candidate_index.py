"""Candidate pruning must preserve the exhaustive algorithm with bounded memory."""

import random
import tracemalloc
from datetime import datetime, timedelta, timezone

import pytest

from trendradar.core.models import ContentItem
from trendradar.intelligence import clustering
from trendradar.intelligence.clustering import ClusteringConfig, cluster_items, item_signals
from trendradar.intelligence.pipeline import (
    process_content_items,
    process_stories_after_persist_best_effort,
)
from trendradar.intelligence.storage import IntelligenceStorage

NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


def exhaustive_candidates(signals, _config):
    for right in range(len(signals)):
        yield right, range(right - 1, -1, -1)


def item(index, *, hours=0, domain="general", title=None, **kwargs):
    return ContentItem.create(
        title=title or f"common topic number {index}", url=f"https://example.test/{index}",
        source=f"rss:source-{index}", domain=domain,
        published_time=NOW + timedelta(hours=hours), collected_at=NOW + timedelta(hours=hours),
        **kwargs,
    )


@pytest.mark.parametrize("threshold", [0, 0.35, 1])
@pytest.mark.parametrize("minimum", [0, 1, 2])
def test_candidates_match_exhaustive_clusters(monkeypatch, threshold, minimum):
    rng = random.Random(20261110)
    vocabulary = ["alpha", "beta", "gamma", "模型", "安全", "发布", "新闻", "芯片"]
    config = ClusteringConfig(token_jaccard_threshold=threshold, min_shared_tokens=minimum)
    indexed = clustering._candidate_indices
    for batch in range(30):
        items = []
        for index in range(30):
            domain = rng.choice(["general", "ai", "security"])
            metadata = {"entities": rng.choice([[], ["vendor-a"], ["vendor-b"]])}
            if domain == "security":
                metadata["cve_ids"] = rng.choice([
                    [], ["CVE-2026-1001"], ["CVE-2026-1002"],
                    ["CVE-2026-1001", "CVE-2026-1002"],
                ])
            items.append(item(
                batch * 30 + index, domain=domain,
                title=" ".join(rng.choices(vocabulary, k=rng.randint(1, 5))),
                hours=rng.choice([-100, -25, -24, 0, 1, 24, 25, 100]),
                metadata=metadata, tags=rng.choice([[], ["one"], ["two"]]),
            ))
        monkeypatch.setattr(clustering, "_candidate_indices", exhaustive_candidates)
        expected = cluster_items(items, config)
        monkeypatch.setattr(clustering, "_candidate_indices", indexed)
        assert cluster_items(items, config) == expected


def test_expired_normal_candidates_are_removed_but_cves_remain():
    items = [item(0, domain="security", metadata={"cve_ids": ["CVE-2026-1001"]})]
    items.extend(item(i, hours=i * 25) for i in range(1, 4000))
    items.append(item(
        4000, hours=100000, domain="security", metadata={"cve_ids": ["CVE-2026-1001"]},
    ))
    config = ClusteringConfig()
    candidates = list(clustering._candidate_indices([item_signals(i, config) for i in items], config))
    assert all(not left for _, left in candidates[:-1])
    assert candidates[-1] == (4000, [0])


def test_dense_candidates_are_streamed_without_quadratic_memory():
    config = ClusteringConfig()
    signals = [item_signals(item(i), config) for i in range(3000)]
    tracemalloc.start()
    try:
        total = sum(len(left) for _, left in clustering._candidate_indices(signals, config))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert total == 3000 * 2999 // 2
    assert peak < 12 * 1024 * 1024


def test_new_stories_updates_and_restart_match_exhaustive(tmp_path, monkeypatch):
    batches = [
        [item(0, title="Alpha model launch worldwide"), item(1, title="Database maintenance")],
        [item(2, hours=1, title="Alpha model launch worldwide"), item(3, hours=25)],
        [item(4, hours=24, title="Alpha model launch worldwide")],
    ]
    indexed = clustering._candidate_indices
    results = []
    for name, candidates in [("exhaustive", exhaustive_candidates), ("indexed", indexed)]:
        monkeypatch.setattr(clustering, "_candidate_indices", candidates)
        path = tmp_path / f"{name}.db"
        snapshots = []
        for number, batch in enumerate(batches):
            # Reopen between batches to exercise stable persisted identity.
            with IntelligenceStorage(path, story_config={"enabled": True}) as storage:
                dedup = process_content_items(batch, storage=storage)
                result = process_stories_after_persist_best_effort(
                    dedup, storage, save_report=False, now=NOW + timedelta(hours=26),
                )
                assert result.processing_succeeded
                if number == 0:
                    assert result.stories_created > 0
                snapshots.append((result.stories, result.clusters))
        results.append(snapshots)
    assert results[0] == results[1]
    initial = next(s for s in results[1][0][0] if batches[0][0].id in s.member_ids)
    extended = next(s for s in results[1][1][0] if batches[1][0].id in s.member_ids)
    assert initial.id == extended.id
    assert set(extended.member_ids) == {batches[0][0].id, batches[1][0].id}
