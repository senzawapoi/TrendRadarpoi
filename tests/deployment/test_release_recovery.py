"""Forward recovery must preserve the failed transaction and the business boundary."""

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import time
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("fcntl", reason="Linux deployment controller")
MODULE = Path(__file__).resolve().parents[2] / "scripts/deploy/recover_release.py"
spec = importlib.util.spec_from_file_location("recover_release", MODULE)
recovery = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = recovery
spec.loader.exec_module(recovery)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux deployment controller")


@pytest.fixture
def scene(tmp_path):
    release = "candidate"
    root = tmp_path / "releases"
    target = root / release
    target.mkdir(parents=True)
    site = target / "venv/lib/python3.12/site-packages"
    payloads = {"trendradar/__init__.py": b'"""test package"""\n', "requirements.lock": b"",
                "trendradar/schema.sql": b"select 1;\n"}
    archive = tmp_path / "candidate.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name, content in payloads.items():
            info = tarfile.TarInfo(f"trendradar-{release}/{name}")
            info.size = len(content)
            stream.addfile(info, io.BytesIO(content))
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            if name.startswith("trendradar/"):
                path = site / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = tmp_path / "RELEASE-MANIFEST.json"
    manifest.write_text(json.dumps({"release_id": release, "git_commit": "a" * 40,
                                    "git_dirty": False, "artifact": {"sha256": sha}}))
    current = tmp_path / "current"
    current.symlink_to(target, target_is_directory=True)
    release_env = tmp_path / "release.env"
    release_env.write_text("TRENDRADAR_RELEASE_ID=candidate\n")
    control = tmp_path / "control"
    control.mkdir()
    failed = {"transaction_id": "failed-deploy", "state": "failed:readiness",
              "new_release_id": release, "new_target": str(target),
              "old_target": str(root / "old"), "current_link": str(current),
              "business_boundary_crossed": True, "controller_pid": 99999999,
              "controller_start_time": "1", "boot_id": "old-boot",
              "pre_active_units": ["trendradar-bot.service", "trendradar-worker.service"],
              "snapshot_id": "original-snapshot", "snapshot_root": str(tmp_path / "output")}
    for name in ["deploy-in-progress.json", "deploy-failed-deploy.json"]:
        (control / name).write_text(json.dumps(failed))
    (control / "restore-guard.json").write_text(json.dumps({"state": "maintenance",
        "accept_new_work": False, "process_recovery": False, "allow_external_send": False,
        "allow_collection": False}))
    config = recovery.Config(release, "failed-deploy", "a" * 40, sha, archive, manifest,
        root, current, release_env, control, tmp_path / "output/intelligence.db",
        tmp_path / "output/ai_frontier.db", tmp_path / "backups", tmp_path / "health",
        "trendradar", os.getgid(), control / "deploy.lock", ())
    return config, failed


def test_valid_scene_checks_archive_source_and_installed_package(scene):
    config, failed = scene
    assert recovery.validate_scene(config) == failed
    assert recovery.verify_artifact(config) == 3


@pytest.mark.parametrize("field,value", [
    ("release_id", "wrong"), ("failed_transaction", "wrong"),
    ("commit", "b" * 40), ("archive_sha", "0" * 64),
])
def test_wrong_candidate_refuses_without_mutation(scene, field, value):
    config, _ = scene
    before = {p.name: p.read_bytes() for p in config.control.iterdir()}
    with pytest.raises(recovery.RecoveryError):
        changed = replace(config, **{field: value})
        recovery.validate_scene(changed)
        recovery.verify_artifact(changed)
    assert {p.name: p.read_bytes() for p in config.control.iterdir()} == before


@pytest.mark.parametrize("mutation", ["missing_guard", "cutover", "restore", "live", "archive",
                                     "wrong_current", "boundary", "symlink", "not_failed"])
def test_unsafe_scene_refuses(scene, mutation):
    config, failed = scene
    if mutation == "missing_guard":
        (config.control / "restore-guard.json").unlink()
    elif mutation == "cutover":
        (config.control / "recovery-cutover.json").write_text("{}")
    elif mutation == "restore":
        (config.control / "restore-activation-test.json").write_text('{"state":"prepare"}')
    elif mutation == "archive":
        (config.control / "deploy-failed-deploy.json").write_text("{}")
    elif mutation == "wrong_current":
        config.current.unlink()
        config.current.symlink_to(config.release_root / "old")
    elif mutation == "symlink":
        marker = config.control / "deploy-in-progress.json"
        marker.unlink()
        marker.symlink_to(config.control / "deploy-failed-deploy.json")
    else:
        if mutation == "live":
            failed.update(recovery.controller_identity())
            failed["controller_lease_boottime_ns"] = 0  # stale lease is NOT permission to steal
        elif mutation == "boundary":
            failed["business_boundary_crossed"] = False
        else:
            failed["state"] = "verify"
        for name in ["deploy-in-progress.json", "deploy-failed-deploy.json"]:
            (config.control / name).write_text(json.dumps(failed))
    with pytest.raises(recovery.RecoveryError):
        recovery.validate_scene(config)


@pytest.mark.parametrize("location", ["source", "installed", "resource", "extra", "link"])
def test_modified_installed_candidate_refuses(scene, location):
    config, _ = scene
    target = config.target
    site = target / "venv/lib/python3.12/site-packages/trendradar"
    if location == "source":
        (target / "requirements.lock").write_text("changed")
    elif location == "installed":
        (site / "__init__.py").write_text("changed")
    elif location == "resource":
        (site / "schema.sql").write_text("changed")
    elif location == "extra":
        (site / "injected.py").write_text("changed")
    else:
        path = target / "requirements.lock"
        path.unlink()
        path.symlink_to(config.archive)
    with pytest.raises(recovery.RecoveryError):
        recovery.verify_artifact(config)


def test_journal_uses_new_identity_and_preserves_failed_bytes(scene):
    config, failed = scene
    old = (config.control / "deploy-failed-deploy.json").read_bytes()
    journal = recovery.Journal(config, failed)
    journal.begin()
    journal.update("resume")
    active = json.loads((config.control / "deploy-in-progress.json").read_text())
    assert active["transaction_id"] != failed["transaction_id"]
    assert active["recovery_of"] == failed["transaction_id"]
    assert active["failed_record_sha256"] == hashlib.sha256(old).hexdigest()
    assert active["controller_pid"] == os.getpid()
    assert active["business_boundary_crossed"] is True
    assert active["snapshot_id"] == failed["snapshot_id"]
    assert (config.control / "deploy-failed-deploy.json").read_bytes() == old


def test_journal_does_not_renew_a_missing_or_replaced_fence(scene):
    config, failed = scene
    journal = recovery.Journal(config, failed)
    journal.begin()
    marker = config.control / "deploy-in-progress.json"
    marker.write_text('{"transaction_id":"someone-else"}')
    with pytest.raises(recovery.RecoveryError):
        journal.update("verify")
    assert json.loads(marker.read_text())["transaction_id"] == "someone-else"
    marker.unlink()
    with pytest.raises(recovery.RecoveryError):
        journal.update("verify")
    assert not marker.exists()


class FakeHost:
    def __init__(self, config, fail=None):
        self.config = config
        self.events = []
        self.fail = fail

    def event(self, name):
        self.events.append(name)
        if name == self.fail:
            raise recovery.RecoveryError("injected " + name)

    def stop_all(self):
        self.event("stop")

    def snapshot(self):
        self.event("snapshot")
        return {"backup_id": "new-snapshot"}

    def clear_guard(self):
        self.event("clear")
        (self.config.control / "restore-guard.json").unlink()

    def enter_guard(self):
        self.event("guard")
        (self.config.control / "restore-guard.json").write_text('{"state":"maintenance"}')

    def refresh_sources(self):
        self.event("sources")

    def verify_sources(self):
        self.event("source_check")

    def start_role(self, role):
        self.event(role)

    def drain_delivery(self):
        self.event("drain")

    def readiness(self):
        self.event("readiness")

    def start_timers(self):
        self.event("timers")

    def finalize(self):
        self.event("finalize")
        (self.config.control / "deploy-in-progress.json").unlink()


def test_recovery_serializes_starts_and_only_finalizes_after_readiness(scene):
    config, failed = scene
    journal = recovery.Journal(config, failed)
    host = FakeHost(config)
    recovery.recover(config, journal, host)
    assert host.events == ["stop", "snapshot", "clear", "sources", "source_check",
                           "bot", "worker", "scheduler", "drain", "timers",
                           "readiness", "finalize"]
    assert not (config.control / "deploy-in-progress.json").exists()
    assert not (config.control / "restore-guard.json").exists()
    assert json.loads(journal.path.read_text())["state"] == "complete"
    assert (config.control / "deploy-failed-deploy.json").exists()


@pytest.mark.parametrize("stage", ["stop", "snapshot", "clear", "sources", "source_check",
                                  "bot", "worker", "scheduler", "drain", "timers",
                                  "readiness", "finalize"])
def test_failure_reestablishes_guard_and_stops_roles_without_rollback(scene, stage):
    config, failed = scene
    journal = recovery.Journal(config, failed)
    host = FakeHost(config, fail=stage)
    with pytest.raises(recovery.RecoveryError):
        recovery.recover(config, journal, host)
    active = json.loads((config.control / "deploy-in-progress.json").read_text())
    assert active["state"].startswith("failed:recovery:")
    assert active["business_boundary_crossed"] is True
    assert (config.control / "restore-guard.json").exists()
    assert host.events[-2:] == ["guard", "stop"]
    assert config.current.resolve() == config.target
    assert (config.control / "deploy-failed-deploy.json").exists()


def test_lease_thread_failure_aborts_operation(scene, monkeypatch):
    config, failed = scene
    journal = recovery.Journal(config, failed)
    journal.begin()
    journal.error = OSError("disk full")
    with pytest.raises(recovery.RecoveryError, match="lease"):
        journal.check()


def test_old_role_heartbeat_cannot_satisfy_start(scene):
    config, _ = scene
    now = recovery.boottime_ns()
    heartbeat = {"pid": 123, "release_id": config.release_id, "state": "connected",
                 "boot_id": recovery.controller_identity()["boot_id"],
                 "updated_boottime_ns": now}
    assert recovery.role_ready(heartbeat, "bot", 123, config.release_id, now)
    assert not recovery.role_ready(heartbeat, "bot", 456, config.release_id, now)
    assert not recovery.role_ready(heartbeat, "bot", 123, "old", now)
    assert not recovery.role_ready(heartbeat, "bot", 123, config.release_id, now + 61_000_000_000)


def test_real_fence_lease_survives_a_slow_child_and_can_finalize(scene, monkeypatch):
    from trendradar.ops import health, maintenance

    config, failed = scene
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", str(config.control))
    monkeypatch.setenv("TRENDRADAR_RELEASE_ID", config.release_id)
    journal = recovery.Journal(config, failed)
    journal.begin()
    assert maintenance.read_guard(config.database) is not None
    journal.update("resume")
    journal.start_lease()
    try:
        assert maintenance.deployment_authorized(config.database)
        assert maintenance.clear_guard(config.database)
        assert maintenance.read_guard(config.database) is None
        first_lease = json.loads(journal.active.read_text())["controller_lease_boottime_ns"]
        # Longer than the application's 15-second fence window; no manual renewals.
        time.sleep(16)
        assert maintenance.deployment_authorized(config.database)
        assert json.loads(journal.active.read_text())["controller_lease_boottime_ns"] > first_lease
    finally:
        journal.stop_lease()
    journal.update("finalize")
    monkeypatch.setattr(health, "collect_health", lambda **kw: {"status": "healthy", "errors": []})
    assert maintenance.finalize_deployment(config.database)["finalized"]
    journal.complete()
    assert not journal.active.exists()


def test_real_fence_rejects_failed_recovery(scene, monkeypatch):
    from trendradar.ops import maintenance

    config, failed = scene
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", str(config.control))
    monkeypatch.setenv("TRENDRADAR_RELEASE_ID", config.release_id)
    journal = recovery.Journal(config, failed)
    journal.begin()
    journal.update("failed:recovery:worker")
    assert not maintenance.deployment_authorized(config.database)
    with pytest.raises(RuntimeError, match="incomplete deployment"):
        maintenance.clear_guard(config.database)


def test_interruption_quiesces_and_retains_fence(scene):
    config, failed = scene
    journal = recovery.Journal(config, failed)
    host = FakeHost(config)
    def interrupt():
        raise KeyboardInterrupt
    host.readiness = interrupt
    with pytest.raises(KeyboardInterrupt):
        recovery.recover(config, journal, host)
    assert host.events[-2:] == ["guard", "stop"]
    assert json.loads(journal.active.read_text())["state"] == "failed:recovery:readiness"


def test_oneshot_waits_for_actual_job_completion(scene, monkeypatch):
    config, failed = scene
    host = recovery.Host(config, recovery.Journal(config, failed))
    commands = []
    monkeypatch.setattr(host, "run", lambda args, **kw: commands.append((args, kw)))
    monkeypatch.setattr(host, "properties", lambda unit: {
        "ActiveState": "inactive", "Result": "success", "ExecMainStatus": "0",
    })
    host.start_once("trendradar-collect-ai.service", 120)
    assert commands[-1] == (["/usr/bin/systemctl", "start", "trendradar-collect-ai.service"],
                            {"timeout": 120})


@pytest.mark.parametrize("reason", ["source_unhealthy:example", "stale_source:example",
                                   "missing_source_run:example", "source_runs_unverified"])
def test_unhealthy_sources_refuse_before_delivery(scene, monkeypatch, reason):
    config, failed = scene
    host = recovery.Host(config, recovery.Journal(config, failed))
    reports = []
    monkeypatch.setattr(host, "ops", lambda *args, **kwargs: {
        "status": "unhealthy", "errors": ["missing_heartbeat:bot", reason],
    })
    monkeypatch.setattr(host, "evidence", lambda label, report: reports.append(label))
    with pytest.raises(recovery.RecoveryError, match="source readiness"):
        host.verify_sources()
    assert reports == ["after-source-refresh"]


def test_source_verification_does_not_require_not_yet_started_roles(scene, monkeypatch):
    config, failed = scene
    host = recovery.Host(config, recovery.Journal(config, failed))
    monkeypatch.setattr(host, "ops", lambda *args, **kwargs: {
        "status": "unhealthy", "errors": ["missing_heartbeat:bot", "missing_heartbeat:worker"],
    })
    monkeypatch.setattr(host, "evidence", lambda *args: None)
    host.verify_sources()


def instant_report(backlog, failed=0):
    return {"config": {"lark_enabled": True, "lark_delivery_enabled": True,
                       "lark_delivery_mode": "instant"},
            "instant_delivery": {"backlog": backlog, "failed_batches": failed}}


def test_recovery_drains_registered_scheduler_work_before_restoring_timers(scene, monkeypatch):
    config, failed = scene
    host = recovery.Host(config, recovery.Journal(config, failed))
    reports = iter([instant_report(41), instant_report(21), instant_report(0)])
    calls = []
    monkeypatch.setattr(host, "ops", lambda *args, **kwargs: next(reports))
    monkeypatch.setattr(host, "evidence", lambda *args: None)
    monkeypatch.setattr(host, "start_once", lambda unit, timeout: calls.append(unit))
    monkeypatch.setattr(recovery.time, "sleep", lambda seconds: None)
    host.drain_delivery()
    assert calls == ["trendradar-scheduler.service"] * 2


@pytest.mark.parametrize("report", [instant_report(-1), instant_report(True),
                                   instant_report("20"), instant_report(20, failed=1)])
def test_delivery_drain_rejects_invalid_or_failed_state(scene, monkeypatch, report):
    config, failed = scene
    host = recovery.Host(config, recovery.Journal(config, failed))
    monkeypatch.setattr(host, "ops", lambda *args, **kwargs: report)
    monkeypatch.setattr(host, "evidence", lambda *args: None)
    monkeypatch.setattr(host, "start_once", lambda *args: pytest.fail("must not send"))
    with pytest.raises(recovery.RecoveryError):
        host.drain_delivery()


def test_delivery_drain_has_a_deadline_and_retains_backlog(scene, monkeypatch):
    config, failed = scene
    host = recovery.Host(replace(config, readiness_timeout=30), recovery.Journal(config, failed))
    clock = [0.0]
    calls = []
    monkeypatch.setattr(recovery.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(recovery.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(host, "ops", lambda *args, **kwargs: instant_report(20))
    monkeypatch.setattr(host, "evidence", lambda *args: None)
    def slow_tick(unit, timeout):
        calls.append((unit, timeout))
        clock[0] += 30
    monkeypatch.setattr(host, "start_once", slow_tick)
    with pytest.raises(recovery.RecoveryError, match="delivery backlog did not drain"):
        host.drain_delivery()
    assert calls == [("trendradar-scheduler.service", 30)]


def test_atomic_journal_preserves_old_marker_when_replace_fails(scene, monkeypatch):
    config, failed = scene
    journal = recovery.Journal(config, failed)
    original = journal.active.read_bytes()
    def fail_replace(*args):
        raise OSError("disk failure")
    monkeypatch.setattr(recovery.os, "replace", fail_replace)
    with pytest.raises(OSError):
        journal.begin()
    assert journal.active.read_bytes() == original
    assert not list(config.control.glob(".deploy-in-progress.json.*"))


@pytest.mark.skipif(os.geteuid() != 0, reason="requires actual root/service UID permissions")
def test_recovery_clears_installer_root_owned_guard_through_authorized_admin_api(scene):
    import pwd

    config, failed = scene
    nobody = pwd.getpwnam("nobody")
    config = replace(config, service_user="nobody", service_gid=nobody.pw_gid)
    for parent in (config.control.parent, *list(config.control.parent.parents)[:2]):
        parent.chmod(0o755)
    os.chown(config.control, nobody.pw_uid, nobody.pw_gid)
    config.control.chmod(0o750)
    guard = config.control / "restore-guard.json"
    guard.chmod(0o600)  # install_release.sh's failed-readiness guard is created by root.
    assert guard.stat().st_uid == 0
    executable = config.target / "venv/bin/python"
    executable.parent.mkdir(parents=True)
    # Only package import selection is shimmed. UID, file permissions, the live
    # controller fence and the application's administrative clear API are real.
    root = Path(__file__).resolve().parents[2]
    executable.write_text(
        f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(root)!r})\n"
        "from trendradar.ops.__main__ import main\nraise SystemExit(main(sys.argv[4:]))\n"
    )
    executable.chmod(0o755)
    journal = recovery.Journal(config, failed)
    journal.begin()
    host = recovery.Host(config, journal)
    host.environment["TRENDRADAR_CONTROL_DIR"] = str(config.control)
    with pytest.raises(recovery.RecoveryError, match="status 2"):
        host.clear_guard()  # Root still cannot bypass an unauthorized deployment fence.
    assert guard.exists()
    journal.update("resume")
    journal.start_lease()
    try:
        probe = subprocess.run(
            ["/usr/sbin/runuser", "-u", "nobody", "--", str(executable), "-I", "-m",
             "trendradar.ops", "maintenance", "clear", "--database", str(config.database)],
            env=host.environment, capture_output=True, text=True, timeout=30,
        )
        assert probe.returncode == 1
        assert "PermissionError" in probe.stderr
        assert guard.exists()
        host.clear_guard()
        assert not guard.exists()
        assert journal.active.exists()  # The deployment fence still protects the recovery.
    finally:
        journal.stop_lease()
