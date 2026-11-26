"""Bounded recovery for the standalone worker's proven SQLite poll BUSY case."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from trendradar.core.sqlite_errors import error_fields


@dataclass(frozen=True)
class PollResult:
    state: Literal["ok", "blocked", "backoff"]
    events: tuple = ()


def poll_pending(ledger, stop, blocked: Callable[[], bool], *, clock=time.monotonic) -> PollResult:
    """Retry only native BUSY with a definitely inactive connection transaction.

    The 30 second deadline is cooperative between calls, not a hard execution
    timeout: SQLite's existing five second busy timeout bounds lock waiting;
    SQL CPU or I/O can overrun. Never start another call with under five seconds
    remaining. No handler, model or delivery operation belongs in this helper.
    """
    deadline = clock() + 30
    for attempt in range(4):
        if stop.is_set() or blocked():
            return PollResult("blocked")
        if deadline - clock() < 5:
            return PollResult("backoff")
        try:
            return PollResult("ok", tuple(ledger.pending_events(recover=True, limit=1)))
        except sqlite3.OperationalError as exc:
            if error_fields(exc)["sqlite_primary"] != "SQLITE_BUSY":
                raise
            try:
                transaction_open = ledger.storage.connection.in_transaction
            except Exception:
                # Inspecting a closed/unavailable connection must not mask exc.
                transaction_open = None
            if transaction_open is not False:
                raise
            remaining = deadline - clock()
            if stop.is_set() or blocked():
                return PollResult("blocked")
            if attempt == 3 or remaining < 5:
                return PollResult("backoff")
            stop.wait(min((1, 2, 4)[attempt], max(0, remaining)))
    return PollResult("backoff")  # Defensive; all bounded-loop paths return above.
