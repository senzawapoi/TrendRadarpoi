"""Core-owned translation orchestration with optional Gemini synthesis."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

import requests

from trendradar.ai.client import GeminiClient, GeminiConfig
from trendradar.ai.errors import GeminiError, GeminiUnavailableError
from trendradar.utils.logging import log

_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]")
_NUMBERED_LINE = re.compile(r"^(\d+)\s*[.\)\uff0e\u3001:\-\uff09]\s*(.+)")
_NUMBER_PREFIX = re.compile(r"^\d+\s*[.\)\uff0e\u3001:\-\uff09]\s*")

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

ANONYMOUS_TRANSLATION_APIS: tuple[dict[str, Any], ...] = (
    {
        "name": "Google Translate",
        "url": "https://translate.googleapis.com/translate_a/single",
        "method": "GET",
        "params": lambda q, source, target: {
            "client": "gtx",
            "sl": source,
            "tl": target,
            "dt": "t",
            "q": q,
        },
        "response_path": (0, 0, 0),
        "max_length": 500,
    },
    {
        "name": "MyMemory",
        "url": "https://api.mymemory.translated.net/get",
        "method": "GET",
        "params": lambda q, source, target: {"q": q, "langpair": f"{source}|{target}"},
        "response_path": ("responseData", "translatedText"),
        "max_length": 500,
    },
)


def is_english_title(title: str) -> bool:
    """Return whether a non-empty title contains no CJK characters."""
    return bool(title and title.strip() and not _CJK_PATTERN.search(title))


def optional_gemini_client(
    *,
    gemini_client: GeminiClient | None = None,
    gemini_api_key: str | None = None,
) -> GeminiClient | None:
    """Return an injected client or a lazy core client for an explicitly supplied key."""
    if gemini_client is not None:
        return gemini_client
    key = str(gemini_api_key or "").strip()
    return GeminiClient(GeminiConfig(api_key=key)) if key else None


class TranslationEngine:
    """Translate through one shared Gemini client, then anonymous providers in fixed order."""

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
        self.gemini_client = gemini_client
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "TrendRadar/1.0 Translation Service"})
        self.request_timeout_seconds = max(1.0, min(30.0, float(request_timeout_seconds)))

    @property
    def gemini_available(self) -> bool:
        return self.gemini_client is not None and self.gemini_client.available

    def generate_text(self, prompt: str, *, instruction: str | None = None) -> str:
        """Generate bounded text through Gemini without exposing provider SDK values."""
        if self.gemini_client is None:
            raise GeminiUnavailableError()
        return self.gemini_client.chat(
            prompt,
            system_instruction=instruction,
        ).text.strip()

    def translate_text(
        self,
        text: str,
        source: str | None = None,
        target: str | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Return the legacy translation result dictionary."""
        del use_cache  # Retained for compatibility; this layer has no implicit persistent cache.
        if not text or not text.strip():
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

        if self.gemini_client is not None:
            result = self._translate_with_gemini(text, source_lang, target_lang)
            if result is not None:
                return result

        for api_config in self.TRANSLATION_APIS:
            try:
                result = self._call_translation_api(api_config, text, source_lang, target_lang)
            except Exception as exc:
                log.warning(
                    "Anonymous translation provider failed",
                    provider=str(api_config["name"]),
                    error_type=type(exc).__name__,
                )
                continue
            if result is not None:
                return result

        return {
            "success": False,
            "error": {
                "code": "TRANSLATION_FAILED",
                "message": "All translation providers failed; retry later",
            },
        }

    def _translate_with_gemini(
        self,
        text: str,
        source: str,
        target: str,
    ) -> dict[str, Any] | None:
        if self.gemini_client is None:
            return None
        source_name = LANGUAGE_NAMES.get(source, source)
        target_name = LANGUAGE_NAMES.get(target, target)
        instruction = (
            f"Translate the supplied {source_name} text into {target_name}. "
            "Return only the translation without commentary."
        )
        try:
            translated = self.generate_text(text, instruction=instruction)
        except GeminiError as exc:
            log.warning(
                "Gemini translation unavailable; anonymous fallback remains active",
                error_code=exc.code,
            )
            return None
        except Exception as exc:
            log.warning(
                "Gemini translation failed; anonymous fallback remains active",
                error_type=type(exc).__name__,
            )
            return None
        if not translated:
            return None
        return {
            "success": True,
            "original_text": text,
            "translated_text": translated,
            "source_lang": source,
            "target_lang": target,
            "api_used": "Google Gemini",
        }

    def _call_translation_api(
        self,
        api_config: Mapping[str, Any],
        text: str,
        source: str,
        target: str,
    ) -> dict[str, Any] | None:
        max_length = max(1, int(api_config.get("max_length", 500)))
        request_text = text if len(text) <= max_length else f"{text[:max_length]}..."
        params_factory = api_config.get("params")
        params = params_factory(request_text, source, target) if callable(params_factory) else None
        method = str(api_config.get("method") or "GET").upper()
        if method == "GET":
            response = self.session.get(
                str(api_config["url"]),
                params=params,
                timeout=self.request_timeout_seconds,
            )
        else:
            response = self.session.post(
                str(api_config["url"]),
                data=params,
                timeout=self.request_timeout_seconds,
            )
        response.raise_for_status()
        translated: Any = response.json()
        for key in api_config.get("response_path", ()):
            if isinstance(translated, list) and isinstance(key, int):
                translated = translated[key] if key < len(translated) else None
            elif isinstance(translated, Mapping):
                translated = translated.get(key)
            else:
                translated = None
            if translated is None:
                break
        while isinstance(translated, list) and translated:
            translated = translated[0]
        if not isinstance(translated, str) or not translated.strip():
            return None
        return {
            "success": True,
            "original_text": request_text,
            "translated_text": translated.strip(),
            "source_lang": source,
            "target_lang": target,
            "api_used": str(api_config["name"]),
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

        for start in range(0, len(values), size):
            batch = values[start : start + size]
            if self.gemini_client is not None:
                self._translate_batch_with_gemini(batch, results, start, source_lang, target_lang)
            for offset, title in enumerate(batch):
                index = start + offset
                if results[index]:
                    continue
                outcome = self.translate_text(title, source_lang, target_lang)
                if outcome.get("success") and outcome.get("translated_text"):
                    results[index] = str(outcome["translated_text"])
        return results

    def _translate_batch_with_gemini(
        self,
        batch: list[str],
        results: list[str],
        start: int,
        source_lang: str,
        target_lang: str,
    ) -> None:
        numbered = "\n".join(f"{index + 1}. {title}" for index, title in enumerate(batch))
        instruction = (
            f"Translate each numbered {LANGUAGE_NAMES.get(source_lang, source_lang)} line into "
            f"{LANGUAGE_NAMES.get(target_lang, target_lang)}. Return only one numbered "
            "translation per line using the original numbering."
        )
        try:
            translated_text = self.generate_text(numbered, instruction=instruction)
        except Exception as exc:
            code = exc.code if isinstance(exc, GeminiError) else type(exc).__name__
            log.warning("Gemini batch translation failed", error_code=code)
            return

        lines = [line.strip() for line in translated_text.splitlines() if line.strip()]
        parsed_count = 0
        for line in lines:
            match = _NUMBERED_LINE.match(line)
            if not match:
                continue
            index = int(match.group(1)) - 1
            if 0 <= index < len(batch) and not results[start + index]:
                results[start + index] = match.group(2).strip()
                parsed_count += 1

        if parsed_count < len(batch) // 2:
            cleaned = [(_NUMBER_PREFIX.sub("", line).strip() or line) for line in lines]
            if len(cleaned) == len(batch):
                for index, translated in enumerate(cleaned):
                    results[start + index] = translated

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
    "is_english_title",
    "optional_gemini_client",
]
