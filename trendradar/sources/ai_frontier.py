"""Adapter wrapper for existing AI Frontier AISource implementations."""

from __future__ import annotations

from datetime import datetime

from trendradar.ai_frontier.sources.base import AIItem, AISource
from trendradar.core.models import ContentItem, content_from_ai_item
from trendradar.sources.base import SourceAdapter


class AIFrontierAdapter(SourceAdapter[AIItem]):
    domain = "ai"

    def __init__(self, source_key: str, source: AISource) -> None:
        self.source_key = source_key
        self.source = source
        self.adapter_id = f"ai_frontier:{source_key}"
        super().__init__()

    async def fetch(self) -> list[AIItem]:
        return await self.source.fetch()

    @property
    def fetch_errors(self) -> tuple[str, ...]:
        return self.source.fetch_errors

    def normalize(self, raw: AIItem, *, collected_at: datetime) -> ContentItem:
        return content_from_ai_item(raw, collected_at=collected_at)


def build_ai_adapters(config: dict) -> list[AIFrontierAdapter]:
    """Build one adapter per enabled top-level ``ai_frontier.sources`` block."""
    from trendradar.ai_frontier.fetcher import SOURCE_CLASSES

    sources_config = (config or {}).get("sources", {}) or {}
    adapters: list[AIFrontierAdapter] = []
    for source_key, source_class in SOURCE_CLASSES.items():
        source_config = sources_config.get(source_key) or {}
        if source_config.get("enabled", True):
            adapters.append(AIFrontierAdapter(source_key, source_class(source_config)))
    return adapters


__all__ = ["AIFrontierAdapter", "build_ai_adapters"]
