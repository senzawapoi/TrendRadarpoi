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
    assert config.delivery_mode == "daily"
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


def test_empty_environment_preserves_identity_but_ignores_retired_push_window(tmp_path):
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
    assert (config.delivery_time, config.delivery_end) == ("00:00", "23:59")
    assert config.delivery_mode == "daily"


def test_explicit_daily_settings_and_mode_precedence(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        'lark:\n  delivery: {mode: daily, time: "8:30", end: "10:00", enabled: true}\n',
        encoding="utf-8",
    )
    daily = FeishuConfig.from_settings(load_settings(path, environ={}))
    assert daily.delivery_mode == "daily" and daily.delivery_enabled
    assert (daily.delivery_time, daily.delivery_end) == ("08:30", "10:00")
    instant = FeishuConfig.from_settings(load_settings(path, environ={
        "LARK_DELIVERY_MODE": "instant", "FEISHU_DELIVERY_MODE": "daily",
        "PUSH_WINDOW_START": "02:00", "PUSH_WINDOW_END": "03:00",
    }))
    assert instant.delivery_mode == "instant"
    assert (instant.delivery_time, instant.delivery_end) == ("08:30", "10:00")
    invalid = FeishuConfig.from_mapping({"delivery_enabled": True, "delivery_mode": "typo"})
    assert not invalid.delivery_enabled


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


@pytest.mark.parametrize("mode,expected,enabled", [
    (None, "daily", True),
    (" DAILY ", "daily", True),
    (" TyPo ", "typo", False),
])
@pytest.mark.parametrize("source", ["LARK_DELIVERY_MODE", "FEISHU_DELIVERY_MODE", "yaml"])
def test_delivery_mode_boundary_preserves_daily_default_and_invalid_disable(
    tmp_path, mode, expected, enabled, source,
):
    path = tmp_path / "config.yaml"
    path.write_text(
        "lark:\n  delivery:\n    enabled: true\n"
        + (f'    mode: "{mode}"\n' if source == "yaml" and mode is not None else ""),
        encoding="utf-8",
    )
    env = {source: mode} if source != "yaml" and mode is not None else {}
    settings = load_settings(path, environ=env)
    transport = FeishuConfig.from_settings(settings)
    assert settings.lark_config["delivery_mode"] == transport.delivery_mode == expected
    assert transport.delivery_enabled is enabled
