"""Isolated Bash control-flow harness; pip/systemctl are explicitly simulated."""

import io
import json
import os
import sqlite3
import sys
import tarfile
from pathlib import Path

from trendradar.ai_frontier.storage import AIFrontierStorage
from trendradar.intelligence.storage import IntelligenceStorage

ROOT = Path(__file__).resolve().parents[2]


def make_installer(tmp_path, *, failure="", pause="", first_install=False,
                   service_user="root", service_group="root", active_units=None,
                   ai_present=False, ai_external=False, old_schema=6, business_write=False,
                   build_lock=True):
    for parent in (tmp_path, tmp_path.parent, tmp_path.parent.parent):
        parent.chmod(0o755)
    binary = tmp_path / "bin"
    binary.mkdir()
    database = tmp_path / "output" / "intelligence.db"
    database.parent.mkdir()
    if not first_install:
        with IntelligenceStorage(database, synchronous="FULL"):
            pass
        if old_schema == 5:
            with sqlite3.connect(database) as connection:
                connection.execute("DROP INDEX idx_feishu_events_recovery")
                for column in ("event_json", "binding_json", "delivery_attempts"):
                    connection.execute(f"ALTER TABLE feishu_events DROP COLUMN {column}")
                connection.execute("PRAGMA user_version = 5")
    ai_database = tmp_path / ("separate/ai.db" if ai_external else "output/ai_frontier.db")
    if ai_present:
        with AIFrontierStorage(ai_database, synchronous="FULL"):
            pass
    if active_units is None:
        active_units = [] if first_install else ["test-bot.service", "test-worker.service"]
    units_state = tmp_path / "units.json"
    units_state.write_text(json.dumps(list(active_units)), encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("intelligence:\n  enabled: true\n", encoding="utf-8")
    environment = {
        "PATH": f"{binary}:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONPATH": str(ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "CONFIG_PATH": str(config),
        "INTELLIGENCE_DB_PATH": str(database),
        "AI_FRONTIER_DB_PATH": str(ai_database),
        "TRENDRADAR_RELEASE_ROOT": str(tmp_path / "releases"),
        "TRENDRADAR_CURRENT_LINK": str(tmp_path / "current"),
        "TRENDRADAR_CONTROL_DIR": str(tmp_path / "control"),
        "TRENDRADAR_HEALTH_DIR": str(tmp_path / "health"),
        "TRENDRADAR_LOCK_DIR": str(tmp_path / "locks"),
        "TRENDRADAR_BACKUP_DIR": str(tmp_path / "backups"),
        "TRENDRADAR_RELEASE_ENV": str(tmp_path / "etc" / "release.env"),
        "TRENDRADAR_SERVICE_USER": service_user,
        "TRENDRADAR_SERVICE_GROUP": service_group,
        "TRENDRADAR_RELEASE_ID": "previous",
        "TRENDRADAR_INITIAL_UNITS": "test-bot.service test-worker.service",
        "TRENDRADAR_MANAGED_UNITS": "test-bot.service test-worker.service test-scheduler.service test-scheduler.timer",
        "TRENDRADAR_HEALTH_EXPECTED_ROLES": "bot,worker",
        "INTELLIGENCE_SQLITE_SYNCHRONOUS": "FULL",
        "INTELLIGENCE_HEALTH_REQUIRE_SOURCE_RUNS": "false",
        "INTELLIGENCE_HEALTH_REQUIRE_BACKUP": "false",
        "TRENDRADAR_DEPLOY_VERIFY_SECONDS": "2",
        "TEST_LOG": str(tmp_path / "systemctl.jsonl"),
        "TEST_OPS_LOG": str(tmp_path / "operations.jsonl"),
        "TEST_UNITS_STATE": str(units_state),
        "TEST_TIMER_NOTIFY": str(tmp_path / "timer-tick"),
        "TEST_OLD_SCHEMA": str(old_schema),
        "TEST_BUSINESS_WRITE": "true" if business_write else "false",
        "TEST_FAILURE": failure, "TEST_PAUSE": pause,
        "TEST_NOTIFY": str(tmp_path / "notify"),
    }
    import grp

    # Root and the configured service identity share only this test-owned log.
    # Simulated pip writes first; real migration/snapshot processes append later.
    operations = Path(environment["TEST_OPS_LOG"])
    operations.touch()
    os.chown(operations, 0, grp.getgrnam(service_group).gr_gid)
    operations.chmod(0o660)
    wrapper = binary / "python3"
    test_environment = {key: value for key, value in environment.items() if key.startswith("TEST_")}
    bootstrap = (f"import os,sys\nos.environ.update({test_environment!r})\n"
                 f"os.environ['PYTHONPATH']={str(ROOT)!r}\n"
                 "os.environ['PYTHONDONTWRITEBYTECODE']='1'\n"
                 f"sys.path.insert(0,{str(ROOT)!r})\n")
    wrapper.write_text(f"#!{sys.executable} -B\n" + bootstrap + r'''
import json, os, pathlib, sys
if sys.argv[1:3] == ['-m', 'venv']:
    path = pathlib.Path(sys.argv[3]) / 'bin'
    path.mkdir(parents=True)
    (path / 'python').symlink_to(__file__)
    raise SystemExit(0)
if sys.argv[1:3] == ['-m', 'pip']:
    with open(os.environ['TEST_OPS_LOG'], 'a') as stream:
        stream.write(json.dumps({'args': sys.argv[1:]}) + '\n')
    raise SystemExit(0)
if sys.argv[1:4] == ['-m', 'trendradar.integrations.lark', '--help']:
    raise SystemExit(0)
if sys.argv[1:3] == ['-m', 'trendradar.ops'] or sys.argv[1:2] == ['-']:
    with open(os.environ['TEST_OPS_LOG'], 'a') as stream:
        stream.write(json.dumps({'args': sys.argv[1:], 'release': (
            'previous' if 'previous' in pathlib.Path(__file__).parts else 'candidate'),
            'active': json.loads(
            pathlib.Path(os.environ['TEST_UNITS_STATE']).read_text())}) + '\n')
if sys.argv[1:4] == ['-m', 'trendradar.ops', 'health']:
    if os.environ['TEST_FAILURE'] == 'health-error':
        raise RuntimeError('test-owned health command exception')
if 'previous' in pathlib.Path(__file__).parts and os.environ['TEST_OLD_SCHEMA'] == '5':
    # Historical code compatibility is simulated; SQLite/schema checks are real.
    import runpy
    from trendradar.intelligence import storage
    storage.SCHEMA_VERSION = 5
    def validate(self):
        if self._connection.execute('PRAGMA user_version').fetchone()[0] != 5:
            raise RuntimeError('previous release requires schema 5')
        self._connection.execute('SELECT event_id, status FROM feishu_events LIMIT 0')
    storage.IntelligenceStorage._validate_existing_schema = validate
    storage.IntelligenceStorage._initialize_schema = validate
    sys.argv = ['trendradar.ops', *sys.argv[3:]]
    runpy.run_module('trendradar.ops', run_name='__main__')
    raise SystemExit(0)
os.execv(sys.executable, [sys.executable, '-B', *sys.argv[1:]])
''', encoding="utf-8")
    wrapper.chmod(0o755)
    systemctl = binary / "systemctl"
    systemctl.write_text(f"#!{sys.executable} -B\n" + bootstrap + r'''
import grp, json, os, pathlib, pwd, signal, sqlite3, sys
from datetime import datetime, timedelta, timezone
import trendradar.core.heartbeat as heartbeat
from trendradar.core.heartbeat import RoleHeartbeat
args=sys.argv[1:]
state_path = pathlib.Path(os.environ['TEST_UNITS_STATE'])
active = json.loads(state_path.read_text())
with open(os.environ['TEST_LOG'],'a') as stream:
    stream.write(json.dumps(args)+'\n')
if args[0]=='is-active':
    raise SystemExit(0 if args[-1] in active else 3)
if args[0]=='stop':
    tick = pathlib.Path(os.environ['TEST_TIMER_NOTIFY'])
    if args[1].endswith('.service') and not tick.exists():
        # Simulate a timer expiry while quiescing. A live timer would restart
        # its writer; a stopped timer cannot. This is not real systemd evidence.
        tick.write_text('test-owned timer expiry')
        for timer in os.environ['TRENDRADAR_MANAGED_UNITS'].split():
            if timer.endswith('.timer'):
                fired = timer in active
                with open(os.environ['TEST_LOG'], 'a') as stream:
                    stream.write(json.dumps([
                        'timer-fired' if fired else 'timer-suppressed', timer])+'\n')
                writer = timer.removesuffix('.timer') + '.service'
                if fired and writer not in active:
                    active.append(writer)
    active = [unit for unit in active if unit != args[1]]
    state_path.write_text(json.dumps(active))
if args[0]=='start':
    unit=args[1]
    role = {'test-bot.service': 'bot', 'test-worker.service': 'worker'}.get(unit)
    if os.environ['TEST_PAUSE']=='first-start' and role=='bot':
        pathlib.Path(os.environ['TEST_NOTIFY']).write_text('ready')
        signal.pause()
    if os.environ['TEST_FAILURE']==role:
        raise SystemExit(1)
    if unit not in active:
        active.append(unit)
    state_path.write_text(json.dumps(active))
    if role is None:
        raise SystemExit(0)
    account = pwd.getpwnam(os.environ['TRENDRADAR_SERVICE_USER'])
    group = grp.getgrnam(os.environ['TRENDRADAR_SERVICE_GROUP'])
    os.setgroups([group.gr_gid])
    os.setgid(group.gr_gid)
    os.setuid(account.pw_uid)
    # These synthetic services are recently healthy, away from the future-time edge.
    heartbeat._now = lambda: (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    RoleHeartbeat(role,os.environ['INTELLIGENCE_DB_PATH']).write(
        state='connecting' if os.environ['TEST_FAILURE']=='readiness' else
        ('connected' if role=='bot' else 'running'), sqlite_synchronous='FULL')
    if role == 'bot' and os.environ['TEST_BUSINESS_WRITE'] == 'true':
        with sqlite3.connect(os.environ['INTELLIGENCE_DB_PATH']) as connection:
            connection.execute("UPDATE deployment_probe SET value='candidate-work'")
''', encoding="utf-8")
    systemctl.chmod(0o755)
    if not first_install:
        previous = tmp_path / "releases/previous/venv/bin"
        previous.mkdir(parents=True)
        (previous / "python").symlink_to(wrapper)
        (tmp_path / "current").symlink_to(previous.parents[1])
        release_env = tmp_path / "etc/release.env"
        release_env.parent.mkdir()
        release_env.write_text("TRENDRADAR_RELEASE_ID=previous\n", encoding="utf-8")
    archive = tmp_path / "candidate.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        files = [("requirements.lock", b""), ("pyproject.toml", b"")]
        if build_lock:
            files.append(("build-requirements.lock", b""))
        for name, payload in files:
            member = tarfile.TarInfo(f"trendradar-candidate/{name}")
            member.size = len(payload)
            stream.addfile(member, io.BytesIO(payload))
    import hashlib
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "release_id": "candidate", "git_dirty": False,
        "artifact": {"sha256": hashlib.sha256(archive.read_bytes()).hexdigest()},
    }), encoding="utf-8")
    # The fixture is a synthetic control-flow archive, never production evidence.
    command = ["bash", str(ROOT / "scripts/deploy/install_release.sh"),
               "candidate", str(archive), str(manifest)]
    return command, environment, database
