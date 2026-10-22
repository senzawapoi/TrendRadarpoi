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


def test_translate_items_skips_when_no_english_items():
    items = [AIItem(source="arxiv", source_name="x", title="中文标题", url="https://u")]
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


class _FakeTranslationService:
    translation_tools = object()

    def __init__(self, translations):
        self.translations = translations
        self.calls = []

    def batch_translate_titles(self, titles, batch_size=15):
        self.calls.append((list(titles), batch_size))
        return list(self.translations)


def test_translate_items_uses_injected_service_without_key_and_propagates_canonical_result():
    first = AIItem(source="arxiv", source_name="ArXiv", title="Shared title", url="https://a")
    duplicate = AIItem(source="blog", source_name="Blog", title="Shared title", url="https://b")
    second = AIItem(source="reddit", source_name="Reddit", title="Second title", url="https://c")
    first._canonical_content_id = "shared"
    duplicate._canonical_content_id = "shared"
    second._canonical_content_id = "second"
    service = _FakeTranslationService(["共享标题", "第二标题"])

    count = translate_items(
        [first, duplicate, second],
        gemini_api_key=None,
        batch_size=7,
        translation_service=service,
    )

    assert count == 2
    assert service.calls == [(["Shared title", "Second title"], 7)]
    assert first.title_translated == "共享标题"
    assert duplicate.title_translated == "共享标题"
    assert second.title_translated == "第二标题"


def test_translate_items_does_not_introspect_mcp_default(monkeypatch):
    captured = {}

    class Service(_FakeTranslationService):
        def __init__(self, gemini_api_key=None, gemini_client=None):
            captured.update(key=gemini_api_key, client=gemini_client)
            super().__init__(["标题"])

    monkeypatch.setattr("trendradar.ai_frontier.translator.TranslationService", Service)
    item = AIItem(source="arxiv", source_name="ArXiv", title="English", url="https://a")

    assert translate_items([item], gemini_api_key=None) == 1
    assert captured == {"key": None, "client": None}
    assert item.title_translated == "标题"
