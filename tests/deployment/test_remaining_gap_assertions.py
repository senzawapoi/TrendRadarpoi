"""Remaining Phase 7 assertions through real entrypoints and temporary SQLite."""

import json
import os
import sqlite3
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trendradar.ops import maintenance

from . import test_environment_entry_linux as environment_tests
from .installer_harness import ROOT, make_installer
from .test_environment_entry_linux import invoke
from .test_installer_behavior import assert_restart_accepting, assert_restart_protected

LINUX_ROOT = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="requires isolated Linux root, POSIX permissions and real service UID",
)


@pytest.fixture
def entry_scope():
    yield from environment_tests.entry_scope.__wrapped__()


@pytest.fixture
def protected_runtime(tmp_path, monkeypatch):
    database = tmp_path / "stores" / "intelligence.db"
    config = tmp_path / "config.yaml"
    config.write_text("intelligence:\n  enabled: true\n", encoding="utf-8")
    environment = {
        **{key: os.environ[key] for key in ("PATH", "SystemRoot", "TEMP", "TMP")
           if key in os.environ},
        "CONFIG_PATH": str(config),
        "INTELLIGENCE_DB_PATH": str(database),
        "AI_FRONTIER_DB_PATH": str(tmp_path / "stores" / "ai_frontier.db"),
        "TRENDRADAR_CONTROL_DIR": str(tmp_path / "transactions"),
        "TRENDRADAR_LOCK_DIR": str(tmp_path / "role-locks"),
        "TRENDRADAR_HEALTH_DIR": str(tmp_path / "heartbeats"),
        "TRENDRADAR_BACKUP_DIR": str(tmp_path / "snapshots"),
        "TRENDRADAR_RELEASE_ID": "candidate",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join(sys.path),
        "GEMINI_ENABLED": "false",
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    maintenance.control_directory(database).mkdir()
    return database, environment


@pytest.mark.parametrize("state", [
    "prepare", "acquire", "quiesce", "snapshot", "migrate", "switch",
    "pre_resume", "resume", "verify", "finalize", "rollback", "failed:readiness",
])
def test_uncontrolled_valid_deployment_stages_block_every_business_entry(protected_runtime, state):
    """GUARD-01: valid stages must fence actual role entrypoints, not just read_guard."""
    database, environment = protected_runtime
    marker = maintenance.control_directory(database) / "deploy-in-progress.json"
    marker.write_text(json.dumps({
        "transaction_id": "test-owned-deployment",
        "state": state,
        "new_release_id": "candidate",
        "old_target": str(database.parent.parent / "previous"),
        "business_boundary_crossed": state in {"resume", "verify", "finalize"},
        "controller_pid": 2**30,
        "controller_start_time": "0",
        "boot_id": "synthetic-dead-controller",
        "updated_at": "2026-10-14T00:00:00+00:00",
    }), encoding="utf-8")
    assert not maintenance.guard_path(database).exists()
    original = marker.read_bytes()
    assert_restart_protected(environment, database)
    assert marker.read_bytes() == original
    assert not database.exists()
    assert not database.parent.exists()


@LINUX_ROOT
@pytest.mark.parametrize("deployment_state", [None, "resume", "verify", "finalize"])
def test_controlled_or_completed_deployment_reaches_real_entrypoint_sentinels(
    protected_runtime, deployment_state,
):
    """GUARD-01: authorized resume/finalize and idle state reach business entrypoints."""
    database, environment = protected_runtime
    marker = maintenance.control_directory(database) / "deploy-in-progress.json"
    if deployment_state is not None:
        marker.write_text(json.dumps({
            "transaction_id": "test-owned-authorized-deployment",
            "state": deployment_state,
            "new_release_id": "candidate",
            "business_boundary_crossed": True,
            "controller_pid": os.getpid(),
            "controller_start_time": Path(f"/proc/{os.getpid()}/stat").read_text()
            .rsplit(")", 1)[1].split()[19],
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "controller_lease_boottime_ns": time.clock_gettime_ns(time.CLOCK_BOOTTIME),
        }), encoding="utf-8")
    assert_restart_accepting(environment, database)


@LINUX_ROOT
def test_fixed_entry_uses_all_configured_paths_for_actual_operations(entry_scope):
    """ENV-02: the fixed entry runs real migrations, health, locks and restore preflight."""
    sandbox, entry, common, values = entry_scope
    helper = sandbox / "maintenance-helper"
    helper.write_text(f"#!{sys.executable} -B\n" + textwrap.dedent(f"""
        import contextlib, io, json, os, sqlite3, sys
        from pathlib import Path
        sys.path.insert(0, {str(ROOT)!r})
        from trendradar.core.heartbeat import RoleHeartbeat
        from trendradar.core.locking import runtime_locks
        from trendradar.ops import backup, database, health, maintenance
        db = Path(os.environ['INTELLIGENCE_DB_PATH'])
        ai = Path(os.environ['AI_FRONTIER_DB_PATH'])
        snapshots = Path(os.environ['TRENDRADAR_BACKUP_DIR'])
        for path, kind, schema in ((db, 'intelligence', 7), (ai, 'ai_frontier', 1)):
            with contextlib.redirect_stdout(io.StringIO()):
                assert database.main(['migrate', '--database', str(path), '--kind', kind]) == 0
                assert database.main(['check', '--database', str(path), '--kind', kind]) == 0
            with contextlib.closing(sqlite3.connect(path)) as connection:
                assert connection.execute('PRAGMA user_version').fetchone()[0] == schema
        for role, state in (('bot', 'connected'), ('worker', 'running')):
            RoleHeartbeat(role, db).write(state=state, sqlite_synchronous='FULL')
        with runtime_locks(db, 'bot', 'worker', 'collector', 'scheduler'):
            locks = sorted(str(p) for p in Path(os.environ['TRENDRADAR_LOCK_DIR']).glob('*.lock'))
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            assert health.main(['--readiness', '--json']) == 0
        report = json.loads(capture.getvalue())
        assert report['database_path'] == str(db)
        assert report['database']['schema'] == 7
        assert report['ai_frontier_database']['schema'] == 1
        snapshot = backup.create_snapshot([db, ai], snapshots, root=db.parent, release_id='candidate')
        restored = Path({str(sandbox / 'restore-preflight')!r})
        result = backup.restore_snapshot(snapshot['path'], restored, guard_database=db)
        assert len(result['databases']) == 2
        assert all(item['integrity_check'] == 'ok' for item in result['databases'])
        assert maintenance.guard_path(db).is_file()
        proof = dict(database=str(db), ai=str(ai), locks=locks, snapshot=snapshot,
                     health=report, restored=str(restored), control=str(maintenance.control_directory(db)))
        Path({str(sandbox / 'entry-proof.json')!r}).write_text(json.dumps(proof))
    """), encoding="utf-8")
    common.write_text(common.read_text(encoding="utf-8") + "\n".join([
        "\nTRENDRADAR_RELEASE_ID=candidate", "TRENDRADAR_HEALTH_EXPECTED_ROLES=bot,worker",
        "INTELLIGENCE_HEALTH_REQUIRE_BACKUP=false", "INTELLIGENCE_HEALTH_REQUIRE_SOURCE_RUNS=false",
    ]), encoding="utf-8")
    Path(values["CONFIG_PATH"]).write_text(
        "intelligence:\n  enabled: true\nai_frontier:\n  enabled: true\n", encoding="utf-8",
    )
    result = invoke(entry, "exercise")
    assert result.returncode == 0, result.stdout + result.stderr
    proof = json.loads((sandbox / "entry-proof.json").read_text(encoding="utf-8"))
    assert proof["database"] == values["INTELLIGENCE_DB_PATH"]
    assert proof["ai"] == values["AI_FRONTIER_DB_PATH"]
    assert proof["control"] == values["TRENDRADAR_CONTROL_DIR"]
    for role in ("bot", "worker"):
        assert (Path(values["TRENDRADAR_HEALTH_DIR"]) / f"{role}.json").is_file()
    assert {Path(p).name for p in proof["locks"]} == {
        "bot.lock", "worker.lock", "collector.lock", "scheduler.lock",
    }
    assert Path(proof["snapshot"]["path"]).parent == Path(values["TRENDRADAR_BACKUP_DIR"])
    assert {item["source"] for item in proof["snapshot"]["databases"]} == {
        values["INTELLIGENCE_DB_PATH"], values["AI_FRONTIER_DB_PATH"],
    }
    db_parent = Path(values["INTELLIGENCE_DB_PATH"]).parent
    for path in (sandbox / "output", sandbox / "control", db_parent / "control",
                 db_parent / "health", db_parent / "locks", db_parent / "backups"):
        assert not path.exists(), path


@LINUX_ROOT
@pytest.mark.parametrize("missing_key", [
    None, "CONFIG_PATH", "INTELLIGENCE_DB_PATH", "AI_FRONTIER_DB_PATH",
    "TRENDRADAR_HEALTH_DIR", "TRENDRADAR_LOCK_DIR", "TRENDRADAR_CONTROL_DIR", "TRENDRADAR_BACKUP_DIR",
])
def test_fixed_entry_quoted_values_and_missing_required_keys(entry_scope, missing_key):
    """ENV-03: legitimate quoted input executes; every missing required key fails before writes."""
    _, entry, common, values = entry_scope
    if missing_key:
        common.write_text("\n".join(
            line for line in common.read_text(encoding="utf-8").splitlines()
            if not line.startswith(missing_key + "=")
        ), encoding="utf-8")
    result = invoke(entry, "migrate")
    database = Path(values["INTELLIGENCE_DB_PATH"])
    if missing_key is None:
        assert result.returncode == 0, result.stdout + result.stderr
        with sqlite3.connect(database) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
    else:
        assert result.returncode == 2
        assert "invalid or missing trusted production configuration" in result.stderr
        assert "SYNTHETIC-CALLER-SECRET" not in result.stdout + result.stderr
        for key in ("INTELLIGENCE_DB_PATH", "AI_FRONTIER_DB_PATH",
                    "TRENDRADAR_CONTROL_DIR", "TRENDRADAR_LOCK_DIR"):
            assert not Path(values[key]).exists()


@LINUX_ROOT
def test_fixed_entry_rejects_actually_unreadable_config_before_migration(entry_scope):
    """ENV-03: EUID 0 without DAC override proves a real CONFIG_PATH read failure."""
    _, entry, _, values = entry_scope
    config = Path(values["CONFIG_PATH"])
    config.chmod(0o000)
    prefix = ["/usr/bin/setpriv", "--bounding-set=-dac_override,-dac_read_search"]
    probe = subprocess.run([
        *prefix, sys.executable, "-B", "-c", "from pathlib import Path; import sys; "
        "Path(sys.argv[1]).read_text()", str(config),
    ], capture_output=True, text=True, timeout=10)
    assert probe.returncode != 0
    assert "PermissionError" in probe.stderr
    result = subprocess.run([*prefix, str(entry), "migrate"],
                            env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "invalid or missing trusted production configuration" in result.stderr
    for key in ("INTELLIGENCE_DB_PATH", "AI_FRONTIER_DB_PATH",
                "TRENDRADAR_CONTROL_DIR", "TRENDRADAR_LOCK_DIR"):
        assert not Path(values[key]).exists()


@LINUX_ROOT
def test_first_install_service_uid_writes_both_databases_in_wal(tmp_path):
    """PERM-02: real service UID commits both application schemas after real migrations."""
    command, environment, database = make_installer(
        tmp_path, first_install=True, service_user="nobody", service_group="nogroup",
    )
    installed = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    probe = subprocess.run([
        sys.executable, "-B", "-c", textwrap.dedent("""
            import os, sqlite3, sys
            from pathlib import Path
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)
            assert os.geteuid() == 65534
            for name, schema in (('intelligence.db', 7), ('ai_frontier.db', 1)):
                path = Path(sys.argv[1]) / name
                connection = sqlite3.connect(path)
                try:
                    assert connection.execute('PRAGMA user_version').fetchone()[0] == schema
                    assert connection.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
                    connection.execute('CREATE TABLE remaining_service_probe(value TEXT)')
                    connection.execute('INSERT INTO remaining_service_probe VALUES (?)', (name,))
                    connection.commit()
                    assert connection.execute('SELECT value FROM remaining_service_probe').fetchone()[0] == name
                    assert Path(str(path) + '-wal').stat().st_size > 0
                    assert Path(str(path) + '-shm').is_file()
                finally:
                    connection.close()
        """), str(database.parent),
    ], env=environment, capture_output=True, text=True, timeout=15)
    assert probe.returncode == 0, probe.stdout + probe.stderr
    for name in ("intelligence.db", "ai_frontier.db"):
        with sqlite3.connect(database.parent / name) as connection:
            assert connection.execute("SELECT value FROM remaining_service_probe").fetchone() == (name,)
    assert not (tmp_path / "control/deploy-in-progress.json").exists()


@pytest.mark.parametrize("payload", [
    '{"state":"prepared"}', '{"state":"installing"}', '[]', '{broken',
])
def test_pending_restore_clear_keeps_every_business_entry_protected(protected_runtime, payload, capsys):
    """GUARD-02: failed public clear retains evidence and fences all role entrypoints."""
    database, environment = protected_runtime
    maintenance.set_guard(database, reason="test-owned pending restore")
    journal = maintenance.control_directory(database) / "restore-activation-test.json"
    journal.write_text(payload, encoding="utf-8")
    original = journal.read_bytes()
    guard_before = maintenance.guard_path(database).read_bytes()
    assert maintenance.main(["clear", "--database", str(database)]) == 2
    assert "requires recovery" in json.loads(capsys.readouterr().out)["error"]
    assert_restart_protected(environment, database)
    assert journal.read_bytes() == original
    assert maintenance.guard_path(database).read_bytes() == guard_before
    assert not database.exists()
    assert not database.parent.exists()
