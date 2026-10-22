"""Source adapters for the unified intelligence pipeline."""

from trendradar.sources.ai_frontier import AIFrontierAdapter, build_ai_adapters
from trendradar.sources.base import (
    AdapterResult,
    HealthStatus,
    SourceAdapter,
    SourceHealth,
)
from trendradar.sources.newsnow import NewsNowAdapter
from trendradar.sources.rss import RSSAdapter
from trendradar.sources.security import CisaKevAdapter, NvdCveAdapter, SecurityRSSAdapter

__all__ = [
    "AIFrontierAdapter",
    "AdapterResult",
    "HealthStatus",
    "NewsNowAdapter",
    "RSSAdapter",
    "CisaKevAdapter",
    "NvdCveAdapter",
    "SecurityRSSAdapter",
    "SourceAdapter",
    "SourceHealth",
    "build_ai_adapters",
]
