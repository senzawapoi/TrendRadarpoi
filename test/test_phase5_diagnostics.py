"""Sandbox observation must not alter authorization or event processing."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from phase5_diagnostics import diagnostics, main

from trendradar.ai.assistant import AssistantService
from trendradar.ai.client import GeminiClient, GeminiConfig
from trendradar.integrations.feishu.client import FeishuClient
from trendradar.integrations.feishu.config import FeishuConfig
from trendradar.integrations.feishu.handler import FeishuHandler
from trendradar.integrations.feishu.ledger import EventLedger
from trendradar.integrations.feishu.models import FeishuMediaPart

PNG = b"\x89PNG\r\n\x1a\nprivate-image-bytes"
QUESTION = "private question text"


def payload(user="private-owner", kind="post"):
    return {
        "header": {"event_type": "im.message.receive_v1", "event_id": "private-event"},
        "event": {
            "sender": {"sender_type": "user", "sender_id": {"open_id": user}},
            "message": {
                "chat_id": "private-chat", "chat_type": "p2p",
                "message_id": "private-message", "message_type": kind,
                "content": json.dumps({"en_us": {"content": [[
                    {"tag": "text", "text": QUESTION},
                    {"tag": "img", "image_key": "private-image-key"},
                ]]}}),
            },
        },
    }


@pytest.fixture
def setup(tmp_path):
    provider = Mock(return_value={
        "text": "private answer text",
        "model_version": "gemini-3.5-flash-lite",
        "candidates": [{"finish_reason": "STOP"}],
        "usage_metadata": {"prompt_token_count": 20, "candidates_token_count": 5,
                           "total_token_count": 25},
    })
    gemini = GeminiClient(
        GeminiConfig(api_key="private-api-key", model="gemini-3.5-flash-lite", max_attempts=1),
        client=SimpleNamespace(models=SimpleNamespace(generate_content=provider)),
    )
    ops = Mock()
    ops.reply.return_value = True
    ops.download_image.return_value = FeishuMediaPart(resource_key="private-image-key", data=PNG)
    assistant = AssistantService(tmp_path / "test.db", gemini)
    ledger = EventLedger(tmp_path / "test.db")
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("private-owner",)),))
    handler = FeishuHandler(config, FeishuClient(ops), assistant, ledger=ledger)
    yield handler, ops, provider
    assistant.close()
    ledger.close()


def test_mixed_event_is_correlated_without_content_and_replay_does_not_call_model(setup):
    handler, ops, provider = setup
    records = []
    original = FeishuHandler.process
    with diagnostics(records.append):
        prepared = handler.prepare(payload())
        assert handler.process(*prepared) == "sent"
        assert handler.handle(payload()) == "sent"
    assert FeishuHandler.process is original
    assert provider.call_count == 1
    assert ops.download_image.call_count == 1
    assert ops.reply.call_count == 2
    assert len({row["event_token"] for row in records}) == 1
    assert records[0]["message_type"] == "post"
    assert records[0]["text_chars"] == len(QUESTION)
    for stage in ("assistant_input", "gemini_input"):
        row = next(row for row in records if row["stage"] == stage)
        assert row["image_count"] == 1
        assert row["image_bytes"] == len(PNG)
    result = next(row for row in records if row["stage"] == "gemini_result")
    assert result["finish_reason"] == "STOP"
    assert result["total_tokens"] == 25
    assert records[-1]["gemini_calls"] == 0
    assert "private-" not in json.dumps(records)
    assert QUESTION not in json.dumps(records)
    assert "private answer text" not in json.dumps(records)
    parts = provider.call_args.kwargs["contents"][-1]["parts"]
    assert any(QUESTION in part.get("text", "") for part in parts)
    assert any(part.get("inline_data", {}).get("data") == PNG for part in parts)


def test_rejected_payload_is_not_inspected_or_forwarded(setup):
    handler, ops, provider = setup

    class PoisonMessage:
        chat_type, chat_id, message_id, mentions = "p2p", "private-chat", "private-msg", []

        @property
        def content(self):
            raise AssertionError("content accessed")

        @property
        def message_type(self):
            raise AssertionError("type accessed")

    message = payload(user="stranger")
    message["event"]["message"] = PoisonMessage()
    records = []
    with diagnostics(records.append):
        assert handler.handle(message) == "ignored"
    assert [row["stage"] for row in records] == ["ignored"]
    assert not provider.called and not ops.download_image.called and not ops.reply.called


def test_broken_diagnostic_sink_does_not_break_delivery(setup):
    handler, ops, provider = setup
    with diagnostics(Mock(side_effect=OSError("private diagnostic error"))):
        assert handler.handle(payload()) == "sent"
    assert provider.call_count == ops.reply.call_count == 1


def test_provider_error_is_sanitized_and_original_fallback_runs(setup):
    handler, ops, provider = setup
    provider.side_effect = ValueError("private-api-key in provider error")
    records = []
    with diagnostics(records.append):
        assert handler.handle(payload()) == "sent"
    assert provider.call_count == ops.reply.call_count == 1
    assert any(row.get("outcome") == "error" for row in records)
    assert any(row.get("degraded") is True for row in records)
    assert "private" not in json.dumps(records)


def test_diagnostic_entrypoint_refuses_non_sandbox_database(monkeypatch, capsys):
    monkeypatch.setenv("INTELLIGENCE_DB_PATH", "output/intelligence.db")
    assert main() == 2
    assert "isolated" in capsys.readouterr().out
