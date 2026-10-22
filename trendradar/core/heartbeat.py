"""Atomic, non-sensitive role heartbeat files for local health inspection."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def heartbeat_directory(database_path: str | Path) -> Path:
    configured = os.environ.get("TRENDRADAR_HEALTH_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(database_path).expanduser().resolve().parent / "health"


class RoleHeartbeat:
    """Write a small atomic status document without logging user content."""

    def __init__(self, role: str, database_path: str | Path) -> None:
        if not role or any(char not in "abcdefghijklmnopqrstuvwxyz-_" for char in role):
            raise ValueError("invalid heartbeat role")
        self.role = role
        self.path = heartbeat_directory(database_path) / f"{role}.json"
        self.started_at = _now()

    def write(self, *, state: str, **fields: object) -> None:
        payload: dict[str, object] = {
            "role": self.role,
            "pid": os.getpid(),
            "started_at": self.started_at,
            "updated_at": _now(),
            "state": state,
            "release_id": os.environ.get("TRENDRADAR_RELEASE_ID", "unknown")[:128],
        }
        for key, value in fields.items():
            if key not in {"text", "content", "payload", "token", "secret"}:
                payload[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.role}-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=True, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary)

    def stop(self, *, reason: str = "stopped") -> None:
        self.write(state="stopped", reason=reason[:80])


__all__ = ["RoleHeartbeat", "heartbeat_directory"]
