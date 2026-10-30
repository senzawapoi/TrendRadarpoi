"""Retention for managed hourly snapshots; manual recovery evidence is untouched."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from trendradar.core.locking import ProcessFileLock
from trendradar.ops.maintenance import control_directory, read_guard


@dataclass(frozen=True)
class RetentionPolicy:
    """Time windows plus a capacity guard that never removes the newest ``min_keep``."""

    hours: int = 24
    days: int = 7
    weeks: int = 4
    max_bytes: int | None = None
    min_free_ratio: float | None = None
    min_keep: int = 2

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> RetentionPolicy:
        values = os.environ if environ is None else environ

        def number(name: str, default: int, minimum: int, maximum: int | None = None) -> int:
            raw = str(values.get(name, "")).strip()
            if not raw:
                return default
            try:
                parsed = int(raw)
            except ValueError:
                raise ValueError(f"{name} must be an integer") from None
            if parsed < minimum or (maximum is not None and parsed > maximum):
                raise ValueError(f"{name} is out of range")
            return parsed

        max_mib = number("TRENDRADAR_BACKUP_MAX_MIB", 0, 0)
        free_percent = number("TRENDRADAR_BACKUP_MIN_FREE_PERCENT", 10, 0, 90)
        return cls(
            hours=number("TRENDRADAR_BACKUP_KEEP_HOURS", 24, 1),
            days=number("TRENDRADAR_BACKUP_KEEP_DAYS", 7, 0),
            weeks=number("TRENDRADAR_BACKUP_KEEP_WEEKS", 4, 0),
            max_bytes=max_mib * 1024 * 1024 or None,
            min_free_ratio=free_percent / 100 or None,
        )


def _snapshot_bytes(original) -> int:
    return sum(entry[2] for entry in original[1][2])


def _over_capacity(root: Path, kept: list, policy: RetentionPolicy) -> bool:
    if policy.max_bytes is not None and sum(
        _snapshot_bytes(original) for _, _, original in kept
    ) > policy.max_bytes:
        return True
    if policy.min_free_ratio is not None:
        usage = shutil.disk_usage(root)
        return bool(usage.total) and usage.free / usage.total < policy.min_free_ratio
    return False


def _legacy_sidecar(child: Path, count: int) -> bool:
    """Read-only validation in older releases left these behind; an empty WAL holds no data."""
    match = re.fullmatch(r"\.database-(\d+)\.db\.\d+\.tmp-(wal|shm)", child.name)
    if match is None or int(match.group(1)) >= count:
        return False
    return match.group(2) == "shm" or child.stat().st_size == 0


def _candidate(path: Path, runtime: Path):
    if path.is_symlink() or not path.is_dir() or not re.fullmatch(r"\d{8}T\d{12}Z", path.name):
        return None
    try:
        manifest = path / "manifest.json"
        if manifest.is_symlink():
            return None
        raw = manifest.read_bytes()
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or data.get("complete") is not True
            or data.get("retention_managed") is not True
            or data.get("backup_id") != path.name
            or data.get("root") != str(runtime)
            or not isinstance(data.get("created_at"), str)
        ):
            return None
        created = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None or created.utcoffset() is None:
            return None
        entries = data["databases"]
        if not isinstance(entries, list) or not entries:
            return None
        names = {f"database-{i}.db" for i in range(len(entries))}
        if any(not isinstance(item, dict) or item.get("file") != f"database-{i}.db"
               for i, item in enumerate(entries)):
            return None
        children = list(path.iterdir())
        allowed = names | {"manifest.json", "offsite-manifest.json"}
        if (
            any(child.is_symlink() or not child.is_file()
                or (child.name not in allowed and not _legacy_sidecar(child, len(entries)))
                for child in children)
            or not names <= {child.name for child in children}
        ):
            return None
        stats = tuple(sorted((child.name, child.stat().st_ino, child.stat().st_size,
                              child.stat().st_mtime_ns) for child in children))
        fingerprint = (path.stat().st_ino, hashlib.sha256(raw).hexdigest(), stats)
        return created.astimezone(timezone.utc), fingerprint, tuple(sorted(c.name for c in children))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _protected(database: Path) -> bool:
    return read_guard(database) is not None or (
        control_directory(database) / "deploy-in-progress.json"
    ).exists()


def _remove_candidate(root: Path, path: Path, original) -> bool:
    """Anchor deletion to opened directories; a replaced path cannot redirect unlinks."""
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        directory_fd = os.open(
            path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd,
        )
        try:
            if os.fstat(directory_fd).st_ino != original[1][0]:
                return False
            names = tuple(sorted(os.listdir(directory_fd)))
            if names != original[2]:
                return False
            stats = []
            for name in names:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    return False
                stats.append((name, info.st_ino, info.st_size, info.st_mtime_ns))
            descriptor = os.open("manifest.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            with os.fdopen(descriptor, "rb") as stream:
                digest = hashlib.sha256(stream.read()).hexdigest()
            if digest != original[1][1] or tuple(stats) != original[1][2]:
                return False
            for name in names:
                os.unlink(name, dir_fd=directory_fd)
            current = os.stat(path.name, dir_fd=root_fd, follow_symlinks=False)
            if not stat.S_ISDIR(current.st_mode) or current.st_ino != original[1][0]:
                return False
            os.rmdir(path.name, dir_fd=root_fd)
            return True
        finally:
            os.close(directory_fd)
    finally:
        os.close(root_fd)


def prune_snapshots(
    destination: str | Path,
    runtime_root: str | Path,
    policy: RetentionPolicy | None = None,
) -> dict:
    """Keep the newest snapshot per hour, day and ISO week (a union), then enforce capacity."""
    policy = policy or RetentionPolicy()
    root = Path(destination).resolve()
    runtime = Path(runtime_root).resolve()
    database = runtime / "intelligence.db"
    if _protected(database):
        return {"status": "maintenance", "removed": []}
    if os.name != "posix":
        return {"status": "unsupported_platform", "removed": []}
    with ProcessFileLock(root / ".retention.lock"):
        candidates = []
        for path in root.iterdir():
            candidate = _candidate(path, runtime)
            if candidate is not None:
                candidates.append((candidate[0], path, candidate))
        candidates.sort(key=lambda item: (item[0], item[1].name), reverse=True)
        retained: set[Path] = set()
        hours, days, weeks = set(), set(), set()
        for created, path, _ in candidates:
            local = created.astimezone(ZoneInfo("Asia/Shanghai"))
            for group, key, count in (
                (hours, local.strftime("%Y-%m-%d-%H"), policy.hours),
                (days, local.date(), policy.days),
                (weeks, local.isocalendar()[:2], policy.weeks),
            ):
                if key not in group and len(group) < count:
                    group.add(key)
                    retained.add(path)
        removed = []
        for _, path, original in candidates:
            if path in retained:
                continue
            if _protected(database):
                return {"status": "maintenance", "removed": removed}
            # Recheck protection and file identity after enumeration. Never recurse into
            # a directory: a concurrently added note or nested recovery copy must survive.
            if path.resolve().parent != root or _candidate(path, runtime) != original:
                continue
            try:
                if _remove_candidate(root, path, original):
                    removed.append(path.name)
            except OSError:
                # Unknown/new entries are retained; never force recursive removal.
                continue
        # Capacity: drop the oldest retained snapshots until the byte budget and free-space
        # floor hold, never below the newest ``min_keep``. Unmanaged evidence is never counted.
        kept = [item for item in candidates if item[1] in retained]
        capacity_removed = []
        while len(kept) > policy.min_keep and _over_capacity(root, kept, policy):
            _, path, original = kept[-1]
            if _protected(database):
                return {"status": "maintenance", "removed": removed + capacity_removed}
            if path.resolve().parent != root or _candidate(path, runtime) != original:
                break
            try:
                if not _remove_candidate(root, path, original):
                    break
            except OSError:
                break
            kept.pop()
            capacity_removed.append(path.name)
        return {
            "status": "complete",
            "retained": len(kept),
            "removed": removed + capacity_removed,
            "capacity_removed": capacity_removed,
            "capacity_exceeded": _over_capacity(root, kept, policy),
        }
