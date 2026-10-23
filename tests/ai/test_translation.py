"""Offline contracts for core translation and compatibility facades."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.tools.translation import TranslationTools
from trendradar.ai.errors import GeminiTimeoutError
from trendradar.ai.translator import (
    TRANSLATION_MODEL,
    TranslationEngine,
    build_translation_client,
)
from trendradar.core.settings import load_settings
from trendradar.services.translation_service import TranslationService
from trendradar.storage.base import NewsItem

from .test_gemini_client import FakeSdkClient, _config, _response


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
    assert gemini.calls[0][0].endswith("\n\nhello")
    assert "Translate" in gemini.calls[0][0]
    assert gemini.calls[0][1] == {}
    assert session.calls == []


def test_failure_retains_original_and_never_uses_anonymous_provider() -> None:
    gemini = FakeGemini(GeminiTimeoutError())
    session = FakeSession()
    engine = TranslationEngine(gemini_client=gemini, session=session)  # type: ignore[arg-type]

    result = engine.translate_text("hello", "en", "zh")

    assert result["success"] is False
    assert result["translated_text"] == result["original_text"] == "hello"
    assert result["error"]["code"] == "GEMINI_TIMEOUT"
    assert session.calls == []


@pytest.mark.parametrize("outcome", [GeminiTimeoutError(), RuntimeError("private"), ""])
def test_failed_whole_batch_does_not_fan_out(outcome) -> None:
    gemini = FakeGemini(outcome)
    engine = TranslationEngine(gemini_client=gemini)
    assert engine.batch_translate_titles(["one", "two", "three"]) == ["", "", ""]
    assert len(gemini.calls) == 1


def test_partial_batch_recovery_is_bounded_and_stops_on_provider_failure() -> None:
    gemini = FakeGemini("1. one-zh", "two-zh", "three-zh", "four-zh")
    engine = TranslationEngine(gemini_client=gemini)
    assert engine.batch_translate_titles(["one", "two", "three", "four", "five"]) == [
        "one-zh", "two-zh", "three-zh", "four-zh", "",
    ]
    assert len(gemini.calls) == 4
    gemini = FakeGemini("1. one-zh", GeminiTimeoutError())
    engine = TranslationEngine(gemini_client=gemini)
    assert engine.batch_translate_titles(["one", "two", "three"]) == ["one-zh", "", ""]
    assert len(gemini.calls) == 2


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


@pytest.mark.parametrize("facade", [TranslationEngine, TranslationService, TranslationTools])
def test_real_inference_client_uses_flash_lite_without_modifying_inference(facade):
    from trendradar.ai import GeminiClient

    sdk = FakeSdkClient(_response("translated"), _response("inference"))
    inference = GeminiClient(_config(models=("inference-one", "inference-two")), client=sdk)
    translator = facade(gemini_client=inference)
    translator.translate_text("hello", "en", "zh")
    assert sdk.models.calls[0]["model"] == "gemini-3.1-flash-lite"
    assert "system_instruction" not in sdk.models.calls[0]["config"]
    assert inference.chat("inference").model == "inference-one"


def test_translation_failure_is_independent_of_inference_cooldowns():
    from trendradar.ai import GeminiClient

    sdk = FakeSdkClient(TimeoutError(), _response("still works"))
    inference = GeminiClient(_config(max_attempts=3), client=sdk)
    translation = TranslationEngine(gemini_client=inference)
    assert translation.batch_translate_titles(["one", "two"]) == ["", ""]
    assert [call["model"] for call in sdk.models.calls] == [TRANSLATION_MODEL]
    assert inference.chat("question").text == "still works"
    assert translation.batch_translate_titles(["three"]) == [""]
    assert len(sdk.models.calls) == 2


def test_translation_failure_never_switches_to_gemma_or_inference_models():
    from trendradar.ai import GeminiClient

    sdk = FakeSdkClient(TimeoutError(), _response("must not be requested"))
    engine = TranslationEngine(gemini_client=GeminiClient(_config(max_attempts=3), client=sdk))
    outcome = engine.translate_text("original title", "en", "zh")
    assert not outcome["success"]
    assert outcome["translated_text"] == "original title"
    assert [call["model"] for call in sdk.models.calls] == ["gemini-3.1-flash-lite"]


def test_settings_translation_ignores_inference_models_and_reuses_key(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("ai:\n  gemini:\n    models: [old-model]\n", encoding="utf-8")
    settings = load_settings(path, environ={
        "GEMINI_API_KEY": "translation-test-key",
        "GEMINI_MODELS": "inference-one,inference-two",
    })
    client = build_translation_client(settings)
    assert client.config.models == (TRANSLATION_MODEL,)
    assert client.config.max_attempts == 1
    assert client.config.api_key == settings.gemini_api_key
    assert not client.initialized
    assert build_translation_client(load_settings(path, environ={})) is None
    assert build_translation_client(load_settings(path, environ={
        "GEMINI_API_KEY": "key", "GEMINI_ENABLED": "false",
    })) is None


def test_mcp_legacy_constructor_loads_environment_key_and_never_anonymous(monkeypatch):
    from trendradar.ai import GeminiClient

    monkeypatch.setenv("GEMINI_API_KEY", "environment-test-key")
    monkeypatch.setenv("GEMINI_MODELS", "ignored-model")
    monkeypatch.setenv("GEMINI_ENABLED", "true")
    sdk = FakeSdkClient(_response("mcp translated"))
    monkeypatch.setattr(GeminiClient, "_default_client_factory", staticmethod(lambda **_kwargs: sdk))
    tools = TranslationTools(session=FakeSession())
    assert tools.gemini_client.config.api_key == "environment-test-key"
    assert tools.translate_text("hello")["translated_text"] == "mcp translated"
    assert sdk.models.calls[0]["model"] == TRANSLATION_MODEL
    assert tools.session.calls == []


def test_canonical_news_failure_and_frontier_failure_keep_originals():
    from trendradar.ai_frontier.sources.base import AIItem
    from trendradar.ai_frontier.translator import translate_items
    from trendradar.intelligence.translation import translate_news_items_canonically

    gemini = FakeGemini(GeminiTimeoutError(), GeminiTimeoutError())
    service = TranslationService(translation_engine=TranslationEngine(gemini_client=gemini))
    news = [NewsItem(title=title, source_id="test") for title in ("one", "one duplicate")]
    for item in news:
        item._canonical_content_id = "one"
    assert translate_news_items_canonically(news, service.translate_news_items) == 0
    assert [item.title for item in news] == ["one", "one duplicate"]
    assert all(not item.title_translated for item in news)
    ai_items = [AIItem(source="arxiv", source_name="ArXiv", title="English", url="https://a")]
    assert translate_items(ai_items, translation_service=service) == 0
    assert ai_items[0].title == "English"
    assert not ai_items[0].title_translated
    assert len(gemini.calls) == 2


def test_missing_credentials_preserve_original_without_any_transport():
    service = TranslationService(gemini_api_key="")
    assert service.translate_text("original", "en", "zh") == (False, "original")
    assert service.batch_translate_titles(["original"]) == [""]
    tools = TranslationTools(gemini_api_key="", session=FakeSession())
    result = tools.translate_text("original")
    assert result["success"] is False
    assert result["translated_text"] == "original"
    assert result["error"]["code"] == "GEMINI_UNAVAILABLE"
    assert tools.session.calls == []


def test_malformed_batch_numbering_is_not_reassigned_or_fanned_out():
    gemini = FakeGemini("9" * 5000 + ". invalid")
    engine = TranslationEngine(gemini_client=gemini)
    assert engine.batch_translate_titles(["one", "two"]) == ["", ""]
    assert len(gemini.calls) == 1


@pytest.mark.parametrize("numbered", [False, True])
def test_median_mistranslation_is_rejected_without_whole_batch_fanout(numbered):
    title = 'Median product "lifespan" has fallen from ~4y down to ~1.5y'
    wrong = "产品平均寿命从约4年降至约1.5年"
    gemini = FakeGemini(("1. " if numbered else "") + wrong)
    engine = TranslationEngine(gemini_client=gemini)
    assert engine.batch_translate_titles([title]) == [""]
    assert len(gemini.calls) == 1
    assert "median means 中位数" in gemini.calls[0][0]
    assert "quantities, units" in gemini.calls[0][0]


def test_median_fixture_preserves_numbers_and_single_text_fallback():
    title = 'Median product "lifespan" has fallen from ~4y down to ~1.5y'
    correct = "产品寿命中位数从约4年降至约1.5年"
    gemini = FakeGemini("1. " + correct, "产品平均寿命下降")
    engine = TranslationEngine(gemini_client=gemini)
    assert engine.batch_translate_titles([title]) == [correct]
    outcome = engine.translate_text(title)
    assert not outcome["success"]
    assert outcome["translated_text"] == title
    assert outcome["error"]["code"] == "TRANSLATION_TERMINOLOGY"

