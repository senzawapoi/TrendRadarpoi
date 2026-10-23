"""Core-owned Gemini translation with bounded calls and original-text fallback."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import requests

from trendradar.ai.client import GeminiClient, GeminiConfig
from trendradar.ai.errors import GeminiError, GeminiResponseError, GeminiUnavailableError
from trendradar.utils.logging import log

if TYPE_CHECKING:
    from trendradar.core.settings import RuntimeSettings

_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]")
_NUMBERED_LINE = re.compile(r"^(\d+)\s*[.\)\uff0e\u3001:\-\uff09]\s*(.+)")
TRANSLATION_MODEL = "gemini-3.1-flash-lite"
MAX_PARTIAL_RECOVERY_CALLS = 3

LANGUAGE_NAMES = {
    "en": "English",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "ru": "Russian",
    "it": "Italian",
}

# Retain the old public constant as an empty registry; no anonymous transport exists.
ANONYMOUS_TRANSLATION_APIS: tuple[dict[str, Any], ...] = ()


def is_english_title(title: str) -> bool:
    """Return whether a non-empty title contains no CJK characters."""
    return bool(title and title.strip() and not _CJK_PATTERN.search(title))


def optional_gemini_client(
    *,
    gemini_client: GeminiClient | None = None,
    gemini_api_key: str | None = None,
) -> GeminiClient | None:
    """Keep legacy injection shapes while fixing real clients to the translation model."""
    if gemini_client is not None:
        if isinstance(gemini_client, GeminiClient):
            return gemini_client.for_model(TRANSLATION_MODEL)
        return gemini_client
    if gemini_api_key is None:
        from trendradar.core.settings import load_settings

        return build_translation_client(load_settings(fallback_to_empty=True))
    key = str(gemini_api_key or "").strip()
    return GeminiClient(
        GeminiConfig(api_key=key, model=TRANSLATION_MODEL, max_attempts=1)
    ) if key else None


def build_translation_client(settings: RuntimeSettings) -> GeminiClient | None:
    """Use the same environment key and transport limits, ignoring inference model routing."""
    if not settings.gemini_enabled or not settings.gemini_api_key:
        return None
    values = settings.gemini_config
    return GeminiClient(GeminiConfig(
        api_key=settings.gemini_api_key,
        model=TRANSLATION_MODEL,
        max_attempts=1,
        **{name: values[name] for name in (
            "timeout_seconds", "min_request_interval_seconds", "max_input_chars",
            "max_output_chars", "model_cooldown_seconds",
        )},
    ))


class TranslationEngine:
    """Use the independent translation model, keeping failed batch slots empty."""

    TRANSLATION_APIS = ANONYMOUS_TRANSLATION_APIS

    def __init__(
        self,
        *,
        default_source: str = "en",
        default_target: str = "zh",
        gemini_client: GeminiClient | None = None,
        session: requests.Session | None = None,
        request_timeout_seconds: float = 10.0,
    ) -> None:
        self.default_source = str(default_source or "en")
        self.default_target = str(default_target or "zh")
        self.gemini_client = (
            gemini_client.for_model(TRANSLATION_MODEL)
            if isinstance(gemini_client, GeminiClient) else gemini_client
        )
        self.session = session  # Compatibility attribute only; no anonymous requests.
        self.request_timeout_seconds = max(1.0, min(30.0, float(request_timeout_seconds)))

    @property
    def gemini_available(self) -> bool:
        return self.gemini_client is not None and self.gemini_client.available

    def generate_text(self, prompt: str, *, instruction: str | None = None) -> str:
        """Generate bounded text through Gemini without exposing provider SDK values."""
        if self.gemini_client is None:
            raise GeminiUnavailableError()
        # Translation needs only a plain prompt, without tool or schema features.
        text = self.gemini_client.chat(
            f"{instruction}\n\n{prompt}" if instruction else prompt,
        ).text.strip()
        if not text:
            raise GeminiResponseError()
        return text

    def translate_text(
        self,
        text: str,
        source: str | None = None,
        target: str | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Return the legacy translation result dictionary."""
        del use_cache  # Retained for compatibility; this layer has no implicit persistent cache.
        if not isinstance(text, str) or not text.strip():
            return {
                "success": False,
                "error": {"code": "EMPTY_TEXT", "message": "Text to translate cannot be empty"},
            }

        source_lang = str(source or self.default_source)
        target_lang = str(target or self.default_target)
        if source_lang == target_lang:
            return {
                "success": True,
                "original_text": text,
                "translated_text": text,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "note": "Source and target languages are identical; translation was skipped",
            }

        return self._translate_with_gemini(text, source_lang, target_lang)

    def _translate_with_gemini(
        self,
        text: str,
        source: str,
        target: str,
    ) -> dict[str, Any]:
        source_name = LANGUAGE_NAMES.get(source, source)
        target_name = LANGUAGE_NAMES.get(target, target)
        instruction = (
            f"Translate the supplied {source_name} text into {target_name}. "
            "Return only the translation without commentary."
        )
        try:
            translated = self.generate_text(text, instruction=instruction)
        except GeminiError as exc:
            return self._failed_translation(text, source, target, exc.code)
        except Exception:
            return self._failed_translation(text, source, target, "TRANSLATION_FAILED")
        return {
            "success": True,
            "original_text": text,
            "translated_text": translated,
            "source_lang": source,
            "target_lang": target,
            "api_used": "Google Gemini",
        }

    @staticmethod
    def _failed_translation(text: str, source: str, target: str, code: str) -> dict[str, Any]:
        log.warning("Gemini translation failed; original text retained", error_code=code)
        return {
            "success": False,
            "original_text": text,
            "translated_text": text,
            "source_lang": source,
            "target_lang": target,
            "error": {"code": code, "message": "Translation failed; original text retained"},
        }

    def batch_translate_titles(
        self,
        titles: Sequence[str],
        source_lang: str = "en",
        target_lang: str = "zh",
        batch_size: int = 15,
    ) -> list[str]:
        """Translate titles in order, retaining empty slots for failed items."""
        if not titles:
            return []
        size = max(1, min(100, int(batch_size)))
        values = [str(title) for title in titles]
        results = [""] * len(values)
        if source_lang == target_lang:
            return values
        if self.gemini_client is None:
            return results

        for start in range(0, len(values), size):
            batch = values[start : start + size]
            usable = self._translate_batch_with_gemini(
                batch, results, start, source_lang, target_lang
            )
            if not usable:
                continue
            recovery_calls = 0
            for offset, title in enumerate(batch):
                index = start + offset
                if results[index]:
                    continue
                if recovery_calls >= MAX_PARTIAL_RECOVERY_CALLS:
                    break
                recovery_calls += 1
                outcome = self.translate_text(title, source_lang, target_lang)
                if outcome.get("success") and outcome.get("translated_text"):
                    results[index] = str(outcome["translated_text"])
                else:
                    break
        return results

    def _translate_batch_with_gemini(
        self,
        batch: list[str],
        results: list[str],
        start: int,
        source_lang: str,
        target_lang: str,
    ) -> bool:
        numbered = "\n".join(f"{index + 1}. {title}" for index, title in enumerate(batch))
        instruction = (
            f"Translate each numbered {LANGUAGE_NAMES.get(source_lang, source_lang)} line into "
            f"{LANGUAGE_NAMES.get(target_lang, target_lang)}. Return only one numbered "
            "translation per line using the original numbering."
        )
        try:
            translated_text = self.generate_text(numbered, instruction=instruction)
        except Exception as exc:
            code = exc.code if isinstance(exc, GeminiError) else "TRANSLATION_FAILED"
            log.warning("Gemini batch translation failed", error_code=code)
            return False

        lines = [line.strip() for line in translated_text.splitlines() if line.strip()]
        parsed_count = 0
        for line in lines:
            match = _NUMBERED_LINE.match(line)
            if not match or len(match.group(1)) > 3:
                continue
            index = int(match.group(1)) - 1
            if 0 <= index < len(batch) and not results[start + index]:
                results[start + index] = match.group(2).strip()
                parsed_count += 1

        if parsed_count == 0 and len(lines) == len(batch):
            if not any(_NUMBERED_LINE.match(line) for line in lines):
                for index, translated in enumerate(lines):
                    results[start + index] = translated
                parsed_count = len(batch)
        return parsed_count > 0

    def translate_news_list(
        self,
        news_list: list[dict[str, Any]],
        fields: list[str] | None = None,
        source: str | None = None,
        target: str | None = None,
        skip_if_chinese: bool = True,
        bilingual: bool = False,
    ) -> dict[str, Any]:
        """Translate selected mapping fields while preserving the legacy response shape."""
        if not news_list:
            return {"success": True, "translated_news": [], "total": 0, "translated_count": 0}
        selected_fields = fields or ["title", "summary"]
        source_lang = source or self.default_source
        target_lang = target or self.default_target
        translated_news: list[dict[str, Any]] = []
        translated_count = 0

        for news in news_list:
            translated_item = news.copy()
            item_translated = False
            for field in selected_fields:
                raw_text = news.get(field)
                if not raw_text:
                    continue
                text = str(raw_text)
                detected_lang = self.detect_language(text)
                if skip_if_chinese and target_lang == "zh" and detected_lang == "zh":
                    continue
                targets = ("zh", "en") if bilingual else (target_lang,)
                for selected_target in targets:
                    if detected_lang == selected_target:
                        continue
                    result = self.translate_text(text, detected_lang, selected_target)
                    if not result.get("success"):
                        continue
                    suffix = "english" if bilingual and selected_target == "en" else "translated"
                    translated_item[f"{field}_{suffix}"] = result["translated_text"]
                    item_translated = True
            translated_news.append(translated_item)
            translated_count += int(item_translated)

        return {
            "success": True,
            "translated_news": translated_news,
            "total": len(news_list),
            "translated_count": translated_count,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "bilingual_mode": bilingual,
        }

    @staticmethod
    def contains_chinese(text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))

    @staticmethod
    def detect_language(text: str) -> str:
        if not text:
            return "unknown"
        sample = str(text)[:100]
        chinese_count = sum("\u4e00" <= char <= "\u9fff" for char in sample)
        return "zh" if chinese_count / len(sample) > 0.2 else "en"


__all__ = [
    "ANONYMOUS_TRANSLATION_APIS",
    "LANGUAGE_NAMES",
    "TranslationEngine",
    "TRANSLATION_MODEL",
    "build_translation_client",
    "is_english_title",
    "optional_gemini_client",
]
