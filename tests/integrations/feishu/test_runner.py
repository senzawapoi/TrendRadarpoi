"""Opt-in runner, bounded queue and rollback-safe offline entrypoints."""

import asyncio
import importlib
import queue
import threading
from unittest.mock import Mock

import pytest

from trendradar.core.settings import load_settings
from trendradar.integrations.feishu.__main__ import main, run_bot, run_worker
from trendradar.integrations.feishu.client import FeishuClient
from trendradar.integrations.feishu.config import FeishuConfig
from trendradar.integrations.feishu.handler import FeishuHandler
from trendradar.integrations.feishu.ledger import EventLedger
from trendradar.integrations.feishu.models import stable_digest

from .test_handler import Operations, payload


def test_disabled_runner_never_constructs_clients_or_storage(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("FEISHU_ENABLED", "false")
    monkeypatch.setattr(
        FeishuClient, "from_credentials", Mock(side_effect=AssertionError("provider"))
    )
    assert main(["--config", str(path)]) == 0
    assert list(tmp_path.iterdir()) == [path]
    monkeypatch.setenv("FEISHU_ENABLED", "true")
    monkeypatch.setenv("INTELLIGENCE_ENABLED", "false")
    assert main(["--config", str(path)]) == 0


def test_check_config_does_not_create_runtime_artifacts(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("{}", encoding="utf-8")
    for key, value in {
        "FEISHU_ENABLED": "true",
        "INTELLIGENCE_ENABLED": "true",
        "FEISHU_APP_ID": "test-app",
        "FEISHU_APP_SECRET": "test-secret",
        "FEISHU_ALLOWED_USERS": "owner",
        "FEISHU_BOT_ID": "bot",
    }.items():
        monkeypatch.setenv(key, value)
    assert main(["--config", str(path), "--check"]) == 0
    assert list(tmp_path.iterdir()) == [path]


def test_real_worker_processes_normalized_input_offline(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("{}", encoding="utf-8")
    settings = load_settings(
        path, environ={"INTELLIGENCE_DB_PATH": str(tmp_path / "test.db"), "GEMINI_ENABLED": "false"}
    )
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),))
    ops, stop, inbox = Operations(), threading.Event(), queue.Queue(maxsize=32)
    client = FeishuClient(ops)
    prepared = FeishuHandler(config, client, None).prepare(payload())
    inbox.put(prepared)
    original_reply = ops.reply

    def reply(message_id, text):
        stop.set()
        return original_reply(message_id, text)

    ops.reply = reply
    run_worker(settings, config, client, inbox, stop)
    assert stop.is_set() and len(ops.replies) == 1
    assert "deterministic" in ops.replies[0][1]


def test_intake_persists_queued_event_when_worker_stops_after_first(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("{}", encoding="utf-8")
    db_path = tmp_path / "test.db"
    settings = load_settings(
        path, environ={"INTELLIGENCE_DB_PATH": str(db_path), "GEMINI_ENABLED": "false"}
    )
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),))
    ops, stop, inbox = Operations(), threading.Event(), queue.Queue(maxsize=32)
    client = FeishuClient(ops)
    normalizer = FeishuHandler(config, client, None)
    prepared = [
        normalizer.prepare(payload(event_id=event_id)) for event_id in ("first", "second")
    ]
    assert all(prepared)
    intake = EventLedger(db_path)
    for event, binding in prepared:
        scope = stable_digest(binding.principal_id, binding.session_id, event.message_id)
        assert intake.record(event, binding, scope)
        inbox.put((event, binding))

    original_reply = ops.reply

    def stop_after_first(message_id, text):
        stop.set()
        return original_reply(message_id, text)

    ops.reply = stop_after_first
    run_worker(settings, config, client, inbox, stop)
    row = intake.storage.connection.execute(
        "SELECT status, event_json FROM feishu_events WHERE event_id='second'"
    ).fetchone()
    assert row["event_json"] and row["status"] == "processing"
    intake.close()


def test_legacy_and_feishu_entrypoints_are_offline_importable(monkeypatch):
    monkeypatch.setenv("INTELLIGENCE_ENABLED", "false")
    for name in (
        "trendradar.__main__",
        "trendradar.ai_frontier.__main__",
        "mcp_server.server",
        "trendradar.integrations.feishu.__main__",
        "trendradar.integrations.lark.__main__",
    ):
        assert importlib.import_module(name)


def test_worker_fatal_failure_is_reported(tmp_path, monkeypatch):
    runner = importlib.import_module("trendradar.integrations.feishu.__main__")
    settings = Mock(intelligence_database_path=tmp_path / "test.db")
    monkeypatch.setattr(runner, "build_gemini_client", Mock(side_effect=RuntimeError("failed")))
    failure, stop = [], threading.Event()
    run_worker(settings, FeishuConfig(), FeishuClient(), queue.Queue(), stop, failure)
    assert stop.is_set() and len(failure) == 1


def test_bot_reports_worker_failure_after_closing_intake(tmp_path, monkeypatch):
    runner = importlib.import_module("trendradar.integrations.feishu.__main__")
    settings = Mock(intelligence_database_path=tmp_path / "test.db")
    closed = []
    original_close = EventLedger.close

    def close(ledger):
        closed.append(ledger)
        original_close(ledger)

    def fail_worker(_settings, _config, _client, _inbox, stop, failure):
        failure.append(RuntimeError("worker failed"))
        stop.set()

    monkeypatch.setattr(runner, "run_worker", fail_worker)
    monkeypatch.setattr(EventLedger, "close", close)
    with pytest.raises(RuntimeError, match="local worker failed"):
        asyncio.run(run_bot(settings, FeishuConfig(), FeishuClient()))
    assert len(closed) == 1
