"""RG-04: opt-in real Linux artifact installation outside the source checkout."""

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import venv
from pathlib import Path

import pytest

from scripts.deploy.build_release import build_release
from scripts.deploy.create_manifest import create_manifest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("TRENDRADAR_P7_ARTIFACT_INSTALL") != "true",
    reason="requires opt-in isolated Linux dependency installation",
)


def _run(command, *, cwd, environment, timeout=300):
    result = subprocess.run(
        command, cwd=cwd, env=environment, capture_output=True, text=True, timeout=timeout,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_locked_artifact_installs_into_empty_venv_and_runs_without_checkout(tmp_path):
    supplied_archive = os.environ.get("TRENDRADAR_P7_ARTIFACT_PATH")
    if supplied_archive:
        archive = Path(supplied_archive).resolve()
        manifest = json.loads(Path(os.environ["TRENDRADAR_P7_ARTIFACT_MANIFEST"]).read_text())
        actual = create_manifest(archive, manifest["release_id"])
        assert not manifest["git_dirty"] and not actual["git_dirty"]
        assert manifest["git_commit"] == actual["git_commit"]
        assert manifest["artifact"] == actual["artifact"]
        assert manifest["dependency_files"] == actual["dependency_files"]
    else:
        archive = build_release(tmp_path / "artifacts", "isolated-install")
        manifest = create_manifest(archive, "isolated-install")
    release_id = manifest["release_id"]
    assert isinstance(manifest["git_dirty"], bool)
    assert manifest["git_commit"] != "unknown"
    # A dirty checkout can prove packaging mechanics, never a clean candidate.
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            parts = Path(member.name).parts
            assert member.isfile()
            assert parts[0] == f"trendradar-{release_id}"
            assert not any(part in {"output", "runtime", "__pycache__", ".pytest_cache", ".ruff_cache"} for part in parts)
            assert not member.name.endswith((".db", ".db-wal", ".db-shm", ".pyc"))
            assert Path(member.name).name != ".env"
        stream.extractall(extracted)
    release = extracted / f"trendradar-{release_id}"
    isolated = tmp_path / "outside-checkout"
    isolated.mkdir()
    virtualenv = tmp_path / "empty-venv"
    # Match Linux `python -m venv`: preserve the base interpreter location,
    # including relocatable CPython toolchains used by isolated systemd tests.
    venv.EnvBuilder(with_pip=True, symlinks=True).create(virtualenv)
    python = str(virtualenv / "bin/python")
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(tmp_path / "pip-home"),
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GEMINI_ENABLED": "false",
        "LARK_ENABLED": "false",
        "INTELLIGENCE_RESEARCH_ENABLED": "false",
        "INTELLIGENCE_DB_PATH": str(tmp_path / "missing/intelligence.db"),
        "FREQUENCY_WORDS_PATH": str(release / "config/frequency_words.txt"),
        "TRENDRADAR_CONTROL_DIR": str(tmp_path / "control"),
        "TRENDRADAR_HEALTH_DIR": str(tmp_path / "health"),
        "TRENDRADAR_LOCK_DIR": str(tmp_path / "locks"),
    }
    _run([python, "-B", "-m", "pip", "install", "-r", str(release / "build-requirements.lock")],
         cwd=isolated, environment=environment)
    runtime_command = [python, "-B", "-m", "pip", "install", "-r", str(release / "requirements.lock")]
    wheelhouse = os.environ.get("TRENDRADAR_P7_WHEELHOUSE")
    if wheelhouse:
        runtime_command += ["--no-index", "--find-links", wheelhouse]
    _run(runtime_command, cwd=isolated, environment=environment)
    _run([python, "-B", "-m", "pip", "install", "--no-build-isolation", "--no-deps", str(release)],
         cwd=isolated, environment=environment)
    checked = _run([python, "-B", "-m", "pip", "check"], cwd=isolated, environment=environment)
    assert "No broken requirements found" in checked.stdout
    imported = _run([
        python, "-B", "-c",
        "import json,sys,sqlite3,trendradar,mcp_server; "
        "from pathlib import Path; "
        "assert Path(trendradar.__file__).is_relative_to(Path(sys.prefix)); "
        "assert Path(mcp_server.__file__).is_relative_to(Path(sys.prefix)); "
        "import trendradar.__main__,trendradar.ai_frontier.__main__,mcp_server.server; "
        "from trendradar.core.frequency import load_frequency_words; "
        "assert len(load_frequency_words()) == 3; "
        "print(json.dumps({'python':sys.version.split()[0],'sqlite':sqlite3.sqlite_version}))",
    ], cwd=isolated, environment=environment)
    _run(["/bin/bash", str(release / "scripts/deploy/release_smoke.sh"), python, str(release)],
         cwd=isolated, environment=environment, timeout=60)
    assert not Path(environment["INTELLIGENCE_DB_PATH"]).exists()
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest["artifact"]["sha256"]
    evidence = {
        "release_id": manifest["release_id"], "artifact": manifest["artifact"],
        "git_commit": manifest["git_commit"], "git_dirty": manifest["git_dirty"],
        "dependencies": manifest["dependency_files"], "runtime": imported.stdout.strip(),
        "pip_check": checked.stdout.strip(), "checkout_imports": False,
        "clean_candidate": not manifest["git_dirty"],
    }
    (tmp_path / "installation-evidence.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8",
    )
    print("INSTALL_EVIDENCE " + json.dumps(evidence, sort_keys=True))
