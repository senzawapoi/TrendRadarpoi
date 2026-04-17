"""__main__.py 配置加载测试"""

from __future__ import annotations

from pathlib import Path

from trendradar.ai_frontier.__main__ import (
    _default_config,
    _deep_merge,
    _resolve_bark_url,
    load_ai_frontier_config,
)


def test_default_config_has_all_sources():
    cfg = _default_config()
    assert cfg["enabled"] is True
    assert "arxiv" in cfg["sources"]
    assert "x_nitter" in cfg["sources"]
    assert cfg["push"]["max_items_per_push"] == 30


def test_deep_merge_overrides_nested():
    base = {"a": 1, "b": {"x": 10, "y": 20}}
    override = {"b": {"y": 99, "z": 100}}
    _deep_merge(base, override)
    assert base == {"a": 1, "b": {"x": 10, "y": 99, "z": 100}}


def test_load_config_returns_default_on_missing(tmp_path: Path):
    cfg = load_ai_frontier_config(tmp_path / "nonexistent.yaml")
    assert cfg["enabled"] is True


def test_load_config_merges_user_overrides(tmp_path: Path):
    yaml_text = """
ai_frontier:
  freshness_hours: 48
  push:
    min_score_hackernews: 200
  sources:
    x_nitter:
      enabled: false
"""
    cfg_path = tmp_path / "test.yaml"
    cfg_path.write_text(yaml_text, encoding="utf-8")

    cfg = load_ai_frontier_config(cfg_path)
    assert cfg["freshness_hours"] == 48
    assert cfg["push"]["min_score_hackernews"] == 200
    assert cfg["push"]["max_items_per_push"] == 30  # 默认保留
    assert cfg["sources"]["x_nitter"]["enabled"] is False
    assert cfg["sources"]["arxiv"]["enabled"] is True  # 默认保留


def test_resolve_bark_url_prefers_env(monkeypatch):
    monkeypatch.setenv("BARK_URL", "https://api.day.app/env_key/")
    cfg = {"push": {"bark_url": "https://api.day.app/cfg_key/"}}
    assert _resolve_bark_url(cfg) == "https://api.day.app/env_key/"


def test_resolve_bark_url_uses_config_when_no_env(monkeypatch):
    monkeypatch.delenv("BARK_URL", raising=False)
    cfg = {"push": {"bark_url": "https://api.day.app/cfg_key/"}}
    assert _resolve_bark_url(cfg) == "https://api.day.app/cfg_key/"


def test_resolve_bark_url_empty_when_none(monkeypatch):
    monkeypatch.delenv("BARK_URL", raising=False)
    cfg = {"push": {"bark_url": ""}}
    assert _resolve_bark_url(cfg) == ""
