"""Durable event claims, bounded recovery payloads and fenced delivery retry."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops.maintenance import read_recovery_cutover

from .models import FeishuInbound, FeishuReply, sanitize_id
from .session import SessionBinding


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ledger timestamp must be aware")
    return value.astimezone(timezone.utc).isoformat()


@contextmanager
def lease_heartbeat(renew, seconds: int):
    stop = threading.Event()

    def run():
        while not stop.wait(seconds / 3):
            try:
                if not renew():
                    return
            except Exception:
                return

    thread = threading.Thread(target=run, name="feishu-lease", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


@dataclass(frozen=True)
class EventClaim:
    status: str
    owner: str = ""
    reply: FeishuReply | None = None


class EventLedger:
    """A dedicated connection allows heartbeat renewal during an Assistant call."""

    def __init__(
        self,
        path: str | Path,
        *,
        lease_seconds: int = 120,
        max_pending_events: int = 32,
        delivery_retry_base_seconds: int = 0,
        delivery_retry_max_seconds: int = 300,
        storage: IntelligenceStorage | None = None,
        require_existing: bool = False,
        synchronous: str = "FULL",
        recovery_cutover_at: datetime | None = None,
        clock=utc_now,
    ):
        self.storage = storage or (
            IntelligenceStorage.open_existing(path, synchronous=synchronous)
            if require_existing
            else IntelligenceStorage(path, synchronous=synchronous)
        )
        self._owns_storage = storage is None
        try:
            self.recovery_cutover_at = recovery_cutover_at or read_recovery_cutover(path)
        except Exception:
            if self._owns_storage:
                self.storage.close()
            raise
        self.lock = threading.RLock()
        self.lease_seconds = max(10, min(3600, lease_seconds))
        self.max_pending_events = max(1, min(1000, int(max_pending_events)))
        self.delivery_retry_base_seconds = max(0, min(300, int(delivery_retry_base_seconds)))
        self.delivery_retry_max_seconds = max(
            self.delivery_retry_base_seconds,
            min(3600, int(delivery_retry_max_seconds)),
        )
        self.clock = clock

    def close(self):
        if self._owns_storage:
            self.storage.close()

    def claim(self, event_id: str, scope: str) -> EventClaim:
        sanitize_id(event_id)
        sanitize_id(scope)
        now = self.clock()
        with self.lock, self.storage.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM feishu_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if row is not None:
                if row["scope"] != scope:
                    return EventClaim("rejected")
                if (
                    row["status"] == "failed" and row["event_json"] is not None
                    and row["attempts"] >= 3 and row["delivery_attempts"] >= 3
                ):
                    return EventClaim("quarantined")
                if row["status"] == "completed":
                    try:
                        reply = FeishuReply.from_dict(json.loads(row["reply_json"]))
                        if reply.event_id != event_id:
                            raise ValueError("reply/event mismatch")
                    except (ValueError, TypeError, AttributeError):
                        return EventClaim("corrupt")
                    # A completed event was already delivered.  Keep the
                    # persisted reply for audit/recovery, but never send it
                    # again when the provider redelivers the same event_id.
                    return EventClaim("duplicate_delivered")
                if row["status"] == "failed" and row["reply_json"]:
                    if row["lease_until"] > stamp(now):
                        return EventClaim("busy")
                    if row["delivery_attempts"] >= 3:
                        return EventClaim("exhausted")
                    try:
                        reply = FeishuReply.from_dict(json.loads(row["reply_json"]))
                        if reply.event_id != event_id:
                            raise ValueError("reply/event mismatch")
                    except (ValueError, TypeError, AttributeError):
                        return EventClaim("corrupt")
                    owner = uuid4().hex
                    connection.execute(
                        """UPDATE feishu_events SET owner=?, lease_until=?,
                           delivery_attempts=delivery_attempts+1, updated_at=?
                           WHERE event_id=? AND status='failed'""",
                        (owner, stamp(now + timedelta(seconds=self.lease_seconds)),
                         stamp(now), event_id),
                    )
                    return EventClaim("deliver", owner, reply)
                if row["status"] == "processing" and row["lease_until"] > stamp(now):
                    return EventClaim("busy")
                if row["attempts"] >= 3:
                    return EventClaim("exhausted")
            owner = uuid4().hex
            connection.execute(
                """INSERT INTO feishu_events
                   (event_id, scope, status, owner, attempts, lease_until, updated_at)
                   VALUES (?, ?, 'processing', ?, 1, ?, ?)
                   ON CONFLICT(event_id) DO UPDATE SET status='processing', owner=excluded.owner,
                   attempts=feishu_events.attempts+1, lease_until=excluded.lease_until,
                   updated_at=excluded.updated_at""",
                (
                    event_id,
                    scope,
                    owner,
                    stamp(now + timedelta(seconds=self.lease_seconds)),
                    stamp(now),
                ),
            )
            return EventClaim("claimed", owner)

    def record(self, event: FeishuInbound, binding: SessionBinding, scope: str) -> bool:
        """Persist a prepared event before accepting it into the in-memory queue."""
        sanitize_id(scope)
        event_json = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"))
        binding_json = json.dumps({
            "principal_id": binding.principal_id,
            "session_id": binding.session_id,
            "identity_field": binding.identity_field,
        }, ensure_ascii=False, separators=(",", ":"))
        now = stamp(self.clock())
        with self.lock, self.storage.transaction() as connection:
            row = connection.execute(
                "SELECT scope FROM feishu_events WHERE event_id=?", (event.event_id,)
            ).fetchone()
            if row is not None:
                if row["scope"] != scope:
                    raise ValueError("event scope mismatch")
                return False
            quarantined = self.should_quarantine(event)
            pending = connection.execute(
                """SELECT COUNT(*) FROM feishu_events
                   WHERE event_json IS NOT NULL AND (
                         (status='processing' AND event_json IS NOT NULL)
                      OR (status='failed' AND reply_json IS NULL AND attempts < 3)
                      OR (status='failed' AND reply_json IS NOT NULL
                          AND delivery_attempts < 3)
                   )"""
            ).fetchone()[0]
            if not quarantined and int(pending) >= self.max_pending_events:
                raise OverflowError("durable event queue is full")
            connection.execute(
                """INSERT INTO feishu_events
                   (event_id, scope, status, owner, attempts, lease_until, updated_at,
                    event_json, binding_json)
                   VALUES (?, ?, 'processing', '', 0, ?, ?, ?, ?)""",
                (event.event_id, scope, now, now, event_json, binding_json),
            )
            if quarantined:
                connection.execute(
                    "UPDATE feishu_events SET status='failed', attempts=3, delivery_attempts=3 "
                    "WHERE event_id=?", (event.event_id,),
                )
            return True

    def should_quarantine(self, event: FeishuInbound) -> bool:
        cutoff = self.recovery_cutover_at
        return cutoff is not None and (
            event.created_at is None or event.created_at < cutoff
        )

    def pending_events(
        self, *, recover: bool = True, limit: int | None = None
    ) -> list[tuple[FeishuInbound, SessionBinding]]:
        """Load durable events that still need processing or reply delivery."""
        now = stamp(self.clock())
        if limit is not None and (isinstance(limit, bool) or not 1 <= limit <= 1000):
            raise ValueError("invalid pending event limit")
        with self.lock, self.storage.transaction() as connection:
            if recover:
                # Reclaim only expired work. A live retry lease is a deliberate
                # backoff and must not be stolen by a startup scan.
                connection.execute(
                    """UPDATE feishu_events SET owner='', lease_until=?, updated_at=?
                       WHERE status IN ('processing', 'failed')
                         AND event_json IS NOT NULL AND lease_until <= ?""",
                    (now, now, now),
                )
                # A processing lease that already consumed the final attempt is
                # terminal; discard its recovery payload instead of polling it forever.
                connection.execute(
                    """UPDATE feishu_events SET status='failed', owner='',
                       event_json=NULL, binding_json=NULL, updated_at=?
                       WHERE status='processing' AND attempts >= 3
                       AND event_json IS NOT NULL AND lease_until <= ?""",
                    (now, now),
                )
            query = """SELECT event_id, event_json, binding_json FROM feishu_events
                   WHERE event_json IS NOT NULL
                     AND (
                         (status='failed' AND reply_json IS NOT NULL
                          AND delivery_attempts < 3 AND lease_until <= ?)
                         OR ((status='processing' OR status='failed')
                             AND reply_json IS NULL AND lease_until <= ? AND attempts < 3)
                     )
                   ORDER BY updated_at, event_id"""
            params: list[object] = [now, now]
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)
            rows = connection.execute(query, params).fetchall()
        pending = []
        for row in rows:
            try:
                raw_event = json.loads(row["event_json"] or "{}")
                event = FeishuInbound.from_dict(raw_event)
                if event.event_id != row["event_id"]:
                    raise ValueError("durable event id mismatch")
                raw_binding = json.loads(row["binding_json"] or "{}")
                binding = SessionBinding(
                    raw_binding["principal_id"], raw_binding["session_id"],
                    raw_binding["identity_field"],
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                self.discard_payload(row["event_id"])
                continue
            if self.should_quarantine(event):
                self.quarantine_payload(event.event_id)
                continue
            pending.append((event, binding))
        return pending

    def quarantine_payload(self, event_id: str) -> bool:
        """Retain an old/unknown event as evidence without allowing auto-replay."""
        sanitize_id(event_id)
        with self.lock, self.storage.transaction() as connection:
            return (
                connection.execute(
                    """UPDATE feishu_events SET status='failed', owner='', attempts=3,
                       delivery_attempts=3, lease_until=?, updated_at=?
                       WHERE event_id=? AND event_json IS NOT NULL""",
                    (stamp(self.clock()), stamp(self.clock()), event_id),
                ).rowcount
                == 1
            )

    def discard_payload(self, event_id: str, scope: str | None = None) -> bool:
        """End work that can no longer be safely recovered without retaining its payload."""
        sanitize_id(event_id)
        with self.lock, self.storage.transaction() as connection:
            where = "event_id=? AND status IN ('processing', 'failed') AND event_json IS NOT NULL"
            params: list[object] = [event_id]
            if scope is not None:
                sanitize_id(scope)
                where += " AND scope=?"
                params.append(scope)
            return (
                connection.execute(
                    """UPDATE feishu_events SET status='failed', owner='', attempts=3,
                       delivery_attempts=3, lease_until=?, updated_at=?,
                       event_json=NULL, binding_json=NULL, reply_json=NULL
                       WHERE """ + where,
                    [stamp(self.clock()), stamp(self.clock()), *params],
                ).rowcount
                == 1
            )

    def renew(self, event_id: str, owner: str) -> bool:
        now = self.clock()
        with self.lock:
            return (
                self.storage.connection.execute(
                    "UPDATE feishu_events SET lease_until=?, updated_at=? "
                    "WHERE event_id=? AND owner=? AND "
                    "(status='processing' OR (status='failed' AND reply_json IS NOT NULL))",
                    (
                        stamp(now + timedelta(seconds=self.lease_seconds)),
                        stamp(now),
                        event_id,
                        owner,
                    ),
                ).rowcount
                == 1
            )

    @contextmanager
    def heartbeat(self, event_id: str, owner: str):
        with lease_heartbeat(lambda: self.renew(event_id, owner), self.lease_seconds):
            yield

    def complete(self, event_id: str, owner: str, reply: FeishuReply) -> bool:
        if reply.event_id != event_id:
            raise ValueError("reply/event mismatch")
        payload = json.dumps(reply.to_dict(), ensure_ascii=False)
        with self.lock, self.storage.transaction() as connection:
            return (
                connection.execute(
                    "UPDATE feishu_events SET status='completed', reply_json=?, updated_at=? "
                    "WHERE event_id=? AND owner=? AND status='processing'",
                    (payload, stamp(self.clock()), event_id, owner),
                ).rowcount
                == 1
            )

    def save_reply(self, event_id: str, owner: str, reply: FeishuReply) -> bool:
        """Durably save a generated reply before attempting provider delivery."""
        if reply.event_id != event_id:
            raise ValueError("reply/event mismatch")
        payload = json.dumps(reply.to_dict(), ensure_ascii=False)
        with self.lock, self.storage.transaction() as connection:
            return (
                connection.execute(
                    "UPDATE feishu_events SET status='failed', reply_json=?, "
                    "delivery_attempts=1, updated_at=? "
                    "WHERE event_id=? AND owner=? AND status='processing'",
                    (payload, stamp(self.clock()), event_id, owner),
                ).rowcount
                == 1
            )

    def mark_delivered(self, event_id: str, owner: str) -> bool:
        with self.lock, self.storage.transaction() as connection:
            return (
                connection.execute(
                    "UPDATE feishu_events SET status='completed', owner='', lease_until=?, "
                    "event_json=NULL, binding_json=NULL, updated_at=? "
                    "WHERE event_id=? AND owner=? AND status='failed'",
                    (stamp(self.clock()), stamp(self.clock()), event_id, owner),
                ).rowcount
                == 1
            )

    def mark_delivery_failed(
        self, event_id: str, owner: str, *, retryable: bool = True,
        retry_after_seconds: int = 0,
    ) -> bool:
        with self.lock, self.storage.transaction() as connection:
            row = connection.execute(
                "SELECT delivery_attempts FROM feishu_events "
                "WHERE event_id=? AND owner=? AND status='failed'",
                (event_id, owner),
            ).fetchone()
            if row is None:
                return False
            attempts = int(row["delivery_attempts"])
            delay = min(
                self.delivery_retry_max_seconds,
                self.delivery_retry_base_seconds * (2 ** max(0, attempts - 1)),
            )
            delay = max(delay, max(0, min(3600, retry_after_seconds)))
            now = self.clock()
            terminal = attempts >= 3 or not retryable
            return (
                connection.execute(
                    """UPDATE feishu_events SET owner='', lease_until=?,
                       delivery_attempts=CASE WHEN ? THEN 3 ELSE delivery_attempts END,
                       event_json=CASE WHEN ? THEN NULL ELSE event_json END,
                       binding_json=CASE WHEN ? THEN NULL ELSE binding_json END,
                       updated_at=?
                       WHERE event_id=? AND owner=? AND status='failed'""",
                    (
                        stamp(now + timedelta(seconds=delay)),
                        terminal,
                        terminal,
                        terminal,
                        stamp(now),
                        event_id,
                        owner,
                    ),
                ).rowcount
                == 1
            )

    def fail(self, event_id: str, owner: str) -> None:
        with self.lock, self.storage.transaction() as connection:
            row = connection.execute(
                "SELECT attempts FROM feishu_events WHERE event_id=? AND owner=? "
                "AND status='processing'", (event_id, owner)
            ).fetchone()
            if row is None:
                return
            terminal = int(row["attempts"]) >= 3
            connection.execute(
                """UPDATE feishu_events SET status='failed', owner='', lease_until=?,
                   event_json=CASE WHEN ? THEN NULL ELSE event_json END,
                   binding_json=CASE WHEN ? THEN NULL ELSE binding_json END,
                   updated_at=? WHERE event_id=? AND owner=? AND status='processing'""",
                (stamp(self.clock()), terminal, terminal, stamp(self.clock()), event_id, owner),
            )
