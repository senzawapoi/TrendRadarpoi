"""Bounded poll recovery, temporary SQLite only; no provider calls."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from trendradar.core.sqlite_errors import error_fields
from trendradar.integrations.feishu import __main__ as runner
from trendradar.integrations.feishu.ledger import EventLedger

from .test_repair_recovery import prepared


def test_gate_nonempty_wal_poll_proves_busy_and_fixed_stage(tmp_path, monkeypatch):
    ledger = EventLedger(tmp_path / "gate.db")
    event, binding, scope = prepared()
    ledger.record(event, binding, scope)
    writer = sqlite3.connect(tmp_path / "gate.db", isolation_level=None, timeout=0)
    logger = Mock()
    monkeypatch.setattr(runner, "log", logger)
    try:
        ledger.storage.connection.execute("PRAGMA busy_timeout=0")
        assert writer.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        writer.execute("BEGIN IMMEDIATE")
        with (
            pytest.raises(sqlite3.OperationalError) as caught,
            runner._worker_operation(ledger.storage, "worker.pending_events"),
        ):
            ledger.pending_events(recover=True, limit=1)
        assert caught.value.sqlite_errorcode & 255 == 5
        assert error_fields(caught.value) == {"sqlite_code": 5, "sqlite_primary": "SQLITE_BUSY"}
        assert ledger.storage.connection.in_transaction is False
        fields = logger.error.call_args.kwargs
        assert fields["stage"] == "worker.pending_events"
        assert fields["transaction_open"] is False
        assert fields["sqlite_code"] == 5 and fields["sqlite_primary"] == "SQLITE_BUSY"
        writer.rollback()
        assert ledger.pending_events(recover=True, limit=1) == [(event, binding)]
    finally:
        writer.rollback()
        writer.close()
        ledger.close()

class Control:
    def __init__(self, on_wait=None):
        self.now = 0.0
        self.stopped = False
        self.waits = []
        self.on_wait = on_wait

    def is_set(self):
        return self.stopped

    def wait(self, delay):
        self.waits.append(delay)
        self.now += delay
        if self.on_wait:
            self.on_wait()
        return self.stopped

    def clock(self):
        return self.now


def busy(code=5):
    error = sqlite3.OperationalError("database is locked; private SQL and path")
    error.sqlite_errorname = "SQLITE_BUSY"
    if code is not None:
        error.sqlite_errorcode = code
    return error


def fake_ledger(effects, connection=None):
    ledger = Mock(storage=SimpleNamespace(
        connection=connection if connection is not None else SimpleNamespace(in_transaction=False)
    ))
    ledger.pending_events.side_effect = effects
    return ledger


def poll(ledger, control, blocked=lambda: False):
    from trendradar.integrations.feishu.polling import poll_pending
    return poll_pending(ledger, control, blocked, clock=control.clock)


def test_two_busy_then_success_returns_events_once():
    control = Control()
    ledger = fake_ledger([busy(), busy(517), [("event", "binding")]])
    result = poll(ledger, control)
    assert result.state == "ok" and result.events == (("event", "binding"),)
    assert ledger.pending_events.call_count == 3 and control.waits == [1, 2]
    assert all(call.kwargs == {"recover": True, "limit": 1}
               for call in ledger.pending_events.call_args_list)
    with pytest.raises(AttributeError):
        result.state = "changed"


@pytest.mark.parametrize("reason", ["stop", "maintenance"])
def test_wait_terminates_before_next_attempt(reason):
    control = Control()
    blocked = [False]
    def interrupt():
        if reason == "stop":
            control.stopped = True
        else:
            blocked[0] = True
    control.on_wait = interrupt
    ledger = fake_ledger([busy(), []])
    assert poll(ledger, control, lambda: blocked[0]).state == "blocked"
    assert ledger.pending_events.call_count == 1 and control.waits == [1]


@pytest.mark.parametrize("reason", ["stop", "maintenance"])
def test_blocked_before_poll_has_no_sql(reason):
    control = Control()
    control.stopped = reason == "stop"
    ledger = fake_ledger([])
    assert poll(ledger, control, lambda: reason == "maintenance").state == "blocked"
    ledger.pending_events.assert_not_called()


def test_four_busy_attempts_return_explicit_backoff():
    control = Control()
    ledger = fake_ledger([busy() for _ in range(4)])
    result = poll(ledger, control)
    assert result.state == "backoff" and result.events == ()
    assert ledger.pending_events.call_count == 4 and control.waits == [1, 2, 4]


@pytest.mark.parametrize("code", [None, 6, 10, 8, 11])
def test_nonretry_codes_preserve_original_exception(code):
    control = Control()
    error = busy(code)
    ledger = fake_ledger([error])
    if code is None:
        assert error_fields(error) == {"sqlite_code": None, "sqlite_primary": "UNKNOWN"}
    with pytest.raises(sqlite3.OperationalError) as caught:
        poll(ledger, control)
    assert caught.value is error
    assert ledger.pending_events.call_count == 1 and control.waits == []


@pytest.mark.parametrize("state", ["active", "unknown", "invalid", "closed", "missing"])
def test_transaction_uncertainty_rethrows_original_busy(state):
    if state == "closed":
        connection = sqlite3.connect(":memory:")
        connection.close()
    elif state == "missing":
        connection = SimpleNamespace()
    else:
        connection = SimpleNamespace(in_transaction={
            "active": True, "unknown": None, "invalid": 0,
        }[state])
    control = Control()
    error = busy()
    ledger = fake_ledger([error], connection)
    with pytest.raises(sqlite3.OperationalError) as caught:
        poll(ledger, control)
    assert caught.value is error and not control.waits
    assert ledger.pending_events.call_count == 1


@pytest.mark.parametrize("error", [ValueError("private"), sqlite3.IntegrityError("private")])
def test_other_exception_types_are_not_swallowed(error):
    control = Control()
    with pytest.raises(type(error)) as caught:
        poll(fake_ledger([error]), control)
    assert caught.value is error and not control.waits


@pytest.mark.parametrize("elapsed", [25.01, 31])
def test_cooperative_deadline_allows_no_extra_attempt_after_overrun(elapsed):
    control = Control()
    def slow_sql(**kwargs):
        control.now += elapsed
        raise busy()
    ledger = fake_ledger([])
    ledger.pending_events.side_effect = slow_sql
    assert poll(ledger, control).state == "backoff"
    assert ledger.pending_events.call_count == 1 and control.waits == []


def test_actual_sqlite_busy_recovers_after_writer_released(tmp_path):
    ledger = EventLedger(tmp_path / "recovery.db")
    event, binding, scope = prepared()
    ledger.record(event, binding, scope)
    writer = sqlite3.connect(tmp_path / "recovery.db", isolation_level=None, timeout=0)
    try:
        ledger.storage.connection.execute("PRAGMA busy_timeout=0")
        writer.execute("BEGIN IMMEDIATE")
        control = Control(on_wait=writer.rollback)
        result = poll(ledger, control)
        assert result.state == "ok" and result.events == ((event, binding),)
        assert control.waits == [1] and ledger.storage.connection.in_transaction is False
    finally:
        writer.rollback()
        writer.close()
        ledger.close()


def runner_harness(monkeypatch, effects, *, blocked=lambda: False, on_poll=None):
    from contextlib import nullcontext
    control = Control()
    storage = SimpleNamespace(connection=SimpleNamespace(in_transaction=False))
    ledger = fake_ledger(effects, storage.connection)
    if on_poll:
        ledger.pending_events.side_effect = on_poll
    heartbeat, logger, handler = Mock(), Mock(), Mock()
    handler.process.side_effect = lambda *_args: setattr(control, "stopped", True)
    gemini, assistant = Mock(return_value=None), Mock(return_value=None)
    monkeypatch.setattr(runner, "read_guard", lambda _path: object() if blocked() else None)
    monkeypatch.setattr(runner, "runtime_locks", lambda *_args: nullcontext())
    monkeypatch.setattr(runner, "IntelligenceStorage", lambda *_args, **_kwargs: nullcontext(storage))
    monkeypatch.setattr(runner, "_ledger", lambda *_args, **_kwargs: ledger)
    monkeypatch.setattr(runner, "FeishuHandler", lambda *_args, **_kwargs: handler)
    monkeypatch.setattr(runner, "RoleHeartbeat", lambda *_args: heartbeat)
    monkeypatch.setattr(runner, "build_gemini_client", gemini)
    monkeypatch.setattr(runner, "build_assistant_service", assistant)
    monkeypatch.setattr(runner, "log", logger)
    return SimpleNamespace(intelligence_database_path="unused"), control, ledger, handler, heartbeat, logger, gemini, assistant


def test_worker_recovered_poll_dispatches_once_without_reinitializing_providers(monkeypatch):
    settings, control, ledger, handler, _, logger, gemini, assistant = runner_harness(
        monkeypatch, [busy(), busy(), [("event", "binding")]],
    )
    runner.run_worker_role(settings, SimpleNamespace(), None, control)
    assert ledger.pending_events.call_count == 3 and control.waits == [1, 2]
    handler.process.assert_called_once_with("event", "binding")
    gemini.assert_called_once_with(settings)
    assistant.assert_called_once()
    assert logger.mock_calls == []


def test_worker_repeated_busy_episodes_cool_down_and_report_backoff(monkeypatch):
    settings, control, ledger, handler, heartbeat, logger, gemini, assistant = runner_harness(
        monkeypatch, [busy() for _ in range(8)],
    )
    def stop_after_two_episodes():
        if control.waits.count(30) == 2:
            control.stopped = True
    control.on_wait = stop_after_two_episodes
    runner.run_worker_role(settings, SimpleNamespace(), None, control)
    assert ledger.pending_events.call_count == 8
    assert control.waits == [1, 2, 4, 30, 1, 2, 4, 30]
    handler.process.assert_not_called()
    assert logger.warning.call_count == 2 and logger.error.call_count == 0
    assert all(call.kwargs == {"stage": "worker.pending_events", "last_result": "poll_busy"}
               for call in logger.warning.call_args_list)
    statuses = [call.kwargs for call in heartbeat.write.call_args_list]
    assert sum(status.get("last_result") == "poll_busy" for status in statuses) == 2
    assert all(status["state"] == "backoff" for status in statuses if "last_result" in status)
    gemini.assert_called_once()
    assistant.assert_called_once()


@pytest.mark.parametrize("interrupt", ["stop", "maintenance"])
def test_worker_checks_guard_after_successful_poll_before_dispatch(monkeypatch, interrupt):
    blocked = [False]
    control_ref = []
    def on_poll(**_kwargs):
        if interrupt == "stop":
            control_ref[0].stopped = True
        else:
            blocked[0] = True
        return [("event", "binding")]
    settings, control, ledger, handler, heartbeat, _, _, _ = runner_harness(
        monkeypatch, [], blocked=lambda: blocked[0], on_poll=on_poll,
    )
    control_ref.append(control)
    runner.run_worker_role(settings, SimpleNamespace(), None, control)
    ledger.pending_events.assert_called_once_with(recover=True, limit=1)
    handler.process.assert_not_called()
    if interrupt == "maintenance":
        assert heartbeat.write.call_args.kwargs["state"] == "maintenance"


def test_native_busy_commit_with_active_transaction_is_never_retried(tmp_path):
    path = tmp_path / "commit.db"
    writer = sqlite3.connect(path, isolation_level=None, timeout=0)
    reader = sqlite3.connect(path, isolation_level=None, timeout=0)
    try:
        writer.execute("CREATE TABLE work (value INTEGER)")
        writer.execute("INSERT INTO work VALUES (1)")
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM work").fetchall()
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE work SET value=2")
        ledger = fake_ledger([], writer)
        errors = []
        def commit(**_kwargs):
            try:
                writer.execute("COMMIT")
            except sqlite3.OperationalError as error:
                errors.append(error)
                raise
        ledger.pending_events.side_effect = commit
        control = Control()
        with pytest.raises(sqlite3.OperationalError) as caught:
            poll(ledger, control)
        assert caught.value is errors[0]
        assert caught.value.sqlite_errorcode & 255 == 5
        assert writer.in_transaction is True and not control.waits
        assert ledger.pending_events.call_count == 1
    finally:
        reader.rollback()
        writer.rollback()
        reader.close()
        writer.close()


@pytest.mark.parametrize("failed_attempt", [1, 4])
@pytest.mark.parametrize("interrupt", ["maintenance", "stop"])
def test_guard_activated_by_busy_sql_prevents_retry_and_cooldown(
    monkeypatch, failed_attempt, interrupt,
):
    blocked, attempts, controls = [False], [], []
    def on_poll(**_kwargs):
        attempts.append(1)
        if len(attempts) == failed_attempt:
            if interrupt == "maintenance":
                blocked[0] = True
            else:
                controls[0].stopped = True
        raise busy()
    settings, control, ledger, handler, heartbeat, logger, _, _ = runner_harness(
        monkeypatch, [], blocked=lambda: blocked[0], on_poll=on_poll,
    )
    controls.append(control)
    runner.run_worker_role(settings, SimpleNamespace(), None, control)
    assert ledger.pending_events.call_count == failed_attempt
    assert control.waits == ([] if failed_attempt == 1 else [1, 2, 4])
    handler.process.assert_not_called()
    logger.warning.assert_not_called()
    logger.error.assert_not_called()
    statuses = [call.kwargs for call in heartbeat.write.call_args_list]
    assert not any(status.get("last_result") == "poll_busy" for status in statuses)
    if interrupt == "maintenance":
        assert statuses[-1]["state"] == "maintenance"


@pytest.mark.parametrize("interrupt", ["maintenance", "stop"])
def test_guard_after_backoff_result_prevents_cooldown_logging(monkeypatch, interrupt):
    from trendradar.integrations.feishu.polling import PollResult
    blocked = [False]
    settings, control, ledger, handler, heartbeat, logger, _, _ = runner_harness(
        monkeypatch, [], blocked=lambda: blocked[0],
    )
    def polled(*_args, **_kwargs):
        if interrupt == "maintenance":
            blocked[0] = True
        else:
            control.stopped = True
        return PollResult("backoff")
    monkeypatch.setattr(runner, "poll_pending", polled)
    runner.run_worker_role(settings, SimpleNamespace(), None, control)
    assert control.waits == []
    ledger.pending_events.assert_not_called()
    handler.process.assert_not_called()
    logger.warning.assert_not_called()
    assert not any(call.kwargs.get("last_result") == "poll_busy"
                   for call in heartbeat.write.call_args_list)
    if interrupt == "maintenance":
        assert heartbeat.write.call_args.kwargs["state"] == "maintenance"


@pytest.mark.parametrize("code,transaction", [(None, False), (6, False), (5, True), (5, None)])
@pytest.mark.parametrize("interrupt", ["maintenance", "stop"])
def test_guard_during_unsafe_error_does_not_swallow_original(code, transaction, interrupt):
    control, blocked = Control(), [False]
    error = busy(code)
    ledger = fake_ledger([], SimpleNamespace(in_transaction=transaction))
    def failed_sql(**_kwargs):
        if interrupt == "maintenance":
            blocked[0] = True
        else:
            control.stopped = True
        raise error
    ledger.pending_events.side_effect = failed_sql
    with pytest.raises(sqlite3.OperationalError) as caught:
        poll(ledger, control, lambda: blocked[0])
    assert caught.value is error and control.waits == []
    assert ledger.pending_events.call_count == 1


@pytest.mark.parametrize("interrupt", ["maintenance", "stop"])
def test_guard_during_backoff_status_publication_prevents_cooldown(monkeypatch, interrupt):
    blocked = [False]
    settings, control, ledger, handler, heartbeat, _, _, _ = runner_harness(
        monkeypatch, [busy() for _ in range(4)], blocked=lambda: blocked[0],
    )
    def publish(**status):
        if status["state"] == "backoff":
            if interrupt == "maintenance":
                blocked[0] = True
            else:
                control.stopped = True
    heartbeat.write.side_effect = publish
    runner.run_worker_role(settings, SimpleNamespace(), None, control)
    assert control.waits == [1, 2, 4]
    assert ledger.pending_events.call_count == 4
    handler.process.assert_not_called()
    if interrupt == "maintenance":
        assert heartbeat.write.call_args.kwargs["state"] == "maintenance"
