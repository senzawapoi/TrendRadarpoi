"""Abrupt process death must leave a recoverable, guarded database set."""

import json
import os
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from trendradar.ops.backup import (
    create_snapshot,
    pending_restore_transactions,
    recover_restore,
    restore_snapshot,
)
from trendradar.ops.maintenance import clear_guard, read_guard

from .test_installer_behavior import assert_restart_protected

CHILD = r'''
import os, sys
from pathlib import Path
import trendradar.ops.backup as backup

phase, restored, database, root = sys.argv[1:]
original_write = backup._write_restore_journal
original_replace = backup.os.replace

def stop():
    # Abrupt exit bypasses except/finally on all platforms. Linux additionally
    # uses an actual SIGKILL, scoped to this child's own PID.
    if sys.platform == "linux":
        import signal
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(91)

def write(path, payload):
    original_write(path, payload)
    if phase == "prepared" and payload["state"] == "prepared":
        stop()
    if (phase == "operation_planned" and payload["operations"]
            and payload["current_operation"] is not None):
        stop()
    if phase == "first_complete" and len(payload["installed"]) == 1:
        stop()

def replace(source, destination):
    original_replace(source, destination)
    if phase == "old_moved" and ".pre-restore-" in str(destination):
        stop()
    if phase == "new_placed" and Path(source).name.startswith(".restore-") and Path(destination).suffix == ".db":
        stop()

backup._write_restore_journal = write
backup.os.replace = replace
backup.activate_restore(restored, database, root=root)
'''


WAL_WRITER = r'''
import os,sqlite3,sys
connections=[]
for index,path in enumerate(sys.argv[1:]):
    connection=sqlite3.connect(path)
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA wal_autocheckpoint=0')
    connection.execute(f'PRAGMA user_version={20 + index}')
    connection.execute("UPDATE marker SET value='before-restore'")
    connection.commit()
    connections.append(connection)
os._exit(91)
'''


def _prepare(tmp_path, monkeypatch, second_missing=False):
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", str(tmp_path / "control"))
    monkeypatch.setenv("TRENDRADAR_LOCK_DIR", str(tmp_path / "locks"))
    databases = [output / "intelligence.db", output / "ai_frontier.db", output / "news/2026-10-14.db"]
    for index, database in enumerate(databases):
        database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA user_version={10 + index}")
            connection.execute("CREATE TABLE marker (value TEXT PRIMARY KEY)")
            connection.execute("INSERT INTO marker VALUES ('desired-snapshot')")
            connection.execute(
                "CREATE TABLE marker_reference (value TEXT NOT NULL "
                "REFERENCES marker(value) ON UPDATE CASCADE)"
            )
            connection.execute("INSERT INTO marker_reference VALUES ('desired-snapshot')")
        connection.close()
    snapshot = create_snapshot(databases, tmp_path / "backups", root=output)
    writer = subprocess.run([sys.executable, "-B", "-c", WAL_WRITER, *map(str, databases)],
                            capture_output=True, timeout=15)
    assert writer.returncode == 91, writer.stderr
    for database in databases:
        assert Path(str(database) + "-wal").stat().st_size > 0
        assert Path(str(database) + "-shm").is_file()
    if second_missing:
        databases[1].unlink()
    restored = tmp_path / "restored"
    restore_snapshot(snapshot["path"], restored, guard_database=databases[0])
    return output, databases, restored


def _interrupt(output, databases, restored, phase):
    process = subprocess.run([
        sys.executable, "-B", "-c", CHILD, phase, str(restored), str(databases[0]), str(output),
    ], capture_output=True, timeout=30)
    assert process.returncode == (-signal.SIGKILL if sys.platform == "linux" else 91), process.stderr


def _assert_original_graph(database, index):
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (20 + index,)
        assert connection.execute("SELECT value FROM marker").fetchall() == [("before-restore",)]
        assert connection.execute("SELECT value FROM marker_reference").fetchall() == [
            ("before-restore",),
        ]
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def _assert_interrupted_mapping(journal, output, databases, restored, phase, second_missing):
    assert journal["state"] == ("prepared" if phase == "prepared" else "installing")
    assert journal["runtime_root"] == str(output)
    assert journal["destinations"] == list(map(str, databases))
    assert journal["sources"] == [str(restored / f"database-{index}.db") for index in range(3)]
    expected_mapping = [
        {"relative_path": str(database.relative_to(output)).replace("\\", "/"),
         "present": not (second_missing and index == 1)}
        for index, database in enumerate(databases)
    ]
    assert [item["present"] for item in journal["original_targets"]] == [
        item["present"] for item in expected_mapping
    ]
    previous = json.loads((Path(journal["previous_snapshot"]["path"]) / "manifest.json").read_text())
    assert previous["target_mapping"] == expected_mapping
    assert journal["installed"] == ([str(databases[0])] if phase == "first_complete" else [])
    if phase == "prepared":
        assert journal["operations"] == []
        assert journal["retained"] == []
    else:
        operation, = journal["operations"]
        assert operation["destination"] == str(databases[0])
        assert operation["installed"] is (phase == "first_complete")
        assert {item["original"] for item in operation["retained_plan"]} == {
            str(databases[0]) + suffix for suffix in ("", "-wal", "-shm")
        }
        assert all(Path(item["retained"]).parent == databases[0].parent
                   for item in operation["retained_plan"])
        if phase == "operation_planned":
            assert journal["retained"] == []
            assert all(Path(item["original"]).is_file()
                       and not Path(item["retained"]).exists()
                       for item in operation["retained_plan"])
        elif phase == "old_moved":
            first = operation["retained_plan"][0]
            assert Path(first["retained"]).is_file()
            assert not Path(first["original"]).exists()
        elif phase == "new_placed":
            assert all(Path(item["retained"]).is_file()
                       for item in operation["retained_plan"])
            assert Path(str(databases[0])).is_file()
            assert all(not Path(item["original"]).exists()
                       for item in operation["retained_plan"]
                       if item["original"].endswith(("-wal", "-shm")))
            assert Path(operation["destination"]).is_file()


def _assert_crash_entries_protected(tmp_path, databases):
    config = tmp_path / "entry-config.yaml"
    config.write_text("intelligence:\n  enabled: true\n", encoding="utf-8")
    environment = {
        **{key: os.environ[key] for key in ("PATH", "SystemRoot", "TEMP", "TMP")
           if key in os.environ},
        "CONFIG_PATH": str(config),
        "INTELLIGENCE_DB_PATH": str(databases[0]),
        "AI_FRONTIER_DB_PATH": str(databases[1]),
        "TRENDRADAR_CONTROL_DIR": str(tmp_path / "control"),
        "TRENDRADAR_LOCK_DIR": str(tmp_path / "locks"),
        "TRENDRADAR_HEALTH_DIR": str(tmp_path / "entry-health"),
        "TRENDRADAR_BACKUP_DIR": str(tmp_path / "backups"),
        "PYTHONPATH": os.pathsep.join(sys.path),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GEMINI_ENABLED": "false",
    }
    assert_restart_protected(environment, databases[0])


@pytest.mark.parametrize(
    "phase", ["prepared", "operation_planned", "old_moved", "new_placed", "first_complete"],
)
@pytest.mark.parametrize("second_missing", [False, True])
def test_abrupt_restore_death_and_idempotent_complete_rollback(tmp_path, monkeypatch, phase, second_missing):
    output, databases, restored = _prepare(tmp_path, monkeypatch, second_missing)
    _interrupt(output, databases, restored, phase)
    pending = pending_restore_transactions(databases[0])
    assert len(pending) == 1
    _assert_interrupted_mapping(pending[0], output, databases, restored, phase, second_missing)
    assert read_guard(databases[0]) is not None
    journal_path = Path(pending[0]["path"])
    journal_before = journal_path.read_bytes()
    _assert_crash_entries_protected(tmp_path, databases)
    assert journal_path.read_bytes() == journal_before
    with pytest.raises(RuntimeError, match="incomplete restore"):
        clear_guard(databases[0])
    recovered = recover_restore(databases[0])
    assert recovered["state"] == "rolled_back"
    for index, database in enumerate(databases):
        if second_missing and database == databases[1]:
            assert not database.exists()
            assert not Path(str(database) + "-wal").exists()
            assert not Path(str(database) + "-shm").exists()
        else:
            _assert_original_graph(database, index)
    assert recover_restore(databases[0]) == {"recovered": False, "pending": []}
    assert pending_restore_transactions(databases[0]) == []
    assert clear_guard(databases[0])
    assert read_guard(databases[0]) is None
    assert json.loads(Path(recovered["transaction"]).read_text())["state"] == "rolled_back"


def test_interrupted_recovery_can_be_repeated_from_consistent_snapshot(tmp_path, monkeypatch):
    output, databases, restored = _prepare(tmp_path, monkeypatch)
    _interrupt(output, databases, restored, "first_complete")
    code = r'''
import os,sys
from pathlib import Path
import trendradar.ops.backup as backup
original=backup.os.replace
def replace(source,destination):
    original(source,destination)
    if Path(source).name.startswith('.rollback-'):
        if sys.platform=='linux':
            import signal
            os.kill(os.getpid(),signal.SIGKILL)
        os._exit(91)
backup.os.replace=replace
backup.recover_restore(sys.argv[1])
'''
    process = subprocess.run([sys.executable, "-B", "-c", code, str(databases[0])],
                             capture_output=True, timeout=30)
    assert process.returncode == (-signal.SIGKILL if sys.platform == "linux" else 91), process.stderr
    assert pending_restore_transactions(databases[0])[0]["state"] == "rolling_back"
    assert read_guard(databases[0]) is not None
    assert recover_restore(databases[0])["state"] == "rolled_back"
    for index, database in enumerate(databases):
        _assert_original_graph(database, index)
    assert recover_restore(databases[0])["recovered"] is False


@pytest.mark.parametrize("fault", ["destination", "snapshot", "metadata", "mapping"])
def test_recovery_refuses_corrupt_mapping_before_replacing_files(tmp_path, monkeypatch, fault):
    output, databases, restored = _prepare(tmp_path, monkeypatch)
    _interrupt(output, databases, restored, "prepared")
    journal = pending_restore_transactions(databases[0])[0]
    if fault == "destination":
        escaped = str(tmp_path / "outside.db")
        journal["original_targets"][1]["path"] = escaped
        journal["destinations"][1] = escaped
    elif fault == "snapshot":
        journal["previous_snapshot"]["path"] = str(tmp_path / "outside-snapshot")
    elif fault == "metadata":
        journal["original_targets"][0]["metadata"] = {"uid": True, "gid": 0, "mode": 0o777}
    else:
        manifest_path = Path(journal["previous_snapshot"]["path"]) / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["target_mapping"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    Path(journal["path"]).write_text(json.dumps(journal), encoding="utf-8")
    before = [file.read_bytes() for file in databases]
    with pytest.raises(RuntimeError):
        recover_restore(databases[0])
    assert [file.read_bytes() for file in databases] == before
    assert read_guard(databases[0]) is not None
    assert not (tmp_path / "outside.db").exists()


@pytest.mark.parametrize("failure", ["copy", "switch"])
@pytest.mark.parametrize("second_missing", [False, True])
def test_restore_io_failure_keeps_original_set_and_guard(tmp_path, monkeypatch, failure, second_missing):
    import trendradar.ops.backup as backup

    output, databases, restored = _prepare(tmp_path, monkeypatch, second_missing)
    if failure == "copy":
        original = backup.shutil.copyfile

        def copy(source, destination, *args, **kwargs):
            if Path(destination).name.startswith(".restore-"):
                raise PermissionError("synthetic target copy denied")
            return original(source, destination, *args, **kwargs)

        monkeypatch.setattr(backup.shutil, "copyfile", copy)
    else:
        original = backup.os.replace

        def replace(source, destination):
            if Path(source).name.startswith(".restore-") and Path(destination).suffix == ".db":
                raise OSError("synthetic target switch denied")
            return original(source, destination)

        monkeypatch.setattr(backup.os, "replace", replace)
    with pytest.raises(OSError):
        backup.activate_restore(restored, databases[0], root=output)
    assert read_guard(databases[0]) is not None
    assert not pending_restore_transactions(databases[0])
    for database in databases:
        if second_missing and database == databases[1]:
            assert not database.exists()
        else:
            connection = sqlite3.connect(database)
            try:
                assert connection.execute("SELECT value FROM marker").fetchone()[0] == "before-restore"
            finally:
                connection.close()
