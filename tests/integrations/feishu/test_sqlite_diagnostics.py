"""Sanitized SQLite diagnostics; no providers or existing databases are used."""

import sqlite3
import threading
from contextlib import closing, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from trendradar.core.sqlite_errors import error_fields
from trendradar.integrations.feishu import __main__ as runner


def sqlite_error(code):
    error = sqlite3.OperationalError("private-db-path and secret SQL")
    error.sqlite_errorcode = code
    error.sqlite_errorname = "attacker-controlled-name"
    return error


@pytest.mark.parametrize("remove_code", [False, True], ids=["native", "python310-no-code"])
def test_native_busy_code_from_two_connections(tmp_path, remove_code):
    path = tmp_path / "private.db"
    with (
        closing(sqlite3.connect(path, timeout=0)) as first,
        closing(sqlite3.connect(path, timeout=0)) as second,
    ):
        first.execute("CREATE TABLE private_table (secret TEXT)")
        first.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError) as caught:
            second.execute("BEGIN IMMEDIATE")
        if remove_code and hasattr(caught.value, "sqlite_errorcode"):
            del caught.value.sqlite_errorcode
        if hasattr(caught.value, "sqlite_errorcode"):
            assert error_fields(caught.value) == {"sqlite_code": 5, "sqlite_primary": "SQLITE_BUSY"}
        else:
            assert error_fields(caught.value) == {"sqlite_code": None, "sqlite_primary": "UNKNOWN"}


@pytest.mark.parametrize(
    ("code", "primary"),
    [(5, "BUSY"), (517, "BUSY"), (6, "LOCKED"), (8, "READONLY"), (10, "IOERR"),
     (11, "CORRUPT"), (13, "FULL"), (0, "OTHER"), (2**31 - 1, "OTHER")],
)
def test_only_native_integer_code_determines_primary(code, primary):
    assert error_fields(sqlite_error(code)) == {
        "sqlite_code": code, "sqlite_primary": "SQLITE_" + primary,
    }


@pytest.mark.parametrize("code", [None, True, False, -1, 2**31, "5", 5.0, object()])
def test_invalid_codes_are_unknown(code):
    assert error_fields(sqlite_error(code)) == {"sqlite_code": None, "sqlite_primary": "UNKNOWN"}


def test_missing_code_and_non_sqlite_errors_are_unknown():
    for error in (sqlite3.OperationalError("secret"), RuntimeError("secret")):
        error.sqlite_errorname = "SQLITE_BUSY"
        assert error_fields(error) == {"sqlite_code": None, "sqlite_primary": "UNKNOWN"}
    error = RuntimeError("secret")
    error.sqlite_errorcode = 5
    assert error_fields(error) == {"sqlite_code": None, "sqlite_primary": "UNKNOWN"}


def worker_harness(monkeypatch, *, pending=None, handler_error=None, poll_error=None,
                   seconds=(0, 0.125), connection=None):
    storage = Mock(connection=connection or SimpleNamespace(in_transaction=False))
    stop = threading.Event()
    stop.wait = Mock(side_effect=lambda _delay: stop.set())
    ledger = Mock(storage=storage)
    ledger.pending_events.return_value = pending or []
    ledger.pending_events.side_effect = poll_error
    handler = Mock()
    def process(*_args):
        stop.set()
        if handler_error:
            raise handler_error
        return "completed"
    handler.process.side_effect = process
    monkeypatch.setattr(runner, "read_guard", lambda _path: None)
    monkeypatch.setattr(runner, "runtime_locks", lambda *_args: nullcontext())
    monkeypatch.setattr(runner, "IntelligenceStorage", lambda *_args, **_kwargs: nullcontext(storage))
    monkeypatch.setattr(runner, "_ledger", lambda *_args, **_kwargs: ledger)
    monkeypatch.setattr(runner, "FeishuHandler", lambda *_args, **_kwargs: handler)
    monkeypatch.setattr(runner, "build_gemini_client", lambda _settings: None)
    monkeypatch.setattr(runner, "build_assistant_service", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "RoleHeartbeat", Mock())
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=Mock(side_effect=seconds)))
    logger = Mock()
    monkeypatch.setattr(runner, "log", logger)
    settings = SimpleNamespace(intelligence_database_path="unused-private-path")
    return settings, stop, logger, ledger, handler


@pytest.mark.parametrize("stage", ["worker.pending_events", "worker.handler"])
def test_worker_errors_have_separate_stages_and_preserve_exception(monkeypatch, stage):
    error = sqlite_error(517)
    is_poll = stage == "worker.pending_events"
    settings, stop, logger, ledger, handler = worker_harness(
        monkeypatch, pending=None if is_poll else [("private-event", "private-binding")],
        poll_error=error if is_poll else None, handler_error=None if is_poll else error,
        seconds=(10, 10.125) if is_poll else (10, 10.125, 20, 20.125),
        connection=SimpleNamespace(in_transaction=True),
    )
    with pytest.raises(sqlite3.OperationalError) as caught:
        runner.run_worker_role(settings, SimpleNamespace(), None, stop)
    assert caught.value is error
    logger.error.assert_called_once_with(
        "Lark worker operation failed", stage=stage, elapsed_ms=125.0,
        transaction_open=True, error_type="OperationalError",
        sqlite_code=517, sqlite_primary="SQLITE_BUSY",
    )
    logger.warning.assert_not_called()
    ledger.pending_events.assert_called_once_with(recover=True, limit=1)
    if is_poll:
        handler.process.assert_not_called()


@pytest.mark.parametrize("connection_state", ["closed", "missing", "invalid"])
def test_unavailable_transaction_state_does_not_mask_original_error(monkeypatch, connection_state):
    if connection_state == "closed":
        connection = sqlite3.connect(":memory:")
        connection.close()
    elif connection_state == "missing":
        connection = SimpleNamespace()
    else:
        connection = SimpleNamespace(in_transaction="private-untrusted-state")
    error = ValueError("private content")
    settings, stop, logger, _, _ = worker_harness(
        monkeypatch, poll_error=error, connection=connection,
    )
    with pytest.raises(ValueError) as caught:
        runner.run_worker_role(settings, SimpleNamespace(), None, stop)
    assert caught.value is error
    assert logger.error.call_args.kwargs == {
        "stage": "worker.pending_events", "elapsed_ms": 125.0, "transaction_open": None,
        "error_type": "ValueError", "sqlite_code": None, "sqlite_primary": "UNKNOWN",
    }


def test_normal_empty_polls_do_not_log_or_change_wait(monkeypatch):
    settings, stop, logger, _, _ = worker_harness(monkeypatch)
    runner.run_worker_role(settings, SimpleNamespace(), None, stop)
    assert logger.mock_calls == []
    stop.wait.assert_called_once_with(runner.WORKER_POLL_SECONDS)


@pytest.mark.parametrize("pending,seconds,stage", [
    ([], (0, 5), "worker.pending_events"),
    ([("private-event", "private-binding")], (0, 0.1, 1, 6), "worker.handler"),
])
def test_successful_slow_operations_warn_once(monkeypatch, pending, seconds, stage):
    settings, stop, logger, _, _ = worker_harness(monkeypatch, pending=pending, seconds=seconds)
    runner.run_worker_role(settings, SimpleNamespace(), None, stop)
    logger.warning.assert_called_once_with(
        "Lark worker operation slow", stage=stage, elapsed_ms=5000.0, transaction_open=False,
    )
    logger.error.assert_not_called()
    logger.info.assert_not_called()


@pytest.mark.parametrize("role,effective", [
    ("worker", "worker"), ("scheduler-once", "scheduler"), ("bot", "bot"),
    ("combined", "combined"),
])
def test_main_failure_keeps_exit_and_adds_effective_role(monkeypatch, role, effective):
    error = sqlite_error(6)
    settings = SimpleNamespace(intelligence_enabled=True, intelligence_database_path="unused")
    config = SimpleNamespace(enabled=True, app_id="private", app_secret="secret",
                             request_timeout_seconds=1, api_domain="private")
    monkeypatch.setattr(runner, "load_settings", lambda _path: settings)
    monkeypatch.setattr(runner.FeishuConfig, "from_settings", lambda _settings: config)
    monkeypatch.setattr(runner, "_validate", lambda *_args: None)
    monkeypatch.setattr(runner, "read_guard", lambda _path: None)
    # Fail before role dispatch, with no actual client or provider access.
    monkeypatch.setattr(runner.FeishuClient, "from_credentials", Mock(side_effect=error))
    monkeypatch.setattr(runner.FeishuClient, "deferred_for_scheduler", Mock(side_effect=error))
    logger = Mock()
    monkeypatch.setattr(runner, "log", logger)
    assert runner.main(["--role", role]) == 1
    logger.error.assert_called_once_with(
        "Lark runner unavailable; no legacy pipeline was changed", error_type="OperationalError",
        role=effective, sqlite_code=6, sqlite_primary="SQLITE_LOCKED",
    )
