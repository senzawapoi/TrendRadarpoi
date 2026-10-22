"""RG-01/02 behavior; fake SSH/pip/systemctl are not live SSH or RG-04 evidence."""

import ast
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import pytest
import yaml

from scripts.deploy.validate_deploy_inputs import validate_deploy_inputs

from .installer_harness import ROOT, make_installer

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="RG behavior requires isolated Linux Bash/root",
)

VALID_INPUTS = {
    "RELEASE_ID": "20261014-RG_01.2",
    "DEPLOY_PATH": "/srv/trendradar/incoming",
    "DEPLOY_USER": "deploy-user",
    "DEPLOY_HOST": "deploy.example.invalid",
    "DEPLOY_PORT": "40618",
}
INVALID_INPUTS = [
    ("DEPLOY_PATH", value)
    for value in (
        "", "relative/path", "/", "/srv/../escape", "/srv/./incoming", "/srv//incoming",
        "/srv/incoming/", "/srv/with space", "/srv/tab\tpath", '/srv/double"quote',
        "/srv/single'quote", "/srv/one\\backslash", "/srv/two\\\\backslashes",
        "/srv/semicolon;touch INPUT-EXECUTED", "/srv/$(touch INPUT-EXECUTED)",
        "/srv/`touch INPUT-EXECUTED`", "/srv/pipe|cat", "/srv/amp&cat",
        "/srv/path\ntouch INPUT-EXECUTED", "/srv/path\r", "/srv/unicode-\u00e9",
    )
] + [
    ("RELEASE_ID", value)
    for value in (
        "", ".", "..", "../escape", "-option", "v1..2", "candidate.", "candidate-",
        "two words", "quote\"", "quote'", "back\\slash", "semi;colon", "newline\n",
        "$(touch INPUT-EXECUTED)", "a" * 121,
    )
] + [
    ("DEPLOY_USER", value)
    for value in (
        "", "-root", "root@host", "root:host", "two words", "root'", 'root"',
        "root\\", "root\n", "root;touch INPUT-EXECUTED", "a" * 33,
    )
] + [
    ("DEPLOY_HOST", value)
    for value in (
        "", "-oProxyCommand=touch", "ssh://example.invalid", "user@host", "host:22",
        "host name", "host'", 'host"', "host\\", "host\n", "host;touch INPUT-EXECUTED",
        "../host", "host..invalid", "-host.invalid", "host-.invalid", "999.1.2.3",
        "127.000.0.1", "[::1]", "a" * 64 + ".invalid", "a." * 127 + "a",
    )
] + [
    ("DEPLOY_PORT", value)
    for value in ("0", "65536", "-22", "+22", "22 ", "22\n", "0x16", "22;id", "000022")
]


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load((ROOT / ".github/workflows/phase7-deploy.yml").read_text())


@pytest.fixture
def workflow_scope(tmp_path, workflow):
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "python3").symlink_to(sys.executable)
    log = tmp_path / "transport.jsonl"
    transport = f"#!{sys.executable} -B\n" + r'''
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
required = ['StrictHostKeyChecking=yes', 'BatchMode=yes', 'IdentitiesOnly=yes',
            'GlobalKnownHostsFile=/dev/null',
            'UserKnownHostsFile=' + os.environ['HOME'] + '/.ssh/known_hosts']
options = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == '-o']
pinned = all(option in options for option in required)
accepted = pinned and os.environ['TEST_HOST_KEY'] == 'match'
command = args[-1]
mutation = accepted and (name == 'scp' or command != 'true')
with open(os.environ['TEST_TRANSPORT_LOG'], 'a') as stream:
    stream.write(json.dumps({'tool': name, 'args': args, 'accepted': accepted,
                             'mutation': mutation}) + '\n')
if not accepted:
    print('synthetic host key rejection', file=sys.stderr)
    raise SystemExit(255)
if name == os.environ.get('TEST_FAIL_TRANSPORT'):
    raise SystemExit(1)
'''
    for name in ("ssh", "scp"):
        executable = binary / name
        executable.write_text(transport)
        executable.chmod(0o755)
    environment = {
        **VALID_INPUTS,
        "PATH": f"{binary}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "DEPLOY_KNOWN_HOSTS": "SYNTHETIC-PINNED-KEY",
        "SSH_PRIVATE_KEY": "SYNTHETIC-PRIVATE-KEY",
        "TEST_HOST_KEY": "match",
        "TEST_TRANSPORT_LOG": str(log),
    }
    copy_step = next(
        step for step in workflow["jobs"]["deploy"]["steps"]
        if step["name"] == "Copy bundle and activate through the fixed installer"
    )
    return tmp_path, environment, log, copy_step["run"]


def run_workflow(scope, changes=None):
    sandbox, environment, log, script = scope
    result = subprocess.run(
        ["bash", "-c", script], cwd=sandbox, env={**environment, **(changes or {})},
        capture_output=True, text=True, timeout=10,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


def test_deploy_inline_validator_is_the_standalone_source(workflow):
    copy_step = workflow["jobs"]["deploy"]["steps"][-1]["run"]
    inline = copy_step.split("python3 -B - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    assert inline + "\n" == (ROOT / "scripts/deploy/validate_deploy_inputs.py").read_text()
    assert not any("actions/checkout@" in step.get("uses", "")
                   for step in workflow["jobs"]["deploy"]["steps"])


def test_changed_python_and_workflow_shell_parse_without_writing_bytecode(workflow):
    for path in (
        ROOT / "scripts/deploy/validate_deploy_inputs.py",
        Path(__file__), ROOT / "tests/deployment/test_deployment_contracts.py",
    ):
        ast.parse(path.read_text(), filename=str(path))
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "run" in step:
                result = subprocess.run(["bash", "-n"], input=step["run"], capture_output=True,
                                        text=True, timeout=5)
                assert result.returncode == 0, step["name"] + ": " + result.stderr


@pytest.mark.parametrize(("field", "value"), INVALID_INPUTS)
def test_invalid_inputs_reject_actual_workflow_before_ssh_or_key_writes(
    workflow_scope, field, value,
):
    sandbox, environment, _, _ = workflow_scope
    with pytest.raises(ValueError, match=f"^invalid {field}$"):
        validate_deploy_inputs({**environment, field: value})
    result, calls = run_workflow(workflow_scope, {field: value})
    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stderr.strip() == f"invalid {field}"
    assert not calls
    assert not (Path(environment["HOME"]) / ".ssh").exists()
    assert not (sandbox / "INPUT-EXECUTED").exists()


@pytest.mark.parametrize("changes", [
    {}, {"DEPLOY_PORT": ""}, {"DEPLOY_PORT": "1"}, {"DEPLOY_PORT": "65535"},
    {"DEPLOY_PORT": "00022", "DEPLOY_HOST": "192.0.2.1"},
    {"RELEASE_ID": "R" + "a" * 119, "DEPLOY_PATH": "/srv/releases-1/.incoming", "DEPLOY_USER": "_deploy"},
])
def test_valid_inputs_reach_upload_and_only_the_fixed_installer(workflow_scope, changes):
    _, environment, _, _ = workflow_scope
    values = {**environment, **changes}
    result, calls = run_workflow(workflow_scope, changes)
    assert result.returncode == 0, result.stdout + result.stderr
    assert [call["tool"] for call in calls] == ["ssh", "ssh", "scp", "ssh"]
    assert all(call["accepted"] for call in calls)
    assert calls[0]["args"][-1] == "true" and not calls[0]["mutation"]
    port = str(validate_deploy_inputs(values))
    for call in calls:
        assert call["args"][:2] == ["-P" if call["tool"] == "scp" else "-p", port]
    release = values["RELEASE_ID"]
    remote = f"{values['DEPLOY_PATH']}/{release}"
    target = f"{values['DEPLOY_USER']}@{values['DEPLOY_HOST']}"
    assert calls[1]["args"][-2:] == [target, f"install -d -m 0750 '{remote}'"]
    assert calls[2]["args"][-3:] == [
        f"dist/trendradar-{release}.tar.gz", "dist/RELEASE-MANIFEST.json", f"{target}:{remote}/",
    ]
    assert calls[3]["args"][-2:] == [target,
        f"sudo -- /usr/local/sbin/trendradar-install-release '{release}' "
        f"'{remote}/trendradar-{release}.tar.gz' '{remote}/RELEASE-MANIFEST.json'",
    ]


def test_host_key_rejection_precedes_all_remote_mutations(workflow_scope):
    result, calls = run_workflow(workflow_scope, {"TEST_HOST_KEY": "mismatch"})
    assert result.returncode == 255
    assert "synthetic host key rejection" in result.stderr
    assert len(calls) == 1 and calls[0]["tool"] == "ssh"
    assert calls[0]["args"][-1] == "true"
    assert not any(call["mutation"] for call in calls)


@pytest.mark.parametrize("field", ["DEPLOY_KNOWN_HOSTS", "SSH_PRIVATE_KEY"])
def test_missing_ssh_material_rejects_before_transport_or_key_writes(workflow_scope, field):
    _, environment, _, _ = workflow_scope
    result, calls = run_workflow(workflow_scope, {field: ""})
    assert result.returncode != 0 and not calls
    assert not (Path(environment["HOME"]) / ".ssh").exists()


def test_scp_failure_does_not_invoke_the_fixed_installer(workflow_scope):
    result, calls = run_workflow(workflow_scope, {"TEST_FAIL_TRANSPORT": "scp"})
    assert result.returncode == 1
    assert [call["tool"] for call in calls] == ["ssh", "ssh", "scp"]


@pytest.mark.parametrize("release", ["candidate.", "candidate-", "..", 'quote"', "back\\slash"])
def test_actual_packaging_validation_step_rejects_unstable_release_ids(workflow, release):
    steps = workflow["jobs"]["validated-artifact"]["steps"]
    step = next(step for step in steps if step["name"] == "Validate release identifier before packaging")
    assert steps.index(step) < next(i for i, step in enumerate(steps)
                                   if step["name"] == "Install and validate this exact revision")
    result = subprocess.run(
        ["bash", "-c", step["run"]], cwd=ROOT,
        env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin", "RELEASE_ID": release,
             "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2 and result.stderr.strip() == "invalid RELEASE_ID"


def installer_scope(sandbox):
    command, environment, database = make_installer(sandbox)
    replace_archive(command)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    # Disable bytecode in harness subprocesses, including the sanitized entry path.
    for name in ("python3", "systemctl"):
        path = sandbox / "bin" / name
        text = path.read_text().replace(f"#!{sys.executable}\n", f"#!{sys.executable} -B\n", 1)
        text = text.replace("import os,sys\n", "import os,sys\nos.environ['PYTHONDONTWRITEBYTECODE']='1'\n", 1)
        if name == "python3":
            anchor = "if sys.argv[1:3] == ['-m', 'venv']:"
            assert anchor in text
            text = text.replace(anchor, "import json\n"
                                f"with open({str(sandbox / 'python.jsonl')!r}, 'a') as stream:\n"
                                "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n" + anchor, 1)
        path.write_text(text)
    previous = sandbox / "releases/previous"
    previous.mkdir(parents=True, exist_ok=True)
    current = sandbox / "current"
    if not current.is_symlink():
        current.symlink_to(previous)
    release_env = Path(environment["TRENDRADAR_RELEASE_ENV"])
    release_env.parent.mkdir(exist_ok=True)
    if not release_env.exists():
        release_env.write_text("TRENDRADAR_RELEASE_ID=previous\n")
    return command, environment, database


def replace_archive(command, *, member_name=None, member_type=tarfile.REGTYPE, extra=None):
    archive = Path(command[3])
    with tarfile.open(archive, "w:gz") as stream:
        entries = [("trendradar-candidate/requirements.lock", b""),
                   ("trendradar-candidate/build-requirements.lock", b""),
                   ("trendradar-candidate/pyproject.toml", b"")]
        if extra:
            entries.append(extra)
        for name, payload in entries:
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            stream.addfile(member, io.BytesIO(payload))
        if member_name:
            member = tarfile.TarInfo(member_name)
            member.type = member_type
            if member_type in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                member.linkname = str(archive.parent / "RG-ESCAPED")
            stream.addfile(member, io.BytesIO(b""))
    manifest = Path(command[4])
    value = json.loads(manifest.read_text())
    value["artifact"]["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(value))


def assert_no_migration_or_switch(sandbox, database, before):
    assert database.read_bytes() == before
    assert not Path(database.parent / "ai_frontier.db").exists()
    assert (sandbox / "current").resolve() == sandbox / "releases/previous"
    assert (sandbox / "etc/release.env").read_text() == "TRENDRADAR_RELEASE_ID=previous\n"
    assert not (sandbox / "releases/candidate").exists()
    assert not (sandbox / "systemctl.jsonl").exists()
    assert not list(sandbox.rglob("RG-ESCAPED"))
    calls = [json.loads(line) for line in (sandbox / "python.jsonl").read_text().splitlines()]
    assert not any(call[:2] in (["-m", "venv"], ["-m", "pip"], ["-m", "trendradar.ops"])
                   for call in calls)
    for path in (sandbox / "control").glob("deploy-*.json"):
        transaction = json.loads(path.read_text())
        assert transaction["business_boundary_crossed"] is False
        assert transaction["state"] in {"prepare", "failed:acquire"}


@pytest.mark.parametrize(("case", "message"), [
    ("sha", "release checksum mismatch"), ("release", "release manifest release id mismatch"),
    ("dirty", "dirty release is not installable"), ("sha-missing", "release manifest has no artifact sha256"),
    ("artifact-missing", "release manifest has no artifact sha256"),
    ("json", "invalid manifest"),
])
def test_real_installer_rejects_bad_manifests_before_migration_or_switch(tmp_path, case, message):
    command, environment, database = installer_scope(tmp_path)
    manifest = Path(command[4])
    value = json.loads(manifest.read_text())
    if case == "sha":
        value["artifact"]["sha256"] = "0" * 64
    elif case == "release":
        value["release_id"] = "different"
    elif case == "dirty":
        value["git_dirty"] = True
    elif case == "sha-missing":
        value["artifact"].pop("sha256")
    elif case == "artifact-missing":
        value.pop("artifact")
    manifest.write_text("{broken" if case == "json" else json.dumps(value))
    before = database.read_bytes()
    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2, result.stdout + result.stderr
    assert message in result.stderr
    assert_no_migration_or_switch(tmp_path, database, before)


@pytest.mark.parametrize(("case", "member_type"), [
    ("traversal", tarfile.REGTYPE), ("absolute", tarfile.REGTYPE),
    ("wrong-root", tarfile.REGTYPE), ("symlink", tarfile.SYMTYPE),
    ("hardlink", tarfile.LNKTYPE), ("fifo", tarfile.FIFOTYPE),
])
def test_real_installer_rejects_unsafe_tar_members_without_escape(tmp_path, case, member_type):
    command, environment, database = installer_scope(tmp_path)
    member_name = {
        "traversal": "trendradar-candidate/../../RG-ESCAPED",
        "absolute": str(tmp_path / "RG-ESCAPED"),
        "wrong-root": "other-release/RG-ESCAPED",
    }.get(case, "trendradar-candidate/link")
    replace_archive(command, member_name=member_name, member_type=member_type)
    before = database.read_bytes()
    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    message = "unsupported archive member" if case in {"symlink", "hardlink", "fifo"} else "invalid archive member"
    assert message in result.stderr, result.stdout + result.stderr
    assert_no_migration_or_switch(tmp_path, database, before)


def test_legal_synthetic_archive_continues_through_real_migration_and_finalize(tmp_path):
    command, environment, database = installer_scope(tmp_path)
    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "current").resolve() == tmp_path / "releases/candidate"
    assert (tmp_path / "etc/release.env").read_text() == "TRENDRADAR_RELEASE_ID=candidate\n"
    assert database.is_file() and (database.parent / "ai_frontier.db").is_file()
    assert not (tmp_path / "control/deploy-in-progress.json").exists()
    transaction, = (tmp_path / "control").glob("deploy-*.json")
    assert json.loads(transaction.read_text())["state"] == "finalize"
    calls = [json.loads(line) for line in (tmp_path / "python.jsonl").read_text().splitlines()]
    assert any(call[:4] == ["-m", "trendradar.ops", "database", "migrate"] for call in calls)
    assert any(call[:3] == ["-m", "trendradar.ops", "health"] for call in calls)
    assert any(call[:4] == ["-m", "trendradar.ops", "maintenance", "finalize-deployment"]
               for call in calls)


@pytest.fixture
def fixed_scope():
    # Retained evidence under root-owned ancestors; never touch installed system paths.
    sandbox = Path(tempfile.mkdtemp(prefix="p7-rg-entry-", dir="/var/lib"))
    command, environment, database = installer_scope(sandbox)
    installer = sandbox / "installer.sh"
    installer.write_text((ROOT / "scripts/deploy/install_release.sh").read_text())
    installer.chmod(0o750)
    common = sandbox / "common.env"
    common.write_text("\n".join(
        f'{key}="{value}"' for key, value in environment.items()
        if key not in {"PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"}
        and not key.startswith("TEST_")
    ))
    common.chmod(0o640)
    loader = sandbox / "loader.py"
    loader.write_text((ROOT / "scripts/deploy/load_environment.py").read_text().replace(
        '"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"', f'"PATH": {environment["PATH"]!r}',
    ))
    entry = sandbox / "entry"
    entry.write_text((ROOT / "deploy/bin/trendradar-install-release").read_text()
                     .replace("/usr/local/libexec/trendradar/install_release.sh", str(installer))
                     .replace("/usr/local/libexec/trendradar/load_environment.py", str(loader))
                     .replace("/etc/trendradar/common.env", str(common)))
    entry.chmod(0o755)
    return sandbox, [str(entry), *command[2:]], environment, database, installer


@pytest.mark.parametrize("release", ["../escape", 'bad"quote', "bad'quote", "bad\\slash", "bad;id", "bad\n"])
def test_fixed_entry_rejects_invalid_release_before_installer_mutations(fixed_scope, release):
    sandbox, command, _, database, _ = fixed_scope
    before = database.read_bytes()
    command[1] = release
    result = subprocess.run(command, env={"PATH": "/usr/bin:/bin"}, capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 2 and "invalid release id" in result.stderr
    assert database.read_bytes() == before
    assert not (sandbox / "control").exists()
    assert (sandbox / "current").resolve() == sandbox / "releases/previous"


def test_fixed_entry_requires_root_before_loading_or_installing(fixed_scope):
    sandbox, command, _, _, _ = fixed_scope
    result = subprocess.run(["/usr/sbin/runuser", "-u", "nobody", "--", *command],
                            env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=15)
    assert result.returncode == 77 and "must be invoked through sudo" in result.stderr
    assert not (sandbox / "control").exists()


def test_fixed_entry_refuses_a_caller_dirty_override(fixed_scope):
    sandbox, command, _, database, _ = fixed_scope
    manifest = Path(command[3])
    value = json.loads(manifest.read_text())
    value["git_dirty"] = True
    manifest.write_text(json.dumps(value))
    before = database.read_bytes()
    result = subprocess.run(command, env={"PATH": "/usr/bin:/bin",
                            "TRENDRADAR_ALLOW_DIRTY_RELEASE": "true"}, capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 2 and "dirty release is not installable" in result.stderr
    assert_no_migration_or_switch(sandbox, database, before)


def test_fixed_entry_rejects_an_untrusted_installer(fixed_scope):
    sandbox, command, _, database, installer = fixed_scope
    before = database.read_bytes()
    installer.chmod(0o777)
    result = subprocess.run(command, env={"PATH": "/usr/bin:/bin"}, capture_output=True,
                            text=True, timeout=15)
    assert result.returncode == 2 and "invalid or missing trusted production configuration" in result.stderr
    assert database.read_bytes() == before and not (sandbox / "control").exists()


def test_archive_cannot_replace_the_executed_fixed_installer(fixed_scope):
    sandbox, command, _, _, installer = fixed_scope
    marker = sandbox / "INPUT-EXECUTED"
    malicious = f"#!/bin/sh\ntouch '{marker}'\nexit 91\n".encode()
    harness_command = ["bash", str(installer), *command[1:]]
    replace_archive(harness_command, extra=("trendradar-candidate/scripts/deploy/install_release.sh", malicious))
    original = installer.read_bytes()
    result = subprocess.run(command, env={"PATH": "/usr/bin:/bin",
                            "TRENDRADAR_RELEASE_ROOT": str(sandbox / "caller-release-root"),
                            "PYTHONPATH": "/untrusted-caller"}, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists() and not (sandbox / "caller-release-root").exists()
    assert installer.read_bytes() == original
    assert (sandbox / "releases/candidate/scripts/deploy/install_release.sh").read_bytes() == malicious
    assert (sandbox / "current").resolve() == sandbox / "releases/candidate"
