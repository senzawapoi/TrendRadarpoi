"""RedditSource 测试（离线解析）"""

from __future__ import annotations

from trendradar.ai_frontier.sources.reddit import RedditSource


def _make_sample(score_high=120, score_low=5):
    return {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "Amazing LLM Paper",
                        "score": score_high,
                        "permalink": "/r/MachineLearning/comments/abc/amazing/",
                        "url_overridden_by_dest": "https://arxiv.org/abs/1234",
                        "url": "https://arxiv.org/abs/1234",
                        "is_self": False,
                        "created_utc": 1713350000.0,
                        "selftext": "",
                        "author": "alice",
                        "link_flair_text": "Research",
                    }
                },
                {
                    "data": {
                        "title": "Low-score question",
                        "score": score_low,
                        "permalink": "/r/MachineLearning/comments/def/low/",
                        "url": "https://www.reddit.com/r/MachineLearning/comments/def/low/",
                        "is_self": True,
                        "created_utc": 1713350001.0,
                        "selftext": "Help me",
                        "author": "bob",
                        "link_flair_text": "",
                    }
                },
            ]
        }
    }


def test_parse_sub_filters_by_min_score():
    src = RedditSource({"min_score": 30})
    items = src._parse_sub("MachineLearning", _make_sample(score_high=120, score_low=5))
    assert len(items) == 1
    assert items[0].score == 120
    assert items[0].source_name == "r/MachineLearning"


def test_parse_sub_respects_min_score_config():
    src = RedditSource({"min_score": 0})
    items = src._parse_sub("MachineLearning", _make_sample(score_high=120, score_low=5))
    assert len(items) == 2


def test_self_post_uses_permalink():
    src = RedditSource({"min_score": 0})
    sample = _make_sample()
    # Second entry is is_self=True
    items = src._parse_sub("MachineLearning", sample)
    self_item = next(i for i in items if "def" in i.url)
    assert self_item.url.startswith("https://www.reddit.com/r/")


def test_external_url_preferred_for_link_posts():
    src = RedditSource({"min_score": 0})
    items = src._parse_sub("MachineLearning", _make_sample())
    link_item = next(i for i in items if "arxiv" in i.url)
    assert link_item.url == "https://arxiv.org/abs/1234"


def test_tags_from_flair():
    src = RedditSource({"min_score": 0})
    items = src._parse_sub("MachineLearning", _make_sample())
    research = next(i for i in items if i.score == 120)
    assert research.tags == ["Research"]


def test_parse_sub_empty_data():
    src = RedditSource({})
    assert src._parse_sub("x", {}) == []
    assert src._parse_sub("x", {"data": {"children": []}}) == []
