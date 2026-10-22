"""Offline contracts for core translation and compatibility facades."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import requests

from mcp_server.tools.translation import TranslationTools
from trendradar.ai.errors import GeminiTimeoutError
from trendradar.ai.translator import TranslationEngine
from trendradar.services.translation_service import TranslationService
from trendradar.storage.base import NewsItem


class FakeGemini:
    available = True

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def chat(self, messages: Any, **kwargs: Any) -> Any:
        self.calls.append((messages, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


class FakeSession:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": "GET", "url": url, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": "POST", "url": url, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


def test_core_translation_prefers_shared_gemini_client() -> None:
    gemini = FakeGemini(" translated ")
    session = FakeSession()
    engine = TranslationEngine(gemini_client=gemini, session=session)  # type: ignore[arg-type]

    result = engine.translate_text("hello", "en", "zh")

    assert result == {
        "success": True,
        "original_text": "hello",
        "translated_text": "translated",
        "source_lang": "en",
        "target_lang": "zh",
        "api_used": "Google Gemini",
    }
    assert gemini.calls[0][0] == "hello"
    assert "Translate" in gemini.calls[0][1]["system_instruction"]
    assert session.calls == []


def test_anonymous_fallback_order_and_legacy_result_shape() -> None:
    gemini = FakeGemini(GeminiTimeoutError())
    session = FakeSession(
        requests.ConnectionError("offline"),
        {"responseData": {"translatedText": "ni hao"}},
    )
    engine = TranslationEngine(gemini_client=gemini, session=session)  # type: ignore[arg-type]

    result = engine.translate_text("hello", "en", "zh")

    assert result["success"] is True
    assert result["translated_text"] == "ni hao"
    assert result["api_used"] == "MyMemory"
    assert [call["url"] for call in session.calls] == [
        "https://translate.googleapis.com/translate_a/single",
        "https://api.mymemory.translated.net/get",
    ]


def test_empty_and_same_language_results_remain_compatible() -> None:
    engine = TranslationEngine(session=FakeSession())  # type: ignore[arg-type]

    assert engine.translate_text("", "en", "zh")["error"]["code"] == "EMPTY_TEXT"
    same = engine.translate_text("unchanged", "en", "en")
    assert same["success"] is True
    assert same["translated_text"] == "unchanged"
    assert same["source_lang"] == "en"
    assert same["target_lang"] == "en"


def test_batch_translation_keeps_order_and_falls_back_per_item() -> None:
    gemini = FakeGemini("1. one-zh\n3. three-zh", "two-zh")
    engine = TranslationEngine(gemini_client=gemini, session=FakeSession())  # type: ignore[arg-type]

    translated = engine.batch_translate_titles(["one", "two", "three"], batch_size=3)

    assert translated == ["one-zh", "two-zh", "three-zh"]
    assert len(gemini.calls) == 2


class StubEngine:
    def __init__(self) -> None:
        self.requests: list[list[str]] = []

    def batch_translate_titles(self, titles: list[str], **_kwargs: Any) -> list[str]:
        self.requests.append(list(titles))
        return [f"zh:{title}" if title != "failed" else "" for title in titles]

    def translate_text(self, text: str, **_kwargs: Any) -> dict[str, Any]:
        return {"success": True, "translated_text": f"zh:{text}"}


def test_translation_service_preserves_news_mutation_and_tuple_contract() -> None:
    engine = StubEngine()
    service = TranslationService(translation_engine=engine)  # type: ignore[arg-type]
    items = [
        NewsItem(title="English title", source_id="one", source_name="One"),
        NewsItem(title="中文标题", source_id="two", source_name="Two"),
        NewsItem(
            title="Existing",
            source_id="three",
            source_name="Three",
            title_translated="已有",
        ),
    ]

    assert service.translate_text("hello", "en", "zh") == (True, "zh:hello")
    assert service.translate_news_items(items) == 1
    assert engine.requests == [["English title"]]
    assert items[0].title_translated == "zh:English title"
    assert items[0].is_english is True
    assert items[1].title_translated == ""
    assert items[1].is_english is False
    assert items[2].title_translated == "已有"


def test_mcp_facade_has_no_default_key_and_delegates_to_core() -> None:
    assert inspect.signature(TranslationTools.__init__).parameters["gemini_api_key"].default is None
    engine = TranslationEngine(gemini_client=FakeGemini("mcp-zh"), session=FakeSession())  # type: ignore[arg-type]
    tools = TranslationTools(translation_engine=engine)

    result = tools.translate_text("hello", source="en", target="zh")

    assert result["success"] is True
    assert result["translated_text"] == "mcp-zh"
    assert tools.detect_language("中文内容") == "zh"


def test_core_translation_modules_do_not_import_mcp() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [Path("trendradar/ai/translator.py"), Path("trendradar/services/translation_service.py")]
    )
    assert "mcp_server" not in sources

