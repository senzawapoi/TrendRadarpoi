"""The tracked health unit can read WAL databases whose sidecars were removed.

SQLite deletes -wal/-shm when the last writer closes; a read-only connection must then
create -shm. The unit runs under ProtectSystem=strict, so it needs write access to the
database directory (never the control directory), while reads stay mode=ro.
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from contextlib import closing
from pathlib import Path

import pytest

from .installer_harness import ROOT

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="requires isolated Linux root and running systemd",
)
PROBE = """import json, sys
from pathlib import Path
sys.path.insert(0, {root!r})
from trendradar.ops.health import _read_only_ai
sandbox = Path({sandbox!r})
report, error = _read_only_ai(sandbox / "output/ai_frontier.db")
try:
    (sandbox / "control/probe-write").write_text("x")
    control = "writable"
except OSError as exc:
    control = type(exc).__name__
(sandbox / "run/result.json").write_text(json.dumps({{"error": error, "report": report,
                                                     "control": control}}))
"""


def test_health_unit_reads_ai_frontier_database_after_sidecars_are_removed():
    if Path("/proc/1/comm").read_text().strip() != "systemd":
        pytest.skip("PID 1 is not systemd")
    sandbox = Path(tempfile.mkdtemp(prefix="p7-health-sandbox-", dir="/var/lib"))
    unit_name = f"trendradar-p7-test-{uuid.uuid4().hex}-health.service"
    unit_path = Path("/run/systemd/system") / unit_name
    try:
        sandbox.chmod(0o755)
        for name in ("output", "control", "run"):
            (sandbox / name).mkdir(mode=0o750)
            os.chown(sandbox / name, 65534, 65534)
        database = sandbox / "output/ai_frontier.db"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA user_version=1")
        os.chown(database, 65534, 65534)
        database.chmod(0o600)
        assert not any(Path(f"{database}{suffix}").exists() for suffix in ("-wal", "-shm"))
        probe = sandbox / "probe.py"
        probe.write_text(PROBE.format(root=str(ROOT), sandbox=str(sandbox)))
        probe.chmod(0o644)
        text = (ROOT / "deploy/systemd/trendradar-health.service").read_text(encoding="utf-8")
        replacements = {
            "User=trendradar": "User=65534",
            "Group=trendradar": "Group=65534",
            "Slice=trendradar.slice": "Slice=system.slice",
            "/opt/trendradar/current/venv/bin/python -m trendradar.ops health "
            "--config /etc/trendradar/config.yaml --json": f"{sys.executable} -B {probe}",
            "/etc/trendradar/": f"{sandbox}/missing-etc/",
            "/var/lib/trendradar": str(sandbox),
            "/run/trendradar": str(sandbox / "run"),
        }
        pattern = "|".join(re.escape(key) for key in sorted(replacements, key=len, reverse=True))
        unit_path.write_text(re.sub(pattern, lambda match: replacements[match[0]], text))
        verify = subprocess.run(["systemd-analyze", "verify", str(unit_path)],
                                capture_output=True, text=True, timeout=30)
        assert verify.returncode == 0, verify.stderr
        subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=30)
        started = subprocess.run(["systemctl", "start", unit_name], capture_output=True,
                                 text=True, timeout=60)
        logs = subprocess.run(["journalctl", "-u", unit_name, "--no-pager"],
                              capture_output=True, text=True, timeout=30)
        assert started.returncode == 0, started.stderr + logs.stdout
        result = json.loads((sandbox / "run/result.json").read_text())
        assert result["error"] is None, result
        assert result["report"]["schema"] == 1
        assert result["control"] != "writable", result
        assert not (sandbox / "control/probe-write").exists()
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        subprocess.run(["systemctl", "stop", unit_name], capture_output=True, timeout=30)
        unit_path.unlink(missing_ok=True)
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=30)
        subprocess.run(["systemctl", "reset-failed", unit_name], capture_output=True, timeout=30)
        shutil.rmtree(sandbox)
