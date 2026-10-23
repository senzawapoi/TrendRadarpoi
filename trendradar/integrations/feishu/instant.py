"""Durable target/Story registration and frozen instant delivery batches."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops.maintenance import read_guard, read_recovery_cutover

from .config import FeishuConfig
from .ledger import lease_heartbeat, stamp
from .models import stable_digest
from .post import message_content


def _validate_chunks(chunks: Any) -> None:
    if not isinstance(chunks, list) or not 1 <= len(chunks) <= 100:
        raise ValueError("invalid instant delivery payload")
    for chunk in chunks:
        message_content(chunk)


class InstantDeliveryScheduler:
    def __init__(
        self, config: FeishuConfig, storage: IntelligenceStorage, delivery, client,
        *, lock: threading.RLock, clock: Callable[[], datetime],
    ) -> None:
        self.config, self.storage, self.delivery, self.client = config, storage, delivery, client
        self.lock, self.clock = lock, clock
        self.target_key = stable_digest(config.delivery_target)

    def _quarantine(
        self, connection: sqlite3.Connection, cutoff: datetime | None, now: datetime,
    ) -> int:
        if cutoff is None:
            return 0
        changed = connection.execute(
            """UPDATE lark_instant_batches SET status='quarantined', last_error='restore_cutover',
                      updated_at=?
               WHERE target_key=? AND status IN ('processing', 'failed')
                 AND first_persisted_at<=?""",
            (stamp(now), self.target_key, stamp(cutoff)),
        ).rowcount
        connection.execute(
            """UPDATE lark_story_deliveries SET status='quarantined'
               WHERE target_key=? AND delivery_key IN (
                   SELECT delivery_key FROM lark_instant_batches WHERE status='quarantined'
               )""",
            (self.target_key,),
        )
        # Includes overflow that had not yet been assigned to a batch at restore time.
        changed += connection.execute(
            """INSERT INTO lark_story_deliveries
                   (target_key, story_id, first_persisted_at, registered_at, status)
               SELECT ?, s.id, s.created_at, ?, 'quarantined' FROM stories AS s
               WHERE s.created_at<=? AND NOT EXISTS (
                   SELECT 1 FROM lark_story_deliveries AS d
                   WHERE d.target_key=? AND d.story_id=s.id
               )""",
            (self.target_key, stamp(now), stamp(cutoff), self.target_key),
        ).rowcount
        return changed

    def _claim(self, now: datetime) -> tuple[str, sqlite3.Row | None]:
        owner = uuid4().hex
        with self.lock, self.storage.transaction() as connection:
            if read_guard(self.storage.db_path) is not None:
                return "maintenance", None
            changed = self._quarantine(
                connection, read_recovery_cutover(self.storage.db_path), now
            )
            row = connection.execute(
                """SELECT * FROM lark_instant_batches
                   WHERE target_key=? AND status IN ('processing', 'failed')
                   ORDER BY created_at, delivery_key LIMIT 1""",
                (self.target_key,),
            ).fetchone()
            lease = stamp(now + timedelta(seconds=self.config.event_lease_seconds))
            if row:
                if row["status"] == "processing" and row["lease_until"] > stamp(now):
                    return "already_claimed", None
                key = row["delivery_key"]
                connection.execute(
                    """UPDATE lark_instant_batches SET status='processing', owner=?,
                              lease_until=?, updated_at=?, attempts=attempts+1
                       WHERE delivery_key=?""",
                    (owner, lease, stamp(now), key),
                )
            else:
                rows = connection.execute(
                    """SELECT s.* FROM stories AS s WHERE NOT EXISTS (
                           SELECT 1 FROM lark_story_deliveries AS d
                           WHERE d.target_key=? AND d.story_id=s.id
                       ) ORDER BY s.created_at, s.id LIMIT ?""",
                    (self.target_key, min(20, self.config.delivery_max_stories)),
                ).fetchall()
                if not rows:
                    return "quarantined" if changed else "empty", None
                stories = [self.storage.get_story(row["id"]) for row in rows]
                # Local bounded rendering and registration share one write transaction.
                # No sender/provider runs until the entire snapshot is committed.
                chunks = list(self.delivery.prepare_stories(now, stories))
                _validate_chunks(chunks)
                key = stable_digest("instant", self.target_key, *(row["id"] for row in rows))
                connection.execute(
                    """INSERT INTO lark_instant_batches
                           (delivery_key, target_key, status, owner, lease_until,
                            first_persisted_at, created_at, updated_at, chunks_json)
                       VALUES (?, ?, 'processing', ?, ?, ?, ?, ?, ?)""",
                    (key, self.target_key, owner, lease, rows[0]["created_at"],
                     stamp(now), stamp(now), json.dumps(chunks, ensure_ascii=False)),
                )
                connection.executemany(
                    """INSERT INTO lark_story_deliveries
                           (target_key, story_id, first_persisted_at, registered_at,
                            delivery_key, status)
                       VALUES (?, ?, ?, ?, ?, 'registered')""",
                    [(self.target_key, row["id"], row["created_at"], stamp(now), key) for row in rows],
                )
            return "claimed", connection.execute(
                "SELECT * FROM lark_instant_batches WHERE delivery_key=?", (key,)
            ).fetchone()

    def _update(self, key: str, owner: str, sql: str, args: tuple = ()) -> bool:
        now = stamp(self.clock())
        with self.lock:
            return self.storage.connection.execute(
                "UPDATE lark_instant_batches SET " + sql + ", updated_at=? "
                "WHERE delivery_key=? AND owner=? AND status='processing' AND lease_until>?",
                (*args, now, key, owner, now),
            ).rowcount == 1

    def _renew(self, key: str, owner: str) -> bool:
        return self._update(
            key, owner, "lease_until=?",
            (stamp(self.clock() + timedelta(seconds=self.config.event_lease_seconds)),),
        )

    def _boundary(self, row: sqlite3.Row) -> str | None:
        if read_guard(self.storage.db_path) is not None:
            return "maintenance"
        cutoff = read_recovery_cutover(self.storage.db_path)
        if cutoff is not None and row["first_persisted_at"] <= stamp(cutoff):
            with self.lock, self.storage.transaction() as connection:
                self._quarantine(connection, cutoff, self.clock())
            return "quarantined"
        return None

    def tick(self, now: datetime) -> str:
        row = None
        try:
            stamp(now)
            result, row = self._claim(now)
            if row is None:
                return result
            key, owner = row["delivery_key"], row["owner"]
            with lease_heartbeat(lambda: self._renew(key, owner), self.config.event_lease_seconds):
                chunks = json.loads(row["chunks_json"])
                _validate_chunks(chunks)
                if not 0 <= row["next_chunk"] <= len(chunks):
                    raise ValueError("invalid instant checkpoint")
                for index in range(row["next_chunk"], len(chunks)):
                    boundary = self._boundary(row)
                    if boundary:
                        return boundary
                    if not self._renew(key, owner):
                        return "lease_lost"
                    # Recheck after renewal in case maintenance began during the DB operation.
                    boundary = self._boundary(row)
                    if boundary:
                        return boundary
                    if not self.client.send(
                        self.config.delivery_target, chunks[index],
                        message_uuid=stable_digest("instant", key, str(index)),
                    ):
                        self._update(key, owner, "status='failed', last_error='send_failed'")
                        return "send_failed"
                    if not self._update(key, owner, "next_chunk=?", (index + 1,)):
                        return "lease_lost"
                boundary = self._boundary(row)
                if boundary:
                    return boundary
                return "sent" if self._update(
                    key, owner, "status='completed', last_error=''"
                ) else "lease_lost"
        except Exception:
            if row is not None:
                with suppress(Exception):
                    self._update(
                        row["delivery_key"], row["owner"],
                        "status='failed', last_error='unavailable'",
                    )
            return "unavailable"
