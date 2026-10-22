"""DTO immutability, stable session identity and offline transport boundaries."""

import ast
import builtins
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from trendradar.integrations.feishu.client import FeishuClient, _SdkOperations
from trendradar.integrations.feishu.config import FeishuConfig
from trendradar.integrations.feishu.models import FeishuInbound, FeishuMediaPart, FeishuReply
from trendradar.integrations.feishu.session import SessionMapper


def event(**kwargs):
    values = {
        "event_id": "ev1",
        "event_type": "im.message.receive_v1",
        "identity": {"open_id": "user"},
        "chat_type": "p2p",
        "chat_id": "chat",
        "message_id": "msg",
        "text": "question",
    }
    return FeishuInbound(**(values | kwargs))


def test_stable_private_and_group_sessions_and_no_cross_principal_merge():
    mapper = SessionMapper(FeishuConfig(identity_fields=(("open_id", ("user", "second")),)))
    first = mapper.authorize(event())
    assert first == mapper.authorize(event())
    group = mapper.authorize(event(chat_type="group"))
    other_chat = mapper.authorize(event(chat_id="other"))
    other_user = mapper.authorize(event(identity={"open_id": "second"}))
    assert (
        len({first.session_id, group.session_id, other_chat.session_id, other_user.session_id}) == 4
    )
    assert "user" not in first.principal_id
    assert SessionMapper(FeishuConfig()).authorize(event()) is None


@pytest.mark.parametrize("value", ["", "a" * 257, "user/name", "user name", None])
def test_invalid_identifier_never_collides_with_authorized_identifier(value):
    with pytest.raises(ValueError):
        event(event_id=value)


def test_media_intent_immutable_and_not_serialized_as_bytes():
    media = FeishuMediaPart(resource_key="img_key", data=b"image-data")
    inbound = event(text="", media=[media])
    assert inbound.has_content and isinstance(inbound.media, tuple)
    assert replace(inbound, text="what is this").has_content
    assert "image-data" not in json.dumps(media.to_dict()) + repr(media)
    with pytest.raises(TypeError):
        inbound.identity["open_id"] = "changed"
    with pytest.raises(ValueError):
        event(media=(media,) * 5)
    with pytest.raises(ValueError):
        event(text="x" * 50001)
    with pytest.raises(ValueError):
        event(received_at=datetime(2026, 9, 12))


def test_reply_roundtrip_and_corrupt_payload():
    reply = FeishuReply("ev1", "answer", degraded=True)
    assert FeishuReply.from_dict(json.loads(json.dumps(reply.to_dict()))) == reply
    with pytest.raises(ValueError):
        FeishuReply.from_dict({"event_id": "ev1", "text": None})


def test_sdk_unavailable_and_fake_provider_injection(monkeypatch):
    original = builtins.__import__

    def no_sdk(name, *args, **kwargs):
        if name.startswith("lark_oapi"):
            raise ImportError("not installed")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sdk)
    assert not FeishuClient.from_credentials("id", "secret").available
    assert not FeishuClient().reply("msg", "text")

    class Operations:
        def reply(self, message_id, text):
            return (message_id, text) == ("msg", "answer")

    assert FeishuClient(Operations()).reply("msg", "answer")


def test_official_sdk_request_builders_without_network(monkeypatch):
    lark = pytest.importorskip("lark_oapi")
    from types import SimpleNamespace

    operations = _SdkOperations(lark, "test-app", "test-secret")
    assert operations._client._config.domain == "https://open.larksuite.com"
    requests = []

    def send(request):
        requests.append(request)
        return SimpleNamespace(success=lambda: True)

    monkeypatch.setattr(operations._client.im.v1.message, "reply", send)
    monkeypatch.setattr(operations._client.im.v1.message, "create", send)
    assert operations.reply("msg", 'quoted "answer"')
    assert operations.send("chat", "daily")
    assert json.loads(requests[0].body.content) == {"text": 'quoted "answer"'}
    assert requests[0].paths == {"message_id": "msg"}
    assert requests[1].body.receive_id == "chat"


def test_core_never_imports_feishu_or_sdk():
    for root in ("trendradar/ai", "trendradar/core", "trendradar/intelligence"):
        for path in Path(root).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                assert not any(
                    name.startswith(("lark_oapi", "trendradar.integrations")) for name in names
                )
