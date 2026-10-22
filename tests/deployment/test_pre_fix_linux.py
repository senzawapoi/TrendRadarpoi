"""Reproduce F-01/F-04 from the retained immutable pre-fix archive, not current code."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0
    or os.environ.get("TRENDRADAR_P7_PRE_FIX") != "true",
    reason="requires isolated Linux root and explicit retained-audit reproduction",
)


@pytest.fixture
def audit_source():
    manifest = json.loads((ROOT / "dist/RELEASE-MANIFEST-phase7-audit.json").read_text())
    archive = ROOT / "dist/trendradar-phase7-audit.tar.gz"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest["artifact"]["sha256"]
    sandbox = Path(tempfile.mkdtemp(prefix="p7-pre-fix-", dir="/var/lib"))
    sandbox.chmod(0o755)
    try:
        with tarfile.open(archive) as stream:
            for member in stream.getmembers():
                assert member.isfile()
                path = Path(member.name)
                assert not path.is_absolute() and ".." not in path.parts
                assert path.parts[0] == "trendradar-phase7-audit"
            stream.extractall(sandbox)
        yield sandbox, sandbox / "trendradar-phase7-audit", manifest
    finally:
        shutil.rmtree(sandbox)


def test_pre_fix_entry_drops_trusted_configuration_and_health_reads_wrong_database(audit_source):
    sandbox, source, manifest = audit_source
    runtime = sandbox / "runtime"
    runtime.mkdir()
    common = sandbox / "common.env"
    configured = runtime / "intelligence.db"
    config = sandbox / "config.yaml"
    config.write_text(json.dumps({"intelligence": {"enabled": True, "health": {
        "expected_roles": ["bot", "worker"], "require_source_runs": False,
        "require_backup": False,
    }}}), encoding="utf-8")
    configured_values = {
        "INTELLIGENCE_DB_PATH": str(configured), "CONFIG_PATH": str(config),
        "TRENDRADAR_CONTROL_DIR": str(sandbox / "control"),
        "TRENDRADAR_HEALTH_DIR": str(sandbox / "health"),
        "TRENDRADAR_RELEASE_ID": "pre-fix-ready",
    }
    common.write_text("\n".join(f'{key}="{value}"' for key, value in configured_values.items()),
                      encoding="utf-8")
    initialized = subprocess.run([
        sys.executable, "-B", "-c",
        "import os; from trendradar.intelligence.storage import IntelligenceStorage; "
        "from trendradar.core.heartbeat import RoleHeartbeat; "
        "db=os.environ['INTELLIGENCE_DB_PATH']; storage=IntelligenceStorage(db); storage.close(); "
        "RoleHeartbeat('bot',db).write(state='connected',sqlite_synchronous='FULL'); "
        "RoleHeartbeat('worker',db).write(state='running',sqlite_synchronous='FULL')",
    ], cwd=source, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(source), **configured_values},
        capture_output=True, text=True, timeout=20)
    assert initialized.returncode == 0, initialized.stderr
    positive = subprocess.run([
        sys.executable, "-B", "-m", "trendradar.ops", "health", "--readiness", "--json",
    ], cwd=source, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(source), **configured_values},
        capture_output=True, text=True, timeout=20)
    assert positive.returncode == 0, positive.stdout + positive.stderr
    helper = sandbox / "controlled-installer"
    helper.write_text(
        f"#!{sys.executable}\nimport json,os,subprocess,sys\n"
        "result=subprocess.run([sys.executable,'-B','-m','trendradar.ops','health',"
        "'--readiness','--json'],capture_output=True,text=True)\n"
        "print(json.dumps({'database':os.environ.get('INTELLIGENCE_DB_PATH'),"
        "'health_exit':result.returncode,'health':json.loads(result.stdout)}))\n",
        encoding="utf-8",
    )
    helper.chmod(0o750)
    entry = sandbox / "entry"
    entry.write_text((source / "deploy/bin/trendradar-install-release").read_text().replace(
        "/usr/local/libexec/trendradar/install_release.sh", str(helper),
    ), encoding="utf-8")
    entry.chmod(0o750)
    observed = subprocess.run([str(entry), "audit"], cwd=source, env={
        "PATH": "/usr/bin:/bin", "PYTHONPATH": str(source),
        "TRENDRADAR_CONTROL_DIR": str(sandbox / "control"),
        "TRENDRADAR_HEALTH_DIR": str(sandbox / "health"),
    }, capture_output=True, text=True, timeout=20)
    assert observed.returncode == 0, observed.stderr
    result = json.loads(observed.stdout)
    assert result["database"] is None
    assert result["health_exit"] != 0
    assert configured.exists()
    assert not (source / "output/intelligence.db").exists()
    print("PRE_FIX_EVIDENCE " + json.dumps({
        "case": "F-01", "artifact_sha256": manifest["artifact"]["sha256"],
        "entry_from_archive": True, "common_configuration_loaded": False,
        "configured_readiness_exit": positive.returncode,
        "readiness_exit": result["health_exit"],
        "limits": "controlled installer substituted by real archived health CLI; no writers started",
    }))


def test_pre_fix_root_restore_removes_service_ownership_and_readability(audit_source):
    sandbox, source, manifest = audit_source
    code = r'''
import json,os,sqlite3,stat,subprocess,sys
from pathlib import Path
import trendradar.ops.backup as backup
root=Path(sys.argv[1]); archived=Path(sys.argv[2])
assert Path(backup.__file__).is_relative_to(archived)
output=root/'runtime'; output.mkdir(mode=0o750); os.chown(output,65534,65534)
database=output/'intelligence.db'
connection=sqlite3.connect(database)
connection.execute('CREATE TABLE marker (value TEXT)')
connection.execute("INSERT INTO marker VALUES ('original')")
connection.commit(); connection.close()
os.chown(database,65534,65534); database.chmod(0o660)
probe="import os,sqlite3,sys; os.setgroups([]); os.setgid(65534); os.setuid(65534); sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True).execute('SELECT * FROM marker')"
before=subprocess.run([sys.executable,'-B','-c',probe,str(database)],capture_output=True)
assert before.returncode==0,before.stderr
snapshot=backup.create_snapshot([database],root/'backups',root=output)
restored=root/'restored'
backup.restore_snapshot(snapshot['path'],restored,guard_database=database)
backup.activate_restore(restored,database,root=output)
after=subprocess.run([sys.executable,'-B','-c',probe,str(database)],capture_output=True)
info=database.stat()
assert info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o600
assert after.returncode!=0
print(json.dumps({'owner':info.st_uid,'group':info.st_gid,'mode':oct(stat.S_IMODE(info.st_mode)),
                 'service_before':before.returncode,'service_after':after.returncode}))
'''
    observed = subprocess.run([sys.executable, "-B", "-c", code, str(sandbox), str(source)],
        cwd=source, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(source),
                        "TRENDRADAR_CONTROL_DIR": str(sandbox / "control"),
                        "TRENDRADAR_LOCK_DIR": str(sandbox / "locks")},
        capture_output=True, text=True, timeout=20)
    assert observed.returncode == 0, observed.stderr
    print("PRE_FIX_EVIDENCE " + json.dumps({
        "case": "F-04", "artifact_sha256": manifest["artifact"]["sha256"],
        "observed": json.loads(observed.stdout), "module_from_archive": True,
    }))
