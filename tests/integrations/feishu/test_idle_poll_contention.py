"""Real SQLite contention and recovery behavior for idle worker polling."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from trendradar.integrations.feishu.ledger import EventLedger, stamp
from trendradar.integrations.feishu.models import FeishuReply

from .test_repair_recovery import prepared


def test_empty_poll_does_not_compete_with_another_writer(tmp_path):
    path = tmp_path / "ledger.db"
    ledger = EventLedger(path)
    writer = sqlite3.connect(path, isolation_level=None, timeout=0)
    try:
        ledger.storage.connection.execute("PRAGMA busy_timeout=0")
        assert writer.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        writer.execute("BEGIN IMMEDIATE")
        try:
            assert ledger.pending_events(recover=True, limit=1) == []
        except sqlite3.OperationalError as error:
            assert error.sqlite_errorcode == sqlite3.SQLITE_BUSY
            raise
        assert not ledger.storage.connection.in_transaction
    finally:
        writer.rollback()
        writer.close()
        ledger.close()


@pytest.fixture
def queued(tmp_path):
    now = [datetime(2026, 11, 11, tzinfo=timezone.utc)]
    ledger = EventLedger(tmp_path / "ledger.db", clock=lambda: now[0])
    event, binding, scope = prepared()
    ledger.record(event, binding, scope)
    try:
        yield ledger, event, binding, scope, now
    finally:
        ledger.close()


def row(ledger):
    return ledger.storage.connection.execute("SELECT * FROM feishu_events").fetchone()


@pytest.mark.parametrize("recover", [True, False])
def test_empty_poll_trace_has_no_write_transaction(tmp_path, recover):
    ledger = EventLedger(tmp_path / "ledger.db")
    trace = []
    try:
        ledger.storage.connection.set_trace_callback(trace.append)
        assert ledger.pending_events(recover=recover) == []
        assert trace
        assert not any(sql.lstrip().upper().startswith(("BEGIN", "UPDATE", "COMMIT"))
                       for sql in trace)
        assert not ledger.storage.connection.in_transaction
    finally:
        ledger.close()


@pytest.mark.parametrize("limit", [True, False, 0, -1, 1001, 1.0, 1.5, "1"])
@pytest.mark.parametrize("has_pending", [True, False])
def test_invalid_limit_is_rejected_even_when_empty(queued, limit, has_pending):
    ledger, event, _, _, _ = queued
    if not has_pending:
        ledger.discard_payload(event.event_id)
    with pytest.raises(ValueError, match="invalid pending event limit"):
        ledger.pending_events(limit=limit)
    assert not ledger.storage.connection.in_transaction


@pytest.mark.parametrize("limit", [None, 1, 1000])
def test_expired_processing_is_recovered_without_claiming(queued, limit):
    ledger, event, binding, scope, now = queued
    claim = ledger.claim(event.event_id, scope)
    now[0] += timedelta(seconds=121)
    assert ledger.pending_events(limit=limit) == [(event, binding)]
    current = row(ledger)
    assert current["owner"] == ""
    assert current["lease_until"] == stamp(now[0])
    assert current["attempts"] == 1 and current["delivery_attempts"] == 0
    assert current["status"] == "processing"
    assert not ledger.renew(event.event_id, claim.owner)


def test_saved_reply_delivery_preserves_payload_and_counts(queued):
    ledger, event, binding, scope, now = queued
    claim = ledger.claim(event.event_id, scope)
    reply = FeishuReply(event.event_id, "saved answer")
    assert ledger.save_reply(event.event_id, claim.owner, reply)
    before = row(ledger)
    now[0] += timedelta(seconds=121)
    assert ledger.pending_events() == [(event, binding)]
    current = row(ledger)
    for field in ("reply_json", "event_json", "binding_json"):
        assert current[field] == before[field]
    assert current["attempts"] == current["delivery_attempts"] == 1
    delivery = ledger.claim(event.event_id, scope)
    assert delivery.status == "deliver" and delivery.reply == reply


def test_exhausted_expired_processing_payload_is_cleaned(queued):
    ledger, _, _, _, _ = queued
    ledger.storage.connection.execute("UPDATE feishu_events SET attempts=3, owner='old'")
    assert ledger.pending_events() == []
    current = row(ledger)
    assert current["status"] == "failed" and current["owner"] == ""
    assert current["event_json"] is None and current["binding_json"] is None
    assert current["attempts"] == 3 and current["delivery_attempts"] == 0


@pytest.mark.parametrize("recover", [True, False])
def test_live_processing_and_delivery_leases_are_not_stolen(queued, recover):
    ledger, event, _, scope, _ = queued
    claim = ledger.claim(event.event_id, scope)
    before = dict(row(ledger))
    assert ledger.pending_events(recover=recover) == []
    assert dict(row(ledger)) == before
    assert ledger.save_reply(event.event_id, claim.owner, FeishuReply(event.event_id, "answer"))
    before = dict(row(ledger))
    assert ledger.pending_events(recover=recover) == []
    assert dict(row(ledger)) == before


def test_completed_payload_is_never_polled_or_resent(queued):
    ledger, event, _, scope, now = queued
    claim = ledger.claim(event.event_id, scope)
    assert ledger.complete(event.event_id, claim.owner, FeishuReply(event.event_id, "answer"))
    before = dict(row(ledger))
    now[0] += timedelta(seconds=121)
    assert ledger.pending_events() == []
    assert dict(row(ledger)) == before
    assert ledger.claim(event.event_id, scope).status == "duplicate_delivered"


def test_corrupt_payload_is_discarded(queued):
    ledger, _, _, _, _ = queued
    ledger.storage.connection.execute("UPDATE feishu_events SET event_json='bad json'")
    assert ledger.pending_events() == []
    current = row(ledger)
    assert current["event_json"] is None and current["binding_json"] is None
    assert current["attempts"] == current["delivery_attempts"] == 3


def test_recovery_cutover_still_quarantines_retained_payload(queued):
    ledger, _, _, _, now = queued
    before = row(ledger)["event_json"]
    ledger.recovery_cutover_at = now[0] + timedelta(days=365)
    assert ledger.pending_events() == []
    current = row(ledger)
    assert current["event_json"] == before
    assert current["status"] == "failed"
    assert current["attempts"] == current["delivery_attempts"] == 3


def test_recover_false_preserves_expired_owner_and_exhausted_payload(queued):
    ledger, event, binding, scope, now = queued
    claim = ledger.claim(event.event_id, scope)
    now[0] += timedelta(seconds=121)
    before = dict(row(ledger))
    assert ledger.pending_events(recover=False) == [(event, binding)]
    assert dict(row(ledger)) == before and row(ledger)["owner"] == claim.owner
    ledger.storage.connection.execute("UPDATE feishu_events SET attempts=3")
    before = dict(row(ledger))
    assert ledger.pending_events(recover=False) == []
    assert dict(row(ledger)) == before


@pytest.mark.parametrize("change", ["lease", "insert"])
def test_transaction_rereads_state_after_precheck(queued, monkeypatch, tmp_path, change):
    ledger, event, binding, _, now = queued
    other = type(event).from_dict({**event.to_dict(), "event_id": "new-event"})
    original = ledger.storage.transaction
    writer = sqlite3.connect(tmp_path / "ledger.db", isolation_level=None, timeout=0)

    @contextmanager
    def transaction_after_external_change():
        writer.execute(
            "UPDATE feishu_events SET lease_until=?, owner='other-owner' WHERE event_id=?",
            (stamp(now[0] + timedelta(seconds=120)), event.event_id),
        )
        if change == "insert":
            writer.execute(
                "INSERT INTO feishu_events (event_id,scope,status,owner,attempts,lease_until,"
                "updated_at,reply_json,delivery_attempts,event_json,binding_json) "
                "SELECT ?,scope,status,'',attempts,?,updated_at,"
                "reply_json,delivery_attempts,?,binding_json FROM feishu_events "
                "WHERE event_id=?",
                (other.event_id, stamp(now[0]), json.dumps(other.to_dict()), event.event_id),
            )
        with original() as connection:
            yield connection

    try:
        monkeypatch.setattr(ledger.storage, "transaction", transaction_after_external_change)
        expected = [(other, binding)] if change == "insert" else []
        assert ledger.pending_events() == expected
        original_row = ledger.storage.connection.execute(
            "SELECT owner FROM feishu_events WHERE event_id=?", (event.event_id,)
        ).fetchone()
        assert original_row["owner"] == "other-owner"
        assert not ledger.storage.connection.in_transaction
    finally:
        writer.close()


def test_event_added_after_empty_poll_is_found_next_time(tmp_path):
    ledger = EventLedger(tmp_path / "ledger.db")
    event, binding, scope = prepared()
    try:
        assert ledger.pending_events() == []
        ledger.record(event, binding, scope)
        assert ledger.pending_events() == [(event, binding)]
    finally:
        ledger.close()


def test_nonempty_recovery_error_rolls_back_and_connection_can_write(queued):
    ledger, _, _, _, _ = queued
    ledger.storage.connection.execute(
        "CREATE TRIGGER stop_recovery BEFORE UPDATE ON feishu_events "
        "BEGIN SELECT RAISE(ABORT, 'recovery failed'); END"
    )
    before = dict(row(ledger))
    with pytest.raises(sqlite3.IntegrityError, match="recovery failed"):
        ledger.pending_events()
    assert not ledger.storage.connection.in_transaction
    assert dict(row(ledger)) == before
    ledger.storage.connection.execute("DROP TRIGGER stop_recovery")
    with ledger.storage.transaction() as connection:
        connection.execute("UPDATE feishu_events SET owner='after-rollback'")
    assert row(ledger)["owner"] == "after-rollback"


@pytest.mark.parametrize("recover", [True, False])
def test_caller_owned_transaction_is_not_hidden_or_ended(tmp_path, recover):
    ledger = EventLedger(tmp_path / "ledger.db")
    connection = ledger.storage.connection
    try:
        connection.execute("BEGIN")
        with pytest.raises(sqlite3.OperationalError, match="within a transaction"):
            ledger.pending_events(recover=recover)
        assert connection.in_transaction
        connection.execute("CREATE TABLE caller_work (value TEXT)")
        connection.rollback()
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='caller_work'"
        ).fetchone() is None
    finally:
        connection.rollback()
        ledger.close()
