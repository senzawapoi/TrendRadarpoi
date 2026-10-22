"""Tests for bounded, principal-scoped Assistant sessions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from trendradar.ai.models import AssistantReply, TimeRange
from trendradar.ai.session import (
    SessionAccessError,
    SessionExpiredError,
    SessionLimits,
    SessionStore,
)
from trendradar.intelligence.storage import IntelligenceStorage

NOW = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)


def _reply(session_id: str, request_id: str, *, text: str = "answer") -> AssistantReply:
    return AssistantReply(
        request_id=request_id,
        session_id=session_id,
        text=text,
        time_range=TimeRange.previous_days(NOW, 7),
        created_at=NOW,
    )


def test_session_ownership_sliding_ttl_and_aware_time(tmp_path) -> None:
    store = SessionStore(tmp_path / "intelligence.db", limits=SessionLimits(ttl_days=30))
    try:
        session = store.create_session("owner", now=NOW, session_id="session-1")
        with pytest.raises(SessionAccessError):
            store.get_session(session.session_id, "other", now=NOW)
        touched = store.get_session(
            session.session_id,
            "owner",
            now=NOW + timedelta(days=20),
        )
        assert touched.expires_at == NOW + timedelta(days=50)
        with pytest.raises(SessionExpiredError):
            store.get_session(
                session.session_id,
                "owner",
                now=NOW + timedelta(days=50),
            )
        with pytest.raises(ValueError, match="timezone-aware"):
            store.create_session("owner", now=datetime(2026, 9, 4))
    finally:
        store.close()


def test_complete_turn_is_idempotent_and_prunes_complete_turns(tmp_path) -> None:
    store = SessionStore(
        tmp_path / "intelligence.db",
        limits=SessionLimits(max_messages=2, max_history_messages=10),
    )
    try:
        session = store.create_session("owner", now=NOW)
        for index in range(3):
            request_id = f"request-{index}"
            reply = _reply(session.session_id, request_id, text=f"answer-{index}")
            first = store.complete_turn(
                session.session_id,
                "owner",
                request_id,
                f"question-{index}",
                reply,
                now=NOW + timedelta(minutes=index),
            )
            assert store.complete_turn(
                session.session_id,
                "owner",
                request_id,
                f"question-{index}",
                reply,
                now=NOW + timedelta(minutes=index),
            ) == first

        messages = store.load_messages(
            session.session_id,
            "owner",
            now=NOW + timedelta(minutes=3),
        )
        assert [(message.role, message.request_id) for message in messages] == [
            ("user", "request-2"),
            ("assistant", "request-2"),
        ]
    finally:
        store.close()


def test_history_reports_message_and_character_truncation(tmp_path) -> None:
    store = SessionStore(
        tmp_path / "intelligence.db",
        limits=SessionLimits(
            max_messages=20,
            max_history_messages=2,
            max_context_chars=256,
        ),
    )
    try:
        session = store.create_session("owner", now=NOW)
        for index in range(2):
            request_id = f"request-{index}"
            store.complete_turn(
                session.session_id,
                "owner",
                request_id,
                "q" * 200,
                _reply(session.session_id, request_id, text="a" * 200),
                now=NOW + timedelta(minutes=index),
            )

        history = store.load_messages_with_state(
            session.session_id,
            "owner",
            now=NOW + timedelta(minutes=2),
        )
        assert history.truncated is True
        assert [message.role for message in history.messages] == ["user", "assistant"]
        assert {message.request_id for message in history.messages} == {"request-1"}
        assert history.loaded_chars <= 256
        assert history.total_messages == 4
    finally:
        store.close()


def test_turn_transaction_rolls_back_both_messages(tmp_path, monkeypatch) -> None:
    store = SessionStore(tmp_path / "intelligence.db")
    try:
        session = store.create_session("owner", now=NOW)

        def fail_prune(_session_id: str) -> None:
            raise RuntimeError("forced rollback")

        monkeypatch.setattr(store, "_prune", fail_prune)
        with pytest.raises(RuntimeError, match="forced rollback"):
            store.complete_turn(
                session.session_id,
                "owner",
                "request-1",
                "question",
                _reply(session.session_id, "request-1"),
                now=NOW,
            )
        assert store.storage.count("assistant_messages") == 0
    finally:
        store.close()


def test_borrowed_storage_is_not_closed(tmp_path) -> None:
    storage = IntelligenceStorage(tmp_path / "intelligence.db")
    store = SessionStore(storage)
    store.close()
    assert storage.count("assistant_sessions") == 0
    storage.close()


def test_two_session_stores_concurrently_keep_one_request_turn(tmp_path) -> None:
    path = tmp_path / "intelligence.db"
    first = SessionStore(path)
    second = SessionStore(path)
    try:
        session = first.create_session("owner", now=NOW)
        reply = _reply(session.session_id, "request-1")

        def complete(store: SessionStore) -> AssistantReply:
            return store.complete_turn(
                session.session_id,
                "owner",
                "request-1",
                "question",
                reply,
                now=NOW,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(complete, (first, second)))

        assert results == [reply, reply]
        assert first.storage.count("assistant_messages") == 2
    finally:
        first.close()
        second.close()
