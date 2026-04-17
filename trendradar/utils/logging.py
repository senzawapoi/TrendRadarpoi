"""
Structured logging with correlation IDs.

Uses structlog with ContextVar for request-scoped correlation IDs,
timed context manager for operation duration tracking, and console output
with colors. Integrates with the project's print-based patterns via a
`log` singleton and a `@timed` decorator.

Based on: python-observability skill (structlog, correlation IDs,
four golden signals, timed context manager)
"""

from __future__ import annotations

import sys
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any

import structlog

# ── Correlation ID ──────────────────────────────────────────────────────────

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)


def get_correlation_id() -> str:
    """Get current correlation ID or generate a new one."""
    cid = _correlation_id.get()
    if cid is None:
        cid = str(uuid.uuid4())[:8]
        _correlation_id.set(cid)
    return cid


def get_run_id() -> str:
    """Get current run ID (stable for the lifetime of one process)."""
    rid = _run_id.get()
    if rid is None:
        rid = str(uuid.uuid4())[:8]
        _run_id.set(rid)
    return rid


@contextmanager
def correlation_context(cid: str | None = None):
    """Temporarily override correlation ID within a context block."""
    token = None
    if cid is not None:
        token = _correlation_id.set(cid)
    try:
        yield get_correlation_id()
    finally:
        if token is not None:
            _correlation_id.reset(token)


# ── Timing ───────────────────────────────────────────────────────────────────

@contextmanager
def timed(operation: str, *, log: Log | None = None):
    """Context manager that logs duration of an operation."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if log is not None:
            log.info(f"{operation} completed", duration_ms=round(elapsed_ms, 1))
        else:
            _log.info(f"{operation} completed", duration_ms=round(elapsed_ms, 1))


def timed_fn(operation: str | None = None) -> Callable[[Callable], Callable]:
    """Decorator that logs function execution time."""
    def decorator(func: Callable) -> Callable:
        name = operation or func.__name__
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                _log.info(f"{name} completed", duration_ms=round(elapsed_ms, 1), func=name)
        return wrapper
    return decorator


# ── structlog configuration ─────────────────────────────────────────────────

def _add_run_id(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Processor that adds run_id to every log entry."""
    event_dict["run_id"] = get_run_id()
    event_dict["cid"] = get_correlation_id()
    return event_dict


def _console_renderer(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> list[str]:
    """Simple console renderer that mimics print output with prefixes."""
    level = method_name.upper()
    # Use emoji prefixes that match the existing print patterns
    emoji = {
        "info": "  ",
        "warning": "⚠️ ",
        "error": "❌",
        "exception": "❌",
        "debug": "  ",
        "critical": "❌",
    }.get(method_name.lower(), "  ")

    # Format duration if present
    duration = ""
    if (dur := event_dict.pop("duration_ms", None)) is not None:
        duration = f" [{dur}ms]"

    # Remove internal fields
    event_dict.pop("run_id", None)
    event_dict.pop("cid", None)
    event_dict.pop("logger", None)
    event_dict.pop("level", None)

    # structlog puts the positional message in "event"
    msg = event_dict.pop("event", event_dict.pop("message", ""))
    # Build remaining fields as key=value pairs
    extras = ""
    if event_dict:
        parts = [f"{k}={v}" for k, v in event_dict.items()]
        extras = " | " + " | ".join(parts)

    output = f"{emoji}[{level}]{duration} {msg}{extras}"
    return output


def configure_logging(debug: bool = False) -> None:
    """Configure structlog with console output and correlation ID processor."""
    # Ensure stdout can print emojis on Windows (GBK -> UTF-8)
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_run_id,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
            _console_renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


# ── Public API ───────────────────────────────────────────────────────────────

def get_logger(name: str = "trendradar") -> structlog.stdlib.BoundLogger:
    """Get a structured logger for the given name."""
    return structlog.get_logger(name)


# Pre-configure on module import
configure_logging()

# Default logger instance (singleton)
_log = get_logger("trendradar")


class Log:
    """
    Drop-in replacement for print-based logging.

    Usage:
        from trendradar.utils.logging import log

        log.info("Starting application")
        log.warning("Something unexpected", key="value")
        log.error("Operation failed", error=str(e))
        log.debug("Detailed info", detail=some_data)

    For correlating with existing print output, use the emoji-matched renderer
    so logs appear alongside print statements without visual confusion.
    """

    def __init__(self, name: str = "trendradar") -> None:
        self._logger = get_logger(name)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._logger.info(msg, **kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._logger.warning(msg, **kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._logger.error(msg, **kwargs)

    def exception(self, msg: str, **kwargs: Any) -> None:
        self._logger.exception(msg, **kwargs)

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._logger.debug(msg, **kwargs)

    def critical(self, msg: str, **kwargs: Any) -> None:
        self._logger.critical(msg, **kwargs)

    # Convenience methods matching existing print patterns
    def success(self, msg: str, **kwargs: Any) -> None:
        """Log success (maps to INFO level with ✅ prefix)."""
        self._logger.info(f"✅ {msg}", **kwargs)

    def skip(self, msg: str, **kwargs: Any) -> None:
        """Log skipped operations (maps to INFO level with ⏭️ prefix)."""
        self._logger.info(f"⏭️ {msg}", **kwargs)

    def start(self, msg: str, **kwargs: Any) -> None:
        """Log start of an operation (maps to INFO level with 🔄 prefix)."""
        self._logger.info(f"🔄 {msg}", **kwargs)


# Module-level singleton for easy import
log = Log()
