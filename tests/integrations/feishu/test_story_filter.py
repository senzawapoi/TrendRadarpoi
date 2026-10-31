"""Reader-interest filter for instant Lark delivery and bounded per-run catch-up."""

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from trendradar.core.models import ContentItem, Story, deterministic_story_id
from trendradar.integrations.feishu.__main__ import drain_ticks
from trendradar.integrations.feishu.config import FeishuConfig
from trendradar.integrations.feishu.delivery import StoryDelivery
from trendradar.integrations.feishu.scheduler import DeliveryScheduler
from trendradar.integrations.feishu.story_filter import StoryInterestFilter
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops.health import _instant_health

NOW = datetime(2026, 10, 31, 4, tzinfo=timezone.utc)
FILTER = StoryInterestFilter(enabled=True)
CONFIG = FeishuConfig(
    enabled=True, delivery_enabled=True, delivery_mode="instant", delivery_target="chat",
    delivery_filter=FILTER,
)


def seed(storage, title, *, source="newsnow:jin10", domain="general", index=0, original=None):
    item = ContentItem.create(
        title=original or title, content="evidence", source=source,
        url=f"https://example.test/{index}", domain=domain,
        collected_at=NOW - timedelta(minutes=10),
    )
    storage.write_batch([item])
    story = Story(
        id=deterministic_story_id(item.id), identity_key=item.id, title=title,
        summary="", domain=domain, member_ids=[item.id],
        event_time=item.collected_at, last_activity_at=item.collected_at,
    )
    storage.upsert_story_batch([], [story])
    storage.connection.execute(
        "UPDATE stories SET created_at=? WHERE id=?",
        ((NOW - timedelta(seconds=1000 - index)).isoformat(), story.id),
    )
    return story


def scheduler(storage, client, config=CONFIG):
    return DeliveryScheduler(
        config, storage.db_path, StoryDelivery(storage), client, storage=storage,
        clock=lambda: NOW,
    )


def sent_titles(client):
    titles = []
    for call in client.send.call_args_list:
        body = json.loads(call.args[1].split("\n", 1)[1])["zh_cn"]["content"]
        titles += [cell["text"] for row in body for cell in row if cell["tag"] == "a"]
    return titles


def test_decide_matches_domain_source_and_bounded_keywords():
    decide = FILTER.decide
    assert decide(domain="ai", sources=["ai_frontier:arxiv"], texts=["x"]) == "domain:ai"
    assert decide(domain="general", sources=["rss:TechCrunch AI"], texts=["x"]).startswith(
        "source:"
    )
    # CJK characters are word characters for \b; ASCII terms still match next to them.
    assert decide(domain="general", sources=[], texts=["国产AI芯片发布"]) == "keyword:AI"
    assert decide(domain="general", sources=[], texts=["He SAID the MAIL was late"]) is None
    assert decide(domain="general", sources=[], texts=["英伟达发布新显卡"]) == "keyword:英伟达"
    assert decide(domain="general", sources=[], texts=["Gold rises on Fed bets"]) is None
    excluded = replace(FILTER, exclude_sources=("newsnow:jin10",))
    assert excluded.decide(domain="ai", sources=["newsnow:jin10"], texts=["AI"]) is None
    assert StoryInterestFilter().decide(domain="general", sources=[], texts=[]) == (
        "filter_disabled"
    )


def test_from_mapping_accepts_yaml_lists_csv_and_string_switches():
    parsed = StoryInterestFilter.from_mapping({
        "enabled": "true", "domains": ["AI"], "sources": "rss:a, rss:b",
        "keywords": ["芯片", " ", "芯片"],
    })
    assert parsed.enabled is True
    assert parsed.domains == ("ai",)
    assert parsed.sources == ("rss:a", "rss:b")
    assert parsed.keywords == ("芯片",)
    assert StoryInterestFilter.from_mapping(None).enabled is False
    config = FeishuConfig.from_mapping(
        {"delivery_filter": {"enabled": True}, "delivery_max_batches_per_tick": 99}
    )
    assert config.delivery_filter.enabled is True
    assert config.delivery_max_batches_per_tick == 10


def test_only_matching_stories_are_sent_and_held_back_ones_are_never_backlog(tmp_path):
    client = Mock(send=Mock(return_value=True))
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        seed(storage, "黄金价格上涨", index=0)
        seed(storage, "OpenAI 发布新模型", index=1)
        seed(storage, "美元指数走弱", index=2)
        # Original English title matches even when the canonical title does not.
        seed(storage, "某公司发布新品", source="rss:hacker-news", index=3,
             original="Nvidia ships a new GPU")
        assert scheduler(storage, client).tick() == "sent"
        assert sent_titles(client) == ["OpenAI 发布新模型", "某公司发布新品"]
        rows = storage.connection.execute(
            "SELECT s.title, d.delivery_key IS NULL AS held FROM lark_story_deliveries d "
            "JOIN stories s ON s.id=d.story_id ORDER BY s.created_at"
        ).fetchall()
        assert [(row["title"], row["held"]) for row in rows] == [
            ("黄金价格上涨", 1), ("OpenAI 发布新模型", 0), ("美元指数走弱", 1), ("某公司发布新品", 0),
        ]
        assert scheduler(storage, client).tick() == "empty"
        assert client.send.call_count == 1
        health = _instant_health(storage.connection, "chat", None)
        assert health["backlog"] == 0
        assert health["unregistered_stories"] == 0
        assert health["held_back_stories_24h"] == 2


def test_long_held_back_prefix_does_not_starve_a_later_match(tmp_path):
    client = Mock(send=Mock(return_value=True))
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        for index in range(250):  # more than one 200-row scan page
            seed(storage, f"大宗商品快讯 {index}", index=index)
        seed(storage, "DeepSeek 开源新模型", index=900)
        assert scheduler(storage, client).tick() == "sent"
        assert sent_titles(client) == ["DeepSeek 开源新模型"]
        assert storage.connection.execute(
            "SELECT COUNT(*) FROM lark_story_deliveries WHERE delivery_key IS NULL"
        ).fetchone()[0] == 250


def test_all_held_back_reports_empty_and_disabled_filter_keeps_old_behavior(tmp_path):
    client = Mock(send=Mock(return_value=True))
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        seed(storage, "黄金价格上涨", index=0)
        assert scheduler(storage, client).tick() == "empty"
        assert client.send.call_count == 0
    with IntelligenceStorage(tmp_path / "other.db") as storage:
        seed(storage, "黄金价格上涨", index=0)
        unfiltered = replace(CONFIG, delivery_filter=StoryInterestFilter())
        assert scheduler(storage, client, unfiltered).tick() == "sent"
        assert sent_titles(client) == ["黄金价格上涨"]


def test_drain_sends_at_most_the_configured_batches_per_run(tmp_path):
    client = Mock(send=Mock(return_value=True))
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        for index in range(70):
            seed(storage, f"AI 新闻 {index}", index=index)
        config = replace(CONFIG, delivery_max_batches_per_tick=3)
        assert drain_ticks(scheduler(storage, client, config), config) == "sent"
        assert client.send.call_count == 3  # 60 Stories; 10 remain for the next run
        assert drain_ticks(scheduler(storage, client, config), config) == "sent"
        assert client.send.call_count == 4
        assert drain_ticks(scheduler(storage, client, config), config) == "empty"
        single = replace(CONFIG, delivery_max_batches_per_tick=1)
        for index in range(70, 110):
            seed(storage, f"AI 新闻 {index}", index=index)
        assert drain_ticks(scheduler(storage, client, single), single) == "sent"
        assert client.send.call_count == 5


def test_drain_stops_at_the_first_unsuccessful_send(tmp_path):
    client = Mock(send=Mock(side_effect=[True, False, True]))
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        for index in range(70):
            seed(storage, f"AI 新闻 {index}", index=index)
        config = replace(CONFIG, delivery_max_batches_per_tick=3)
        assert drain_ticks(scheduler(storage, client, config), config) == "send_failed"
        assert client.send.call_count == 2
