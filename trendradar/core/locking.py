"""Small cross-process locks for role and collection exclusivity.

The lock is held by the process, rather than inferred from a PID file.  The
directory is deliberately configurable so Linux services can use ``/run``
while local tests use a temporary directory next to their database.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

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


__all__ = ["LockUnavailable", "ProcessFileLock", "lock_directory", "runtime_locks"]
