"""Official Lark SDK boundary with injectable provider operations."""

from __future__ import annotations

import json
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from .config import LARK_API_DOMAIN
from .models import FeishuMediaPart, stable_digest
from .reply_context import MAX_RESPONSE_BYTES, ReplyContext, parse_reply_content, quote_limit


@dataclass(frozen=True)
class ReplyDelivery:
    delivered: bool
    retryable: bool = True
    retry_after_seconds: int = 0
    error_code: str = ""


class FeishuOperations(Protocol):
    def reply(self, message_id: str, text: str) -> bool: ...
    def send(self, target: str, text: str, *, message_uuid: str | None = None) -> bool: ...
    def download_image(self, message_id: str, resource_key: str) -> FeishuMediaPart | None: ...
    def get_message(self, message_id: str) -> Any:
        """Return the SDK-shaped response: code, success(), raw, data.items[]."""
        ...


class FeishuClient:
    """Small provider-neutral facade; SDK construction is intentionally lazy."""

    def __init__(self, operations: FeishuOperations | None = None) -> None:
        self._operations = operations

    @property
    def available(self) -> bool:
        return self._operations is not None

    def reply(self, message_id: str, text: str) -> bool:
        return self.reply_result(message_id, text).delivered

    def reply_result(
        self, message_id: str, text: str, *, message_uuid: str | None = None
    ) -> ReplyDelivery:
        try:
            from .delivery import safe_text, text_chunks

            chunks = text_chunks(safe_text(text))
            if not self._operations or not chunks:
                return ReplyDelivery(False, error_code="unavailable")
            detailed = getattr(type(self._operations), "reply_result", None)
            for index, chunk in enumerate(chunks):
                if callable(detailed):
                    outcome = self._operations.reply_result(
                        message_id, chunk,
                        message_uuid=stable_digest(message_uuid, str(index)) if message_uuid else None,
                    )
                    if not isinstance(outcome, ReplyDelivery):
                        return ReplyDelivery(False, error_code="invalid_response")
                    if not outcome.delivered:
                        return outcome
                elif not self._operations.reply(message_id, chunk):
                    return ReplyDelivery(False, error_code="unavailable")
            return ReplyDelivery(True)
        except Exception:
            return ReplyDelivery(False, error_code="unavailable")

    def send(self, target: str, text: str, *, message_uuid: str | None = None) -> bool:
        try:
            if message_uuid is not None:
                return bool(
                    self._operations
                    and self._operations.send(target, text, message_uuid=message_uuid)
                )
            return bool(self._operations and self._operations.send(target, text))
        except Exception:
            return False

    def download_image(self, message_id: str, resource_key: str) -> FeishuMediaPart | None:
        try:
            return (
                self._operations.download_image(message_id, resource_key)
                if self._operations
                else None
            )
        except Exception:
            return None

    def get_replied_message(
        self, parent_message_id: str | None, *, chat_id: str, max_chars: int = 4000,
    ) -> ReplyContext:
        """Read just the direct parent after caller authorization, never roots or attachments."""
        if parent_message_id is None or parent_message_id == "":
            return ReplyContext("absent")
        if not all(
            isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value)
            for value in (parent_message_id, chat_id)
        ):
            return ReplyContext("invalid_response")
        if not quote_limit(max_chars):
            return ReplyContext("input_limit")
        operation = getattr(self._operations, "get_message", None)
        if not callable(operation):
            return ReplyContext("unavailable")
        try:
            response = operation(parent_message_id)
        except (TimeoutError, PermissionError) as exc:
            return ReplyContext("timeout" if isinstance(exc, TimeoutError) else "permission_denied")
        except (ValueError, RecursionError):
            return ReplyContext("invalid_response")
        except Exception as exc:
            from requests.exceptions import Timeout

            return ReplyContext("timeout" if isinstance(exc, Timeout) else "unavailable")
        try:
            return _message_context(response, parent_message_id, chat_id, max_chars)
        except Exception:
            # Provider model failures never log raw bodies, identities, URLs or exception text.
            return ReplyContext("invalid_response")

    @classmethod
    def from_credentials(
        cls,
        app_id: str,
        app_secret: str,
        *,
        timeout_seconds: int = 30,
        api_domain: str = LARK_API_DOMAIN,
    ) -> FeishuClient:
        """Build SDK operations only when explicitly requested by a runner."""
        if not app_id or not app_secret:
            return cls()
        try:
            import lark_oapi as lark
        except ImportError:
            return cls()
        return cls(
            _SdkOperations(
                lark,
                app_id,
                app_secret,
                timeout_seconds=timeout_seconds,
                api_domain=api_domain,
            )
        )


class _SdkOperations:
    """SDK-specific code is confined to this private boundary."""

    def __init__(
        self,
        sdk: Any,
        app_id: str,
        app_secret: str,
        *,
        timeout_seconds: int = 30,
        api_domain: str = LARK_API_DOMAIN,
    ) -> None:
        self._sdk = sdk
        self._client = (
            sdk.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .domain(api_domain)
            .timeout(timeout_seconds)
            .log_level(sdk.LogLevel.ERROR)
            .build()
        )

    def get_message(self, message_id: str) -> Any:
        from lark_oapi.api.im.v1 import GetMessageRequest

        request = GetMessageRequest.builder().message_id(message_id).build()
        # Preserve this client's configured SDK timeout; no retries or ancestor traversal.
        return self._client.im.v1.message.get(request)

    def reply(self, message_id: str, text: str) -> bool:
        return self.reply_result(message_id, text).delivered

    def reply_result(
        self, message_id: str, text: str, *, message_uuid: str | None = None
    ) -> ReplyDelivery:
        from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody

        builder = (
            ReplyMessageRequestBody.builder()
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
        )
        if message_uuid:
            builder.uuid(message_uuid)
        body = builder.build()
        request = ReplyMessageRequest.builder().message_id(message_id).request_body(body).build()
        response = self._client.im.v1.message.reply(request)
        if response.success():
            return ReplyDelivery(True)
        raw = response.raw
        status = getattr(raw, "status_code", None)
        headers = getattr(raw, "headers", {}) or {}
        delay = 0
        with suppress(TypeError, ValueError):
            delay = max(0, min(3600, int(headers.get("Retry-After", headers.get("retry-after", 0)))))
        if status == 429:
            return ReplyDelivery(False, retry_after_seconds=delay, error_code="rate_limited")
        if status in {400, 403, 404, 405, 410, 413, 422}:
            return ReplyDelivery(False, retryable=False, error_code="rejected")
        # Unknown business codes stay bounded-retry failures; do not infer
        # permanence from localized provider message text.
        return ReplyDelivery(False, retry_after_seconds=delay, error_code="unavailable")

    def send(self, target: str, text: str, *, message_uuid: str | None = None) -> bool:
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        from .post import message_content

        message_type, content = message_content(text)
        builder = (
            CreateMessageRequestBody.builder()
            .receive_id(target)
            .msg_type(message_type)
            .content(content)
        )
        if message_uuid:
            builder.uuid(message_uuid)
        body = builder.build()
        request = (
            CreateMessageRequest.builder().receive_id_type("chat_id").request_body(body).build()
        )
        return self._client.im.v1.message.create(request).success()

    def download_image(self, message_id: str, resource_key: str) -> FeishuMediaPart | None:
        import requests
        from lark_oapi.api.im.v1 import GetMessageResourceRequest
        from lark_oapi.core.http.transport import _build_header, _build_url
        from lark_oapi.core.model import RequestOption
        from lark_oapi.core.token.auth import verify

        request = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(resource_key)
            .type("image")
            .build()
        )
        # The pinned SDK buffers binary responses. Reuse its typed request/auth,
        # but stream this one fixed resource endpoint to enforce a real byte cap.
        conf, option = self._client._config, RequestOption()
        verify(conf, request, option)
        url = _build_url(conf.domain, request.uri, request.paths)
        deadline = time.monotonic() + conf.timeout
        with requests.get(
            url,
            headers=_build_header(request, option, conf),
            params=request.queries,
            timeout=conf.timeout,
            stream=True,
            allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                return None
            limit = 4 * 1024 * 1024
            if int(response.headers.get("Content-Length", "0")) > limit:
                return None
            data = bytearray()
            for chunk in response.iter_content(64 * 1024):
                if len(data) + len(chunk) > limit or time.monotonic() > deadline:
                    return None
                data.extend(chunk)
        return FeishuMediaPart(resource_key=resource_key, data=bytes(data))


def _message_context(
    response: Any, parent_message_id: str, chat_id: str, max_chars: int,
) -> ReplyContext:
    if response is None:
        return ReplyContext("invalid_response")
    raw = getattr(response, "raw", None)
    status = getattr(raw, "status_code", None)
    if status in {401, 403}:
        return ReplyContext("permission_denied")
    if status in {404, 410}:
        return ReplyContext("not_found")
    if status in {408, 504}:
        return ReplyContext("timeout")
    if type(status) is not int:
        return ReplyContext("invalid_response")
    code = getattr(response, "code", None)
    if status == 400 and type(code) is int:
        # GetMessage's documented permission/visibility/deletion errors use HTTP 400.
        if code in {230027, 230002, 230013, 230050}:
            return ReplyContext("permission_denied")
        if code == 230110:
            return ReplyContext("not_found")
    if not 200 <= status < 300:
        return ReplyContext("unavailable")
    if type(code) is not int:
        return ReplyContext("invalid_response")
    if code == 99991672:
        return ReplyContext("permission_denied")
    if code != 0:
        return ReplyContext("unavailable")
    if response.success() is not True:
        return ReplyContext("invalid_response")
    content = getattr(raw, "content", None)
    if not isinstance(content, bytes | str):
        return ReplyContext("invalid_response")
    # SDK 1.7.3 has already buffered/decoded this response; this is a post-SDK bound.
    if len(content) > MAX_RESPONSE_BYTES or (
        isinstance(content, str) and len(content.encode("utf-8")) > MAX_RESPONSE_BYTES
    ):
        return ReplyContext("too_large", truncated=True)
    items = getattr(getattr(response, "data", None), "items", None)
    if not isinstance(items, list):
        return ReplyContext("invalid_response")
    if not items:
        return ReplyContext("not_found")
    if len(items) != 1:
        return ReplyContext("invalid_response")
    message = items[0]
    returned_id = getattr(message, "message_id", None)
    returned_chat = getattr(message, "chat_id", None)
    if not isinstance(returned_id, str) or not isinstance(returned_chat, str):
        return ReplyContext("invalid_response")
    if returned_id != parent_message_id:
        return ReplyContext("mismatched_message")
    if returned_chat != chat_id:
        return ReplyContext("cross_chat")
    if getattr(message, "deleted", None) is True:
        return ReplyContext("not_found")
    return parse_reply_content(
        getattr(message, "msg_type", None),
        getattr(getattr(message, "body", None), "content", None),
        max_chars=max_chars,
    )


__all__ = ["FeishuClient", "FeishuOperations"]
