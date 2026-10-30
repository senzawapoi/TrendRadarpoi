import json
import os
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trendradar.ops import backup_retention
from trendradar.ops.backup_retention import RetentionPolicy, prune_snapshots
from trendradar.ops.maintenance import set_guard

pytestmark = pytest.mark.skipif(os.name != "posix", reason="directory-fenced Linux retention")
shutil_usage = namedtuple("usage", "total used free")


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


def _sizes(path):
    return sum(child.stat().st_size for child in path.iterdir())


def test_shorter_windows_rotate_snapshots_faster(tmp_path):
    root, runtime = tmp_path / "backups", tmp_path / "output"
    now = datetime(2026, 10, 23, 3, tzinfo=timezone.utc)
    paths = [snapshot(root, runtime, now - timedelta(hours=i)) for i in range(24 * 10)]
    result = prune_snapshots(root, runtime, RetentionPolicy(hours=6, days=2, weeks=0))
    assert result["status"] == "complete"
    assert all(path.exists() for path in paths[:6])
    remaining = [path for path in root.iterdir() if path.is_dir()]
    assert 6 <= len(remaining) <= 8


def test_byte_budget_removes_oldest_retained_but_keeps_newest(tmp_path):
    root, runtime = tmp_path / "backups", tmp_path / "output"
    now = datetime(2026, 10, 23, 3, tzinfo=timezone.utc)
    paths = [snapshot(root, runtime, now - timedelta(hours=i)) for i in range(10)]
    budget = _sizes(paths[0]) * 3
    result = prune_snapshots(root, runtime, RetentionPolicy(max_bytes=budget))
    assert result["capacity_exceeded"] is False
    assert result["capacity_removed"] == [path.name for path in reversed(paths[3:])]
    assert all(path.exists() for path in paths[:3])
    assert not any(path.exists() for path in paths[3:])
    tiny = prune_snapshots(root, runtime, RetentionPolicy(max_bytes=1))
    assert tiny["capacity_exceeded"] is True
    assert [path.exists() for path in paths[:3]] == [True, True, False]


def test_free_space_floor_prunes_until_satisfied_and_spares_unmanaged(tmp_path, monkeypatch):
    root, runtime = tmp_path / "backups", tmp_path / "output"
    now = datetime(2026, 10, 23, 3, tzinfo=timezone.utc)
    paths = [snapshot(root, runtime, now - timedelta(hours=i)) for i in range(8)]
    evidence = snapshot(root, runtime, now - timedelta(days=30), retention_managed=False)

    def usage(_path):
        managed = sum(1 for path in paths if path.exists())
        return shutil_usage(total=100, used=50 + 5 * managed, free=50 - 5 * managed)

    monkeypatch.setattr(backup_retention.shutil, "disk_usage", usage)
    result = prune_snapshots(root, runtime, RetentionPolicy(min_free_ratio=0.3))
    assert result["capacity_exceeded"] is False
    assert sum(path.exists() for path in paths) == 4  # free 30/100 with four left
    assert evidence.exists()
    strict = prune_snapshots(root, runtime, RetentionPolicy(min_free_ratio=0.6))
    assert strict["capacity_exceeded"] is True
    assert [path.exists() for path in paths[:3]] == [True, True, False]
    assert evidence.exists()


def test_policy_from_environment_defaults_overrides_and_rejects_invalid_values():
    default = RetentionPolicy.from_environment({})
    assert (default.hours, default.days, default.weeks) == (24, 7, 4)
    assert default.max_bytes is None and default.min_free_ratio == 0.1
    custom = RetentionPolicy.from_environment({
        "TRENDRADAR_BACKUP_KEEP_HOURS": "12", "TRENDRADAR_BACKUP_KEEP_DAYS": "3",
        "TRENDRADAR_BACKUP_KEEP_WEEKS": "0", "TRENDRADAR_BACKUP_MAX_MIB": "2048",
        "TRENDRADAR_BACKUP_MIN_FREE_PERCENT": "20",
    })
    assert (custom.hours, custom.days, custom.weeks) == (12, 3, 0)
    assert custom.max_bytes == 2048 * 1024 * 1024 and custom.min_free_ratio == 0.2
    disabled = RetentionPolicy.from_environment({"TRENDRADAR_BACKUP_MIN_FREE_PERCENT": "0"})
    assert disabled.min_free_ratio is None
    for name, value in (("TRENDRADAR_BACKUP_KEEP_HOURS", "0"), ("TRENDRADAR_BACKUP_KEEP_DAYS", "x"),
                        ("TRENDRADAR_BACKUP_MAX_MIB", "-1"),
                        ("TRENDRADAR_BACKUP_MIN_FREE_PERCENT", "95")):
        with pytest.raises(ValueError, match=name):
            RetentionPolicy.from_environment({name: value})


def test_invalid_policy_fails_before_any_snapshot_is_written(tmp_path, monkeypatch):
    from trendradar.ops.backup import main

    runtime, destination = tmp_path / "output", tmp_path / "backups"
    runtime.mkdir()
    monkeypatch.setenv("TRENDRADAR_BACKUP_KEEP_HOURS", "0")
    with pytest.raises(SystemExit) as exited:
        main(["create", "--root", str(runtime), "--destination", str(destination),
              "--apply-retention"])
    assert exited.value.code == 2
    assert not destination.exists() or not any(destination.iterdir())


def test_real_snapshots_are_retention_candidates(tmp_path):
    from trendradar.intelligence.storage import IntelligenceStorage
    from trendradar.ops.backup import create_snapshot

    root, runtime = tmp_path / "backups", tmp_path / "output"
    runtime.mkdir()
    with IntelligenceStorage(runtime / "intelligence.db"):
        pass
    ids = [create_snapshot([runtime / "intelligence.db"], root, root=runtime,
                           retention_managed=True)["backup_id"] for _ in range(3)]
    result = prune_snapshots(root, runtime)
    # All three fall in one hour, so the hourly window keeps only the newest.
    assert sorted(result["removed"]) == sorted(ids[:2])
    assert (root / ids[2] / "database-0.db").is_file()


def test_legacy_validation_sidecars_do_not_block_pruning(tmp_path):
    root, runtime = tmp_path / "backups", tmp_path / "output"
    now = datetime(2026, 10, 23, 3, tzinfo=timezone.utc)
    paths = [snapshot(root, runtime, now - timedelta(hours=i)) for i in range(30)]
    for path in paths:
        (path / ".database-0.db.4242.tmp-wal").write_bytes(b"")
        (path / ".database-0.db.4242.tmp-shm").write_bytes(b"\0" * 32768)
    unsafe = [paths[26], paths[27]]
    (unsafe[0] / ".database-0.db.4242.tmp-wal").write_bytes(b"uncheckpointed frames")
    (unsafe[1] / ".database-3.db.4242.tmp-shm").write_bytes(b"")
    result = prune_snapshots(root, runtime, RetentionPolicy(hours=24, days=0, weeks=0))
    assert sorted(result["removed"]) == sorted(path.name for path in (*paths[24:26], *paths[28:]))
    assert all(path.exists() for path in (*paths[:24], *unsafe))
    assert not any(path.exists() for path in (*paths[24:26], *paths[28:]))


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
