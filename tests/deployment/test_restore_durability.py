"""Restore failures must preserve evidence and never report a partial set as complete."""

import json
import os
import sqlite3
from pathlib import Path

import pytest

from trendradar.ops import backup
from trendradar.ops.maintenance import pending_restore_transactions, read_guard


def _prepare(tmp_path, monkeypatch, *, missing=False, nested=False):
    root = tmp_path / "runtime"
    databases = [
        root / ("stores/intelligence.db" if nested else "intelligence.db"),
        root / "ai_frontier.db",
    ]
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", str(tmp_path / "control"))
    monkeypatch.setenv("TRENDRADAR_LOCK_DIR", str(tmp_path / "locks"))
    for database in databases:
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE marker (value TEXT)")
            connection.execute("INSERT INTO marker VALUES ('snapshot')")
            connection.commit()
        finally:
            connection.close()
    snapshot = backup.create_snapshot(databases, tmp_path / "backups", root=root)
    for database in databases:
        connection = sqlite3.connect(database)
        try:
            connection.execute("UPDATE marker SET value='original'")
            connection.commit()
        finally:
            connection.close()
    if missing:
        databases[1].unlink()
    restored = tmp_path / "restored"
    backup.restore_snapshot(snapshot["path"], restored, guard_database=databases[0])
    return root, databases, restored


def _assert_original(databases, missing=False):
    for index, database in enumerate(databases):
        if missing and index == 1:
            assert not database.exists()
            continue
        assert database.is_file()
        connection = sqlite3.connect(database)
        try:
            assert connection.execute("SELECT value FROM marker").fetchone()[0] == "original"
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            connection.close()


def _prepared_journal(root, databases, restored, monkeypatch):
    write = backup._write_restore_journal

    def interrupt(path, payload):
        write(path, payload)
        if payload["state"] == "prepared":
            raise KeyboardInterrupt("test-only interruption after prepared journal")

    with monkeypatch.context() as injection:
        injection.setattr(backup, "_write_restore_journal", interrupt)
        with pytest.raises(KeyboardInterrupt):
            backup.activate_restore(restored, databases[0], root=root)
    journal = pending_restore_transactions(databases[0])[0]
    return journal, Path(journal["path"])


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory fsync")
def test_journal_directory_fsync_error_refuses_database_publication(tmp_path, monkeypatch):
    root, databases, restored = _prepare(tmp_path, monkeypatch)
    original = backup._sync_directory
    control = tmp_path / "control"

    def sync_directory(path):
        if path == control:
            raise OSError("synthetic journal directory fsync failure")
        original(path)

    # Inject the journal's directory sync, after the independent maintenance
    # marker has been persisted; a guard failure has a different boundary.
    monkeypatch.setattr(backup, "_sync_directory", sync_directory)
    with pytest.raises(OSError, match="journal directory fsync"):
        backup.activate_restore(restored, databases[0], root=root)
    _assert_original(databases)
    assert read_guard(databases[0]) is not None
    assert pending_restore_transactions(databases[0])


@pytest.mark.parametrize("phase", ["old_moved", "new_placed"])
@pytest.mark.parametrize("missing", [False, True])
def test_directory_fsync_error_after_rename_rolls_back_the_entire_set(
    tmp_path, monkeypatch, phase, missing,
):
    root, databases, restored = _prepare(tmp_path, monkeypatch, missing=missing)
    original = backup._sync_directory
    fired = False

    def sync(directory):
        nonlocal fired
        moved = list(directory.glob("*.db.pre-restore-*"))
        ready = moved and (not databases[0].exists() if phase == "old_moved" else databases[0].exists())
        if directory == databases[0].parent and not fired and ready:
            fired = True
            raise OSError("synthetic database directory fsync failure")
        original(directory)

    monkeypatch.setattr(backup, "_sync_directory", sync)
    with pytest.raises(OSError, match="database directory fsync"):
        backup.activate_restore(restored, databases[0], root=root)
    assert fired
    _assert_original(databases, missing)
    assert read_guard(databases[0]) is not None
    assert pending_restore_transactions(databases[0]) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX service metadata syscalls")
@pytest.mark.parametrize("method", ["chown", "chmod"])
@pytest.mark.parametrize("missing", [False, True])
def test_target_metadata_failure_preserves_originals_and_protection(
    tmp_path, monkeypatch, method, missing,
):
    root, databases, restored = _prepare(tmp_path, monkeypatch, missing=missing)
    original = getattr(backup.os, method)
    applied = 0

    def metadata(path, *args, **kwargs):
        nonlocal applied
        if Path(path).name.startswith(".restore-"):
            applied += 1
            if applied == 2:
                raise PermissionError("synthetic metadata denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(backup.os, method, metadata)
    with pytest.raises(PermissionError, match="metadata denied"):
        backup.activate_restore(restored, databases[0], root=root)
    _assert_original(databases, missing)
    assert read_guard(databases[0]) is not None
    assert not pending_restore_transactions(databases[0])
    journal = next((tmp_path / "control").glob("restore-activation-*.json"))
    assert json.loads(journal.read_text())["state"] == "rolled_back"


def test_recovery_uses_declared_runtime_root_for_nested_guarded_database(tmp_path, monkeypatch):
    root, databases, restored = _prepare(tmp_path, monkeypatch, nested=True)
    _prepared_journal(root, databases, restored, monkeypatch)
    assert backup.recover_restore(databases[0])["state"] == "rolled_back"
    _assert_original(databases)
    assert backup.recover_restore(databases[0])["recovered"] is False


@pytest.mark.parametrize("fault", [
    "path_type", "missing_digest", "cutover_type", "cutover_time", "cutover_naive", "root_type", "root_mismatch",
])
def test_invalid_recovery_fields_fail_before_any_database_change(tmp_path, monkeypatch, fault):
    root, databases, restored = _prepare(tmp_path, monkeypatch)
    journal, path = _prepared_journal(root, databases, restored, monkeypatch)
    if fault == "path_type":
        journal["destinations"][1] = {}
        journal["original_targets"][1]["path"] = {}
    elif fault == "missing_digest":
        manifest_path = Path(journal["previous_snapshot"]["path"]) / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        del manifest["databases"][0]["sha256"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif fault == "cutover_naive":
        journal["recovery_cutover_at"] = "2026-10-14T00:00:00"
    elif fault == "root_type":
        journal["runtime_root"] = []
    elif fault == "root_mismatch":
        journal["runtime_root"] = str(tmp_path)
    else:
        journal["recovery_cutover_at"] = {} if fault == "cutover_type" else "not-a-time"
    path.write_text(json.dumps(journal), encoding="utf-8")
    before = [database.read_bytes() for database in databases]
    with pytest.raises(RuntimeError):
        backup.recover_restore(databases[0])
    assert [database.read_bytes() for database in databases] == before
    assert read_guard(databases[0]) is not None
    assert pending_restore_transactions(databases[0])


def test_legacy_parent_root_recovery_mapping_remains_readable(tmp_path, monkeypatch):
    root, databases, restored = _prepare(tmp_path, monkeypatch)
    journal, path = _prepared_journal(root, databases, restored, monkeypatch)
    del journal["runtime_root"]
    path.write_text(json.dumps(journal), encoding="utf-8")
    manifest_path = Path(journal["previous_snapshot"]["path"]) / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["root"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert backup.recover_restore(databases[0])["state"] == "rolled_back"
    _assert_original(databases)


def test_snapshot_cannot_silently_include_an_originally_absent_target(tmp_path, monkeypatch):
    root, databases, restored = _prepare(tmp_path, monkeypatch)
    journal, path = _prepared_journal(root, databases, restored, monkeypatch)
    journal["original_targets"][1]["present"] = False
    path.write_text(json.dumps(journal), encoding="utf-8")
    manifest_path = Path(journal["previous_snapshot"]["path"]) / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["target_mapping"][1]["present"] = False
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = [file.read_bytes() for file in databases]
    with pytest.raises(RuntimeError, match="original database set"):
        backup.recover_restore(databases[0])
    assert [file.read_bytes() for file in databases] == before
    assert pending_restore_transactions(databases[0])


def test_failed_automatic_rollback_remains_pending_and_can_be_recovered(tmp_path, monkeypatch):
    root, databases, restored = _prepare(tmp_path, monkeypatch)
    replace = backup.os.replace
    sync = backup._sync_directory
    rolling_back = False

    def fail_publication(source, destination):
        nonlocal rolling_back
        if Path(source).name.startswith(".restore-") and Path(destination) == databases[1]:
            rolling_back = True
            raise OSError("synthetic second database publication failure")
        replace(source, destination)

    def fail_rollback_sync(directory):
        if rolling_back and directory == root:
            raise OSError("synthetic rollback directory fsync failure")
        sync(directory)

    with monkeypatch.context() as injection:
        injection.setattr(backup.os, "replace", fail_publication)
        injection.setattr(backup, "_sync_directory", fail_rollback_sync)
        with pytest.raises(OSError, match="rollback directory fsync"):
            backup.activate_restore(restored, databases[0], root=root)
    assert pending_restore_transactions(databases[0])[0]["state"] == "rolling_back"
    assert read_guard(databases[0]) is not None
    assert backup.recover_restore(databases[0])["state"] == "rolled_back"
    _assert_original(databases)
    assert backup.recover_restore(databases[0])["recovered"] is False
