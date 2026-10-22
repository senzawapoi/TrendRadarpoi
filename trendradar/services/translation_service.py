"""Backward-compatible application translation facade."""

from __future__ import annotations

from typing import Any

from trendradar.ai.client import GeminiClient
from trendradar.ai.translator import TranslationEngine, is_english_title, optional_gemini_client
from trendradar.storage.base import NewsData, NewsItem
from trendradar.utils.logging import log


class TranslationService:
    """Preserve legacy tuple/list APIs while delegating to the core AI layer."""

    def __init__(
        self,
        gemini_api_key: str | None = None,
        *,
        gemini_client: GeminiClient | None = None,
        translation_engine: TranslationEngine | None = None,
    ) -> None:
        self.gemini_api_key = gemini_api_key
        self.translation_tools: TranslationEngine | None = None
        self._init_translation_tools(
            gemini_client=gemini_client,
            translation_engine=translation_engine,
        )

    def _init_translation_tools(
        self,
        *,
        gemini_client: GeminiClient | None = None,
        translation_engine: TranslationEngine | None = None,
    ) -> None:
        """Initialize the core engine; anonymous providers remain usable without a key."""
        try:
            client = optional_gemini_client(
                gemini_client=gemini_client,
                gemini_api_key=self.gemini_api_key,
            )
            self.translation_tools = translation_engine or TranslationEngine(gemini_client=client)
            log.info("Translation service initialized", gemini_enabled=client is not None)
        except Exception as exc:
            log.warning("Translation service initialization failed", error_type=type(exc).__name__)
            self.translation_tools = None

    @staticmethod
    def is_english_title(title: str) -> bool:
        return is_english_title(title)

    def translate_text(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> tuple[bool, str]:
        if self.translation_tools is None:
            return False, ""
        result = self.translation_tools.translate_text(
            text,
            source=source_lang,
            target=target_lang,
        )
        if result.get("success"):
            return True, str(result.get("translated_text", ""))
        error = result.get("error")
        error_code = (
            error.get("code", "TRANSLATION_FAILED")
            if isinstance(error, dict)
            else "TRANSLATION_FAILED"
        )
        log.warning("Translation failed", error_code=error_code)
        return False, ""

    def translate_title(self, title: str, target_lang: str = "zh") -> tuple[bool, str]:
        source_lang = "en" if self.is_english_title(title) else "zh"
        if source_lang == target_lang:
            return True, title
        return self.translate_text(title, source_lang, target_lang)

    def _gemini_call(self, prompt: str) -> str:
        if self.translation_tools is None:
            raise RuntimeError("Translation service is unavailable")
        return self.translation_tools.generate_text(
            prompt,
            instruction="Return only the requested translations without commentary.",
        )

    def batch_translate_titles(
        self,
        titles: list[str],
        source_lang: str = "en",
        target_lang: str = "zh",
        batch_size: int = 15,
    ) -> list[str]:
        if self.translation_tools is None:
            return [""] * len(titles)
        return self.translation_tools.batch_translate_titles(
            titles,
            source_lang=source_lang,
            target_lang=target_lang,
            batch_size=batch_size,
        )

    def translate_news_items(self, news_items: list[NewsItem], skip_existing: bool = True) -> int:
        if self.translation_tools is None:
            log.warning("Translation service unavailable; skipping news translation")
            return 0

        indices: list[int] = []
        titles: list[str] = []
        for index, item in enumerate(news_items):
            item.is_english = self.is_english_title(item.title)
            if not item.is_english:
                continue
            if skip_existing and getattr(item, "title_translated", ""):
                continue
            indices.append(index)
            titles.append(item.title)

        if not titles:
            return 0
        translations = self.batch_translate_titles(titles)
        translated_count = 0
        for index, translated in zip(indices, translations, strict=False):
            if translated:
                news_items[index].title_translated = translated
                translated_count += 1
        return translated_count

    def translate_news_data(self, news_data: NewsData, skip_existing: bool = True) -> int:
        return sum(
            self.translate_news_items(news_list, skip_existing)
            for news_list in news_data.items.values()
        )

    def translate_news_list(
        self,
        news_list: list[dict[str, Any]],
        fields: list[str] | None = None,
        source: str | None = None,
        target: str | None = None,
        skip_if_chinese: bool = True,
        bilingual: bool = False,
    ) -> dict[str, Any]:
        if self.translation_tools is None:
            return {
                "success": False,
                "error": {
                    "code": "TRANSLATION_UNAVAILABLE",
                    "message": "Translation unavailable",
                },
            }
        return self.translation_tools.translate_news_list(
            news_list,
            fields=fields,
            source=source,
            target=target,
            skip_if_chinese=skip_if_chinese,
            bilingual=bilingual,
        )


__all__ = ["TranslationService"]
