"""Check restore metadata and SQLite access using actual non-root Linux UIDs."""

import hashlib
import io
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from trendradar.ops.backup import activate_restore, create_snapshot, restore_snapshot
from trendradar.ops.maintenance import pending_restore_transactions, read_guard

from .installer_harness import make_installer

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="requires isolated Linux root and UID switching",
)


@pytest.mark.parametrize("mode", [0o600, 0o660])
def test_restore_keeps_service_metadata_and_real_uid_can_write(tmp_path, monkeypatch, mode):
    # Only the private test tree is opened for traversal, never a runtime tree.
    for parent in (tmp_path, tmp_path.parent, tmp_path.parent.parent):
        parent.chmod(0o755)
    output = tmp_path / "output"
    output.mkdir(mode=0o750)
    os.chown(output, 65534, 65534)
    monkeypatch.setenv("TRENDRADAR_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", str(tmp_path / "control"))
    databases = [output / "intelligence.db", output / "ai_frontier.db", output / "news.db"]
    for database in databases:
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE marker (value TEXT)")
            connection.execute("INSERT INTO marker VALUES ('original')")
        os.chown(database, 65534, 65534)
        database.chmod(mode)
    snapshot = create_snapshot(databases, tmp_path / "backups", root=output)
    restored = tmp_path / "restored"
    restore_snapshot(snapshot["path"], restored, guard_database=databases[0])
    activate_restore(restored, databases[0], root=output)
    for database in databases:
        info = database.stat()
        assert (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (65534, 65534, mode)
        script = (
            "import os,sqlite3,sys; os.setgroups([]); os.setgid(65534); os.setuid(65534); "
            "db=sqlite3.connect(sys.argv[1]); "
            "assert db.execute('SELECT value FROM marker').fetchone()[0]=='original'; "
            "assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'; "
            "db.execute(\"UPDATE marker SET value='service-written'\"); db.commit(); db.close()"
        )
        result = subprocess.run([sys.executable, "-c", script, str(database)], capture_output=True)
        assert result.returncode == 0, result.stderr.decode()
        denied = subprocess.run([
            sys.executable, "-c",
            "import os,sqlite3,sys; os.setgroups([]); os.setgid(65533); os.setuid(65533); "
            "sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True).execute('SELECT * FROM marker')",
            str(database),
        ], capture_output=True)
        assert denied.returncode != 0


def test_first_install_and_upgrade_snapshots_use_actual_service_uid(tmp_path):
    command, environment, database = make_installer(
        tmp_path, first_install=True, service_user="nobody", service_group="nogroup",
    )
    installed = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=45)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    databases = [database, database.parent / "ai_frontier.db"]
    for file in [*databases, tmp_path / "locks/bot.lock", tmp_path / "locks/collector.lock"]:
        info = file.stat()
        assert (info.st_uid, info.st_gid) == (65534, 65534)
        assert stat.S_IMODE(info.st_mode) == 0o600
    assert (database.parent.stat().st_uid, (tmp_path / "locks").stat().st_uid) == (65534, 65534)
    probe = subprocess.run([
        sys.executable, "-B", "-c",
        "import os,sqlite3,sys; from pathlib import Path; "
        "os.setgroups([]); os.setgid(65534); os.setuid(65534); "
        "root=Path(sys.argv[1]); "
        "db=sqlite3.connect(root/'intelligence.db'); "
        "assert db.execute('PRAGMA user_version').fetchone()[0]==6; "
        "assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'; "
        "db.execute('CREATE TABLE service_probe (value TEXT)'); "
        "db.execute(\"INSERT INTO service_probe VALUES ('service-write')\"); db.commit(); db.close(); "
        "db=sqlite3.connect(root/'ai_frontier.db'); "
        "assert db.execute('PRAGMA user_version').fetchone()[0]==1; db.close()",
        str(database.parent),
    ], capture_output=True, text=True, timeout=15)
    assert probe.returncode == 0, probe.stderr
    archive = tmp_path / "candidate.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name in ("requirements.lock", "build-requirements.lock", "pyproject.toml"):
            member = tarfile.TarInfo(f"trendradar-upgrade/{name}")
            stream.addfile(member, io.BytesIO(b""))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"release_id": "upgrade", "git_dirty": False,
                                   "artifact": {"sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}}))
    command[2] = "upgrade"
    upgraded = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=45)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    snapshots = list((tmp_path / "backups").glob("*/manifest.json"))
    assert len(snapshots) == 1
    for file in snapshots[0].parent.iterdir():
        assert file.stat().st_uid == 65534
        assert stat.S_IMODE(file.stat().st_mode) & 0o007 == 0
    fake = tmp_path / "read-restic.py"
    fake.write_text(
        "import json,sys\nfrom pathlib import Path\n"
        "snapshot=Path(sys.argv[2]); manifest=json.loads((snapshot/'manifest.json').read_text())\n"
        "for entry in manifest['databases']: assert (snapshot/entry['file']).read_bytes()\n"
        "print(json.dumps({'snapshot_id':'service-readable-snapshot'}))\n", encoding="utf-8",
    )
    daily = subprocess.run([
        sys.executable, "-B", "-c",
        "import os,sys; from pathlib import Path; "
        "from trendradar.ops.backup import create_snapshot; "
        "from scripts.deploy.offsite_backup import upload_snapshot; "
        "os.setgroups([]); os.setgid(65534); os.setuid(65534); os.umask(0o077); "
        "root=Path(sys.argv[1]); "
        "daily=create_snapshot([root/'output/intelligence.db',root/'output/ai_frontier.db'],root/'backups'); "
        "snapshots=[sys.argv[2],daily['path']]; "
        "[upload_snapshot(p,restic_bin=[sys.executable,'-B',sys.argv[3]],"
        "repository='fake-local',password_file='fake-password') for p in snapshots]",
        str(tmp_path), str(snapshots[0].parent), str(fake),
    ], capture_output=True, text=True, timeout=20)
    assert daily.returncode == 0, daily.stdout + daily.stderr
    assert len(list((tmp_path / "backups").glob("*/offsite-manifest.json"))) == 2


@pytest.mark.parametrize("failure", ["chown", "chmod", "copy", "switch"])
@pytest.mark.parametrize("second_missing", [False, True])
def test_failed_restore_keeps_service_access_and_unrelated_metadata(
    tmp_path, monkeypatch, failure, second_missing,
):
    import trendradar.ops.backup as backup

    for parent in (tmp_path, tmp_path.parent, tmp_path.parent.parent):
        parent.chmod(0o755)
    root = tmp_path / "output"
    root.mkdir(mode=0o750)
    os.chown(root, 65534, 65534)
    monkeypatch.setenv("TRENDRADAR_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", str(tmp_path / "control"))
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir(mode=0o710)
    sentinel = unrelated / "preserved.txt"
    sentinel.write_bytes(b"unrelated test-owned data")
    sentinel.chmod(0o600)

    def metadata(path):
        info = path.stat()
        return info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)

    untouched = {path: metadata(path) for path in (unrelated, sentinel)}
    databases = [root / "intelligence.db", root / "ai_frontier.db"]
    for path in databases:
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE marker(value TEXT)")
            connection.execute("INSERT INTO marker VALUES ('snapshot')")
        os.chown(path, 65534, 65534)
        path.chmod(0o600)
    snapshot = create_snapshot(databases, tmp_path / "backups", root=root)
    for path in databases:
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE marker SET value='original'")
    if second_missing:
        databases[1].unlink()
    restored = tmp_path / "restored"
    restore_snapshot(snapshot["path"], restored, guard_database=databases[0])
    calls = 0

    if failure in {"chown", "chmod", "copy"}:
        module = backup.shutil if failure == "copy" else backup.os
        name = "copyfile" if failure == "copy" else failure
        original = getattr(module, name)

        def fail_prepare(path, *args, **kwargs):
            nonlocal calls
            destination = args[0] if failure == "copy" else path
            if Path(destination).name.startswith(".restore-"):
                calls += 1
                if calls == 2:
                    raise PermissionError("test-owned second target preparation denied")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(module, name, fail_prepare)
    else:
        original = backup.os.replace

        def fail_switch(source, destination):
            if Path(source).name.startswith(".restore-") and Path(destination) == databases[1]:
                raise PermissionError("test-owned second target publication denied")
            return original(source, destination)

        monkeypatch.setattr(backup.os, "replace", fail_switch)
    with pytest.raises(PermissionError, match="test-owned second target"):
        activate_restore(restored, databases[0], root=root)
    assert read_guard(databases[0]) is not None
    assert pending_restore_transactions(databases[0]) == []
    journal, = (tmp_path / "control").glob("restore-activation-*.json")
    assert json.loads(journal.read_text())["state"] == "rolled_back"
    assert {path: metadata(path) for path in untouched} == untouched
    assert sentinel.read_bytes() == b"unrelated test-owned data"
    for index, database in enumerate(databases):
        if second_missing and index == 1:
            assert not database.exists()
            continue
        assert metadata(database) == (65534, 65534, 0o600)
        result = subprocess.run([
            sys.executable, "-B", "-c",
            "import os,sqlite3,sys; os.setgroups([]); os.setgid(65534); os.setuid(65534); "
            "db=sqlite3.connect(sys.argv[1]); "
            "assert db.execute('SELECT value FROM marker').fetchone()==('original',); "
            "assert db.execute('PRAGMA journal_mode=WAL').fetchone()==('wal',); "
            "db.execute(\"UPDATE marker SET value='service-after-failure'\"); db.commit(); "
            "assert db.execute('SELECT value FROM marker').fetchone()==('service-after-failure',); "
            "db.close()", str(database),
        ], capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
