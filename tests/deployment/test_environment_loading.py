"""Configuration parsing evaluates data only, never shell expressions."""

import os
from pathlib import Path

import pytest

from scripts.deploy.load_environment import parse_environment


@pytest.mark.skipif(os.name == "nt", reason="production EnvironmentFile uses POSIX absolute paths")
def test_quoted_configuration_and_caller_environment_are_separate(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("intelligence: {}", encoding="utf-8")
    common = tmp_path / "common.env"
    common.write_text("\n".join([
        f'CONFIG_PATH="{config}"',
        *(f'{key}="{tmp_path / key.lower()}"' for key in (
            "INTELLIGENCE_DB_PATH", "AI_FRONTIER_DB_PATH", "TRENDRADAR_HEALTH_DIR",
            "TRENDRADAR_LOCK_DIR", "TRENDRADAR_CONTROL_DIR", "TRENDRADAR_BACKUP_DIR",
        )),
        "INTELLIGENCE_SQLITE_SYNCHRONOUS=FULL",
        "TRENDRADAR_INITIAL_UNITS=unit-a.service unit-b.timer",
    ]), encoding="utf-8")
    parsed = parse_environment(common)
    assert parsed["CONFIG_PATH"] == str(config)
    assert parsed["TRENDRADAR_INITIAL_UNITS"] == "unit-a.service unit-b.timer"
    common.write_text(common.read_text() + "\nPATH=/malicious", encoding="utf-8")
    with pytest.raises(ValueError, match="not allowed"):
        parse_environment(common)


@pytest.mark.parametrize("assignment", [
    "not-an-assignment", "export BAD=value", "PATH=/tmp", 'CONFIG_PATH="unterminated',
])
def test_invalid_configuration_is_rejected(tmp_path, assignment):
    common = tmp_path / "common.env"
    common.write_text(assignment, encoding="utf-8")
    with pytest.raises(ValueError):
        parse_environment(common)


def test_shell_substitution_is_never_executed(tmp_path):
    common = tmp_path / "common.env"
    sentinel = tmp_path / "should-not-exist"
    common.write_text(f"CONFIG_PATH=$(touch {sentinel})", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_environment(common)
    assert not sentinel.exists()


def test_fixed_entry_uses_trusted_loader():
    entry = Path(__file__).resolve().parents[2] / "deploy/bin/trendradar-install-release"
    assert "/usr/bin/python3 -I" in entry.read_text()
