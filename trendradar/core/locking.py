"""Small cross-process locks for role and collection exclusivity.

The lock is held by the process, rather than inferred from a PID file.  The
directory is deliberately configurable so Linux services can use ``/run``
while local tests use a temporary directory next to their database.
"""

from __future__ import annotations

import errno
import math
import os
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

try:  # pragma: no cover - the branch depends on the host operating system.
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows only.
    fcntl = None

try:  # pragma: no cover - exercised on Windows only.
    import msvcrt
except ImportError:  # pragma: no cover - Linux does not provide msvcrt.
    msvcrt = None


class LockUnavailable(RuntimeError):
    """Raised when another process owns a requested runtime lock."""


class ProcessFileLock:
    """Non-blocking OS lock backed by a stable file path."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif msvcrt is not None:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover
                raise LockUnavailable("no supported OS lock implementation")
        except (BlockingIOError, OSError) as exc:
            handle.close()
            raise LockUnavailable(f"runtime lock is busy: {self.path}") from exc
        self._handle = handle

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            handle.close()

    def __enter__(self) -> ProcessFileLock:
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


def lock_directory(database_path: str | Path) -> Path:
    """Return the stable lock directory for a runtime database."""
    configured = os.environ.get("TRENDRADAR_LOCK_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(database_path).expanduser().resolve().parent / "locks"


@contextmanager
def runtime_locks(database_path: str | Path, *roles: str) -> Iterator[None]:
    """Acquire role locks in lexical order and release them in reverse order."""
    accepted = {"bot", "worker", "scheduler", "collector"}
    requested = tuple(sorted(set(roles)))
    if not requested or any(role not in accepted for role in requested):
        raise ValueError("invalid or empty runtime lock set")
    with ExitStack() as stack:
        root = lock_directory(database_path)
        for role in requested:
            stack.enter_context(ProcessFileLock(root / f"{role}.lock"))
        yield


class CollectionBlocked(RuntimeError):
    """Maintenance forbids collection before upstream I/O."""


class CollectionTimeout(LockUnavailable):
    """The shared collector slot remained busy until the deadline."""


def collector_wait_seconds() -> float:
    """Parse the opt-in environment setting without exposing its input."""
    try:
        value = float(os.environ.get("TRENDRADAR_COLLECTOR_WAIT_SECONDS", "0"))
    except (ValueError, TypeError):
        raise ValueError("invalid collector wait; expected finite seconds in 0..1800") from None
    if not math.isfinite(value) or not 0 <= value <= 1800:
        raise ValueError("invalid collector wait; expected finite seconds in 0..1800")
    return value


@dataclass
class CollectorAttempt:
    """Monotonic timings for one real invocation, never a calendar identity."""

    collector: str
    emit: Callable[..., None] | None
    clock: Callable[[], float]
    attempt_id: str
    started: float
    acquired_at: float | None = None

    @property
    def wait_seconds(self) -> float:
        end = self.clock() if self.acquired_at is None else self.acquired_at
        return max(0., end - self.started)

    def record(self, state: str) -> None:
        if self.emit is not None:
            self.emit(
                state=state, collector=self.collector, attempt_id=self.attempt_id,
                wait_seconds=self.wait_seconds,
                run_seconds=(0. if self.acquired_at is None
                             else max(0., self.clock() - self.acquired_at)),
            )


class _CollectorLock(Protocol):
    def acquire(self) -> None: ...
    def release(self) -> None: ...


@contextmanager
def collector_slot(
    database_path: str | Path, *, wait_seconds: float = 0.,
    blocked: Callable[[], bool] = lambda: False,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    lock_factory: Callable[[Path], _CollectorLock] = ProcessFileLock,
    collector: str = "main", emit: Callable[..., None] | None = None,
) -> Iterator[CollectorAttempt]:
    """Wait only for confirmed OS contention; never replay the protected body."""
    if (type(wait_seconds) not in (int, float) or not math.isfinite(wait_seconds)
            or not 0 <= wait_seconds <= 1800):
        raise ValueError("invalid collector wait; expected finite seconds in 0..1800")
    if collector not in {"main", "ai"}:
        raise ValueError("invalid collector role")
    attempt = CollectorAttempt(collector, emit, clock, uuid.uuid4().hex, clock())
    deadline = attempt.started + wait_seconds
    lock = lock_factory(lock_directory(database_path) / "collector.lock")
    waited = False
    try:
        while True:
            if blocked():
                raise CollectionBlocked("collection blocked by maintenance")
            # A deadline reached during sleep must not permit a late acquisition.
            if waited and clock() >= deadline:
                raise CollectionTimeout("collector wait timed out")
            try:
                lock.acquire()
                break
            except LockUnavailable as exc:
                cause = exc.__cause__
                busy = {errno.EAGAIN, errno.EWOULDBLOCK}
                if os.name == "nt":
                    busy.add(errno.EACCES)
                if not isinstance(cause, OSError) or cause.errno not in busy:
                    if isinstance(cause, OSError):
                        raise cause from None
                    raise
                remaining = deadline - clock()
                if remaining <= 0:
                    raise CollectionTimeout("collector wait timed out") from exc
                if not waited:
                    attempt.record("waiting")
                    waited = True
                sleep(min(1., remaining))
    except CollectionBlocked:
        attempt.record("maintenance")
        raise
    except CollectionTimeout:
        attempt.record("timeout")
        raise
    except BaseException:
        attempt.record("failed")
        raise
    try:
        if blocked():
            attempt.record("maintenance")
            raise CollectionBlocked("collection blocked by maintenance")
        attempt.acquired_at = clock()
        attempt.record("acquired")
        try:
            yield attempt
        except BaseException:
            attempt.record("failed")
            raise
    finally:
        lock.release()


__all__ = [
    "CollectionBlocked",
    "CollectionTimeout",
    "LockUnavailable",
    "ProcessFileLock",
    "collector_slot",
    "collector_wait_seconds",
    "lock_directory",
    "runtime_locks",
]
