"""AIItem 与 AISource 基础测试"""

from __future__ import annotations

from datetime import datetime

import pytest

from trendradar.ai_frontier.sources.base import AIItem, AISource


def test_ai_item_minimal():
    item = AIItem(source="arxiv", source_name="ArXiv cs.AI", title="Test", url="https://x")
    assert item.source == "arxiv"
    assert item.score == 0
    assert item.is_new is False
    assert item.tags == []


def test_ai_item_unique_key():
    a = AIItem(source="arxiv", source_name="x", title="a", url="https://u")
    b = AIItem(source="arxiv", source_name="y", title="b", url="https://u")
    assert a.unique_key() == b.unique_key()


def test_ai_item_to_dict_roundtrip():
    dt = datetime(2026, 4, 17, 10, 0, 0)
    item = AIItem(
        source="hackernews",
        source_name="HN",
        title="t",
        url="https://u",
        published_at=dt,
        score=42,
        tags=["ai", "llm"],
    )
    d = item.to_dict()
    assert d["source"] == "hackernews"
    assert d["published_at"] == "2026-04-17T10:00:00"
    assert d["score"] == 42
    assert d["tags"] == ["ai", "llm"]


def test_ai_source_is_abstract():
    with pytest.raises(TypeError):
        AISource({})  # type: ignore[abstract]


def test_ai_source_subclass_instantiable():
    class Dummy(AISource):
        source_type = "arxiv"

        async def fetch(self) -> list[AIItem]:
            return []

    d = Dummy({"enabled": True})
    assert d.enabled is True
    assert d.name == "arxiv"
