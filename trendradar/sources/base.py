"""Common asynchronous source adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Generic, TypeVar

from trendradar.core.models import ContentItem

RawT = TypeVar("RawT")


class HealthStatus(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True)
class SourceHealth:
    """Passive status from the adapter's most recent execution."""

    adapter_id: str
    status: HealthStatus = HealthStatus.UNKNOWN
    checked_at: datetime | None = None
    fetched_count: int = 0
    normalized_count: int = 0
    error_count: int = 0
    error_summary: str = ""


@dataclass
class AdapterResult(Generic[RawT]):
    adapter_id: str
    items: list[ContentItem] = field(default_factory=list)
    raw_items: list[RawT] = field(default_factory=list)
    normalized_raw_items: list[RawT] = field(default_factory=list)
    health: SourceHealth | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int = 0
    normalize_errors: list[str] = field(default_factory=list)
    fetch_error: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.fetch_error)


class SourceAdapter(Generic[RawT], ABC):
    """Fetch raw source records and normalize them into ContentItem objects."""

    adapter_id: str
    domain: str

    def __init__(self) -> None:
        self._health = SourceHealth(adapter_id=self.adapter_id)

    @abstractmethod
    async def fetch(self) -> list[RawT]:
        """Fetch raw records from one logical source."""

    @abstractmethod
    def normalize(self, raw: RawT, *, collected_at: datetime) -> ContentItem:
        """Normalize one raw record without performing network I/O."""

    async def health_check(self) -> SourceHealth:
        """Return recent execution state without performing another request."""
        return self._health

    @property
    def fetch_errors(self) -> tuple[str, ...]:
        """Failures isolated inside a successful partial fetch, without refetching."""
        return ()

    def _set_health(self, health: SourceHealth) -> None:
        self._health = health


__all__ = [
    "AdapterResult",
    "HealthStatus",
    "RawT",
    "SourceAdapter",
    "SourceHealth",
]
