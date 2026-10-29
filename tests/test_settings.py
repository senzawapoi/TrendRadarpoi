"""Tests for the shared YAML and environment settings boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from config.settings import load_settings as load_repository_settings
from mcp_server.services.parser_service import ParserService
from mcp_server.tools.storage_sync import StorageSyncTools
from mcp_server.utils import validators
from mcp_server.utils.errors import FileParseError
from trendradar.ai_frontier import __main__ as ai_frontier_main
from trendradar.ai_frontier.sources.base import AIItem
from trendradar.core.loader import load_config
from trendradar.core.settings import RuntimeSettings, load_settings, load_yaml_config


def _write_config(path: Path, text: str = "app:\n  timezone: UTC\n") -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_repository_facade_exports_core_api(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "config.yaml")

    settings = load_repository_settings(config_path, environ={})

    assert isinstance(settings, RuntimeSettings)
    assert settings.timezone == "UTC"


def test_config_path_precedence_is_explicit_then_environment(tmp_path: Path) -> None:
    env_path = _write_config(tmp_path / "env.yaml", "app:\n  timezone: Env/Yaml\n")
    explicit_path = _write_config(
        tmp_path / "explicit.yaml",
        "app:\n  timezone: Explicit/Yaml\n",
    )

    from_environment = load_settings(environ={"CONFIG_PATH": str(env_path)})
    explicit = load_settings(explicit_path, environ={"CONFIG_PATH": str(env_path)})

    assert from_environment.config_path == env_path
    assert from_environment.timezone == "Env/Yaml"
    assert explicit.config_path == explicit_path
    assert explicit.timezone == "Explicit/Yaml"


def test_value_precedence_is_environment_then_yaml_then_default(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "config.yaml")

    environment = load_settings(config_path, environ={"TIMEZONE": "Asia/Shanghai"})
    empty_environment = load_settings(config_path, environ={"TIMEZONE": "  "})
    default = load_settings(_write_config(tmp_path / "empty.yaml", "{}\n"), environ={})

    assert environment.timezone == "Asia/Shanghai"
    assert empty_environment.timezone == "UTC"
    assert default.timezone == "Asia/Shanghai"


def test_typed_resolvers_parse_environment_and_fall_back_to_yaml(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "config.yaml",
        "feature:\n  enabled: true\n  limit: 7\n  ratio: 1.25\n"
        "  users: [yaml-a, yaml-b]\n",
    )
    settings = load_settings(
        config_path,
        environ={
            "FEATURE_ENABLED": "false",
            "FEATURE_LIMIT": "12",
            "FEATURE_RATIO": "2.5",
            "FEATURE_USERS": " env-a, env-b, ,env-a ",
        },
    )
    fallback = load_settings(
        config_path,
        environ={
            "FEATURE_ENABLED": "invalid",
            "FEATURE_LIMIT": "invalid",
            "FEATURE_RATIO": "invalid",
        },
    )

    assert settings.get_bool("FEATURE_ENABLED", "feature.enabled") is False
    assert settings.get_int("FEATURE_LIMIT", "feature.limit") == 12
    assert settings.get_float("FEATURE_RATIO", "feature.ratio") == 2.5
    assert settings.get_csv("FEATURE_USERS", "feature.users") == (
        "env-a",
        "env-b",
        "env-a",
    )
    assert fallback.get_bool("FEATURE_ENABLED", "feature.enabled") is True
    assert fallback.get_int("FEATURE_LIMIT", "feature.limit") == 7
    assert fallback.get_float("FEATURE_RATIO", "feature.ratio") == 1.25
    assert fallback.get_csv("MISSING_USERS", "feature.users") == ("yaml-a", "yaml-b")


def test_raw_config_is_deeply_read_only_and_copy_is_mutable(tmp_path: Path) -> None:
    settings = load_settings(
        _write_config(tmp_path / "config.yaml", "nested:\n  values: [one, two]\n"),
        environ={},
    )

    with pytest.raises(TypeError):
        settings.raw_config["new"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        settings.raw_config["nested"]["new"] = "value"  # type: ignore[index]

    mutable = settings.as_dict()
    mutable["nested"]["values"].append("three")
    assert settings.raw_config["nested"]["values"] == ("one", "two")


def test_secret_fields_are_environment_only_and_redacted(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "config.yaml",
        "gemini_api_key: yaml-value\nfeishu:\n  app_id: yaml-id\n  app_secret: yaml-secret\n",
    )
    yaml_only = load_settings(config_path, environ={})
    from_environment = load_settings(
        config_path,
        environ={
            "GEMINI_API_KEY": "environment-key",
            "FEISHU_APP_ID": "environment-id",
            "FEISHU_APP_SECRET": "environment-secret",
        },
    )

    assert yaml_only.gemini_api_key == ""
    assert yaml_only.feishu_app_id == ""
    assert yaml_only.feishu_app_secret == ""
    assert from_environment.gemini_api_key == "environment-key"
    assert from_environment.feishu_app_id == "environment-id"
    assert from_environment.feishu_app_secret == "environment-secret"
    rendered = repr(from_environment)
    assert "<redacted>" in rendered
    assert "environment-key" not in rendered
    assert "environment-id" not in rendered
    assert "environment-secret" not in rendered


def test_gemini_settings_are_bounded_environment_first_and_secret_free(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "gemini.yaml",
        """
gemini_api_key: root-yaml-secret
ai:
  gemini:
    enabled: true
    model: yaml-model
    timeout_seconds: 12.5
    max_attempts: 2
    retry_backoff_seconds: 0.25
    min_request_interval_seconds: 2
    max_input_chars: 4000
    max_output_chars: 2000
    api_key: nested-yaml-secret
    key: short-yaml-secret
    access_key: access-yaml-secret
    credentials:
      token: nested-token
""".lstrip(),
    )
    settings = load_settings(
        config_path,
        environ={
            "GEMINI_API_KEY": "environment-only-key",
            "GEMINI_ENABLED": "false",
            "GEMINI_MODEL": "env-model",
            "GEMINI_TIMEOUT_SECONDS": "999",
            "GEMINI_MAX_ATTEMPTS": "0",
            "GEMINI_RETRY_BACKOFF_SECONDS": "-2",
            "GEMINI_MIN_REQUEST_INTERVAL_SECONDS": "99",
            "GEMINI_MAX_INPUT_CHARS": "999999",
            "GEMINI_MAX_OUTPUT_CHARS": "1",
        },
    )

    assert settings.gemini_api_key == "environment-only-key"
    assert settings.gemini_config == {
        "enabled": False,
        "model": "env-model",
        "models": ("env-model",),
        "model_cooldown_seconds": 60.0,
        "timeout_seconds": 120.0,
        "max_attempts": 1,
        "retry_backoff_seconds": 0.0,
        "min_request_interval_seconds": 60.0,
        "max_input_chars": 200_000,
        "max_output_chars": 256,
    }
    assert "gemini_api_key" not in settings.raw_config
    assert "api_key" not in settings.raw_config["ai"]["gemini"]
    assert "key" not in settings.raw_config["ai"]["gemini"]
    assert "access_key" not in settings.raw_config["ai"]["gemini"]
    assert "credentials" not in settings.raw_config["ai"]["gemini"]
    serialized = str(settings.as_dict()) + repr(settings)
    assert "root-yaml-secret" not in serialized
    assert "nested-yaml-secret" not in serialized
    assert "short-yaml-secret" not in serialized
    assert "access-yaml-secret" not in serialized
    assert "nested-token" not in serialized
    assert "environment-only-key" not in serialized

    yaml_only = load_settings(config_path, environ={})
    assert yaml_only.gemini_api_key == ""
    assert yaml_only.gemini_config == {
        "enabled": True,
        "model": "yaml-model",
        "models": ("yaml-model",),
        "model_cooldown_seconds": 60.0,
        "timeout_seconds": 12.5,
        "max_attempts": 2,
        "retry_backoff_seconds": 0.25,
        "min_request_interval_seconds": 2.0,
        "max_input_chars": 4000,
        "max_output_chars": 2000,
    }


def test_database_and_allowed_user_fields_share_the_same_precedence(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "config.yaml",
        "storage:\n  local:\n    data_dir: yaml-output\n"
        "ai_frontier:\n  database_path: yaml-ai.db\n"
        "intelligence:\n  enabled: true\n  database_path: yaml-intelligence.db\n"
        "feishu:\n  allowed_users: [yaml-user]\n",
    )
    yaml_settings = load_settings(config_path, environ={})
    env_settings = load_settings(
        config_path,
        environ={
            "DATABASE_PATH": "env-output",
            "AI_FRONTIER_DB_PATH": "env-ai.db",
            "INTELLIGENCE_ENABLED": "false",
            "INTELLIGENCE_DB_PATH": "env-intelligence.db",
            "FEISHU_ALLOWED_USERS": "user-a,user-b",
        },
    )

    assert yaml_settings.database_path == Path("yaml-output")
    assert yaml_settings.ai_frontier_database_path == Path("yaml-ai.db")
    assert yaml_settings.intelligence_enabled is True
    assert yaml_settings.intelligence_database_path == Path("yaml-intelligence.db")
    assert yaml_settings.intelligence_story_config["enabled"] is True
    assert yaml_settings.intelligence_story_config["output_dir"] == "output/stories"
    assert yaml_settings.intelligence_story_wording_enabled is False
    assert yaml_settings.feishu_allowed_users == ("yaml-user",)
    assert env_settings.database_path == Path("env-output")
    assert env_settings.ai_frontier_database_path == Path("env-ai.db")
    assert env_settings.intelligence_enabled is False
    assert env_settings.intelligence_database_path == Path("env-intelligence.db")
    assert env_settings.intelligence_story_config["enabled"] is True
    assert env_settings.feishu_allowed_users == ("user-a", "user-b")


def test_security_settings_are_bounded_and_nvd_key_is_environment_only(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "security.yaml",
        """
intelligence:
  security:
    enabled: true
    max_concurrency: 999
    stale_after_hours: 0
    nvd_api_key: yaml-must-not-load
    sources:
      nvd:
        api_key: nested-yaml-must-not-load
""".lstrip(),
    )
    settings = load_settings(
        config_path,
        environ={
            "INTELLIGENCE_SECURITY_ENABLED": "false",
            "INTELLIGENCE_SECURITY_MAX_CONCURRENCY": "99",
            "INTELLIGENCE_SECURITY_STALE_AFTER_HOURS": "-4",
            "NVD_API_KEY": "environment-only-key",
        },
    )

    assert settings.intelligence_security_config["enabled"] is False
    assert settings.intelligence_security_config["max_concurrency"] == 16
    assert settings.intelligence_security_config["stale_after_hours"] == 1
    assert "nvd_api_key" not in settings.intelligence_security_config
    assert "api_key" not in settings.intelligence_security_config["sources"]["nvd"]
    assert settings.nvd_api_key == "environment-only-key"
    assert "environment-only-key" not in repr(settings)

    yaml_only = load_settings(config_path, environ={})
    assert yaml_only.nvd_api_key == ""


def test_assistant_settings_are_bounded_environment_first(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "assistant.yaml",
        """
intelligence:
  assistant:
    enabled: true
    session_ttl_days: 15
    max_messages: 80
    max_context_chars: 16000
    default_lookback_days: 5
    max_tool_calls: 2
    tools:
      search_stories: false
""".lstrip(),
    )
    settings = load_settings(
        config_path,
        environ={
            "INTELLIGENCE_ASSISTANT_ENABLED": "false",
            "INTELLIGENCE_ASSISTANT_SESSION_TTL_DAYS": "99999",
            "INTELLIGENCE_ASSISTANT_MAX_MESSAGES": "1",
            "INTELLIGENCE_ASSISTANT_MAX_CONTEXT_CHARS": "1",
            "INTELLIGENCE_ASSISTANT_LOOKBACK_DAYS": "0",
            "INTELLIGENCE_ASSISTANT_MAX_TOOL_CALLS": "99",
            "INTELLIGENCE_ASSISTANT_TOOL_SEARCH_STORIES_ENABLED": "true",
        },
    )

    assistant = settings.intelligence_assistant_config
    assert assistant["enabled"] is False
    assert assistant["session_ttl_days"] == 3650
    assert assistant["max_messages"] == 2
    assert assistant["max_context_chars"] == 512
    assert assistant["default_lookback_days"] == 1
    assert assistant["max_tool_calls"] == 3
    assert assistant["tools"] == {
        "search_stories": True,
        "search_content_items": True,
        "get_story_evidence": True,
    }

    yaml_only = load_settings(config_path, environ={}).intelligence_assistant_config
    assert yaml_only["session_ttl_days"] == 15
    assert yaml_only["max_messages"] == 80
    assert yaml_only["max_context_chars"] == 16_000
    assert yaml_only["default_lookback_days"] == 5
    assert yaml_only["max_tool_calls"] == 2
    assert yaml_only["tools"]["search_stories"] is False


def test_yaml_loader_rejects_missing_or_non_mapping_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_yaml_config(tmp_path / "missing.yaml")

    invalid_root = _write_config(tmp_path / "list.yaml", "- one\n- two\n")
    with pytest.raises(ValueError, match="mapping"):
        load_yaml_config(invalid_root)


def test_settings_can_explicitly_fall_back_to_empty_config(tmp_path: Path) -> None:
    settings = load_settings(
        tmp_path / "missing.yaml",
        environ={"TIMEZONE": "UTC"},
        fallback_to_empty=True,
    )

    assert settings.raw_config == {}
    assert settings.timezone == "UTC"


def test_legacy_loader_keeps_dictionary_contract_with_environment_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_config(
        tmp_path / "legacy.yaml",
        """
app:
  timezone: UTC
advanced:
  crawler:
    enabled: false
    request_interval: 123
  batch_size:
    default: 4000
report:
  mode: daily
  display_mode: keyword
notification:
  enabled: false
  channels:
    bark:
      url: yaml-bark
storage:
  backend: local
  formats:
    sqlite: true
    txt: false
    html: true
  local:
    data_dir: yaml-output
platforms:
  - id: sample
    name: Sample
rss:
  enabled: true
  feeds: []
""".lstrip(),
    )
    monkeypatch.setenv("TIMEZONE", "Asia/Shanghai")
    monkeypatch.setenv("ENABLE_CRAWLER", "true")
    monkeypatch.setenv("DATABASE_PATH", "env-output")
    monkeypatch.setenv("BARK_URL", "env-bark")

    config = load_config(str(config_path))

    assert config["TIMEZONE"] == "Asia/Shanghai"
    assert config["ENABLE_CRAWLER"] is True
    assert config["REQUEST_INTERVAL"] == 123
    assert config["REPORT_MODE"] == "daily"
    assert config["PLATFORMS"] == [{"id": "sample", "name": "Sample"}]
    assert config["RSS"]["ENABLED"] is True
    assert config["STORAGE"]["LOCAL"]["DATA_DIR"] == "env-output"
    assert config["INTELLIGENCE"]["ENABLED"] is True
    assert Path(config["INTELLIGENCE"]["DATABASE_PATH"]) == Path("output/intelligence.db")
    assert config["INTELLIGENCE"]["SECURITY"]["enabled"] is True
    assert config["INTELLIGENCE"]["ASSISTANT"]["enabled"] is True
    assert config["INTELLIGENCE"]["ASSISTANT"]["max_tool_calls"] == 3
    assert config["AI"]["GEMINI"]["enabled"] is True
    assert config["AI"]["GEMINI"]["model"] == "gemini-3.8-flash"
    assert "api_key" not in config["AI"]["GEMINI"]
    assert "BARK_URL" not in config
    assert "NOTIFICATION_ENABLED" not in config


def test_ai_frontier_run_uses_configured_database_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_config(
        tmp_path / "ai.yaml",
        "ai_frontier:\n  enabled: true\n  translate: false\n"
        "intelligence:\n  enabled: false\n",
    )
    expected_path = tmp_path / "custom-ai.db"
    captured = {}
    item = AIItem(
        source="arxiv",
        source_name="ArXiv",
        title="Settings path",
        url="https://example.invalid/settings-path",
    )

    class FakeStorage:
        def __init__(self, path: Path) -> None:
            captured["path"] = path

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

        def upsert_items(self, items):
            return list(items), []

    async def fake_fetch(_config):
        return [item]

    monkeypatch.setenv("AI_FRONTIER_DB_PATH", str(expected_path))
    monkeypatch.delenv("BARK_URL", raising=False)
    monkeypatch.setattr(ai_frontier_main, "AIFrontierStorage", FakeStorage)
    monkeypatch.setattr(ai_frontier_main, "fetch_and_process", fake_fetch)
    monkeypatch.setattr(ai_frontier_main, "save_html_report", lambda *_args, **_kwargs: None)

    result = asyncio.run(ai_frontier_main._run(str(config_path)))

    assert result == 0
    assert captured["path"] == expected_path


def test_mcp_parser_preserves_yaml_and_error_contracts(tmp_path: Path) -> None:
    parser = ParserService(project_root=str(tmp_path))
    config_path = _write_config(tmp_path / "valid.yaml", "platforms: [{id: sample}]\n")
    invalid_path = _write_config(tmp_path / "invalid.yaml", "- not-a-mapping\n")

    assert parser.parse_yaml_config(str(config_path)) == {"platforms": [{"id": "sample"}]}
    with pytest.raises(FileParseError) as missing_error:
        parser.parse_yaml_config(str(tmp_path / "missing.yaml"))
    with pytest.raises(FileParseError) as invalid_error:
        parser.parse_yaml_config(str(invalid_path))

    assert missing_error.value.code == "FILE_PARSE_ERROR"
    assert "配置文件不存在" in missing_error.value.message
    assert invalid_error.value.__cause__ is not None


def test_storage_sync_uses_environment_over_yaml_and_missing_file_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_config(
        config_dir / "config.yaml",
        """
storage:
  remote:
    endpoint_url: yaml-endpoint
    bucket_name: yaml-bucket
    access_key_id: yaml-access
    secret_access_key: yaml-secret
    region: yaml-region
""".lstrip(),
    )
    monkeypatch.setenv("S3_ENDPOINT_URL", "env-endpoint")
    monkeypatch.setenv("S3_BUCKET_NAME", "env-bucket")

    tools = StorageSyncTools(project_root=str(tmp_path))

    assert tools._load_config()["storage"]["remote"]["bucket_name"] == "yaml-bucket"
    assert tools._get_remote_config() == {
        "endpoint_url": "env-endpoint",
        "bucket_name": "env-bucket",
        "access_key_id": "yaml-access",
        "secret_access_key": "yaml-secret",
        "region": "yaml-region",
    }
    assert StorageSyncTools(project_root=str(tmp_path / "missing"))._load_config() == {}


def test_platform_validator_keeps_empty_list_failure_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        validators,
        "load_yaml_config",
        lambda _path: {"platforms": [{"id": "one"}, {"id": "two"}]},
    )
    assert validators.get_supported_platforms() == ["one", "two"]

    def fail_load(_path):
        raise OSError("unavailable")

    monkeypatch.setattr(validators, "load_yaml_config", fail_load)
    assert validators.get_supported_platforms() == []


def test_env_example_contains_only_empty_secret_placeholders() -> None:
    values = {}
    for line in Path(".env.example").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", maxsplit=1)
            values[key] = value

    for secret_name in (
        "GEMINI_API_KEY",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "LARK_APP_ID",
        "LARK_APP_SECRET",
        "S3_SECRET_ACCESS_KEY",
    ):
        assert secret_name in values
        assert values[secret_name] == ""

    for setting_name in (
        "GEMINI_ENABLED",
        "GEMINI_MODEL",
        "GEMINI_TIMEOUT_SECONDS",
        "GEMINI_MAX_ATTEMPTS",
        "GEMINI_RETRY_BACKOFF_SECONDS",
        "GEMINI_MIN_REQUEST_INTERVAL_SECONDS",
        "GEMINI_MAX_INPUT_CHARS",
        "GEMINI_MAX_OUTPUT_CHARS",
        "INTELLIGENCE_ASSISTANT_ENABLED",
        "INTELLIGENCE_ASSISTANT_MAX_CONTEXT_CHARS",
        "INTELLIGENCE_ASSISTANT_MAX_TOOL_CALLS",
        "INTELLIGENCE_ASSISTANT_TOOL_SEARCH_STORIES_ENABLED",
    ):
        assert setting_name in values
        assert values[setting_name] == ""
