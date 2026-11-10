"""Empty scheduler ticks avoid the SDK; real sends retain durable retry semantics."""

import json
from unittest.mock import Mock

import pytest

from trendradar.integrations.feishu import __main__ as runner
from trendradar.integrations.feishu import client as client_module
from trendradar.integrations.feishu.client import FeishuClient
from trendradar.integrations.feishu.models import stable_digest
from trendradar.intelligence.storage import IntelligenceStorage

from .test_instant import scheduler, seed


def deferred(monkeypatch, factory):
    monkeypatch.setattr(client_module, "find_spec", lambda _name: object())
    monkeypatch.setattr(FeishuClient, "from_credentials", factory)
    return FeishuClient.deferred_for_scheduler("app", "secret", timeout_seconds=7)


def test_empty_scheduler_entrypoint_does_not_build_sdk(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    for key, value in {
        "LARK_ENABLED": "true", "INTELLIGENCE_ENABLED": "true",
        "LARK_APP_ID": "app", "LARK_APP_SECRET": "secret",
        "LARK_DELIVERY_ENABLED": "true", "LARK_DELIVERY_MODE": "instant",
        "LARK_DELIVERY_TARGET": "chat", "INTELLIGENCE_DB_PATH": str(tmp_path / "test.db"),
        "INTELLIGENCE_REQUIRE_EXISTING": "false",
    }.items():
        monkeypatch.setenv(key, value)
    factory = Mock(side_effect=AssertionError("empty tick imported SDK"))
    deferred(monkeypatch, factory)
    assert runner.main(["--role", "scheduler-once", "--config", str(config)]) == 0
    factory.assert_not_called()


def test_first_send_initializes_once_and_preserves_uuid_and_timeout(monkeypatch):
    operations = Mock(send=Mock(return_value=True))
    factory = Mock(return_value=FeishuClient(operations))
    client = deferred(monkeypatch, factory)
    assert client.available
    factory.assert_not_called()
    assert client.send("chat", "first", message_uuid="stable-1")
    assert client.send("chat", "second", message_uuid="stable-2")
    factory.assert_called_once_with(
        "app", "secret", timeout_seconds=7, api_domain=client_module.LARK_API_DOMAIN,
    )
    assert [c.kwargs["message_uuid"] for c in operations.send.call_args_list] == [
        "stable-1", "stable-2",
    ]


@pytest.mark.parametrize("factory_result", [None, "raises"])
def test_initialization_failure_retries_saved_batch_without_changing_payload(
    tmp_path, monkeypatch, factory_result,
):
    factory = Mock(
        return_value=FeishuClient(),
        side_effect=RuntimeError("synthetic provider error") if factory_result else None,
    )
    failed = deferred(monkeypatch, factory)
    path = tmp_path / "test.db"
    with IntelligenceStorage(path) as storage:
        seed(storage)
        assert scheduler(storage, failed).tick() == "send_failed"
        saved = dict(storage.connection.execute("SELECT * FROM lark_instant_batches").fetchone())
    operations = Mock(send=Mock(return_value=True))
    retried = deferred(monkeypatch, Mock(return_value=FeishuClient(operations)))
    with IntelligenceStorage.open_existing(path) as storage:
        assert scheduler(storage, retried).tick() == "sent"
        delivered = dict(storage.connection.execute("SELECT * FROM lark_instant_batches").fetchone())
    assert saved["delivery_key"] == delivered["delivery_key"]
    assert saved["chunks_json"] == delivered["chunks_json"]
    assert json.loads(saved["chunks_json"])
    assert delivered["attempts"] == 2 and delivered["status"] == "completed"
    assert operations.send.call_args.kwargs["message_uuid"] == stable_digest(
        "instant", saved["delivery_key"], "0",
    )


def test_missing_sdk_or_credentials_stays_unavailable(monkeypatch):
    monkeypatch.setattr(client_module, "find_spec", lambda _name: None)
    assert not FeishuClient.deferred_for_scheduler("app", "secret").available
    assert not FeishuClient.deferred_for_scheduler("", "secret").available
