"""Authorize envelopes before parsing content, downloading resources or invoking Assistant."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from trendradar.ai.models import AssistantRequest
from trendradar.ops.maintenance import read_guard

from .client import FeishuClient, ReplyDelivery
from .config import FeishuConfig
from .media import resolve_images
from .models import FeishuInbound, FeishuMediaPart, FeishuReply, sanitize_id, stable_digest
from .session import SessionBinding, SessionMapper

MEDIA_FAILURE = "Image processing is unavailable. Please retry with a smaller image or text."
SERVICE_FAILURE = "The local Assistant is unavailable. Please try again later."


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _message_created_at(message: Any) -> datetime | None:
    value = _get(message, "create_time")
    try:
        if isinstance(value, bool) or not str(value).isdigit():
            return None
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def envelope(payload: Any, config: FeishuConfig) -> tuple[FeishuInbound, Any, tuple[str, ...]]:
    header, event = _get(payload, "header"), _get(payload, "event")
    if _get(header, "event_type") != "im.message.receive_v1":
        raise ValueError("unsupported event")
    sender, message = _get(event, "sender"), _get(event, "message")
    if _get(sender, "sender_type") != "user":
        raise ValueError("unsupported sender")
    ids = _get(sender, "sender_id")
    identity = {key: _get(ids, key) for key in ("open_id", "user_id", "union_id") if _get(ids, key)}
    mentions = _get(message, "mentions") or ()
    if not isinstance(mentions, list | tuple) or len(mentions) > 100:
        raise ValueError("invalid mentions")
    markers = tuple(
        _get(item, "key")
        for item in mentions
        if config.bot_id
        and _get(_get(item, "id"), "open_id") == config.bot_id
        and isinstance(_get(item, "key"), str)
    )
    inbound = FeishuInbound(
        event_id=_get(header, "event_id"),
        event_type=_get(header, "event_type"),
        identity=identity,
        chat_type=_get(message, "chat_type"),
        chat_id=_get(message, "chat_id"),
        message_id=_get(message, "message_id"),
        mentioned=bool(markers),
        created_at=_message_created_at(message),
    )
    return inbound, message, markers


def parse_content(
    event: FeishuInbound, message: Any, markers: tuple[str, ...], limit: int
) -> FeishuInbound:
    kind = _get(message, "message_type")
    if kind not in {"text", "image", "post"}:
        raise ValueError("unsupported message")
    raw = _get(message, "content")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 200_000:
        raise ValueError("invalid message size")
    content = json.loads(raw)
    if not isinstance(content, dict):
        raise ValueError("invalid content")
    texts, media = [], []
    if kind == "text":
        if not isinstance(content.get("text"), str):
            raise ValueError("invalid text")
        texts.append(content["text"])
    elif kind == "image":
        media.append(
            FeishuMediaPart(resource_key=sanitize_id(content.get("image_key"), maximum=512))
        )
    else:
        post = content
        if "content" not in post:
            post = content.get("zh_cn", content.get("en_us", {}))
        if not isinstance(post, dict):
            raise ValueError("invalid post")
        if isinstance(post.get("title"), str):
            texts.append(post["title"])
        rows = post.get("content", [])
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("invalid post rows")
        for row in rows:
            if not isinstance(row, list) or len(row) > 100:
                raise ValueError("invalid post row")
            for part in row:
                if not isinstance(part, dict):
                    raise ValueError("invalid post part")
                tag = part.get("tag")
                if tag in {"text", "a"} and isinstance(part.get("text"), str):
                    texts.append(part["text"])
                elif tag == "img":
                    media.append(
                        FeishuMediaPart(
                            resource_key=sanitize_id(part.get("image_key"), maximum=512)
                        )
                    )
                elif tag == "at":
                    if part.get("user_id") not in markers:
                        texts.append(str(part.get("user_name") or "[mention]"))
                else:
                    raise ValueError("unsupported post part")
    text = "\n".join(texts)
    for marker in markers:
        text = re.sub(re.escape(marker) + r"(?!\w)", "", text)
    if len(text) > limit:
        raise ValueError("message exceeds input limit")
    result = replace(event, text=text, media=tuple(media))
    if not result.has_content:
        raise ValueError("empty message")
    return result


def render_reply(reply: Any, event_id: str) -> FeishuReply:
    lines = [reply.text]
    for citation in reply.citations:
        try:
            url = urlsplit(citation.url)
        except ValueError:
            continue
        if url.scheme in {"http", "https"} and url.netloc:
            lines.append(f"[{citation.ref}] {citation.title}\n{citation.url}")
    interval = reply.time_range
    lines.append(f"UTC: {interval.start.isoformat()} to {interval.end.isoformat()} (exclusive)")
    if reply.degraded:
        lines.append("Degraded: " + reply.degraded_reason)
    return FeishuReply(event_id, "\n\n".join(lines)[:50_000], reply.session_id, reply.degraded)


class FeishuHandler:
    def __init__(
        self, config: FeishuConfig, client: FeishuClient, assistant: Any, *, ledger=None
    ) -> None:
        self.config, self.client, self.assistant = config, client, assistant
        self.mapper = SessionMapper(config)
        self.ledger = ledger

    def prepare(self, payload: Any) -> tuple[FeishuInbound, SessionBinding] | None:
        if not self.config.enabled:
            return None
        try:
            inbound, message, markers = envelope(payload, self.config)
            binding = self.mapper.authorize(inbound)
            if binding is None or (inbound.chat_type == "group" and not inbound.mentioned):
                return None
            return parse_content(inbound, message, markers, self.config.max_message_chars), binding
        except (ValueError, TypeError, AttributeError):
            return None

    def respond(self, event: FeishuInbound, binding: SessionBinding) -> FeishuReply:
        try:
            images = resolve_images(event, self.client)
        except ValueError:
            return FeishuReply(event.event_id, MEDIA_FAILURE, degraded=True)
        try:
            self.mapper.ensure_session(self.assistant.sessions, binding, event.received_at)
            request = AssistantRequest(
                event.request_id,
                binding.principal_id,
                event.text,
                binding.session_id,
                requested_at=event.received_at,
                images=images,
            )
            return render_reply(self.assistant.handle(request), event.event_id)
        except Exception:
            return FeishuReply(event.event_id, SERVICE_FAILURE, degraded=True)

    def handle(self, payload: Any) -> str:
        prepared = self.prepare(payload)
        if prepared is None:
            return "ignored"
        event, binding = prepared
        return self.process(event, binding)

    def process(self, event: FeishuInbound, binding: SessionBinding) -> str:
        if (
            not self.config.enabled
            or self.mapper.authorize(event) != binding
            or (event.chat_type == "group" and not event.mentioned)
        ):
            if self.ledger is not None:
                self.ledger.discard_payload(event.event_id)
            return "ignored"
        if self.ledger is None:
            # No persistent claim means no model work: production must fail closed.
            return "ledger_unavailable"
        if read_guard(self.ledger.storage.db_path) is not None:
            return "maintenance"
        if self.ledger.should_quarantine(event):
            scope = stable_digest(binding.principal_id, binding.session_id, event.message_id)
            self.ledger.record(event, binding, scope)
            self.ledger.quarantine_payload(event.event_id)
            return "quarantined"
        scope = stable_digest(binding.principal_id, binding.session_id, event.message_id)
        try:
            claim = self.ledger.claim(event.event_id, scope)
            if claim.status == "rejected":
                return "ignored"
            if claim.status == "duplicate_delivered":
                return "already_delivered"
            if claim.status == "quarantined":
                return "quarantined"
            if claim.status == "corrupt":
                return "ledger_unavailable"
            if claim.status == "deliver":
                reply = claim.reply
            elif claim.status == "claimed":
                with self.ledger.heartbeat(event.event_id, claim.owner):
                    reply = self.respond(event, binding)
                    if not self.ledger.save_reply(event.event_id, claim.owner, reply):
                        return "lease_lost"
            else:
                text = (
                    "This event is still being processed."
                    if claim.status == "busy"
                    else SERVICE_FAILURE
                )
                reply = FeishuReply(event.event_id, text, degraded=True)
        except Exception:
            return "ledger_unavailable"
        try:
            if read_guard(self.ledger.storage.db_path) is not None:
                return "maintenance"
            if claim.status in {"claimed", "deliver"}:
                with self.ledger.heartbeat(event.event_id, claim.owner):
                    outcome = self.client.reply_result(
                        event.message_id, reply.text,
                        message_uuid=stable_digest("reply", event.event_id, scope),
                    )
            else:
                outcome = ReplyDelivery(self.client.reply(event.message_id, reply.text))
        except Exception:
            outcome = ReplyDelivery(False, error_code="unavailable")
        if not outcome.delivered:
            if claim.status in {"claimed", "deliver"}:
                self.ledger.mark_delivery_failed(
                    event.event_id, claim.owner, retryable=outcome.retryable,
                    retry_after_seconds=outcome.retry_after_seconds,
                )
            return "send_failed"
        if claim.status in {"claimed", "deliver"} and not self.ledger.mark_delivered(
            event.event_id, claim.owner
        ):
            return "lease_lost"
        return "sent"
