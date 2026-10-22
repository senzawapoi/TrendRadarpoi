"""Automatic rollback is bound to a live installer and its exact old snapshot."""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trendradar.ops import backup
from trendradar.ops.maintenance import pending_restore_transactions, read_guard


def _prepare(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    database = root / "intelligence.db"
    ai = root / "ai_frontier.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE probe(value TEXT)")
        connection.execute("INSERT INTO probe VALUES ('previous')")
        connection.execute("PRAGMA user_version=5")
    control = tmp_path / "control"
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", str(control))
    monkeypatch.setenv("TRENDRADAR_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setenv("TRENDRADAR_BACKUP_DIR", str(tmp_path / "backups"))
    snapshot = backup.create_snapshot(
        [database], tmp_path / "backups", root=root, release_id="previous",
        target_mapping=[database, ai],
    )
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE probe SET value='candidate'")
        connection.execute("PRAGMA user_version=6")
    with sqlite3.connect(ai) as connection:
        connection.execute("CREATE TABLE probe(value TEXT)")
        connection.execute("INSERT INTO probe VALUES ('candidate-ai')")
    restored = tmp_path / "restored"
    backup.restore_snapshot(snapshot["path"], restored, guard_database=database)
    return root, database, ai, restored, snapshot, control


def _controller(root, snapshot):
    return {
        "transaction_id": "fixture-deployment",
        "state": "switch",
        "business_boundary_crossed": False,
        "snapshot_id": snapshot["backup_id"],
        "snapshot_root": str(root),
        "old_target": str(root.parent / "releases/previous"),
        "controller_pid": os.getpid(),
        "controller_start_time": Path(f"/proc/{os.getpid()}/stat").read_text()
        .rsplit(")", 1)[1].split()[19],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _contents(database):
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        return (connection.execute("PRAGMA user_version").fetchone()[0],
                connection.execute("SELECT value FROM probe").fetchone()[0])


def test_deployment_rollback_without_controller_cannot_change_data(tmp_path, monkeypatch):
    root, database, ai, restored, _, _ = _prepare(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="live pre-business-boundary"):
        backup.activate_restore(restored, database, root=root, deployment_rollback=True)
    assert _contents(database) == (6, "candidate")
    assert ai.exists()
    assert read_guard(database)
    assert not pending_restore_transactions(database)


@pytest.mark.skipif(sys.platform != "linux", reason="actual Linux controller identity")
@pytest.mark.parametrize("fault", [
    None, "boundary", "state", "stale", "pid-reused", "boot", "root", "snapshot",
    "manifest-mapping", "source", "guard-database", "partial-set", "checksum",
])
def test_deployment_rollback_checks_controller_and_complete_snapshot(tmp_path, monkeypatch, fault):
    root, database, ai, restored, snapshot, control = _prepare(tmp_path, monkeypatch)
    deployment = _controller(root, snapshot)
    manifest_path = restored / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if fault == "boundary":
        deployment["business_boundary_crossed"] = True
    elif fault == "state":
        deployment["state"] = "verify"
    elif fault == "stale":
        deployment["updated_at"] = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    elif fault == "pid-reused":
        deployment["controller_start_time"] = "0"
    elif fault == "boot":
        deployment["boot_id"] = "wrong-boot"
    elif fault == "root":
        deployment["snapshot_root"] = str(tmp_path)
    elif fault == "snapshot":
        deployment["snapshot_id"] = "../escaped"
    elif fault == "manifest-mapping":
        manifest["target_mapping"] = manifest["target_mapping"][:1]
    elif fault == "source":
        manifest["source"] = str(tmp_path / "other-snapshot")
    elif fault == "guard-database":
        manifest["guard_database"] = str(ai)
    elif fault == "checksum":
        manifest["databases"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    (control / "deploy-in-progress.json").write_text(json.dumps(deployment))
    cutover_path = control / "recovery-cutover.json"
    previous_cutover = b'{"recovery_cutover_at":"2026-08-01T00:00:00+00:00"}\n'
    cutover_path.write_bytes(previous_cutover)
    if fault:
        with pytest.raises((RuntimeError, ValueError)):
            backup.activate_restore(
                restored, database, root=root, deployment_rollback=True,
                index=0 if fault == "partial-set" else None,
            )
        assert _contents(database) == (6, "candidate")
        assert ai.exists()
        assert not pending_restore_transactions(database)
    else:
        result = backup.activate_restore(restored, database, root=root, deployment_rollback=True)
        assert _contents(database) == (5, "previous")
        assert not ai.exists()
        assert not Path(str(ai) + "-wal").exists()
        assert not Path(str(ai) + "-shm").exists()
        journal = json.loads(Path(result["transaction"]).read_text())
        assert journal["deployment_rollback"] is True
        assert journal["operations"][1]["removed"] is True
        assert journal["state"] == "complete"
    assert cutover_path.read_bytes() == previous_cutover
    assert read_guard(database)


def test_restore_keeps_complete_snapshot_mapping(tmp_path, monkeypatch):
    root, _, _, restored, snapshot, _ = _prepare(tmp_path, monkeypatch)
    manifest = json.loads((restored / "manifest.json").read_text())
    assert manifest["root"] == str(root)
    assert manifest["target_mapping"] == snapshot["target_mapping"]


@pytest.mark.skipif(sys.platform != "linux", reason="actual Linux controller identity")
def test_live_rollback_stage_restores_while_business_remains_guarded(tmp_path, monkeypatch):
    root, database, ai, restored, snapshot, control = _prepare(tmp_path, monkeypatch)
    deployment = _controller(root, snapshot)
    deployment["state"] = "rollback"
    (control / "deploy-in-progress.json").write_text(json.dumps(deployment))
    assert read_guard(database)["reason"] == "incomplete_deployment_transaction"
    backup.activate_restore(restored, database, root=root, deployment_rollback=True)
    assert _contents(database) == (5, "previous")
    assert not ai.exists()
    assert read_guard(database)["reason"] == "incomplete_deployment_transaction"


@pytest.mark.skipif(sys.platform != "linux", reason="actual Linux controller identity")
@pytest.mark.parametrize("cutover_present", [False, True])
def test_interrupted_deployment_rollback_recovers_candidate_set_without_new_cutover(
    tmp_path, monkeypatch, cutover_present,
):
    root, database, ai, restored, snapshot, control = _prepare(tmp_path, monkeypatch)
    deployment = _controller(root, snapshot)
    (control / "deploy-in-progress.json").write_text(json.dumps(deployment))
    cutover = control / "recovery-cutover.json"
    prior = b'{"recovery_cutover_at":"2026-08-01T00:00:00+00:00"}\n'
    if cutover_present:
        cutover.write_bytes(prior)
    real_write = backup._write_restore_journal

    def interrupt(path, payload):
        real_write(path, payload)
        if (payload["state"] == "installing" and payload["current_operation"] is None
                and len(payload["operations"]) == 2):
            raise KeyboardInterrupt("test-only stop after removing the deployment-created AI DB")

    with monkeypatch.context() as fault:
        fault.setattr(backup, "_write_restore_journal", interrupt)
        with pytest.raises(KeyboardInterrupt):
            backup.activate_restore(restored, database, root=root, deployment_rollback=True)
    assert not ai.exists()
    assert pending_restore_transactions(database)
    assert backup.recover_restore(database)["state"] == "rolled_back"
    assert _contents(database) == (6, "candidate")
    assert _contents(ai)[1] == "candidate-ai"
    assert backup.recover_restore(database)["recovered"] is False
    assert read_guard(database)
    if cutover_present:
        assert cutover.read_bytes() == prior
    else:
        assert not cutover.exists()
