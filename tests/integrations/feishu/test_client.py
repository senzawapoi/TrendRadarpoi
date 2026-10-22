"""Pinned SDK callback registration, streaming bounds, and error isolation."""

import json
from unittest.mock import Mock

import pytest

from trendradar.integrations.feishu.client import FeishuClient, _SdkOperations
from trendradar.integrations.feishu.config import LARK_API_DOMAIN
from trendradar.integrations.feishu.transport import build_dispatcher

from .test_handler import payload


def test_real_sdk_dispatcher_converts_message_event():
    pytest.importorskip("lark_oapi")
    received = []
    dispatcher = build_dispatcher(received.append)
    value = payload()
    value["schema"] = "2.0"
    dispatcher._do_without_validation(json.dumps(value).encode())
    assert received[0].header.event_id == "ev1"
    assert received[0].event.message.message_id == "msg"


def test_injected_sdk_errors_do_not_escape():
    client = FeishuClient(
        Mock(
            reply=Mock(side_effect=RuntimeError("secret")),
            send=Mock(side_effect=RuntimeError("secret")),
            download_image=Mock(side_effect=RuntimeError("secret")),
        )
    )
    assert not client.reply("msg", "text")
    assert not client.send("chat", "text")
    assert client.download_image("msg", "img") is None


def test_streaming_resource_limits_before_buffering(monkeypatch):
    lark = pytest.importorskip("lark_oapi")
    import lark_oapi.core.token.auth as auth
    import requests

    monkeypatch.setattr(auth, "verify", lambda *args: None)
    response = Mock(status_code=200, headers={"Content-Length": "9000000"})
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    get = Mock(return_value=response)
    monkeypatch.setattr(requests, "get", get)
    operations = _SdkOperations(lark, "test", "test")
    assert operations._client._config.domain == LARK_API_DOMAIN
    assert operations.download_image("msg", "img") is None
    response.iter_content.assert_not_called()
    assert get.call_args.kwargs["stream"] and not get.call_args.kwargs["allow_redirects"]
    response.headers = {}
    response.iter_content.return_value = iter([b"x" * 3_000_000, b"x" * 3_000_000])
    assert operations.download_image("msg", "img") is None
