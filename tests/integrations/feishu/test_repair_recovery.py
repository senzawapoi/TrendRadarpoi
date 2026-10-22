"""Repair-plan regressions use temporary durable ledgers and no provider I/O."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from trendradar.integrations.feishu.client import FeishuClient
from trendradar.integrations.feishu.config import FeishuConfig
from trendradar.integrations.feishu.handler import FeishuHandler
from trendradar.integrations.feishu.ledger import EventLedger
from trendradar.integrations.feishu.models import FeishuReply, stable_digest

from .test_handler import Operations, payload


def prepared():
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),))
    handler = FeishuHandler(config, FeishuClient(Operations()), None)
    event, binding = handler.prepare(payload())
    scope = stable_digest(binding.principal_id, binding.session_id, event.message_id)
    return event, binding, scope


def test_exhausted_processing_is_not_polled_forever(tmp_path):
    event, binding, scope = prepared()
    ledger = EventLedger(tmp_path / "test.db")
    try:
        ledger.record(event, binding, scope)
        for _ in range(3):
            claim = ledger.claim(event.event_id, scope)
            ledger.fail(event.event_id, claim.owner)
        assert ledger.pending_events() == []
        row = ledger.storage.connection.execute("SELECT * FROM feishu_events").fetchone()
        assert row["event_json"] is None and row["binding_json"] is None
    finally:
        ledger.close()


def test_last_active_processing_attempt_still_counts_towards_capacity(tmp_path):
    event, binding, scope = prepared()
    ledger = EventLedger(tmp_path / "test.db", max_pending_events=1)
    try:
        ledger.record(event, binding, scope)
        for _ in range(2):
            claim = ledger.claim(event.event_id, scope)
            ledger.fail(event.event_id, claim.owner)
        assert ledger.claim(event.event_id, scope).status == "claimed"
        other = type(event).from_dict({**event.to_dict(), "event_id": "other"})
        with pytest.raises(OverflowError):
            ledger.record(other, binding, scope)
    finally:
        ledger.close()


@pytest.mark.parametrize("change", [{"payload_version": 99}, {"event_id": "other"},
                                  {"mentioned": "false"}])
def test_bad_recovery_payload_is_terminal_before_side_effects(tmp_path, change):
    event, binding, scope = prepared()
    ledger = EventLedger(tmp_path / "test.db")
    try:
        ledger.record(event, binding, scope)
        raw = {**event.to_dict(), **change}
        ledger.storage.connection.execute(
            "UPDATE feishu_events SET event_json=?", (json.dumps(raw),)
        )
        assert ledger.pending_events() == []
        assert ledger.storage.connection.execute(
            "SELECT event_json FROM feishu_events"
        ).fetchone()[0] is None
    finally:
        ledger.close()


def test_delivery_lease_can_be_renewed_without_owner_takeover(tmp_path):
    event, binding, scope = prepared()
    now = [datetime.now(timezone.utc)]
    path = tmp_path / "test.db"
    first = EventLedger(path, lease_seconds=10, clock=lambda: now[0])
    second = EventLedger(path, lease_seconds=10, clock=lambda: now[0])
    try:
        first.record(event, binding, scope)
        claim = first.claim(event.event_id, scope)
        first.save_reply(event.event_id, claim.owner, FeishuReply(event.event_id, "answer"))
        now[0] += timedelta(seconds=9)
        assert first.renew(event.event_id, claim.owner)
        now[0] += timedelta(seconds=2)
        assert second.claim(event.event_id, scope).status == "busy"
        now[0] += timedelta(seconds=10)
        replacement = second.claim(event.event_id, scope)
        assert replacement.status == "deliver"
        assert not first.mark_delivered(event.event_id, claim.owner)
    finally:
        first.close()
        second.close()


def test_delivered_event_drops_input_and_suppresses_duplicate(tmp_path):
    event, binding, scope = prepared()
    ledger = EventLedger(tmp_path / "test.db")
    try:
        ledger.record(event, binding, scope)
        claim = ledger.claim(event.event_id, scope)
        ledger.save_reply(event.event_id, claim.owner, FeishuReply(event.event_id, "answer"))
        assert ledger.mark_delivered(event.event_id, claim.owner)
        row = ledger.storage.connection.execute("SELECT * FROM feishu_events").fetchone()
        assert row["event_json"] is None and row["binding_json"] is None
        duplicate = ledger.claim(event.event_id, scope)
        assert duplicate.status == "duplicate_delivered"
        assert duplicate.reply is None
    finally:
        ledger.close()


def test_final_failed_delivery_drops_recovery_input(tmp_path):
    event, binding, scope = prepared()
    ledger = EventLedger(tmp_path / "test.db")
    try:
        ledger.record(event, binding, scope)
        claim = ledger.claim(event.event_id, scope)
        ledger.save_reply(event.event_id, claim.owner, FeishuReply(event.event_id, "answer"))
        for attempt in range(3):
            ledger.mark_delivery_failed(event.event_id, claim.owner)
            if attempt < 2:
                claim = ledger.claim(event.event_id, scope)
        assert ledger.pending_events() == []
        assert ledger.storage.connection.execute(
            "SELECT event_json FROM feishu_events"
        ).fetchone()[0] is None
    finally:
        ledger.close()


def test_permanent_delivery_failure_is_not_retried(tmp_path):
    event, binding, scope = prepared()
    ledger = EventLedger(tmp_path / "test.db")
    try:
        ledger.record(event, binding, scope)
        claim = ledger.claim(event.event_id, scope)
        ledger.save_reply(event.event_id, claim.owner, FeishuReply(event.event_id, "answer"))
        assert ledger.mark_delivery_failed(event.event_id, claim.owner, retryable=False)
        row = ledger.storage.connection.execute("SELECT * FROM feishu_events").fetchone()
        assert row["delivery_attempts"] == 3
        assert row["event_json"] is None and ledger.pending_events() == []
    finally:
        ledger.close()


def test_reply_delivery_uses_stable_uuid_without_requiring_legacy_operations_change():
    from trendradar.integrations.feishu.client import FeishuClient, ReplyDelivery

    class OperationsWithDetailedReply(Operations):
        def __init__(self):
            super().__init__()
            self.uuids = []

        def reply_result(self, message_id, text, *, message_uuid=None):
            self.uuids.append(message_uuid)
            self.replies.append((message_id, text))
            return ReplyDelivery(True)

    operations = OperationsWithDetailedReply()
    client = FeishuClient(operations)
    first = client.reply_result("msg", "answer", message_uuid="event")
    second = client.reply_result("msg", "answer", message_uuid="event")
    assert first.delivered and second.delivered and operations.uuids[0] == operations.uuids[1]
