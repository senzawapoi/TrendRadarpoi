"""Bounded, principal-scoped Assistant sessions backed by intelligence.db."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from trendradar.ai.models import AssistantMessage, AssistantReply, Citation
from trendradar.intelligence.storage import IntelligenceStorage


class SessionError(RuntimeError):
    """Base error for fail-closed session operations."""


class SessionNotFoundError(SessionError):
    pass


class SessionAccessError(SessionError):
    pass


class SessionExpiredError(SessionError):
    pass


@dataclass(frozen=True, slots=True)
class SessionLimits:
    ttl_days: int = 30
    max_messages: int = 100
    max_history_messages: int = 12
    max_context_chars: int = 24_000
    max_input_chars: int = 8_000
    max_output_chars: int = 12_000

    def __post_init__(self) -> None:
        bounds = {
            "ttl_days": (1, 3650),
            "max_messages": (2, 1000),
            "max_history_messages": (2, 100),
            "max_context_chars": (256, 200_000),
            "max_input_chars": (1, 50_000),
            "max_output_chars": (1, 50_000),
        }
        for name, (minimum, maximum) in bounds.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            object.__setattr__(self, name, max(minimum, min(maximum, value)))


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    principal_id: str
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.session_id or not self.principal_id:
            raise ValueError("session and principal identifiers are required")
        for name in ("created_at", "last_active_at", "expires_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
            object.__setattr__(self, name, value.astimezone(timezone.utc))


@dataclass(frozen=True, slots=True)
class SessionHistory:
    """A complete-turn history selection and whether older data was omitted."""

    messages: tuple[AssistantMessage, ...] = ()
    citations: tuple[Citation, ...] = ()
    truncated: bool = False
    total_messages: int = 0
    loaded_chars: int = 0


def _utc(value: datetime | None, field_name: str = "now") -> datetime:
    timestamp = value or datetime.now(tz=timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return timestamp.astimezone(timezone.utc)


def _identifier(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 256:
        raise ValueError(f"{field_name} is invalid")
    return normalized


class SessionStore:
    """Own session lifecycle and atomic complete-turn persistence."""

    def __init__(
        self,
        storage: IntelligenceStorage | sqlite3.Connection | str | Path,
        *,
        limits: SessionLimits | None = None,
    ) -> None:
        if isinstance(storage, IntelligenceStorage):
            self.storage = storage
            self._owns_storage = False
        elif isinstance(storage, sqlite3.Connection):
            self.storage = IntelligenceStorage.from_connection(storage)
            self._owns_storage = False
        else:
            self.storage = IntelligenceStorage(storage)
            self._owns_storage = True
        self.connection = self.storage.connection
        self.limits = limits or SessionLimits()
        self._lock = threading.RLock()

    def close(self) -> None:
        if self._owns_storage:
            self.storage.close()

    def create_session(
        self,
        principal_id: str,
        *,
        now: datetime | None = None,
        session_id: str | None = None,
    ) -> SessionRecord:
        principal = _identifier(principal_id, "principal_id")
        timestamp = _utc(now)
        identifier = _identifier(session_id, "session_id") if session_id else str(uuid4())
        expiry = timestamp + timedelta(days=self.limits.ttl_days)
        with self._lock, self._transaction():
            self.connection.execute(
                """
                INSERT INTO assistant_sessions
                    (session_id, principal_id, created_at, last_active_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    principal,
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                    expiry.isoformat(),
                ),
            )
        return SessionRecord(identifier, principal, timestamp, timestamp, expiry)

    def get_or_create(
        self,
        principal_id: str,
        session_id: str | None = None,
        *,
        now: datetime | None = None,
    ) -> SessionRecord:
        if not session_id:
            return self.create_session(principal_id, now=now)
        return self.get_session(session_id, principal_id, now=now, touch=True)

    def open_session(self, principal_id: str, session_id: str, *, now: datetime) -> SessionRecord:
        """Explicit transport-owned session creation or expiry renewal, never principal takeover."""
        principal = _identifier(principal_id, "principal_id")
        identifier = _identifier(session_id, "session_id")
        timestamp = _utc(now)
        with self._lock, self._transaction():
            row = self.connection.execute(
                "SELECT * FROM assistant_sessions WHERE session_id = ?", (identifier,)
            ).fetchone()
            if row is not None and row["principal_id"] != principal:
                raise SessionAccessError("session principal mismatch")
            if row is not None and timestamp >= _parse_timestamp(row["expires_at"]):
                self.connection.execute("DELETE FROM assistant_sessions WHERE session_id = ?", (identifier,))
                row = None
            if row is None:
                expiry = timestamp + timedelta(days=self.limits.ttl_days)
                self.connection.execute(
                    "INSERT INTO assistant_sessions VALUES (?, ?, ?, ?, ?)",
                    (identifier, principal, timestamp.isoformat(), timestamp.isoformat(), expiry.isoformat()),
                )
        return self.get_session(identifier, principal, now=timestamp, touch=False)

    def get_session(
        self,
        session_id: str,
        principal_id: str,
        *,
        now: datetime | None = None,
        touch: bool = True,
    ) -> SessionRecord:
        identifier = _identifier(session_id, "session_id")
        principal = _identifier(principal_id, "principal_id")
        timestamp = _utc(now)
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM assistant_sessions WHERE session_id = ?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise SessionNotFoundError("session does not exist")
            if str(row["principal_id"]) != principal:
                raise SessionAccessError("session principal mismatch")
            expires = _parse_timestamp(row["expires_at"])
            if timestamp >= expires:
                raise SessionExpiredError("session has expired")
            last_active = _parse_timestamp(row["last_active_at"])
            if touch:
                expires = timestamp + timedelta(days=self.limits.ttl_days)
                self.connection.execute(
                    """
                    UPDATE assistant_sessions
                    SET last_active_at = ?, expires_at = ?
                    WHERE session_id = ? AND principal_id = ?
                    """,
                    (timestamp.isoformat(), expires.isoformat(), identifier, principal),
                )
                last_active = timestamp
            return SessionRecord(
                session_id=identifier,
                principal_id=principal,
                created_at=_parse_timestamp(row["created_at"]),
                last_active_at=last_active,
                expires_at=expires,
            )

    def get_completed_reply(
        self,
        session_id: str,
        principal_id: str,
        request_id: str,
        *,
        now: datetime | None = None,
    ) -> AssistantReply | None:
        session = self.get_session(session_id, principal_id, now=now, touch=False)
        request = _identifier(request_id, "request_id")
        row = self.connection.execute(
            """
            SELECT metadata_json FROM assistant_messages
            WHERE session_id = ? AND request_id = ? AND role = 'assistant'
            ORDER BY sequence DESC LIMIT 1
            """,
            (session.session_id, request),
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["metadata_json"] or "{}")
            return AssistantReply.from_dict(payload["reply"])
        except (TypeError, KeyError, ValueError, json.JSONDecodeError) as exc:
            raise SessionError("stored Assistant reply is invalid") from exc

    def load_messages(
        self,
        session_id: str,
        principal_id: str,
        *,
        now: datetime | None = None,
    ) -> tuple[AssistantMessage, ...]:
        return self.load_messages_with_state(
            session_id,
            principal_id,
            now=now,
        ).messages

    def load_messages_with_state(
        self,
        session_id: str,
        principal_id: str,
        *,
        now: datetime | None = None,
    ) -> SessionHistory:
        """Load newest complete turns while reporting message/character truncation."""
        session = self.get_session(session_id, principal_id, now=now, touch=False)
        rows = self.connection.execute(
            """
            SELECT sequence, request_id, role, content, created_at, metadata_json
            FROM assistant_messages
            WHERE session_id = ?
            ORDER BY sequence DESC
            """,
            (session.session_id,),
        ).fetchall()
        groups: list[list[sqlite3.Row]] = []
        by_request: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_request.setdefault(str(row["request_id"]), []).append(row)
        for request_rows in by_request.values():
            if any(str(row["role"]) == "user" for row in request_rows) and any(
                str(row["role"]) == "assistant" for row in request_rows
            ):
                groups.append(sorted(request_rows, key=lambda row: int(row["sequence"])))
        groups.sort(key=lambda values: int(values[-1]["sequence"]), reverse=True)
        selected: list[Any] = []
        chars = 0
        complete_message_count = sum(len(group) for group in groups)
        truncated = complete_message_count != len(rows)
        for index, group in enumerate(groups):
            if len(selected) + len(group) > self.limits.max_history_messages:
                truncated = True
                break
            group_chars = sum(len(str(row["content"])) for row in group)
            if selected and chars + group_chars > self.limits.max_context_chars:
                truncated = True
                break
            if not selected and group_chars > self.limits.max_context_chars:
                # Keep both sides of the newest turn.  Truncating each message is
                # preferable to returning an orphaned assistant answer that has no
                # corresponding user question.
                truncated = True
                budget = max(2, self.limits.max_context_chars)
                first = group[0]
                second = group[-1] if len(group) > 1 else None
                if second is None:
                    group = [_row_with_content(first, str(first["content"])[:budget])]
                    group_chars = len(str(group[0]["content"]))
                else:
                    first_budget = max(1, budget // 2)
                    second_budget = max(1, budget - first_budget)
                    group = [
                        _row_with_content(first, str(first["content"])[:first_budget]),
                        _row_with_content(second, str(second["content"])[:second_budget]),
                    ]
                    group_chars = sum(len(str(row["content"])) for row in group)
            selected.extend(group)
            chars += group_chars
            if index + 1 < len(groups) and (
                len(selected) >= self.limits.max_history_messages
                or chars >= self.limits.max_context_chars
            ):
                truncated = True
        selected.sort(key=lambda row: int(row["sequence"]))
        messages = tuple(
            AssistantMessage(
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=_parse_timestamp(row["created_at"]),
                sequence=int(row["sequence"]),
                request_id=str(row["request_id"]),
            )
            for row in selected
        )
        citations: dict[str, Citation] = {}
        for row in selected:
            if str(row["role"]) != "assistant":
                continue
            try:
                payload = json.loads(row["metadata_json"] or "{}")
                stored_reply = AssistantReply.from_dict(payload["reply"])
            except (TypeError, KeyError, ValueError, json.JSONDecodeError):
                continue
            visible_content = str(row["content"])
            for citation in stored_reply.citations:
                if citation.ref in visible_content:
                    citations[citation.ref] = citation
        return SessionHistory(
            messages=messages,
            citations=tuple(citations.values()),
            truncated=truncated or len(messages) < complete_message_count,
            total_messages=len(rows),
            loaded_chars=sum(len(message.content) for message in messages),
        )

    def complete_turn(
        self,
        session_id: str,
        principal_id: str,
        request_id: str,
        user_content: str,
        reply: AssistantReply,
        *,
        now: datetime | None = None,
    ) -> AssistantReply:
        identifier = _identifier(session_id, "session_id")
        principal = _identifier(principal_id, "principal_id")
        request = _identifier(request_id, "request_id")
        if not isinstance(user_content, str) or not user_content.strip():
            raise ValueError("user_content must not be empty")
        if len(user_content.strip()) > self.limits.max_input_chars:
            raise ValueError("user_content exceeds its limit")
        if reply.session_id != identifier or reply.request_id != request:
            raise ValueError("reply/session request identifiers do not match")
        if len(reply.text) > self.limits.max_output_chars:
            raise ValueError("reply exceeds its limit")
        timestamp = _utc(now)
        with self._lock:
            try:
                with self._transaction():
                    self._session_for_update(identifier, principal, timestamp)
                    existing = self._reply_in_transaction(identifier, request)
                    if existing is not None:
                        return existing
                    next_sequence = int(
                        self.connection.execute(
                            "SELECT COALESCE(MAX(sequence), -1) FROM assistant_messages "
                            "WHERE session_id = ?",
                            (identifier,),
                        ).fetchone()[0]
                    ) + 1
                    self.connection.execute(
                        """
                        INSERT INTO assistant_messages
                            (session_id, sequence, request_id, role, content, created_at, metadata_json)
                        VALUES (?, ?, ?, 'user', ?, ?, '{}')
                        """,
                        (identifier, next_sequence, request, user_content.strip(), timestamp.isoformat()),
                    )
                    self.connection.execute(
                        """
                        INSERT INTO assistant_messages
                            (session_id, sequence, request_id, role, content, created_at, metadata_json)
                        VALUES (?, ?, ?, 'assistant', ?, ?, ?)
                        """,
                        (
                            identifier,
                            next_sequence + 1,
                            request,
                            reply.text,
                            reply.created_at.isoformat(),
                            json.dumps({"reply": reply.to_dict()}, ensure_ascii=False, sort_keys=True),
                        ),
                    )
                    self._prune(identifier)
                    expiry = timestamp + timedelta(days=self.limits.ttl_days)
                    self.connection.execute(
                        "UPDATE assistant_sessions SET last_active_at = ?, expires_at = ? "
                        "WHERE session_id = ?",
                        (timestamp.isoformat(), expiry.isoformat(), identifier),
                    )
                    return reply
            except sqlite3.IntegrityError:
                existing = self._reply_in_transaction(identifier, request)
                if existing is not None:
                    return existing
                raise

    def list_messages(
        self,
        session_id: str,
        principal_id: str,
        **kwargs: Any,
    ) -> tuple[AssistantMessage, ...]:
        """Compatibility alias for callers that use list terminology."""
        return self.load_messages(session_id, principal_id, **kwargs)

    @contextmanager
    def _transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    def _session_for_update(
        self,
        session_id: str,
        principal_id: str,
        now: datetime,
    ) -> SessionRecord:
        row = self.connection.execute(
            "SELECT * FROM assistant_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise SessionNotFoundError("session does not exist")
        if str(row["principal_id"]) != principal_id:
            raise SessionAccessError("session principal mismatch")
        if now >= _parse_timestamp(row["expires_at"]):
            raise SessionExpiredError("session has expired")
        return SessionRecord(
            session_id=session_id,
            principal_id=principal_id,
            created_at=_parse_timestamp(row["created_at"]),
            last_active_at=_parse_timestamp(row["last_active_at"]),
            expires_at=_parse_timestamp(row["expires_at"]),
        )

    def _reply_in_transaction(self, session_id: str, request_id: str) -> AssistantReply | None:
        row = self.connection.execute(
            "SELECT metadata_json FROM assistant_messages "
            "WHERE session_id = ? AND request_id = ? AND role = 'assistant' "
            "ORDER BY sequence DESC LIMIT 1",
            (session_id, request_id),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["metadata_json"] or "{}")
        return AssistantReply.from_dict(payload["reply"])

    def _prune(self, session_id: str) -> None:
        count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM assistant_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
        )
        while count > self.limits.max_messages:
            row = self.connection.execute(
                "SELECT request_id FROM assistant_messages WHERE session_id = ? "
                "ORDER BY sequence LIMIT 1",
                (session_id,),
            ).fetchone()
            if row is None:
                break
            request_id = str(row[0])
            self.connection.execute(
                "DELETE FROM assistant_messages WHERE session_id = ? AND request_id = ?",
                (session_id, request_id),
            )
            count = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM assistant_messages WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
            )


def _parse_timestamp(value: Any) -> datetime:
    try:
        timestamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise SessionError("stored session timestamp is invalid") from exc
    return _utc(timestamp, "stored timestamp")


def _row_with_content(row: sqlite3.Row, content: str) -> dict[str, Any]:
    """Copy a SQLite row while replacing only its bounded message body."""
    copied = dict(row)
    copied["content"] = content
    return copied


AssistantSessionStore = SessionStore


__all__ = [
    "AssistantSessionStore",
    "SessionAccessError",
    "SessionError",
    "SessionExpiredError",
    "SessionHistory",
    "SessionLimits",
    "SessionNotFoundError",
    "SessionRecord",
    "SessionStore",
]
