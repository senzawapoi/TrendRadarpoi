"""Contracts for split security acquisition systemd units and per-cadence source health."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trendradar.crawler.rss import RSSFeedConfig
from trendradar.intelligence.runner import AdapterRunner
from trendradar.intelligence.storage import IntelligenceStorage, SourceRunRecord
from trendradar.ops.health import collect_health
from trendradar.sources.rss import RSSAdapter
from trendradar.storage.base import RSSItem

ROOT = Path(__file__).resolve().parents[2]


def test_security_collector_systemd_templates_follow_hardening_and_schedule():
    service_path = ROOT / "deploy/systemd/trendradar-collect-security.service"
    timer_path = ROOT / "deploy/systemd/trendradar-collect-security.timer"
    assert service_path.is_file(), "missing trendradar-collect-security.service"
    assert timer_path.is_file(), "missing trendradar-collect-security.timer"

    service = service_path.read_text(encoding="utf-8")
    timer = timer_path.read_text(encoding="utf-8")

    assert "Type=oneshot" in service
    assert "Slice=trendradar.slice" in service
    assert "MemoryLow=" not in service
    assert "PrivateTmp=yes" in service
    assert "ProtectSystem=strict" in service
    assert "ProtectHome=yes" in service
    assert "NoNewPrivileges=yes" in service
    assert "ReadWritePaths=/var/lib/trendradar /run/trendradar" in service
    assert (
        "ExecStart=/opt/trendradar/current/venv/bin/python -m trendradar --scope security"
        in service
    )

    assert "OnCalendar=*-*-* 01/4:45:00" in timer
    assert "Persistent=false" in timer
    assert "Unit=trendradar-collect-security.service" in timer
    main_service = (ROOT / "deploy/systemd/trendradar-collect-main.service").read_text(
        encoding="utf-8"
    )
    assert "Environment=TRENDRADAR_MAIN_SCOPE=general" in main_service
    collector_env = (ROOT / "deploy/config/collector.env.example").read_text(
        encoding="utf-8"
    )
    assert "TRENDRADAR_MAIN_SCOPE=general" in collector_env


def test_health_supports_slower_security_source_cadence_and_quiet_rss_feeds(
    tmp_path, monkeypatch
):
    import asyncio
    from types import SimpleNamespace

    db_path = tmp_path / "output/intelligence.db"
    db_path.parent.mkdir(parents=True)
    backup_dir = tmp_path / "backups"
    snap = backup_dir / "20261125T120000Z"
    snap.mkdir(parents=True)
    now = datetime.now(timezone.utc)

    with IntelligenceStorage(db_path, synchronous="FULL") as storage:
        feed = RSSFeedConfig(
            id="deepmind",
            name="DeepMind Blog",
            url="https://deepmind.google/blog/rss.xml",
            max_age_days=3,
        )
        adapter = RSSAdapter(feed, timezone="UTC")
        old_pub = (now - timedelta(days=10)).isoformat()

        async def fake_fetch_all(max_workers=1):
            return SimpleNamespace(
                items={
                    "deepmind": [
                        RSSItem(
                            title="Last Week Research",
                            feed_id="deepmind",
                            feed_name="DeepMind Blog",
                            url="https://deepmind.google/blog/p1",
                            published_at=old_pub,
                            crawl_time="12:00",
                        )
                    ]
                },
                id_to_name={"deepmind": "DeepMind Blog"},
                failed_ids=[],
            )

        monkeypatch.setattr(adapter.fetcher, "async_fetch_all", fake_fetch_all)
        asyncio.run(AdapterRunner(storage=storage).run([adapter], collected_at=now))

        sec_finished = now - timedelta(hours=5)
        storage.record_source_run(
            SourceRunRecord(
                adapter_id="security:cisa_kev",
                status="healthy",
                started_at=sec_finished - timedelta(seconds=4),
                finished_at=sec_finished,
                duration_ms=4000,
                fetched_count=12,
                normalized_count=12,
                error_count=0,
            )
        )

    manifest = {
        "backup_id": "20261125T120000Z",
        "complete": True,
        "created_at": (now - timedelta(hours=1)).isoformat(),
        "release_id": "acq-test-release",
    }
    (snap / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    cfg = tmp_path / "config.yaml"
    cfg.write_text("intelligence:\n  enabled: true\n", encoding="utf-8")

    monkeypatch.setenv("INTELLIGENCE_DB_PATH", str(db_path))
    monkeypatch.setenv("TRENDRADAR_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("TRENDRADAR_RELEASE_ID", "acq-test-release")
    monkeypatch.setenv("TRENDRADAR_HEALTH_EXPECTED_ROLES", "")
    monkeypatch.setenv("INTELLIGENCE_HEALTH_REQUIRE_SOURCE_RUNS", "true")
    monkeypatch.setenv(
        "TRENDRADAR_HEALTH_EXPECTED_SOURCES", "rss:deepmind,security:cisa_kev"
    )
    monkeypatch.setenv("INTELLIGENCE_HEALTH_SOURCE_MAX_AGE_HOURS", "4")
    monkeypatch.setenv("INTELLIGENCE_HEALTH_SECURITY_SOURCE_MAX_AGE_HOURS", "8")

    report = collect_health(cfg)
    assert report["status"] == "healthy", report
    assert "warnings" not in report

    monkeypatch.setenv("INTELLIGENCE_HEALTH_SECURITY_SOURCE_MAX_AGE_HOURS", "4")
    stale_report = collect_health(cfg)
    assert stale_report["status"] == "degraded"
    assert "stale_source:security:cisa_kev" in stale_report["warnings"]


@pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="requires isolated Linux root and running systemd",
)
def test_real_security_collector_unit_verifies_and_passes_scope_argument():
    if Path("/proc/1/comm").read_text().strip() != "systemd":
        pytest.skip("PID 1 is not systemd")
    sandbox = Path(tempfile.mkdtemp(prefix="acq-sec-systemd-", dir="/var/lib"))
    base_name = f"trendradar-acq-sec-{uuid.uuid4().hex}"
    service_path = Path("/run/systemd/system") / f"{base_name}.service"
    timer_path = Path("/run/systemd/system") / f"{base_name}.timer"
    try:
        sandbox.chmod(0o750)
        os.chown(sandbox, 65534, 65534)
        probe_out = sandbox / "probe.json"
        probe_pkg = sandbox / "pkg" / "trendradar"
        probe_pkg.mkdir(parents=True, mode=0o750)
        for directory in (sandbox / "pkg", probe_pkg):
            directory.chmod(0o750)
            os.chown(directory, 0, 65534)

        init_py = probe_pkg / "__init__.py"
        main_py = probe_pkg / "__main__.py"
        init_py.write_text("", encoding="utf-8")
        main_py.write_text(
            "import json, os, sys\nfrom pathlib import Path\n"
            f"Path({str(probe_out)!r}).write_text(json.dumps({{"
            "'argv': sys.argv[1:], 'uid': os.getuid(), "
            "'lock_dir': os.environ.get('TRENDRADAR_LOCK_DIR')}))\n",
            encoding="utf-8",
        )
        for py_file in (init_py, main_py):
            py_file.chmod(0o640)
            os.chown(py_file, 0, 65534)

        common = sandbox / "common.env"
        common.write_text(f"PYTHONPATH={sandbox / 'pkg'}\n", encoding="utf-8")
        collector = sandbox / "collector.env"
        collector.write_text("INTELLIGENCE_SECURITY_ENABLED=true\n", encoding="utf-8")
        release = sandbox / "release.env"
        release.write_text("TRENDRADAR_RELEASE_ID=acq-systemd-test\n", encoding="utf-8")
        for env_file in (common, collector, release):
            env_file.chmod(0o640)
            os.chown(env_file, 0, 65534)

        svc_text = (ROOT / "deploy/systemd/trendradar-collect-security.service").read_text(
            encoding="utf-8"
        )
        replacements = {
            "User=trendradar": "User=65534",
            "Group=trendradar": "Group=65534",
            "Slice=trendradar.slice": "Slice=system.slice",
            "/etc/trendradar/common.env": str(common),
            "/etc/trendradar/collector.env": str(collector),
            "/etc/trendradar/release.env": str(release),
            "/opt/trendradar/current/venv/bin/python": sys.executable,
            "/var/lib/trendradar": str(sandbox),
            "/run/trendradar": str(sandbox),
        }
        pattern = "|".join(re.escape(k) for k in sorted(replacements, key=len, reverse=True))
        svc_text = re.sub(pattern, lambda m: replacements[m[0]], svc_text)
        tmr_text = (
            (ROOT / "deploy/systemd/trendradar-collect-security.timer")
            .read_text(encoding="utf-8")
            .replace("Unit=trendradar-collect-security.service", f"Unit={base_name}.service")
        )
        service_path.write_text(svc_text, encoding="utf-8")
        timer_path.write_text(tmr_text, encoding="utf-8")

        verify = subprocess.run(
            ["systemd-analyze", "verify", str(service_path), str(timer_path)],
            capture_output=True,
            text=True,
        )
        assert verify.returncode == 0, verify.stderr
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        started = subprocess.run(
            ["systemctl", "start", f"{base_name}.service"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        logs = subprocess.run(
            ["journalctl", "-u", f"{base_name}.service", "--no-pager"],
            capture_output=True,
            text=True,
        )
        assert started.returncode == 0, started.stderr + "\n" + logs.stdout
        payload = json.loads(probe_out.read_text(encoding="utf-8"))
        assert payload["argv"] == ["--scope", "security"]
        assert payload["uid"] == 65534
        assert payload["lock_dir"] == str(sandbox)
    finally:
        subprocess.run(
            ["systemctl", "stop", f"{base_name}.timer", f"{base_name}.service"],
            capture_output=True,
        )
        service_path.unlink(missing_ok=True)
        timer_path.unlink(missing_ok=True)
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
        subprocess.run(
            ["systemctl", "reset-failed", f"{base_name}.service"],
            capture_output=True,
        )
        shutil.rmtree(sandbox)
