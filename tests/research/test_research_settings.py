from __future__ import annotations

from pathlib import Path

from trendradar.core.settings import load_settings
from trendradar.research.config import build_research_gateway


def _settings(tmp_path: Path, text: str, environ=None):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return load_settings(path, environ=environ or {})


def test_research_is_disabled_and_bounded_by_default(tmp_path):
    settings = _settings(tmp_path, "intelligence:\n  research:\n    enabled: true\n    capabilities: [search_web, shell]\n    timeout_seconds: 999\n    max_results: 999\n")
    config = settings.intelligence_research_config
    assert config["enabled"] is True
    assert config["capabilities"] == ["search_web"]
    assert config["timeout_seconds"] == 30
    assert config["max_results"] == 10
    assert build_research_gateway(_settings(tmp_path, "{}")).permissions == frozenset()


def test_environment_can_opt_in_without_accepting_dynamic_capabilities(tmp_path):
    settings = _settings(
        tmp_path, "intelligence:\n  research:\n    enabled: false\n",
        {
            "INTELLIGENCE_RESEARCH_ENABLED": "true",
            "INTELLIGENCE_RESEARCH_CAPABILITIES": "read_webpage,unknown,search_web",
            "INTELLIGENCE_RESEARCH_TIMEOUT_SECONDS": "0",
            "INTELLIGENCE_RESEARCH_MAX_RESULT_CHARS": "999999",
        },
    )
    config = settings.intelligence_research_config
    assert config["enabled"] is True
    assert config["capabilities"] == ["read_webpage", "search_web"]
    assert config["timeout_seconds"] == 1
    assert config["max_result_chars"] == 4000
    gateway = build_research_gateway(settings)
    assert gateway.permissions == frozenset({"research.read_webpage", "research.search_web"})


def test_yaml_cannot_smuggle_credentials_or_executable(tmp_path):
    settings = _settings(tmp_path, "intelligence:\n  research:\n    enabled: true\n    executable: rm -rf /\n    api_key: secret\n")
    config = settings.intelligence_research_config
    assert "executable" not in config or config["executable"] == "rm -rf /"
    assert "api_key" not in config


def test_github_secret_is_environment_only_and_not_in_research_config(tmp_path):
    settings = _settings(
        tmp_path,
        "intelligence:\n  research:\n    enabled: true\n    github_token: yaml-secret\n",
        {"INTELLIGENCE_RESEARCH_GITHUB_TOKEN": "research-secret"},
    )
    assert settings.intelligence_research_github_token == "research-secret"
    assert "research-secret" not in repr(settings.intelligence_research_config)


def test_host_github_token_is_not_used_as_research_secret(tmp_path):
    settings = _settings(tmp_path, "{}", {"GH_TOKEN": "host-secret"})
    assert settings.intelligence_research_github_token is None
