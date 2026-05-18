"""detector 测试"""

from __future__ import annotations

from trendradar.ai_frontier.detector import filter_new_for_push, group_by_source
from trendradar.ai_frontier.sources.base import AIItem


def _item(source, score=0, url=None):
    return AIItem(
        source=source,
        source_name=source,
        title=f"{source}-{score}",
        url=url or f"https://{source}/{score}",
        score=score,
    )


def test_filter_applies_source_specific_thresholds():
    items = [
        _item("hackernews", score=40),
        _item("hackernews", score=80),
        _item("reddit", score=10),
        _item("reddit", score=50),
        _item("github", score=50),
        _item("github", score=200),
        _item("arxiv", score=0),  # 无阈值，应保留
    ]
    cfg = {
        "min_score_hackernews": 50,
        "min_score_reddit": 30,
        "min_stars_github": 100,
    }
    out = filter_new_for_push(items, cfg)
    urls = {i.url for i in out}
    assert "https://hackernews/80" in urls
    assert "https://hackernews/40" not in urls
    assert "https://reddit/50" in urls
    assert "https://reddit/10" not in urls
    assert "https://github/200" in urls
    assert "https://github/50" not in urls
    assert "https://arxiv/0" in urls


def test_filter_sorts_by_score_descending():
    items = [_item("hackernews", score=60), _item("hackernews", score=120), _item("hackernews", score=90)]
    cfg = {"min_score_hackernews": 50}
    out = filter_new_for_push(items, cfg)
    assert [i.score for i in out] == [120, 90, 60]


def test_filter_truncates_to_max_items():
    items = [_item("arxiv", score=i) for i in range(50)]
    cfg = {"max_items_per_push": 10}
    out = filter_new_for_push(items, cfg)
    assert len(out) == 10


def test_filter_empty_returns_empty():
    assert filter_new_for_push([], {}) == []


def test_group_by_source_preserves_order():
    items = [
        _item("x", score=10),
        _item("blog", score=0),
        _item("arxiv", score=5),
        _item("podcast", score=0),
        _item("hackernews", score=100),
    ]
    groups = group_by_source(items)
    keys = list(groups.keys())
    # arxiv 在前，podcast/blog 在 x 之后（固定顺序）
    assert keys.index("arxiv") < keys.index("hackernews") < keys.index("x")
    assert keys.index("x") < keys.index("podcast") < keys.index("blog")


def test_group_by_source_skips_empty_buckets():
    items = [_item("arxiv", score=5)]
    groups = group_by_source(items)
    assert list(groups.keys()) == ["arxiv"]
