"""CI selection/exit evidence only: sudo is stubbed; no installer or unit runs."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/phase7-ci.yml"
OPT_IN_MODULES = {"test_pre_fix_linux.py", "test_release_install_linux.py"}
PLAN_MODULES = {
    "tests/deployment/test_health.py",
    "tests/deployment/test_backup.py",
    "tests/deployment/test_offsite_backup.py",
    "tests/deployment/test_offsite_processes.py",
    "tests/deployment/test_restore_recovery.py",
    "tests/deployment/test_deployment_contracts.py",
    "tests/deployment/test_installer_behavior.py",
    "tests/deployment/test_runtime_guards.py",
    "tests/deployment/test_restore_permissions_linux.py",
    "tests/deployment/test_systemd_contract_linux.py",
    "tests/deployment/test_release_inputs.py",
    "tests/deployment/test_deployment_rollback.py",
    "tests/deployment/test_combined_readiness.py",
    "tests/deployment/test_systemd_quiesce_linux.py",
    "tests/deployment/test_remaining_gap_assertions.py",
    "tests/integrations/feishu/test_phase7_roles.py",
}
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="actual CI Bash argv checks")


@pytest.fixture
def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture
def fake_shell(tmp_path):
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "commands.jsonl"
    stub = f"#!{sys.executable} -B\n" + r'''
import json, os, sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
operation = name
if name == 'sudo':
    if '-m' in args:
        index = args.index('-m')
        operation = args[index + 1]
        if operation == 'pip':
            operation += '-' + args[index + 2]
    elif args[-1:] == ['-']:
        operation = 'preflight'
    elif args[:1] == ['runuser']:
        operation = 'runuser'
record = {'tool': name, 'args': args, 'operation': operation,
          'stdin': sys.stdin.read() if args[-1:] == ['-'] else ''}
with Path(os.environ['CI_TEST_LOG']).open('a') as stream:
    stream.write(json.dumps(record) + '\n')
if name == 'cat':
    assert args == ['/proc/1/comm'], args
    print(os.environ['CI_TEST_PID1'])
raise SystemExit(19 if operation == os.environ.get('CI_TEST_FAILURE') else 0)
'''
    for name in ("sudo", "cat", "python"):
        executable = binary / name
        executable.write_text(stub, encoding="utf-8")
        executable.chmod(0o755)

    def run(script, *, failure="", pid1="systemd"):
        log.unlink(missing_ok=True)
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
            cwd=tmp_path,
            env={"PATH": str(binary), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
                 "GITHUB_WORKSPACE": str(tmp_path / "checkout with spaces"),
                 "GITHUB_SHA": "0123456789abcdef0123456789abcdef01234567",
                 "CI_TEST_LOG": str(log), "CI_TEST_PID1": pid1, "CI_TEST_FAILURE": failure},
            capture_output=True, text=True, timeout=10,
        )
        commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, commands

    return run


def _command(record):
    assert record["tool"] == "sudo"
    args = list(record["args"])
    environment = {}
    if args[:1] == ["env"]:
        args.pop(0)
        while args and "=" in args[0]:
            key, value = args.pop(0).split("=", 1)
            environment[key] = value
    return environment, args


@pytest.fixture
def privileged_trace(workflow, fake_shell):
    trace = []
    for step in workflow["jobs"]["privileged-linux"]["steps"]:
        if "run" not in step:
            continue
        result, commands = fake_shell(step["run"])
        assert result.returncode == 0, step["name"] + ": " + result.stderr
        trace.extend((step, record) for record in commands)
    return trace


def _pytest_calls(trace):
    return [(step, *_command(record)) for step, record in trace
            if record["operation"] == "pytest"]


def _targets(args):
    assert args[1:4] == ["-B", "-m", "pytest"], args
    options = args[4:]
    assert not any(option.startswith(("-k", "-m", "--ignore", "--deselect"))
                   for option in options), "acceptance must not filter cases"
    assert options[options.index("-p") + 1] == "no:cacheprovider"
    return [arg for arg in options if arg == "tests" or arg.startswith("tests/")]


@pytest.mark.parametrize("job_name", ["offline", "privileged-linux"])
def test_workflow_run_blocks_are_valid_bash(workflow, job_name):
    for step in workflow["jobs"][job_name]["steps"]:
        if "run" in step:
            result = subprocess.run(["/bin/bash", "-n"], input=step["run"],
                                    capture_output=True, text=True, timeout=5)
            assert result.returncode == 0, step["name"] + ": " + result.stderr


def test_privileged_selection_covers_plan_and_current_deployment_modules(privileged_trace):
    calls = _pytest_calls(privileged_trace)
    focus, = (args for _, environment, args in calls
              if environment.get("TRENDRADAR_P7_ARTIFACT_INSTALL") != "true")
    targets = _targets(focus)
    for target in targets:
        assert (ROOT / target).is_file(), f"missing CI test file: {target}"
    assert set(targets) >= PLAN_MODULES, PLAN_MODULES - set(targets)
    current = {path.relative_to(ROOT).as_posix() for path in (ROOT / "tests/deployment").glob("test_*.py")
               if path.name not in OPT_IN_MODULES}
    assert current <= set(targets), current - set(targets)
    assert len(targets) == len(set(targets)), "duplicate modules waste privileged runtime"


def test_artifact_opt_in_is_separate_and_all_pytest_runs_use_root_toolchain(privileged_trace):
    calls = _pytest_calls(privileged_trace)
    artifact_calls = []
    for step, environment, args in calls:
        assert environment.get("PYTHONDONTWRITEBYTECODE") == "1"
        assert Path(args[0]).is_absolute() and Path("/var/lib") in Path(args[0]).parents
        targets = _targets(args)
        assert "tests" not in targets, "whole-suite regression belongs to the offline job"
        if environment.get("TRENDRADAR_P7_ARTIFACT_INSTALL") == "true":
            assert targets == ["tests/deployment/test_release_install_linux.py"]
            artifact_calls.append(step)
        else:
            assert not any(Path(target).name in OPT_IN_MODULES for target in targets)
    assert len(artifact_calls) == 1


def test_toolchain_uses_python310_locked_dependencies_and_service_uid(workflow, privileged_trace):
    job = workflow["jobs"]["privileged-linux"]
    setup, = (step for step in job["steps"] if "actions/setup-python@" in step.get("uses", ""))
    assert str(setup["with"]["python-version"]) == "3.10"
    commands = [_command(record)[1] for _, record in privileged_trace if record["tool"] == "sudo"]
    venv, = (args for args in commands if args[1:4] == ["-B", "-m", "venv"])
    assert Path("/var/lib") in Path(venv[-1]).parents
    installs = [args for args in commands if args[1:5] == ["-B", "-m", "pip", "install"]]
    assert [args[args.index("-r") + 1] for args in installs] == [
        "build-requirements.lock", "requirements.lock",
    ]
    dependency_check, = (args for args in commands if args[1:] == ["-B", "-m", "pip", "check"])
    assert commands.index(dependency_check) > commands.index(installs[-1])
    service_check, = (args for args in commands if args[:1] == ["runuser"])
    assert service_check[:4] == ["runuser", "-u", "nobody", "--"]
    assert service_check[4] == dependency_check[0]
    assert commands.index(service_check) < next(index for index, args in enumerate(commands)
                                              if args[1:4] == ["-B", "-m", "pytest"])


def test_privileged_acceptance_uses_same_revision_outside_runner_home(privileged_trace):
    commands = [_command(record)[1] for _, record in privileged_trace if record["tool"] == "sudo"]
    clone, = (args for args in commands if args[0] == "git" and "clone" in args)
    checkout, = (args for args in commands if args[0] == "git" and "checkout" in args)
    source = Path(clone[-1])
    assert source.is_absolute() and Path("/var/lib") in source.parents
    assert "--no-hardlinks" in clone
    assert checkout == ["git", "-C", str(source), "checkout", "--detach",
                        "0123456789abcdef0123456789abcdef01234567"]
    service_check, = (args for args in commands if args[:1] == ["runuser"])
    assert commands.index(checkout) < commands.index(service_check)
    assert str(source) in service_check[-1]
    for step, _, _ in _pytest_calls(privileged_trace):
        assert Path(step["working-directory"]) == source


@pytest.mark.parametrize("failure", ["venv", "pip-install", "pip-check", "preflight", "runuser"])
def test_bootstrap_failures_stop_before_later_commands(workflow, fake_shell, failure):
    step, = (step for step in workflow["jobs"]["privileged-linux"]["steps"]
             if "pip install" in step.get("run", ""))
    result, commands = fake_shell(step["run"], failure=failure)
    assert result.returncode == 19, result.stderr
    assert commands[-1]["operation"] == failure
    assert not any(record["operation"] == "pytest" for record in commands)


def test_missing_systemd_rejects_before_creating_toolchain(workflow, fake_shell):
    step, = (step for step in workflow["jobs"]["privileged-linux"]["steps"]
             if "pip install" in step.get("run", ""))
    result, commands = fake_shell(step["run"], pid1="init")
    assert result.returncode != 0
    assert [record["tool"] for record in commands] == ["cat"]


@pytest.mark.parametrize("artifact", [False, True])
def test_acceptance_failure_is_the_step_exit_code(privileged_trace, fake_shell, artifact):
    step, = (step for step, environment, _ in _pytest_calls(privileged_trace)
             if (environment.get("TRENDRADAR_P7_ARTIFACT_INSTALL") == "true") is artifact)
    result, commands = fake_shell(step["run"], failure="pytest")
    assert result.returncode == 19, result.stderr
    assert len(commands) == 1 and commands[0]["operation"] == "pytest"


@pytest.mark.parametrize("executable,base,version,uid,accepted", [
    ("/var/lib/p7/venv/bin/python", "/opt/hostedtoolcache/Python/3.10/bin/python", (3, 10), 0, True),
    ("/tmp/venv/bin/python", "/usr/bin/python3.10", (3, 10), 0, False),
    ("/var/lib/p7/venv/bin/python", "/var/tmp/python/bin/python", (3, 10), 0, False),
    ("/var/lib/p7/venv/bin/python", "/usr/bin/python3.11", (3, 11), 0, False),
    ("/var/lib/p7/venv/bin/python", "/usr/bin/python3.10", (3, 10), 1001, False),
])
def test_actual_python_preflight_rejects_wrong_runtime_and_private_tmp_paths(
    privileged_trace, executable, base, version, uid, accepted,
):
    script, = (record["stdin"] for _, record in privileged_trace
               if record["operation"] == "preflight")
    prefix = (f"import os,sys\nos.geteuid=lambda: {uid}\n"
              f"sys.executable={executable!r}\nsys._base_executable={base!r}\n"
              f"sys.version_info={version!r}\n")
    result = subprocess.run([sys.executable, "-B", "-c", prefix + script],
                            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                            capture_output=True, text=True, timeout=5)
    assert (result.returncode == 0) is accepted, result.stderr
