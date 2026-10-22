"""Authorized SDK-envelope to real local Assistant contract tests."""

import json
from types import SimpleNamespace

import pytest

from trendradar.ai.assistant import AssistantService
from trendradar.ai.client import GeminiResult
from trendradar.integrations.feishu.client import FeishuClient
from trendradar.integrations.feishu.config import FeishuConfig
from trendradar.integrations.feishu.handler import FeishuHandler
from trendradar.integrations.feishu.ledger import EventLedger
from trendradar.integrations.feishu.models import FeishuMediaPart

PNG = b"\x89PNG\r\n\x1a\nfixture-image"


def payload(*, event_id="ev1", user="owner", chat="p2p", kind="text", content=None, mention=False):
    return {
        "header": {"event_id": event_id, "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_type": "user", "sender_id": {"open_id": user}},
            "message": {
                "chat_id": "chat",
                "chat_type": chat,
                "message_id": "msg",
                "message_type": kind,
                "content": json.dumps(content or {"text": "question"}),
                "mentions": [{"id": {"open_id": "bot"}, "key": "@_user_1"}] if mention else [],
            },
        },
    }


class Operations:
    def __init__(self):
        self.replies, self.downloads = [], []
        self.image = PNG

    def reply(self, message_id, text):
        self.replies.append((message_id, text))
        return True

    def download_image(self, message_id, key):
        self.downloads.append((message_id, key))
        return FeishuMediaPart(resource_key=key, data=self.image)


class Gemini:
    def __init__(self):
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return GeminiResult("answer", "test")


@pytest.fixture
def setup(tmp_path):
    operations, gemini = Operations(), Gemini()
    assistant = AssistantService(tmp_path / "test.db", gemini)
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),), bot_id="bot")
    ledger = EventLedger(tmp_path / "test.db")
    handler = FeishuHandler(config, FeishuClient(operations), assistant, ledger=ledger)
    yield handler, operations, gemini
    assistant.close()
    ledger.close()


def test_private_text_and_mentioned_group_use_separate_sessions(setup):
    handler, ops, gemini = setup
    assert handler.handle(payload()) == "sent"
    assert (
        handler.handle(
            payload(
                chat="group",
                mention=True,
                event_id="ev2",
                content={"text": "@_user_1 hello @_user_10"},
            )
        )
        == "sent"
    )
    assert len(gemini.calls) == 2
    assert "@_user_10" in gemini.calls[1][-1].content
    assert "@_user_1 hello" not in gemini.calls[1][-1].content
    assert "UTC:" in ops.replies[0][1]
    assert (
        handler.assistant.storage.connection.execute(
            "SELECT COUNT(*) FROM assistant_sessions"
        ).fetchone()[0]
        == 2
    )


@pytest.mark.parametrize(
    "message",
    [
        payload(user="stranger"),
        payload(chat="group"),
        payload(kind="file"),
        payload(content={"text": 2}),
    ],
)
def test_rejected_events_have_no_provider_media_or_session_side_effects(setup, message):
    handler, ops, gemini = setup
    assert handler.handle(message) == "ignored"
    assert not ops.replies and not ops.downloads and not gemini.calls
    assert (
        handler.assistant.storage.connection.execute(
            "SELECT COUNT(*) FROM assistant_sessions"
        ).fetchone()[0]
        == 0
    )


def test_authorization_happens_before_content_access(setup):
    handler, _, gemini = setup

    class PoisonMessage:
        chat_type, chat_id, message_id, mentions = "p2p", "chat", "msg", []

        @property
        def content(self):
            raise AssertionError("unauthorized content was accessed")

    value = payload(user="stranger")
    value["event"]["message"] = PoisonMessage()
    assert handler.handle(value) == "ignored"
    assert not gemini.calls


@pytest.mark.parametrize(
    "kind,content",
    [
        ("image", {"image_key": "img1"}),
        (
            "post",
            {
                "title": "Inspect",
                "content": [
                    [{"tag": "text", "text": "Explain"}, {"tag": "img", "image_key": "img1"}]
                ],
            },
        ),
    ],
)
def test_image_only_and_mixed_inputs_reach_gemini_without_persistence(setup, kind, content):
    handler, ops, gemini = setup
    assert handler.handle(payload(kind=kind, content=content)) == "sent"
    assert gemini.calls[0][-1].images[0].data == PNG
    if kind == "post":
        assert "Inspect" in gemini.calls[0][-1].content
        assert "Explain" in gemini.calls[0][-1].content
    assert len(ops.downloads) == 1
    rows = handler.assistant.storage.connection.execute(
        "SELECT content, metadata_json FROM assistant_messages"
    ).fetchall()
    assert "fixture-image" not in str([tuple(row) for row in rows])


def test_media_failure_replies_without_inventing_image_analysis(setup):
    handler, ops, gemini = setup
    ops.image = b"not an image"
    assert handler.handle(payload(kind="image", content={"image_key": "img1"})) == "sent"
    assert "Image processing is unavailable" in ops.replies[0][1]
    assert not gemini.calls


def test_sdk_object_envelope_shape(setup):
    handler, _, _ = setup

    def sdk(value):
        if isinstance(value, dict):
            return SimpleNamespace(**{key: sdk(item) for key, item in value.items()})
        return value

    assert handler.handle(sdk(payload())) == "sent"
