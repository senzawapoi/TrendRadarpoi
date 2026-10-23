"""MCP-facing compatibility adapter for the core translation service."""

from __future__ import annotations

from typing import Any, ClassVar

import requests

from trendradar.ai.client import GeminiClient
from trendradar.ai.translator import (
    ANONYMOUS_TRANSLATION_APIS,
    TRANSLATION_MODEL,
    TranslationEngine,
    optional_gemini_client,
)


class TranslationTools:
    """Preserve MCP result dictionaries while delegating translation inward."""

    TRANSLATION_APIS: ClassVar[list[dict[str, Any]]] = list(ANONYMOUS_TRANSLATION_APIS)

    def __init__(
        self,
        default_source: str = "en",
        default_target: str = "zh",
        gemini_api_key: str | None = None,
        *,
        gemini_client: GeminiClient | None = None,
        session: requests.Session | None = None,
        translation_engine: TranslationEngine | None = None,
    ) -> None:
        resolved_client = optional_gemini_client(
            gemini_client=gemini_client,
            gemini_api_key=gemini_api_key,
        )
        self.default_source = default_source
        self.default_target = default_target
        self.gemini_api_key = gemini_api_key
        self.gemini_client = resolved_client
        self.gemini_model = TRANSLATION_MODEL
        self._engine = translation_engine or TranslationEngine(
            default_source=default_source,
            default_target=default_target,
            gemini_client=resolved_client,
            session=session,
        )
        self.session = self._engine.session

    def translate_text(
        self,
        text: str,
        source: str | None = None,
        target: str | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        return self._engine.translate_text(
            text,
            source=source,
            target=target,
            use_cache=use_cache,
        )

    def _translate_with_gemini(
        self,
        text: str,
        source: str,
        target: str,
    ) -> dict[str, Any] | None:
        return self._engine._translate_with_gemini(text, source, target)

    def translate_news_list(
        self,
        news_list: list[dict[str, Any]],
        fields: list[str] | None = None,
        source: str | None = None,
        target: str | None = None,
        skip_if_chinese: bool = True,
        bilingual: bool = False,
    ) -> dict[str, Any]:
        return self._engine.translate_news_list(
            news_list,
            fields=fields,
            source=source,
            target=target,
            skip_if_chinese=skip_if_chinese,
            bilingual=bilingual,
        )

    def _contains_chinese(self, text: str) -> bool:
        return self._engine.contains_chinese(text)

    def detect_language(self, text: str) -> str:
        return self._engine.detect_language(text)


__all__ = ["TranslationTools"]
