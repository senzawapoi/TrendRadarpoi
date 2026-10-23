import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trendradar.ops.backup_retention import prune_snapshots
from trendradar.ops.maintenance import set_guard

pytestmark = pytest.mark.skipif(os.name != "posix", reason="directory-fenced Linux retention")


def snapshot(destination, runtime, created, **overrides):
    name = created.strftime("%Y%m%dT%H%M%S%fZ")
    path = destination / name
    path.mkdir(parents=True)
    (path / "database-0.db").write_bytes(b"test snapshot")
    payload = {"backup_id": name, "created_at": created.isoformat(), "root": str(runtime),
               "retention_managed": True, "complete": True,
               "databases": [{"file": "database-0.db"}]}
    payload.update(overrides)
    (path / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_retention_keeps_hour_day_week_union_and_is_idempotent(tmp_path):
    root, runtime = tmp_path / "backups", tmp_path / "output"
    now = datetime(2026, 10, 23, 3, tzinfo=timezone.utc)
    paths = [snapshot(root, runtime, now - timedelta(hours=i)) for i in range(24 * 40)]
    result = prune_snapshots(root, runtime)
    assert result["status"] == "complete" and result["removed"]
    assert all(path.exists() for path in paths[:24])
    assert paths[132].exists()  # October 17 at 23:00 Asia/Shanghai, newest of that day.
    assert paths[276].exists()  # October 11 at 23:00, retained by the weekly policy.
    remaining = sorted(path for path in root.iterdir() if path.is_dir())
    assert 24 < len(remaining) <= 35
    assert prune_snapshots(root, runtime)["removed"] == []


def test_retention_preserves_unmanaged_incomplete_foreign_and_unknown_files(tmp_path):
    root, runtime = tmp_path / "backups", tmp_path / "output"
    now = datetime(2026, 10, 23, tzinfo=timezone.utc)
    for index in range(40):
        snapshot(root, runtime, now - timedelta(hours=index))
    protected = [
        snapshot(root, runtime, now - timedelta(days=90), retention_managed=False),
        snapshot(root, runtime, now - timedelta(days=91), complete=False),
        snapshot(root, runtime, now - timedelta(days=92), root="/somewhere/else"),
        snapshot(root, runtime, now - timedelta(days=93)),
    ]
    (protected[-1] / "operator-notes.txt").write_text("keep")
    prune_snapshots(root, runtime)
    assert all(path.exists() for path in protected)


def test_retention_stops_during_maintenance(tmp_path):
    root, runtime = tmp_path / "backups", tmp_path / "output"
    root.mkdir()
    set_guard(runtime / "intelligence.db", reason="test recovery")
    assert prune_snapshots(root, runtime) == {"status": "maintenance", "removed": []}


@pytest.mark.parametrize("protection", ["unmanaged", "notes"])
def test_retention_rechecks_protection_after_scan(tmp_path, monkeypatch, protection):
    root, runtime = tmp_path / "backups", tmp_path / "output"
    now = datetime(2026, 10, 23, 3, tzinfo=timezone.utc)
    paths = [snapshot(root, runtime, now - timedelta(hours=i)) for i in range(80)]
    target = paths[25]
    original_iterdir = Path.iterdir

    def changing_directory(path):
        yield from original_iterdir(path)
        if path == root:
            if protection == "unmanaged":
                manifest = target / "manifest.json"
                data = json.loads(manifest.read_text())
                data["retention_managed"] = False
                manifest.write_text(json.dumps(data))
            else:
                (target / "operator-notes.txt").write_text("preserve recovery evidence")

    monkeypatch.setattr(Path, "iterdir", changing_directory)
    result = prune_snapshots(root, runtime)
    assert target.name not in result["removed"]
    assert (target / "database-0.db").read_bytes() == b"test snapshot"
    assert (target / "manifest.json").is_file()


@pytest.mark.parametrize("invalid_time", [None, 4, [], {}])
def test_retention_preserves_malformed_time_and_prunes_valid_snapshots(tmp_path, invalid_time):
    root, runtime = tmp_path / "backups", tmp_path / "output"
    now = datetime(2026, 10, 23, 3, tzinfo=timezone.utc)
    for index in range(80):
        snapshot(root, runtime, now - timedelta(hours=index))
    malformed = snapshot(root, runtime, now - timedelta(days=100), created_at=invalid_time)
    result = prune_snapshots(root, runtime)
    assert result["status"] == "complete" and result["removed"]
    assert (malformed / "database-0.db").is_file()


def test_directory_swap_cannot_redirect_deletion(tmp_path, monkeypatch):
    from trendradar.ops import backup_retention

    root, runtime = tmp_path / "backups", tmp_path / "output"
    now = datetime(2026, 10, 23, 3, tzinfo=timezone.utc)
    paths = [snapshot(root, runtime, now - timedelta(hours=i)) for i in range(80)]
    target = paths[25]
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    for name in ("database-0.db", "manifest.json"):
        (foreign / name).write_text("must remain")
    original_unlink = os.unlink
    replaced = False

    def swap_before_unlink(path, *, dir_fd=None):
        nonlocal replaced
        if not replaced and dir_fd is not None and os.fstat(dir_fd).st_ino == target.stat().st_ino:
            replaced = True
            target.rename(root / "retained-original")
            target.symlink_to(foreign, target_is_directory=True)
        return original_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(backup_retention.os, "unlink", swap_before_unlink)
    prune_snapshots(root, runtime)
    assert replaced
    assert (foreign / "database-0.db").read_text() == "must remain"
    assert (foreign / "manifest.json").read_text() == "must remain"
