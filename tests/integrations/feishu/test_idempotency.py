"""Durable delivery retry, claim fencing and abandoned event recovery."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from trendradar.ai.assistant import AssistantService
from trendradar.integrations.feishu.client import FeishuClient
from trendradar.integrations.feishu.config import FeishuConfig
from trendradar.integrations.feishu.handler import FeishuHandler
from trendradar.integrations.feishu.ledger import EventLedger
from trendradar.integrations.feishu.models import FeishuReply
from trendradar.intelligence.storage import IntelligenceStorage

from .test_handler import Gemini, Operations, payload


def test_duplicate_delivered_event_is_suppressed_after_restart(tmp_path):
    path = tmp_path / "test.db"
    ops, gemini = Operations(), Gemini()
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),))
    results = []
    for _ in range(2):
        assistant, ledger = AssistantService(path, gemini), EventLedger(path)
        handler = FeishuHandler(config, FeishuClient(ops), assistant, ledger=ledger)
        results.append(handler.handle(payload()))
        assistant.close()
        ledger.close()
    assert results == ["sent", "already_delivered"]
    assert len(gemini.calls) == 1
    assert len(ops.replies) == 1


def test_live_claim_renewal_fencing_and_retry_bound(tmp_path):
    now = [datetime(2026, 9, 12, tzinfo=timezone.utc)]
    path = tmp_path / "test.db"
    first, second = EventLedger(path, clock=lambda: now[0]), EventLedger(path, clock=lambda: now[0])
    claim = first.claim("ev", "scope")
    assert second.claim("ev", "scope").status == "busy"
    now[0] += timedelta(seconds=100)
    assert first.renew("ev", claim.owner)
    now[0] += timedelta(seconds=100)
    assert second.claim("ev", "scope").status == "busy"
    now[0] += timedelta(seconds=121)
    reclaimed = second.claim("ev", "scope")
    assert reclaimed.status == "claimed"
    assert not first.complete("ev", claim.owner, FeishuReply("ev", "old"))
    second.fail("ev", reclaimed.owner)
    third = first.claim("ev", "scope")
    first.fail("ev", third.owner)
    assert second.claim("ev", "scope").status == "exhausted"
    assert second.claim("ev", "other").status == "rejected"
    first.close()
    second.close()


def test_corrupt_completed_event_fails_closed(tmp_path):
    ledger = EventLedger(tmp_path / "test.db")
    claim = ledger.claim("ev", "scope")
    ledger.complete("ev", claim.owner, FeishuReply("ev", "answer"))
    ledger.storage.connection.execute("UPDATE feishu_events SET reply_json='{}'")
    assert ledger.claim("ev", "scope").status == "corrupt"
    ledger.close()


def test_corrupt_completed_event_does_not_send_a_fallback_reply(tmp_path):
    path = tmp_path / "test.db"
    operations, gemini = Operations(), Gemini()
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),))
    assistant = AssistantService(path, gemini)
    ledger = EventLedger(path)
    handler = FeishuHandler(config, FeishuClient(operations), assistant, ledger=ledger)
    assert handler.handle(payload(event_id="corrupt")) == "sent"
    ledger.storage.connection.execute(
        "UPDATE feishu_events SET reply_json='{}' WHERE event_id='corrupt'"
    )
    assert handler.handle(payload(event_id="corrupt")) == "ledger_unavailable"
    assert len(operations.replies) == 1
    assert len(gemini.calls) == 1
    assistant.close()
    ledger.close()


def test_prepared_event_is_recovered_after_intake_restart(tmp_path):
    path = tmp_path / "test.db"
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),))
    handler = FeishuHandler(config, FeishuClient(Operations()), None)
    prepared = handler.prepare(payload(event_id="durable"))
    assert prepared is not None
    event, binding = prepared
    first = EventLedger(path)
    scope = "scope"
    assert first.record(event, binding, scope)
    first.close()

    restarted = EventLedger(path)
    recovered = restarted.pending_events()
    assert recovered == [prepared]
    restarted.close()


def test_recovery_cutover_quarantines_old_event_without_deleting_evidence(tmp_path):
    path = tmp_path / "test.db"
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),))
    handler = FeishuHandler(config, FeishuClient(Operations()), None)
    prepared = handler.prepare(payload(event_id="before-cutover"))
    assert prepared is not None
    event, binding = prepared
    old_event = replace(event, received_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    first = EventLedger(path)
    assert first.record(old_event, binding, "scope")
    first.close()
    restarted = EventLedger(
        path,
        recovery_cutover_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    assert restarted.pending_events() == []
    row = restarted.storage.connection.execute(
        "SELECT status, attempts, event_json FROM feishu_events WHERE event_id=?",
        ("before-cutover",),
    ).fetchone()
    assert row["status"] == "failed" and row["attempts"] == 3 and row["event_json"]
    restarted.close()


def test_durable_intake_is_bounded_and_retries_after_backoff(tmp_path):
    path = tmp_path / "test.db"
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),))
    handler = FeishuHandler(config, FeishuClient(Operations()), None)
    prepared = [handler.prepare(payload(event_id=str(index))) for index in range(3)]
    now = [datetime(2026, 9, 12, tzinfo=timezone.utc)]
    ledger = EventLedger(path, max_pending_events=2, delivery_retry_base_seconds=10,
                         clock=lambda: now[0])
    for event, binding in prepared[:2]:
        assert ledger.record(event, binding, f"scope-{event.event_id}")
    with pytest.raises(OverflowError):
        ledger.record(prepared[2][0], prepared[2][1], "scope-2")
    recovered = ledger.pending_events(limit=1)
    assert len(recovered) == 1
    claim = ledger.claim("0", "scope-0")
    ledger.save_reply("0", claim.owner, FeishuReply("0", "answer"))
    ledger.mark_delivery_failed("0", claim.owner)
    assert all(event.event_id != "0" for event, _binding in ledger.pending_events())
    now[0] += timedelta(seconds=10)
    assert ledger.pending_events(limit=1)
    ledger.close()


def test_failed_reply_is_retried_without_recomputing_assistant_turn(tmp_path):
    path = tmp_path / "test.db"
    operations = Operations()
    gemini = Gemini()
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),))
    assistant = AssistantService(path, gemini)
    ledger = EventLedger(path)
    handler = FeishuHandler(config, FeishuClient(operations), assistant, ledger=ledger)

    original_reply = operations.reply
    operations.reply = lambda *_args: False
    assert handler.handle(payload(event_id="retry")) == "send_failed"
    assert len(gemini.calls) == 1
    row = ledger.storage.connection.execute(
        "SELECT status, reply_json, delivery_attempts FROM feishu_events WHERE event_id='retry'"
    ).fetchone()
    assert row["status"] == "failed" and row["reply_json"] and row["delivery_attempts"] == 1

    assistant.close()
    ledger.close()
    operations.reply = original_reply
    restarted_assistant = AssistantService(path, gemini)
    restarted_ledger = EventLedger(path)
    restarted_handler = FeishuHandler(
        config, FeishuClient(operations), restarted_assistant, ledger=restarted_ledger
    )
    assert restarted_handler.handle(payload(event_id="retry")) == "sent"
    assert len(gemini.calls) == 1
    assert restarted_ledger.storage.connection.execute(
        "SELECT status FROM feishu_events WHERE event_id='retry'"
    ).fetchone()[0] == "completed"
    assert len(operations.replies) == 1
    restarted_assistant.close()
    restarted_ledger.close()

    operations.reply = lambda *_args: False
    duplicate_assistant = AssistantService(path, gemini)
    duplicate_ledger = EventLedger(path)
    duplicate_handler = FeishuHandler(
        config, FeishuClient(operations), duplicate_assistant, ledger=duplicate_ledger
    )
    assert duplicate_handler.handle(payload(event_id="retry")) == "already_delivered"
    assert len(gemini.calls) == 1
    assert len(operations.replies) == 1
    duplicate_assistant.close()
    duplicate_ledger.close()


def test_migration_keeps_v3_sessions_and_content(tmp_path):
    path = tmp_path / "test.db"
    assistant = AssistantService(path)
    assistant.create_session("owner", session_id="s")
    assistant.storage.connection.execute("DROP TABLE feishu_events")
    assistant.storage.connection.execute("PRAGMA user_version=3")
    assistant.close()
    with IntelligenceStorage(path) as storage:
        assert (
            storage.connection.execute("SELECT principal_id FROM assistant_sessions").fetchone()[0]
            == "owner"
        )
        assert storage.connection.execute("SELECT COUNT(*) FROM feishu_events").fetchone()[0] == 0


def test_missing_ledger_never_calls_provider(tmp_path):
    gemini, ops = Gemini(), Operations()
    assistant = AssistantService(tmp_path / "test.db", gemini)
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),))
    handler = FeishuHandler(config, FeishuClient(ops), assistant)
    assert handler.handle(payload()) == "ledger_unavailable"
    assert not gemini.calls
    assistant.close()


def test_recovery_after_core_turn_persisted_before_ledger_completion(tmp_path):
    from trendradar.integrations.feishu.models import stable_digest

    path = tmp_path / "test.db"
    gemini, ops = Gemini(), Operations()
    now = [datetime.now(timezone.utc)]
    config = FeishuConfig(enabled=True, identity_fields=(("open_id", ("owner",)),))
    assistant, ledger = AssistantService(path, gemini), EventLedger(path, clock=lambda: now[0])
    handler = FeishuHandler(config, FeishuClient(ops), assistant, ledger=ledger)
    event, binding = handler.prepare(payload())
    ledger.claim(
        event.event_id, stable_digest(binding.principal_id, binding.session_id, event.message_id)
    )
    original = handler.respond(event, binding)
    assistant.close()
    ledger.close()
    now[0] += timedelta(seconds=121)
    assistant, ledger = AssistantService(path, gemini), EventLedger(path, clock=lambda: now[0])
    handler = FeishuHandler(config, FeishuClient(ops), assistant, ledger=ledger)
    assert handler.handle(payload()) == "sent"
    assert len(gemini.calls) == 1
    assert ops.replies[0][1] == original.text
    assistant.close()
    ledger.close()
