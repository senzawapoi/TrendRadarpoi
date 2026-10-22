"""Official Lark SDK boundary with injectable provider operations."""

from __future__ import annotations

import json
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from .config import LARK_API_DOMAIN
from .models import FeishuMediaPart, stable_digest


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

        builder = (
            CreateMessageRequestBody.builder()
            .receive_id(target)
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
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


__all__ = ["FeishuClient", "FeishuOperations"]
