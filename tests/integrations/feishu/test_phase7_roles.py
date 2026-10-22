"""Phase 7 role boundaries; all tests stay offline and use temporary ledgers."""

import threading

from trendradar.core.locking import LockUnavailable, runtime_locks
from trendradar.core.settings import load_settings
from trendradar.integrations.feishu import __main__ as runner
from trendradar.integrations.feishu.client import FeishuClient
from trendradar.integrations.feishu.config import FeishuConfig
from trendradar.integrations.feishu.handler import FeishuHandler
from trendradar.integrations.feishu.ledger import EventLedger
from trendradar.integrations.feishu.models import stable_digest

from .test_handler import Operations, payload


def settings_for(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    return load_settings(
        config,
        environ={
            "INTELLIGENCE_DB_PATH": str(tmp_path / "intelligence.db"),
            "GEMINI_ENABLED": "false",
        },
    )


def test_role_checks_are_offline_and_do_not_create_database(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    for key, value in {
        "LARK_ENABLED": "true",
        "INTELLIGENCE_ENABLED": "true",
        "LARK_APP_ID": "app",
        "LARK_APP_SECRET": "secret",
        "LARK_IDENTITY_FIELDS": '{"open_id":["owner"]}',
        "LARK_BOT_ID": "bot",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        runner.FeishuClient,
        "from_credentials",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network")),
    )

    for role in ("bot", "worker", "scheduler-once"):
        assert runner.main(["--config", str(config_path), "--role", role, "--check"]) == 0
    assert list(tmp_path.iterdir()) == [config_path]


def test_bot_role_never_builds_assistant_or_worker(monkeypatch, tmp_path):
    settings = settings_for(tmp_path)
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),))
    seen = {}

    class StopTransport:
        def __init__(self, _config, factory):
            seen["factory"] = factory

        async def run(self):
            connection = seen["factory"]()
            assert connection.callback is not None
            connection.callback(payload(event_id="bot-event"))
            raise RuntimeError("test stop")

    monkeypatch.setattr(runner, "FeishuTransport", StopTransport)
    monkeypatch.setattr(
        runner,
        "build_gemini_client",
        lambda _settings: (_ for _ in ()).throw(AssertionError("bot built Gemini")),
    )
    monkeypatch.setattr(
        runner,
        "build_assistant_service",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("bot built Assistant")),
    )

    import asyncio

    try:
        asyncio.run(runner.run_bot_role(settings, config, FeishuClient()))
    except RuntimeError as exc:
        assert str(exc) == "test stop"
    ledger = EventLedger(settings.intelligence_database_path)
    try:
        row = ledger.storage.connection.execute(
            "SELECT event_id, status FROM feishu_events WHERE event_id='bot-event'"
        ).fetchone()
        assert row["event_id"] == "bot-event" and row["status"] == "processing"
    finally:
        ledger.close()


def test_worker_role_polls_durable_event_without_websocket(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),))
    operations = Operations()
    stop = threading.Event()
    original_reply = operations.reply

    def stop_after_reply(message_id, text):
        result = original_reply(message_id, text)
        stop.set()
        return result

    operations.reply = stop_after_reply
    source = FeishuHandler(config, FeishuClient(operations), None)
    event, binding = source.prepare(payload(event_id="worker-event"))
    ledger = EventLedger(settings.intelligence_database_path)
    scope = stable_digest(binding.principal_id, binding.session_id, event.message_id)
    assert ledger.record(event, binding, scope)
    ledger.close()
    monkeypatch.setattr(
        runner,
        "FeishuTransport",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("worker opened WebSocket")),
    )

    runner.run_worker_role(settings, config, FeishuClient(operations), stop, poll_seconds=0.1)
    assert len(operations.replies) == 1


def test_scheduler_role_does_not_initialize_gemini_or_chat_consumer(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    config = FeishuConfig(enabled=True, delivery_enabled=False)
    monkeypatch.setattr(
        runner,
        "build_gemini_client",
        lambda _settings: (_ for _ in ()).throw(AssertionError("scheduler built Gemini")),
    )
    monkeypatch.setattr(
        runner,
        "FeishuTransport",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("scheduler opened WebSocket")),
    )
    assert runner.run_scheduler_once(settings, config, FeishuClient()) == "disabled"
    assert settings.intelligence_database_path.exists()


def test_role_lock_rejects_same_database_role(tmp_path):
    path = tmp_path / "intelligence.db"
    with runtime_locks(path, "worker"):
        try:
            with runtime_locks(path, "worker"):
                raise AssertionError("nested role lock unexpectedly succeeded")
        except LockUnavailable:
            pass
