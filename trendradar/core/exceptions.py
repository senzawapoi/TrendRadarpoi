"""
Custom exception hierarchy for TrendRadar.

Based on: python-error-handling skill
- Fail-fast validation with custom exceptions
- Partial failure handling with BatchResult
- Exception chaining for transparent error propagation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

# ── Exception Hierarchy ────────────────────────────────────────────────────────

class TrendRadarError(Exception):
    """Base exception for all TrendRadar errors."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self._cause = cause
        if cause is not None:
            self.__cause__ = cause

    @property
    def cause(self) -> BaseException | None:
        return self._cause


# ── Fetch / Crawl errors ───────────────────────────────────────────────────────

class FetchError(TrendRadarError):
    """Raised when a data fetch (RSS, hot榜单) fails."""

    def __init__(self, message: str, *, feed_id: str = "", cause: BaseException | None = None) -> None:
        super().__init__(message, cause=cause)
        self.feed_id = feed_id


class RSSFetchError(FetchError):
    """Raised specifically when an RSS feed fails to fetch."""

    def __init__(self, feed_id: str, feed_name: str, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(f"[{feed_name}] {message}", feed_id=feed_id, cause=cause)
        self.feed_name = feed_name


class TranslationError(TrendRadarError):
    """Raised when translation API call fails."""

    def __init__(self, message: str, *, source_lang: str = "", target_lang: str = "", cause: BaseException | None = None) -> None:
        super().__init__(message, cause=cause)
        self.source_lang = source_lang
        self.target_lang = target_lang


class TranslationBatchError(TranslationError):
    """Raised when a batch translation call fails, but partial results may be available."""

    def __init__(self, message: str, batch_size: int, success_count: int, failed_indices: list[int], *, source_lang: str = "", target_lang: str = "", cause: BaseException | None = None) -> None:
        super().__init__(message, source_lang=source_lang, target_lang=target_lang, cause=cause)
        self.batch_size = batch_size
        self.success_count = success_count
        self.failed_indices = failed_indices


# ── Storage errors ─────────────────────────────────────────────────────────────

class StorageError(TrendRadarError):
    """Raised when storage operations fail."""


class StorageReadError(StorageError):
    """Raised when reading from storage fails."""


class StorageWriteError(StorageError):
    """Raised when writing to storage fails."""


# ── Notification errors ───────────────────────────────────────────────────────

class NotificationError(TrendRadarError):
    """Raised when notification sending fails."""

    def __init__(self, message: str, channel: str = "", *, cause: BaseException | None = None) -> None:
        super().__init__(message, cause=cause)
        self.channel = channel


class NotificationPartialFailure(NotificationError):
    """
    Raised when some batches of a notification send succeed but others fail.

    Based on: python-error-handling skill — partial failure handling pattern.
    """

    def __init__(self, channel: str, total_batches: int, success_count: int, failed_batches: list[int], *, cause: BaseException | None = None) -> None:
        message = f"[{channel}] 部分批次发送失败: {success_count}/{total_batches} 成功"
        super().__init__(message, channel=channel, cause=cause)
        self.total_batches = total_batches
        self.success_count = success_count
        self.failed_batches = failed_batches


# ── Config errors ──────────────────────────────────────────────────────────────

class ConfigError(TrendRadarError):
    """Raised when configuration is invalid or missing."""


class ValidationError(TrendRadarError):
    """Raised when data validation fails (fail-fast pattern)."""

    def __init__(self, message: str, field: str = "", *, cause: BaseException | None = None) -> None:
        super().__init__(message, cause=cause)
        self.field = field


# ── Batch Result (Partial Failure Handling) ────────────────────────────────────
# Based on: python-error-handling skill — BatchResult pattern

T = TypeVar("T")


@dataclass
class BatchSuccess(Generic[T]):
    """A successful item in a batch result."""
    index: int
    value: T


@dataclass
class BatchFailure:
    """A failed item in a batch result."""
    index: int
    error: str
    cause: BaseException | None = None


@dataclass
class BatchResult(Generic[T]):
    """
    Result of a batch operation that may partially succeed.

    Usage:
        result = translate_batch(titles)
        if result.successes:
            apply_translations(result.successes)
        if result.failures:
            handle_failures(result.failures)

    """
    successes: list[BatchSuccess[T]] = field(default_factory=list)
    failures: list[BatchFailure] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.successes) + len(self.failures)

    @property
    def all_succeeded(self) -> bool:
        return len(self.failures) == 0

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return len(self.successes) / self.total

    def __bool__(self) -> bool:
        return self.all_succeeded
