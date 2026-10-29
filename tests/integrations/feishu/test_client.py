"""Pinned SDK callback registration, streaming bounds, and error isolation."""

import json
from importlib.metadata import version
from types import SimpleNamespace
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


def lookup_response(*, message_id="parent", chat_id="chat", message_type="text", content=None):
    """SDK 1.7.3 GetMessageResponse.data.items, not an inbound event shape."""
    return SimpleNamespace(
        success=lambda: True,
        code=0,
        raw=SimpleNamespace(status_code=200, content=b""),
        data=SimpleNamespace(items=[SimpleNamespace(
            message_id=message_id,
            chat_id=chat_id,
            msg_type=message_type,
            deleted=False,
            root_id="never-follow-root",
            parent_id="never-follow-parent",
            body=SimpleNamespace(content=content or json.dumps({"text": "quoted news"})),
        )]),
    )


def test_pinned_get_message_sdk_wiring(monkeypatch, record_testsuite_property):
    lark = pytest.importorskip("lark_oapi")
    from lark_oapi.api.im.v1 import GetMessageRequest, GetMessageResponse

    assert version("lark-oapi") == "1.7.3"
    record_testsuite_property(
        "TRP-LARK-001-root-cause",
        "Confirmed: pre-fix facade had no direct-parent lookup. Parent/handler wiring is separate.",
    )
    record_testsuite_property(
        "TRP-LARK-001-sdk-scope",
        "SDK 1.7.3 GetMessageRequest uses GET /open-apis/im/v1/messages/:message_id; "
        "GetMessageResponse.data.items contains Message with body.content JSON. "
        "SDK declares TENANT/USER token types, not required permission scopes; "
        "exact scope and live tenant approval remain unverified offline. No live calls.",
    )
    record_testsuite_property(
        "TRP-LARK-001-bounds",
        "Official SDK buffers and decodes responses before returning; size checks here are "
        "post-SDK limits, not a streaming wire-byte cap. Existing SDK timeout is preserved.",
    )
    operations = _SdkOperations(lark, "offline-app", "offline-secret", timeout_seconds=7)
    response = GetMessageResponse({
        "code": 0,
        "data": {"items": [{
            "message_id": "parent", "chat_id": "chat", "msg_type": "post",
            "body": {"content": json.dumps({"title": "News", "content": [[
                {"tag": "a", "text": "source", "href": "https://example.org/news?q=private"},
            ]]})},
        }]},
    })
    response.raw = SimpleNamespace(status_code=200, content=b"{}")
    get = Mock(return_value=response)
    monkeypatch.setattr(operations._client.im.v1.message, "get", get)
    result = FeishuClient(operations).get_replied_message("parent", chat_id="chat")
    assert result.status == "available"
    assert "https://example.org/news?q=private" in result.text
    request = get.call_args.args[0]
    assert isinstance(request, GetMessageRequest)
    assert request.message_id == "parent"
    assert request.paths == {"message_id": "parent"}
    assert request.uri == "/open-apis/im/v1/messages/:message_id"
    get.assert_called_once()
    assert operations._client._config.timeout == 7
    assert operations._client._config.domain == LARK_API_DOMAIN


@pytest.mark.parametrize("parent", [None, ""])
def test_absent_parent_does_not_call_operations(parent):
    operations = Mock()
    result = FeishuClient(operations).get_replied_message(parent, chat_id="chat")
    assert result.status == "absent" and not result.text
    operations.get_message.assert_not_called()


@pytest.mark.parametrize("parent,chat", [
    ("../parent", "chat"), ("parent?x=secret", "chat"), (" parent ", "chat"),
    ("parent", ""), ("parent", None), (123, "chat"), ("x" * 257, "chat"),
])
def test_invalid_lookup_ids_do_not_reach_sdk(parent, chat):
    operations = Mock()
    result = FeishuClient(operations).get_replied_message(parent, chat_id=chat)
    assert result.status == "invalid_response" and not result.text
    operations.get_message.assert_not_called()


def test_lookup_uses_only_one_exact_parent_and_preserves_query(caplog, capsys):
    url = "https://example.org/news?token=synthetic-private-value&lang=en#section"
    operations = Mock(get_message=Mock(return_value=lookup_response(
        content=json.dumps({"text": "news " + url}),
    )))
    result = FeishuClient(operations).get_replied_message("parent", chat_id="chat")
    assert result.status == "available" and result.text == "news " + url
    operations.get_message.assert_called_once_with("parent")
    operations.download_image.assert_not_called()
    assert "synthetic-private-value" not in repr(result)
    assert "synthetic-private-value" not in caplog.text
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


@pytest.mark.parametrize("message_id,chat_id,status", [
    ("other-parent", "chat", "mismatched_message"),
    ("parent", "other-chat", "cross_chat"),
    (None, "chat", "invalid_response"),
    ("parent", None, "invalid_response"),
])
def test_identity_checked_before_body_access(message_id, chat_id, status):
    class UntouchableBody:
        @property
        def content(self):
            pytest.fail("Unverified quote body must never be accessed")

    response = lookup_response(message_id=message_id, chat_id=chat_id)
    response.data.items[0].body = UntouchableBody()
    result = FeishuClient(Mock(get_message=Mock(return_value=response))).get_replied_message(
        "parent", chat_id="chat",
    )
    assert result.status == status and not result.text


@pytest.mark.parametrize("items,status", [
    ([], "not_found"), (None, "invalid_response"), ({}, "invalid_response"),
    ([None], "invalid_response"), ([object(), object()], "invalid_response"),
])
def test_items_must_be_exactly_one_message(items, status):
    response = lookup_response()
    response.data.items = items
    result = FeishuClient(Mock(get_message=Mock(return_value=response))).get_replied_message(
        "parent", chat_id="chat",
    )
    assert result.status == status and not result.text


@pytest.mark.parametrize("http_status,code,success,status", [
    (403, 0, True, "permission_denied"),
    (401, 0, True, "permission_denied"),
    (404, 0, True, "not_found"),
    (410, 0, True, "not_found"),
    (408, 0, True, "timeout"),
    (504, 0, True, "timeout"),
    (429, 0, True, "unavailable"),
    (500, 0, True, "unavailable"),
    (200, 99991672, False, "permission_denied"),
    (200, 99991672, True, "permission_denied"),
    (200, 99999999, False, "unavailable"),
    (200, 99999999, True, "unavailable"),
    (200, 0, False, "invalid_response"),
    (200, None, True, "invalid_response"),
    (200, "0", True, "invalid_response"),
    (200, False, True, "invalid_response"),
    (200, 0, "yes", "invalid_response"),
])
def test_lookup_failure_and_false_success_classification(http_status, code, success, status):
    response = lookup_response()
    response.raw.status_code = http_status
    response.code = code
    response.success = lambda: success
    result = FeishuClient(Mock(get_message=Mock(return_value=response))).get_replied_message(
        "parent", chat_id="chat",
    )
    assert result.status == status and not result.text


@pytest.mark.parametrize("http_status,code,status", [
    (400, 230027, "permission_denied"),
    (400, 230002, "permission_denied"),
    (400, 230013, "permission_denied"),
    (400, 230050, "permission_denied"),
    (400, 230110, "not_found"),
    (400, 230006, "unavailable"),
    (400, 99999999, "unavailable"),
    (400, "230027", "unavailable"),
    (400, 0, "unavailable"),
    (403, 230110, "permission_denied"),
    (404, 230027, "not_found"),
    (500, 230027, "unavailable"),
])
@pytest.mark.parametrize("success", [False, True])
def test_documented_http_400_codes_do_not_inspect_error_text_or_body(
    http_status, code, status, success,
):
    class ErrorData:
        @property
        def items(self):
            pytest.fail("Failed lookups must never inspect quote items")

    response = lookup_response()
    response.raw.status_code = http_status
    response.code = code
    response.success = lambda: success
    response.msg = "permission denied; message deleted; do not infer status from this text"
    response.data = ErrorData()
    operations = Mock(get_message=Mock(return_value=response))
    result = FeishuClient(operations).get_replied_message("parent", chat_id="chat")
    assert result.status == status and not result.text
    operations.get_message.assert_called_once_with("parent")
    operations.download_image.assert_not_called()


@pytest.mark.parametrize("exception,status", [
    (TimeoutError("private query"), "timeout"),
    (PermissionError("private query"), "permission_denied"),
    (RuntimeError("private query"), "unavailable"),
    (ValueError("private query"), "invalid_response"),
])
def test_lookup_exception_categories_do_not_leak(exception, status, caplog, capsys):
    operations = Mock(get_message=Mock(side_effect=exception))
    result = FeishuClient(operations).get_replied_message("parent", chat_id="chat")
    assert result.status == status and not result.text
    assert "private query" not in caplog.text
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


def test_requests_timeout_is_classified():
    from requests.exceptions import ReadTimeout

    operations = Mock(get_message=Mock(side_effect=ReadTimeout("secret")))
    assert FeishuClient(operations).get_replied_message(
        "parent", chat_id="chat",
    ).status == "timeout"


def test_missing_operations_and_missing_response_are_distinct():
    assert FeishuClient().get_replied_message("parent", chat_id="chat").status == "unavailable"
    client = FeishuClient(Mock(get_message=Mock(return_value=None)))
    assert client.get_replied_message("parent", chat_id="chat").status == "invalid_response"


def test_deleted_message_is_unavailable_even_with_body():
    response = lookup_response()
    response.data.items[0].deleted = True
    result = FeishuClient(Mock(get_message=Mock(return_value=response))).get_replied_message(
        "parent", chat_id="chat",
    )
    assert result.status == "not_found" and not result.text


def test_post_sdk_raw_response_bound():
    response = lookup_response()
    response.raw.content = b"x" * (128 * 1024 + 1)
    result = FeishuClient(Mock(get_message=Mock(return_value=response))).get_replied_message(
        "parent", chat_id="chat",
    )
    assert result.status == "too_large" and result.truncated and not result.text


def test_facade_respects_requested_character_budget():
    operations = Mock(get_message=Mock(return_value=lookup_response()))
    result = FeishuClient(operations).get_replied_message("parent", chat_id="chat", max_chars=6)
    assert result.status == "available" and result.text == "quoted" and result.truncated


def test_media_quote_never_downloads_image():
    operations = Mock(get_message=Mock(return_value=lookup_response(
        message_type="image", content=json.dumps({"image_key": "never-download"}),
    )))
    result = FeishuClient(operations).get_replied_message("parent", chat_id="chat")
    assert result.status == "unsupported" and result.message_type == "image"
    assert not result.text
    operations.download_image.assert_not_called()
