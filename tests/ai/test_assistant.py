"""Tests for the provider-neutral local Assistant flow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from trendradar.ai.assistant import AssistantLimits, AssistantService
from trendradar.ai.client import GeminiResult
from trendradar.ai.errors import GeminiTimeoutError
from trendradar.ai.models import AssistantRequest
from trendradar.ai.retrieval import RetrievalLimits
from trendradar.ai.session import SessionAccessError, SessionLimits

NOW = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)


class FakeGemini:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def chat(self, messages: Any, **kwargs: Any) -> Any:
        self.calls.append((messages, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_no_gemini_returns_and_persists_deterministic_local_evidence(
    seeded_intelligence,
) -> None:
    service = AssistantService(seeded_intelligence.storage, gemini_client=None)
    request = AssistantRequest("request-1", "owner", "Alpha AI", requested_at=NOW)

    reply = service.handle(request)
    history = service.sessions.load_messages(
        reply.session_id,
        "owner",
        now=NOW,
    )

    assert reply.degraded is True
    assert "Gemini" in reply.degraded_reason
    assert "Alpha AI model released" in reply.text
    assert reply.time_range.start == NOW - timedelta(days=7)
    assert reply.time_range.end == NOW
    assert any(citation.story_id == seeded_intelligence.story.id for citation in reply.citations)
    assert [message.role for message in history] == ["user", "assistant"]
    service.close()
    assert seeded_intelligence.storage.count("assistant_messages") == 2


def test_model_citations_are_validated_and_duplicate_request_is_idempotent(
    seeded_intelligence,
) -> None:
    story_ref = f"story:{seeded_intelligence.story.id}"
    gemini = FakeGemini(
        GeminiResult(
            text=f"Grounded [{story_ref}], forged [story:not-real].",
            model="fake",
        )
    )
    service = AssistantService(seeded_intelligence.storage, gemini_client=gemini)
    session = service.create_session("owner", now=NOW)
    request = AssistantRequest(
        "request-1",
        "owner",
        "Alpha AI",
        session_id=session.session_id,
        requested_at=NOW,
    )

    first = service.handle(request)
    second = service.handle(request)

    assert second == first
    assert len(gemini.calls) == 1
    assert story_ref in first.text
    assert "story:not-real" not in first.text
    assert [citation.ref for citation in first.citations] == [story_ref]
    assert first.degraded is True
    assert "ungrounded" in first.degraded_reason
    assert seeded_intelligence.storage.count("assistant_messages") == 2


def test_follow_up_accepts_server_validated_citations_visible_in_history(
    seeded_intelligence,
) -> None:
    story_ref = f"story:{seeded_intelligence.story.id}"
    gemini = FakeGemini(
        GeminiResult(text=f"Budget is 10 [{story_ref}].", model="fake"),
        GeminiResult(text=f"The total is 30 [{story_ref}].", model="fake"),
    )
    service = AssistantService(seeded_intelligence.storage, gemini_client=gemini)
    session = service.create_session("owner", now=NOW)

    first = service.handle(
        AssistantRequest(
            "request-1",
            "owner",
            "Alpha AI",
            session_id=session.session_id,
            requested_at=NOW,
        )
    )
    follow_up = service.handle(
        AssistantRequest(
            "request-2",
            "owner",
            "calculate the previous budget",
            session_id=session.session_id,
            requested_at=NOW + timedelta(minutes=1),
        )
    )

    assert first.degraded is False
    assert follow_up.degraded is False
    assert [citation.ref for citation in follow_up.citations] == [story_ref]
    assert len(gemini.calls) == 2


def test_invalid_citation_cleanup_removes_empty_brackets(seeded_intelligence) -> None:
    gemini = FakeGemini(
        GeminiResult(
            text="Budget is 10 [story:not-real, observation:not-real].",
            model="fake",
        )
    )
    service = AssistantService(seeded_intelligence.storage, gemini_client=gemini)

    reply = service.handle(
        AssistantRequest("request-1", "owner", "Alpha AI", requested_at=NOW)
    )

    assert reply.text == "Budget is 10."
    assert reply.degraded is True
    assert "ungrounded" in reply.degraded_reason


def test_provider_failure_degrades_without_losing_the_turn(seeded_intelligence) -> None:
    gemini = FakeGemini(GeminiTimeoutError())
    service = AssistantService(seeded_intelligence.storage, gemini_client=gemini)

    reply = service.handle(
        AssistantRequest("request-1", "owner", "Alpha", requested_at=NOW)
    )

    assert reply.degraded is True
    assert "timed out" in reply.degraded_reason
    assert "private" not in reply.degraded_reason
    assert seeded_intelligence.storage.count("assistant_messages") == 2


def test_history_truncation_and_configured_default_lookback_are_reported(
    seeded_intelligence,
) -> None:
    limits = AssistantLimits(
        session=SessionLimits(max_history_messages=2, max_messages=20),
        retrieval=RetrievalLimits(),
        default_lookback_days=3,
    )
    service = AssistantService(
        seeded_intelligence.storage,
        gemini_client=None,
        limits=limits,
    )
    session = service.create_session("owner", now=NOW)
    for index in range(3):
        reply = service.handle(
            AssistantRequest(
                f"request-{index}",
                "owner",
                "Alpha",
                session_id=session.session_id,
                requested_at=NOW + timedelta(minutes=index),
            )
        )

    assert reply.truncation.history is True
    assert reply.time_range.end == NOW + timedelta(minutes=2)
    assert reply.time_range.start == reply.time_range.end - timedelta(days=3)


def test_cross_principal_session_fails_closed(seeded_intelligence) -> None:
    service = AssistantService(seeded_intelligence.storage)
    session = service.create_session("owner", now=NOW)

    with pytest.raises(SessionAccessError):
        service.handle(
            AssistantRequest(
                "request-1",
                "other",
                "Alpha",
                session_id=session.session_id,
                requested_at=NOW,
            )
        )


def test_retrieval_failure_does_not_refetch_or_escape(seeded_intelligence) -> None:
    class FailedRetriever:
        def __init__(self) -> None:
            self.calls = 0

        def retrieve(self, *_args: Any, **_kwargs: Any) -> None:
            self.calls += 1
            raise RuntimeError("private database detail")

    retriever = FailedRetriever()
    service = AssistantService(
        seeded_intelligence.storage,
        retriever=retriever,
        gemini_client=None,
    )

    reply = service.handle(
        AssistantRequest("request-1", "owner", "Alpha", requested_at=NOW)
    )

    assert retriever.calls == 1
    assert reply.degraded is True
    assert "private database detail" not in reply.text
    assert reply.truncation.stories is True
    assert reply.truncation.items is True


def test_configured_input_limit_is_checked_before_session_or_model_call(
    seeded_intelligence,
) -> None:
    gemini = FakeGemini(GeminiResult(text="unused", model="fake"))
    service = AssistantService(
        seeded_intelligence.storage,
        gemini_client=gemini,
        limits=AssistantLimits.from_mapping({"max_input_chars": 3}),
    )

    with pytest.raises(ValueError, match="configured Assistant input limit"):
        service.handle(
            AssistantRequest("request-1", "owner", "four", requested_at=NOW)
        )

    assert gemini.calls == []
    assert seeded_intelligence.storage.count("assistant_sessions") == 0


def test_mapping_request_rejects_non_datetime_timestamp(seeded_intelligence) -> None:
    service = AssistantService(seeded_intelligence.storage)

    with pytest.raises(ValueError, match="requested_at must be a datetime"):
        service.handle(
            {
                "request_id": "request-1",
                "principal_id": "owner",
                "text": "Alpha",
                "requested_at": "2026-09-04T12:00:00Z",
            }
        )
