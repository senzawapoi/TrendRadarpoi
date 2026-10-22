"""Optional Gemini wording enhancement for deterministic Stories."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from trendradar.ai.client import GeminiClient, GeminiConfig
from trendradar.ai.errors import GeminiResponseError
from trendradar.core.settings import RuntimeSettings
from trendradar.utils.logging import log

DEFAULT_MODEL = "gemini-2.0-flash"
MAX_TITLE_LENGTH = 240
MAX_SUMMARY_LENGTH = 1200


def _response_payload(text: str) -> Mapping[str, Any]:
    """Decode a JSON object while tolerating the markdown fences Gemini adds."""
    cleaned = str(text or "").strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()[1:-1]
        if lines and lines[0].strip().casefold() in {"json", "javascript"}:
            lines = lines[1:]
        cleaned = "\n".join(lines).strip()
    try:
        value = json.loads(cleaned)
    except (TypeError, json.JSONDecodeError) as exc:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Gemini wording response is not valid JSON") from exc
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as nested_exc:
            raise ValueError("Gemini wording response is not valid JSON") from nested_exc
    if not isinstance(value, Mapping):
        raise ValueError("Gemini wording response must be a JSON object")
    return value


def _bounded_text(value: Any, field_name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Gemini wording field {field_name} is empty")
    return value.strip()[:limit].rstrip()


class GeminiStoryWordingClient:
    """Compatibility facade that delegates wording to the shared core client."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = DEFAULT_MODEL,
        client: Any | None = None,
        gemini_client: GeminiClient | None = None,
    ) -> None:
        key = str(api_key or "").strip()
        if gemini_client is not None:
            resolved = gemini_client
        elif isinstance(client, GeminiClient):
            resolved = client
        elif client is not None and key:
            resolved = GeminiClient(
                GeminiConfig(
                    api_key=key,
                    model=str(model or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
                    max_attempts=1,
                    min_request_interval_seconds=0,
                ),
                client=client,
            )
        elif key:
            resolved = GeminiClient(
                GeminiConfig(
                    api_key=key,
                    model=str(model or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
                )
            )
        else:
            raise ValueError("GEMINI_API_KEY is required")
        self.client = resolved
        self.model = resolved.config.model

    def enhance(self, *, title: str, summary: str) -> dict[str, str]:
        context = json.dumps(
            {"title": str(title), "summary": str(summary)},
            ensure_ascii=False,
        )
        instruction = (
            "Rewrite the supplied Story wording for a concise personal intelligence digest. "
            "Return only one JSON object with non-empty string fields title and summary. "
            "Do not add fields or discuss IDs, members, sources, evidence, ranking, or scores."
        )
        try:
            response = self.client.analyze(
                context,
                instruction=instruction,
                response_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "required": ["title", "summary"],
                    "additionalProperties": False,
                },
                response_mime_type="application/json",
            )
        except GeminiResponseError:
            raise ValueError("Gemini wording response is not valid JSON") from None
        payload = _response_payload(response.text)
        return {
            "title": _bounded_text(payload.get("title"), "title", MAX_TITLE_LENGTH),
            "summary": _bounded_text(
                payload.get("summary"),
                "summary",
                MAX_SUMMARY_LENGTH,
            ),
        }


def build_story_wording_client(
    settings: RuntimeSettings,
    *,
    story_config: Mapping[str, Any] | None = None,
    gemini_client: GeminiClient | None = None,
) -> GeminiStoryWordingClient | None:
    """Create the optional client only when all runtime gates are satisfied."""
    if not settings.intelligence_enabled or not settings.intelligence_story_wording_enabled:
        return None
    api_key = settings.gemini_api_key
    if not api_key:
        return None
    config = story_config if isinstance(story_config, Mapping) else {}
    wording = config.get("wording")
    wording = wording if isinstance(wording, Mapping) else {}
    model = str(wording.get("model") or DEFAULT_MODEL)
    try:
        options: dict[str, Any] = {"model": model}
        if gemini_client is not None:
            options["gemini_client"] = gemini_client
        return GeminiStoryWordingClient(api_key, **options)
    except Exception as exc:
        log.warning(
            "Story wording client unavailable; deterministic fallback remains active",
            error_type=type(exc).__name__,
        )
        return None


__all__ = [
    "DEFAULT_MODEL",
    "GeminiStoryWordingClient",
    "build_story_wording_client",
]
