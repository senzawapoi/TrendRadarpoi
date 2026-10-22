"""ENV-02..04: fixed entry, sanitized caller and actual OS lock contention."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from trendradar.core.locking import runtime_locks
from trendradar.ops.backup import create_snapshot, restore_snapshot

from .installer_harness import ROOT

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="trusted POSIX entry requires isolated Linux root",
)


@pytest.fixture
def entry_scope():
    sandbox = Path(tempfile.mkdtemp(prefix="p7-environment-", dir="/var/lib"))
    try:
        config = sandbox / "config.yaml"
        config.write_text("{}", encoding="utf-8")
        values = {
            "CONFIG_PATH": str(config), "INTELLIGENCE_DB_PATH": str(sandbox / "runtime/unified.db"),
            "AI_FRONTIER_DB_PATH": str(sandbox / "runtime/ai.db"),
            "TRENDRADAR_CONTROL_DIR": str(sandbox / "transactions"),
            "TRENDRADAR_HEALTH_DIR": str(sandbox / "run/heartbeats"),
            "TRENDRADAR_LOCK_DIR": str(sandbox / "run/role-locks"),
            "TRENDRADAR_BACKUP_DIR": str(sandbox / "snapshots"),
            "INTELLIGENCE_SQLITE_SYNCHRONOUS": "FULL",
        }
        common = sandbox / "common.env"
        common.write_text("\n".join(f'{key}="{value}"' for key, value in values.items()), encoding="utf-8")
        common.chmod(0o640)
        loader = sandbox / "loader.py"
        shutil.copyfile(ROOT / "scripts/deploy/load_environment.py", loader)
        installer = sandbox / "maintenance-helper"
        # This isolated trusted helper substitutes only installer operations;
        # the fixed entry and production environment parser remain unchanged.
        installer.write_text(
            f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0,{str(ROOT)!r})\n"
            "from trendradar.ops.database import main as database_main\n"
            "from trendradar.ops.backup import main as backup_main\n"
            "from trendradar.core.heartbeat import heartbeat_directory\n"
            "from trendradar.core.locking import lock_directory\n"
            "from trendradar.ops.maintenance import control_directory\n"
            "database=os.environ['INTELLIGENCE_DB_PATH']\n"
            "if sys.argv[1]=='paths':\n"
            "    print(json.dumps({'database':database,'ai':os.environ['AI_FRONTIER_DB_PATH'],"
            "'health':str(heartbeat_directory(database)),'locks':str(lock_directory(database)),"
            "'control':str(control_directory(database)),'backup':os.environ['TRENDRADAR_BACKUP_DIR'],"
            "'caller_secret_present':'GEMINI_API_KEY' in os.environ}))\n"
            "elif sys.argv[1]=='migrate':\n"
            "    raise SystemExit(database_main(['migrate','--database',database]))\n"
            "else:\n"
            "    raise SystemExit(backup_main(['activate','--restored',sys.argv[2],"
            "'--database',database,'--root',str(Path(database).parent)]))\n", encoding="utf-8",
        )
        installer.chmod(0o750)
        entry = sandbox / "entry"
        entry.write_text((ROOT / "deploy/bin/trendradar-install-release").read_text()
                         .replace("/usr/local/libexec/trendradar/install_release.sh", str(installer))
                         .replace("/usr/local/libexec/trendradar/load_environment.py", str(loader))
                         .replace("/etc/trendradar/common.env", str(common)), encoding="utf-8")
        entry.chmod(0o750)
        yield sandbox, entry, common, values
    finally:
        shutil.rmtree(sandbox)


def invoke(entry, *args):
    return subprocess.run([str(entry), *args], env={"PATH": "/usr/bin:/bin",
        "GEMINI_API_KEY": "SYNTHETIC-CALLER-SECRET", "INTELLIGENCE_DB_PATH": "/ignored.db"},
        capture_output=True, text=True, timeout=15)


def test_all_runtime_paths_use_trusted_configuration(entry_scope):
    sandbox, entry, _, values = entry_scope
    result = invoke(entry, "paths")
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    for field, key in (("database", "INTELLIGENCE_DB_PATH"), ("ai", "AI_FRONTIER_DB_PATH"),
                       ("health", "TRENDRADAR_HEALTH_DIR"), ("locks", "TRENDRADAR_LOCK_DIR"),
                       ("control", "TRENDRADAR_CONTROL_DIR"), ("backup", "TRENDRADAR_BACKUP_DIR")):
        assert observed[field] == values[key]
    assert observed["caller_secret_present"] is False
    assert not (sandbox / "output").exists()


@pytest.mark.parametrize("case", ["missing", "format", "config-directory", "substitution", "writable"])
def test_invalid_common_fails_before_maintenance(entry_scope, case):
    sandbox, entry, common, values = entry_scope
    if case == "missing":
        common.unlink()
    elif case == "format":
        common.write_text('CONFIG_PATH="unterminated\n', encoding="utf-8")
    elif case == "config-directory":
        common.write_text(common.read_text().replace(values["CONFIG_PATH"], str(sandbox)))
    elif case == "substitution":
        common.write_text(common.read_text().replace(values["CONFIG_PATH"], "$(touch SYNTHETIC-CALLER-SECRET)"))
    else:
        common.chmod(0o666)
    result = invoke(entry, "migrate")
    assert result.returncode == 2
    assert "invalid or missing trusted production configuration" in result.stderr
    assert "SYNTHETIC-CALLER-SECRET" not in result.stdout + result.stderr
    assert not Path(values["INTELLIGENCE_DB_PATH"]).exists()
    assert not Path(values["TRENDRADAR_CONTROL_DIR"]).exists()
    assert not Path(values["TRENDRADAR_LOCK_DIR"]).exists()


@pytest.mark.parametrize("role", ["bot", "worker", "collector", "scheduler"])
@pytest.mark.parametrize("operation", ["migrate", "activate"])
def test_entry_maintenance_contends_for_real_role_lock(entry_scope, monkeypatch, role, operation):
    sandbox, entry, _, values = entry_scope
    database = Path(values["INTELLIGENCE_DB_PATH"])
    monkeypatch.setenv("TRENDRADAR_LOCK_DIR", values["TRENDRADAR_LOCK_DIR"])
    monkeypatch.setenv("TRENDRADAR_CONTROL_DIR", values["TRENDRADAR_CONTROL_DIR"])
    assert invoke(entry, "migrate").returncode == 0
    before = database.read_bytes()
    args = ["migrate"]
    if operation == "activate":
        snapshot = create_snapshot([database], sandbox / "snapshots", root=database.parent)
        restored = sandbox / "restored"
        restore_snapshot(snapshot["path"], restored, guard_database=database)
        args = ["activate", str(restored)]
    with runtime_locks(database, role):
        blocked = invoke(entry, *args)
        assert blocked.returncode != 0
        assert "runtime lock is busy" in blocked.stderr
        assert database.read_bytes() == before
    allowed = invoke(entry, *args)
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    assert (Path(values["TRENDRADAR_LOCK_DIR"]) / f"{role}.lock").is_file()
    assert not (database.parent / "locks").exists()
