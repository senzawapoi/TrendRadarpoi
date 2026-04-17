"""translator 测试"""

from __future__ import annotations

from trendradar.ai_frontier.sources.base import AIItem
from trendradar.ai_frontier.translator import is_english_title, translate_items


def test_is_english_detects_pure_english():
    assert is_english_title("Scaling Laws for LLM") is True
    assert is_english_title("GPT-5 Released") is True


def test_is_english_detects_chinese():
    assert is_english_title("大模型进展") is False
    assert is_english_title("Claude 4 发布") is False  # 混合含中文


def test_is_english_detects_japanese_korean():
    assert is_english_title("LLMの研究") is False
    assert is_english_title("인공지능 연구") is False


def test_is_english_empty():
    assert is_english_title("") is False
    assert is_english_title("   ") is False


def test_translate_items_skips_when_no_key():
    items = [AIItem(source="arxiv", source_name="x", title="Hello", url="https://u")]
    count = translate_items(items, gemini_api_key=None)
    assert count == 0
    assert items[0].title_translated == ""


def test_translate_items_skips_non_english(monkeypatch):
    """即使有 key，中文标题也应被跳过"""
    items = [
        AIItem(source="arxiv", source_name="x", title="中文标题", url="https://u1"),
        AIItem(source="arxiv", source_name="x", title="日本語のタイトル", url="https://u2"),
    ]
    # 不实际调用 API：translate_items 在筛选阶段就会过滤掉
    # 若无英文条目且无需调用 service，返回 0
    count = translate_items(items, gemini_api_key="fake-key")
    # 非英文被过滤，en_titles 为空，直接返回 0
    assert count == 0


def test_translate_items_skips_already_translated():
    items = [
        AIItem(
            source="arxiv",
            source_name="x",
            title="English",
            url="https://u",
            title_translated="已有翻译",
        ),
    ]
    count = translate_items(items, gemini_api_key="fake-key")
    assert count == 0
    assert items[0].title_translated == "已有翻译"
