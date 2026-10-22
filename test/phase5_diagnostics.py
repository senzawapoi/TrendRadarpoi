"""Opt-in, metadata-only diagnostics for the isolated local Lark UAT runner."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trendradar.ai.assistant import AssistantService
from trendradar.ai.client import GeminiClient
from trendradar.integrations.feishu.handler import FeishuHandler, _get


def _stdout(record):
    print("UAT " + json.dumps(record, sort_keys=True), flush=True)


@contextmanager
def diagnostics(sink=_stdout):
    """Observe existing calls once; never log payloads, raw IDs, or exception text."""
    key = secrets.token_bytes(32)
    current = ContextVar("uat_event", default=None)
    write_lock = threading.Lock()
    prepare, process = FeishuHandler.prepare, FeishuHandler.process
    handle = AssistantService.handle
    generate, bound = GeminiClient._generate, GeminiClient._bound_messages

    def token(event_id):
        return hmac.new(key, event_id.encode("utf-8"), hashlib.sha256).hexdigest()[:24]

    def emit(stage, event_token=None, **fields):
        state = current.get()
        record = {
            "stage": stage,
            "utc": datetime.now(timezone.utc).isoformat(),
            "event_token": event_token or (state["token"] if state else None),
            **fields,
        }
        try:
            with write_lock:
                sink(record)
        except Exception:
            # Diagnostic output must not change authorization, retries or delivery.
            pass

    def traced_prepare(self, payload):
        result = prepare(self, payload)
        if result is None:
            emit("ignored")
            return None
        event, _ = result
        message = _get(_get(payload, "event"), "message")
        kind = _get(message, "message_type")
        emit(
            "inbound", token(event.event_id),
            message_type=kind if kind in {"post", "image", "text"} else "other",
            text_chars=len(event.text), media_count=len(event.media),
        )
        return result

    def traced_process(self, event, binding):
        state = {"token": token(event.event_id), "calls": 0}
        context_token = current.set(state)
        try:
            result = process(self, event, binding)
            allowed = {
                "sent", "send_failed", "ignored", "ledger_unavailable", "lease_lost"
            }
            emit("delivery", outcome=result if result in allowed else "other",
                 gemini_calls=state["calls"])
            return result
        finally:
            current.reset(context_token)

    def traced_handle(self, request, *args, **kwargs):
        if current.get() is not None:
            emit("assistant_input", text_chars=len(request.text),
                 image_count=len(request.images),
                 image_bytes=sum(len(image.data) for image in request.images))
        result = handle(self, request, *args, **kwargs)
        if current.get() is not None:
            emit("assistant_result", degraded=bool(result.degraded),
                 citation_count=len(result.citations))
        return result

    def traced_bound(self, messages):
        result = bound(self, messages)
        state = current.get()
        if state is not None:
            images = [image for message in result for image in message.images]
            user = next((message for message in reversed(result) if message.role == "user"), None)
            emit("gemini_input", call=state["calls"], image_count=len(images),
                 image_bytes=sum(len(image.data) for image in images),
                 last_user_chars=len(user.content) if user else 0)
        return result

    def traced_generate(self, *args, **kwargs):
        state = current.get()
        if state is None:
            return generate(self, *args, **kwargs)
        state["calls"] += 1
        try:
            result = generate(self, *args, **kwargs)
        except Exception:
            emit("gemini_result", call=state["calls"], outcome="error")
            raise
        finish = result.finish_reason
        allowed_finish = {"STOP", "MAX_TOKENS", "SAFETY", "RECITATION", "OTHER"}
        usage = result.usage
        emit(
            "gemini_result", call=state["calls"], outcome="success",
            model=(result.model if result.model == "gemini-3.5-flash-lite" else "other"),
            finish_reason=finish if finish in allowed_finish else "other",
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
            tool_call_count=len(result.tool_calls),
        )
        return result

    with ExitStack() as stack:
        for target, name, replacement in (
            (FeishuHandler, "prepare", traced_prepare),
            (FeishuHandler, "process", traced_process),
            (AssistantService, "handle", traced_handle),
            (GeminiClient, "_bound_messages", traced_bound),
            (GeminiClient, "_generate", traced_generate),
        ):
            stack.enter_context(patch.object(target, name, replacement))
        yield


def main():
    expected = Path(__file__).resolve().parent / "runtime" / "intelligence.db"
    if Path(os.environ.get("INTELLIGENCE_DB_PATH", "")).resolve() != expected.resolve():
        print("Diagnostics require the isolated test/runtime/intelligence.db.")
        return 2
    from trendradar.integrations.lark.__main__ import main as run

    with diagnostics():
        return run()


if __name__ == "__main__":
    raise SystemExit(main())
