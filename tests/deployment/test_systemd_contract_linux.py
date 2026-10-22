"""Run an isolated copy of the backup unit under real systemd and a service UID."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from trendradar.intelligence.storage import IntelligenceStorage

from .installer_harness import ROOT

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="requires isolated Linux root and running systemd",
)


@pytest.mark.parametrize("override", [False, True])
def test_real_backup_unit_environment_defaults_overrides_and_release(override):
    if Path("/proc/1/comm").read_text().strip() != "systemd":
        pytest.skip("PID 1 is not systemd")
    sandbox = Path(tempfile.mkdtemp(prefix="p7-systemd-", dir="/var/lib"))
    unit_name = f"trendradar-p7-test-{uuid.uuid4().hex}.service"
    unit_path = Path("/run/systemd/system") / unit_name
    try:
        sandbox.chmod(0o750)
        os.chown(sandbox, 65534, 65534)
        output = sandbox / "output"
        backup = sandbox / "backups"
        binary = sandbox / "bin"
        for directory in (output, backup, binary):
            directory.mkdir(mode=0o750)
            os.chown(directory, 65534, 65534)
        database = output / "intelligence.db"
        with IntelligenceStorage(database, synchronous="FULL"):
            pass
        os.chown(database, 65534, 65534)
        database.chmod(0o600)
        common = sandbox / "common.env"
        common.write_text(f"PYTHONPATH={ROOT}\nTRENDRADAR_OFFSITE_ENABLED=true\n")
        role = sandbox / "backup.env"
        role.write_text(f"PATH={binary}:/usr/bin:/bin\nRESTIC_REPOSITORY=fake-local\n"
                        f"RESTIC_PASSWORD_FILE={sandbox / 'password'}\n" +
                        ("TRENDRADAR_OFFSITE_TIMEOUT_SECONDS=123\nTRENDRADAR_OFFSITE_KILL_GRACE_SECONDS=7\n" if override else ""))
        release = sandbox / "release.env"
        release.write_text("TRENDRADAR_RELEASE_ID=systemd-test-release\n")
        for file in (common, role, release):
            os.chown(file, 0, 65534)
            file.chmod(0o640)
        fake = binary / "restic"
        fake.write_text(f"#!{sys.executable}\nimport json\n"
                        "print(json.dumps({'snapshot_id':'systemd-fake-snapshot'}))\n")
        fake.chmod(0o750)
        os.chown(fake, 0, 65534)
        helper = sandbox / "offsite.py"
        helper.write_text(
            "import json,sys,os\nfrom pathlib import Path\n"
            "from scripts.deploy.offsite_backup import main\n"
            f"Path({str(sandbox / 'arguments.json')!r}).write_text(json.dumps({{"
            "'argv':sys.argv[1:],'uid':os.getuid(),'release':os.environ.get('TRENDRADAR_RELEASE_ID')}))\n"
            "raise SystemExit(main())\n"
        )
        helper.chmod(0o640)
        os.chown(helper, 0, 65534)
        text = (ROOT / "deploy/systemd/trendradar-backup.service").read_text()
        replacements = {
            "User=trendradar": "User=65534",
            "Group=trendradar": "Group=65534",
            "Slice=trendradar.slice": "Slice=system.slice",
            "/etc/trendradar/common.env": str(common),
            "/etc/trendradar/backup.env": str(role),
            "/etc/trendradar/release.env": str(release),
            "/opt/trendradar/current/venv/bin/python": sys.executable,
            "/opt/trendradar/current/scripts/deploy/offsite_backup.py": str(helper),
            "/var/backups/trendradar/local": str(backup),
            "/var/backups/trendradar": str(backup),
            "/var/lib/trendradar": str(sandbox),
            "/run/trendradar": str(sandbox),
        }
        pattern = "|".join(re.escape(key) for key in sorted(replacements, key=len, reverse=True))
        text = re.sub(pattern, lambda match: replacements[match[0]], text)
        unit_path.write_text(text)
        verify = subprocess.run(["systemd-analyze", "verify", str(unit_path)], capture_output=True)
        assert verify.returncode == 0, verify.stderr.decode()
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        started = subprocess.run(["systemctl", "start", unit_name], capture_output=True, timeout=60)
        logs = subprocess.run(["journalctl", "-u", unit_name, "--no-pager"], capture_output=True, text=True)
        assert started.returncode == 0, started.stderr.decode() + logs.stdout
        arguments = json.loads((sandbox / "arguments.json").read_text())
        assert arguments["uid"] == 65534
        assert arguments["release"] == "systemd-test-release"
        argv = arguments["argv"]
        assert argv[argv.index("--timeout-seconds") + 1] == ("123" if override else "900")
        assert argv[argv.index("--kill-grace-seconds") + 1] == ("7" if override else "10")
        snapshots = list(backup.glob("*/manifest.json"))
        assert len(snapshots) == 1
        manifest = json.loads(snapshots[0].read_text())
        assert manifest["release_id"] == "systemd-test-release"
        assert json.loads((snapshots[0].parent / "offsite-manifest.json").read_text())["success"]
    finally:
        subprocess.run(["systemctl", "stop", unit_name], capture_output=True)
        unit_path.unlink(missing_ok=True)
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
        subprocess.run(["systemctl", "reset-failed", unit_name], capture_output=True)
        shutil.rmtree(sandbox)
