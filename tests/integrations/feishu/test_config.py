"""Fail-closed identity configuration and shared-loader compatibility."""

import pytest

from trendradar.core.loader import load_config
from trendradar.core.settings import load_settings
from trendradar.integrations.feishu.config import LARK_API_DOMAIN, FeishuConfig


def test_environment_over_yaml_secrets_are_not_exported(tmp_path, monkeypatch):
    path = tmp_path / "settings.yaml"
    path.write_text(
        "feishu:\n  enabled: false\n  app_secret: ignored\n  app_id: ignored\n"
        "  identity_fields: {user_id: [yaml-user]}\n",
        encoding="utf-8",
    )
    env = {
        "FEISHU_ENABLED": "true",
        "FEISHU_APP_SECRET": "environment-secret",
        "FEISHU_APP_ID": "environment-id",
        "FEISHU_ALLOWED_USERS": "env-user",
        "FEISHU_COOLDOWN_SECONDS": "999999",
    }
    settings = load_settings(path, environ=env)
    config = FeishuConfig.from_settings(settings)
    assert config.enabled
    assert config.identity_fields == (("open_id", ("env-user",)),)
    assert config.cooldown_seconds == 86400
    assert config.app_secret == "environment-secret"
    assert "ignored" not in str(settings.as_dict())
    assert "environment-secret" not in repr(config) + repr(settings) + str(settings.feishu_config)
    assert "env-user" not in repr(config)
    monkeypatch.setenv("FEISHU_ENABLED", "false")
    assert load_config(str(path))["FEISHU"]["enabled"] is False


def test_defaults_and_legacy_allowlist(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("feishu:\n  allowed_users: [legacy]\n", encoding="utf-8")
    settings = load_settings(path, environ={})
    config = FeishuConfig.from_settings(settings)
    assert not config.enabled and not config.delivery_enabled
    assert config.identity_fields == (("open_id", ("legacy",)),)
    assert config.timezone == "Asia/Shanghai"
    assert config.api_domain == LARK_API_DOMAIN
    assert FeishuConfig().identity_fields == ()


def test_lark_environment_and_yaml_take_precedence_over_legacy_names(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "lark:\n  enabled: true\n  identity_fields: {open_id: [lark-yaml]}\n"
        "feishu:\n  enabled: false\n  identity_fields: {open_id: [legacy-yaml]}\n",
        encoding="utf-8",
    )
    settings = load_settings(
        path,
        environ={
            "LARK_APP_ID": "lark-app",
            "LARK_APP_SECRET": "lark-secret",
            "LARK_IDENTITY_FIELDS": '{"user_id":["lark-user"]}',
            "FEISHU_APP_ID": "legacy-app",
            "FEISHU_APP_SECRET": "legacy-secret",
            "FEISHU_IDENTITY_FIELDS": '{"open_id":["legacy-user"]}',
        },
    )
    config = FeishuConfig.from_settings(settings)
    assert config.enabled
    assert config.app_id == "lark-app"
    assert config.app_secret == "lark-secret"
    assert config.identity_fields == (("user_id", ("lark-user",)),)
    assert "lark-secret" not in repr(settings) + repr(config) + str(settings.as_dict())


@pytest.mark.parametrize("raw", ["{", "[]", '{"display_name":["someone"]}', '{"open_id":[null]}'])
def test_invalid_identity_override_denies_instead_of_using_yaml(tmp_path, raw):
    path = tmp_path / "config.yaml"
    path.write_text("feishu:\n  identity_fields: {open_id: [valid]}\n", encoding="utf-8")
    settings = load_settings(path, environ={"FEISHU_IDENTITY_FIELDS": raw})
    assert not FeishuConfig.from_settings(settings).identity_fields


def test_empty_environment_preserves_yaml_and_delivery_window(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "feishu:\n  identity_fields: {union_id: [union]}\n"
        'notification:\n  push_window: {start: "8:30", end: "10:00"}\n',
        encoding="utf-8",
    )
    config = FeishuConfig.from_settings(
        load_settings(path, environ={"FEISHU_IDENTITY_FIELDS": " "})
    )
    assert config.identity_fields == (("union_id", ("union",)),)
    assert (config.delivery_time, config.delivery_end) == ("08:30", "10:00")


def test_invalid_mapping_bounds_and_booleans():
    config = FeishuConfig.from_mapping(
        {
            "enabled": "false",
            "allowed_chat_types": 1,
            "reconnect_attempts": "bad",
            "delivery_time": "99:99",
        }
    )
    assert not config.enabled
    assert config.allowed_chat_types == ()
    assert config.reconnect_attempts == 5
    assert config.delivery_time == "00:00"
