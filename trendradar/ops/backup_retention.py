"""Retention for managed hourly snapshots; manual recovery evidence is untouched."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from trendradar.core.locking import ProcessFileLock
from trendradar.ops.maintenance import control_directory, read_guard


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
            any(child.is_symlink() or not child.is_file() or child.name not in allowed
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


def prune_snapshots(destination: str | Path, runtime_root: str | Path) -> dict:
    """Keep the newest snapshot in 24 hours, 7 days and 4 ISO weeks, as a union."""
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
                (hours, local.strftime("%Y-%m-%d-%H"), 24),
                (days, local.date(), 7),
                (weeks, local.isocalendar()[:2], 4),
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
        return {"status": "complete", "retained": len(retained), "removed": removed}
