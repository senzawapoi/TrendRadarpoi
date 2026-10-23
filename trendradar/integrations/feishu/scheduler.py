"""One scheduler with exclusive instant or explicit daily delivery modes."""

from __future__ import annotations

import json
import threading
from contextlib import suppress
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops.maintenance import read_guard, read_recovery_cutover

from .config import FeishuConfig
from .instant import InstantDeliveryScheduler
from .ledger import lease_heartbeat, stamp, utc_now
from .models import stable_digest


def window_key(config: FeishuConfig, now: datetime) -> str | None:
    stamp(now)
    local = now.astimezone(ZoneInfo(config.timezone))
    minute = local.hour * 60 + local.minute
    start_hour, start_minute = map(int, config.delivery_time.split(":"))
    end_hour, end_minute = map(int, config.delivery_end.split(":"))
    start, end = start_hour * 60 + start_minute, end_hour * 60 + end_minute
    date = local.date()
    if start <= end:
        if not start <= minute <= end:
            return None
    else:
        if end < minute < start:
            return None
        if minute <= end:
            date -= timedelta(days=1)
    return stable_digest(
        config.delivery_target, date.isoformat(), config.delivery_time, config.delivery_end
    )


class DeliveryScheduler:
    def __init__(
        self,
        config: FeishuConfig,
        path,
        delivery,
        client,
        *,
        storage: IntelligenceStorage | None = None,
        require_existing: bool = False,
        synchronous: str = "FULL",
        clock=utc_now,
    ):
        self.config, self.delivery, self.client = config, delivery, client
        self.storage = storage or (
            IntelligenceStorage.open_existing(path, synchronous=synchronous)
            if require_existing
            else IntelligenceStorage(path, synchronous=synchronous)
        )
        self._owns_storage = storage is None
        self.clock = clock
        self.lock = threading.RLock()

    def close(self):
        if self._owns_storage:
            self.storage.close()

    def _claim(self, key, now):
        owner = uuid4().hex
        with self.lock, self.storage.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM feishu_deliveries WHERE delivery_key=?", (key,)
            ).fetchone()
            if row and (
                row["status"] == "completed"
                or (row["status"] == "processing" and row["lease_until"] > stamp(now))
            ):
                return None
            connection.execute(
                """INSERT INTO feishu_deliveries (delivery_key, status, owner, lease_until, updated_at)
                VALUES (?, 'processing', ?, ?, ?)
                ON CONFLICT(delivery_key) DO UPDATE SET status='processing', owner=excluded.owner,
                lease_until=excluded.lease_until, updated_at=excluded.updated_at""",
                (
                    key,
                    owner,
                    stamp(now + timedelta(seconds=self.config.event_lease_seconds)),
                    stamp(now),
                ),
            )
            return owner, row

    def _renew(self, key, owner):
        now = self.clock()
        with self.lock:
            return (
                self.storage.connection.execute(
                    "UPDATE feishu_deliveries SET lease_until=?, updated_at=? "
                    "WHERE delivery_key=? AND owner=? AND status='processing'",
                    (
                        stamp(now + timedelta(seconds=self.config.event_lease_seconds)),
                        stamp(now),
                        key,
                        owner,
                    ),
                ).rowcount
                == 1
            )

    def _update(self, key, owner, sql, args=()):
        with self.lock:
            return (
                self.storage.connection.execute(
                    "UPDATE feishu_deliveries SET " + sql + ", updated_at=? "
                    "WHERE delivery_key=? AND owner=? AND status='processing'",
                    (*args, stamp(self.clock()), key, owner),
                ).rowcount
                == 1
            )

    def tick(self, now=None) -> str:
        if (
            not self.config.enabled
            or not self.config.delivery_enabled
            or not self.config.delivery_target
        ):
            return "disabled"
        now = now or self.clock()
        if read_guard(self.storage.db_path) is not None:
            return "maintenance"
        if self.config.delivery_mode == "instant":
            return InstantDeliveryScheduler(
                self.config, self.storage, self.delivery, self.client,
                lock=self.lock, clock=self.clock,
            ).tick(now)
        if self.config.delivery_mode != "daily":
            return "disabled"
        key = window_key(self.config, now)
        if key is None:
            return "not_due"
        cutoff = read_recovery_cutover(self.storage.db_path)
        if cutoff is not None:
            local_now = now.astimezone(ZoneInfo(self.config.timezone))
            local_cutoff = cutoff.astimezone(ZoneInfo(self.config.timezone))
            start_hour, start_minute = map(int, self.config.delivery_time.split(":"))
            window_start = local_now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
            if window_start > local_now:
                window_start -= timedelta(days=1)
            if window_start <= local_cutoff:
                return "quarantined"
        try:
            claimed = self._claim(key, now)
            if claimed is None:
                return "already_claimed"
            owner, row = claimed
            with lease_heartbeat(lambda: self._renew(key, owner), self.config.event_lease_seconds):
                if row and row["chunks_json"]:
                    chunks = json.loads(row["chunks_json"])
                else:
                    chunks = list(self.delivery.prepare(now))
                    if not self._update(
                        key, owner, "chunks_json=?", (json.dumps(chunks, ensure_ascii=False),)
                    ):
                        return "lease_lost"
                if (
                    not isinstance(chunks, list)
                    or len(chunks) > 100
                    or any(
                        not isinstance(chunk, str)
                        or not chunk
                        or len(json.dumps({"text": chunk}, ensure_ascii=False).encode()) > 20_000
                        for chunk in chunks
                    )
                ):
                    raise ValueError("invalid delivery payload")
                if not chunks:
                    self._update(key, owner, "status='failed', chunks_json=NULL")
                    return "empty"
                next_chunk = row["next_chunk"] if row else 0
                if not 0 <= next_chunk <= len(chunks):
                    raise ValueError("invalid chunk checkpoint")
                for index in range(next_chunk, len(chunks)):
                    if read_guard(self.storage.db_path) is not None:
                        return "maintenance"
                    if not self._renew(key, owner):
                        return "lease_lost"
                    # Stable SDK UUID narrows the send-accepted/local-checkpoint crash window.
                    sent = self.client.send(
                        self.config.delivery_target,
                        chunks[index],
                        message_uuid=stable_digest(key, str(index)),
                    )
                    if not sent:
                        self._update(key, owner, "status='failed'")
                        return "send_failed"
                    if not self._update(key, owner, "next_chunk=?", (index + 1,)):
                        return "lease_lost"
                return "sent" if self._update(key, owner, "status='completed'") else "lease_lost"
        except Exception:
            # A failed or uncertain operation never marks the window complete.
            if "owner" in locals():
                with suppress(Exception):
                    self._update(key, owner, "status='failed'")
            return "unavailable"
