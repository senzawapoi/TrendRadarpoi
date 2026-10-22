from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ci_targets_repository_default_branch_and_templates_are_tracked():
    workflow = (ROOT / ".github/workflows/phase7-ci.yml").read_text(encoding="utf-8")
    assert "branches: [master, main]" in workflow
    for name in (
        "backup.env.example",
        "bot.env.example",
        "collector.env.example",
        "common.env.example",
        "config.yaml.example",
        "scheduler.env.example",
        "worker.env.example",
    ):
        path = ROOT / "deploy/config" / name
        assert path.is_file()
        assert "*.env.*" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_systemd_roles_share_resource_slice_and_production_defaults_are_strict():
    slice_unit = (ROOT / "deploy/systemd/trendradar.slice").read_text(encoding="utf-8")
    assert "MemoryMax=1250M" in slice_unit
    assert "TasksMax=128" in slice_unit
    for path in (ROOT / "deploy/systemd").glob("trendradar-*.service"):
        assert "Slice=trendradar.slice" in path.read_text(encoding="utf-8")
    common = (ROOT / "deploy/config/common.env.example").read_text(encoding="utf-8")
    assert "INTELLIGENCE_REQUIRE_EXISTING=true" in common
    assert "INTELLIGENCE_SQLITE_SYNCHRONOUS=FULL" in common


def test_release_and_offsite_workflows_have_explicit_control_boundaries():
    deploy = (ROOT / ".github/workflows/phase7-deploy.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github/workflows/phase7-release.yml").read_text(encoding="utf-8")
    offsite = (ROOT / "scripts/deploy/offsite_backup.py").read_text(encoding="utf-8")
    installer = (ROOT / "scripts/deploy/install_release.sh").read_text(encoding="utf-8")
    assert "type: environment" in deploy
    assert "sha256" in installer and "release checksum mismatch" in installer
    assert "gh release create" in release
    assert "release_id must contain only" in release
    assert "RESTIC_PASSWORD_FILE" in offsite
    assert "requirements.lock" in installer
    assert "requirements.lock" in (ROOT / "scripts/deploy/create_manifest.py").read_text(encoding="utf-8")
    assert "TimeoutStartSec=20min" in (ROOT / "deploy/systemd/trendradar-backup.service").read_text(
        encoding="utf-8"
    )
    backup_unit = (ROOT / "deploy/systemd/trendradar-backup.service").read_text(encoding="utf-8")
    assert "${TRENDRADAR_OFFSITE_TIMEOUT_SECONDS:-" not in backup_unit
    assert "Environment=TRENDRADAR_OFFSITE_TIMEOUT_SECONDS=900" in backup_unit
    assert (ROOT / "scripts/deploy/linux_smoke.sh").is_file()
    assert (ROOT / "scripts/deploy/release_smoke.sh").is_file()


def test_installer_records_stages_and_uses_schema_aware_failure_boundary():
    installer = (ROOT / "scripts/deploy/install_release.sh").read_text(encoding="utf-8")
    for stage in (
        "prepare",
        "acquire",
        "quiesce",
        "snapshot",
        "migrate",
        "switch",
        "pre_resume",
        "resume",
        "verify",
        "finalize",
    ):
        assert f"write_state {stage}" in installer
    assert "rollback_before_resume" in installer
    assert "manual rollback required" in installer
    assert "TRENDRADAR_INITIAL_UNITS" in installer
    assert 'active_transaction=true' in installer
    assert 'targets = [Path(active_path), Path(transaction_path)] if active == "true"' in installer
    assert 'rm -f "$in_progress_file"' in installer
    assert 'source "$release_env"' in installer
    assert 'TRENDRADAR_RELEASE_ID="$release_id"' in installer
    assert 'service_group="${TRENDRADAR_SERVICE_GROUP:-trendradar}"' in installer
    assert 'chgrp "$service_group" "$release_env"' in installer
    for unit in (
        "trendradar-scheduler.service",
        "trendradar-collect-main.service",
        "trendradar-collect-ai.service",
        "trendradar-health.service",
        "trendradar-backup.service",
    ):
        assert unit in installer


def test_deploy_workflow_does_not_recheckout_or_scan_host_keys_at_deploy_time():
    workflow = (ROOT / ".github/workflows/phase7-deploy.yml").read_text(encoding="utf-8")
    assert workflow.count("actions/checkout@") == 1
    assert "TRENDRADAR_DEPLOY_KNOWN_HOSTS" in workflow
    assert "StrictHostKeyChecking=yes" in workflow
    assert "ssh-keyscan" not in workflow
    assert "python -B -m pytest tests -q" in workflow
    assert "dist/install_release.sh" not in workflow
    assert "/usr/local/sbin/trendradar-install-release" in workflow
    assert "scripts/deploy/validate_deploy_inputs.py --release-only" in workflow
    assert "def validate_deploy_inputs" in workflow
    assert 'ssh "${ssh_opts[@]}" "$DEPLOY_USER@$DEPLOY_HOST" true' in workflow
    assert "GlobalKnownHostsFile=/dev/null" in workflow
    assert "sudo -- /usr/local/sbin/trendradar-install-release" in workflow
    assert (ROOT / "deploy/bin/trendradar-install-release").is_file()
