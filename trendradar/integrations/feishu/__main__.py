"""Opt-in Lark runtime with combined and independently deployable roles."""

from __future__ import annotations

import argparse
import asyncio
import queue
import threading
import time
from contextlib import ExitStack
from typing import Any

from trendradar.core.heartbeat import RoleHeartbeat
from trendradar.core.locking import LockUnavailable, runtime_locks
from trendradar.core.settings import load_settings
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops.maintenance import read_guard
from trendradar.utils.logging import log

from .client import FeishuClient
from .config import FeishuConfig
from .delivery import StoryDelivery
from .handler import FeishuHandler
from .ledger import EventLedger
from .models import stable_digest
from .scheduler import DeliveryScheduler
from .transport import FeishuTransport, SdkConnection

EVENT_QUEUE_CAPACITY = 32
WORKER_POLL_SECONDS = 0.75


def _require_existing(settings) -> bool:
    value = getattr(settings, "intelligence_require_existing", False)
    return value if isinstance(value, bool) else False


def _synchronous(settings) -> str:
    value = getattr(settings, "intelligence_sqlite_synchronous", "FULL")
    value = value.upper() if isinstance(value, str) else "FULL"
    return value if value in {"OFF", "NORMAL", "FULL", "EXTRA"} else "FULL"


def _actual_synchronous(storage, settings) -> str:
    policy = getattr(storage, "connection_policy", {})
    value = policy.get("sqlite_synchronous") if isinstance(policy, dict) else None
    return value if value in {"OFF", "NORMAL", "FULL", "EXTRA"} else _synchronous(settings)


# Lazy wrappers preserve the old module-level seams used by tests and keep the
# Bot process from importing Assistant, Gemini, or research integrations.
def build_gemini_client(settings):
    from trendradar.ai.client import build_gemini_client as factory

    return factory(settings)


def build_assistant_service(settings, **kwargs):
    from trendradar.ai.assistant import build_assistant_service as factory

    return factory(settings, **kwargs)


def build_digest_analyzer(gemini):
    from trendradar.ai.analyzer import DailyDigestAnalyzer

    return DailyDigestAnalyzer(gemini)


def _ledger(settings, config, *, storage=None) -> EventLedger:
    return EventLedger(
        settings.intelligence_database_path,
        lease_seconds=config.event_lease_seconds,
        max_pending_events=EVENT_QUEUE_CAPACITY,
        delivery_retry_base_seconds=config.delivery_retry_base_seconds,
        delivery_retry_max_seconds=config.delivery_retry_max_seconds,
        require_existing=_require_existing(settings),
        synchronous=_synchronous(settings),
        storage=storage,
    )


def _intake_callback(normalizer, intake_ledger):
    """Build a callback that persists before returning to the SDK."""

    def callback(payload: Any) -> None:
        if read_guard(intake_ledger.storage.db_path) is not None:
            raise RuntimeError("runtime is in maintenance mode")
        prepared = normalizer.prepare(payload)
        if prepared is None:
            return
        event, binding = prepared
        scope = stable_digest(binding.principal_id, binding.session_id, event.message_id)
        # A completed duplicate is deliberately a successful no-op.  Raising
        # here would ask the provider to redeliver an event already handled.
        intake_ledger.record(event, binding, scope)

    return callback


def run_worker(settings, config, client, inbox, stop, failure=None):
    """Run the legacy combined-mode worker and its one in-process scheduler."""
    try:
        with ExitStack() as stack:
            storage = stack.enter_context(
                IntelligenceStorage(
                    settings.intelligence_database_path,
                    synchronous=_synchronous(settings),
                    allow_create=not _require_existing(settings),
                    allow_migrate=not _require_existing(settings),
                )
            )
            gemini = build_gemini_client(settings)
            assistant = build_assistant_service(settings, storage=storage, gemini_client=gemini)
            if assistant:
                stack.callback(assistant.close)
            ledger = _ledger(settings, config, storage=storage)
            stack.callback(ledger.close)
            handler = FeishuHandler(config, client, assistant, ledger=ledger)
            delivery = StoryDelivery(
                storage,
                max_stories=config.delivery_max_stories,
                digest_analyzer=build_digest_analyzer(gemini) if gemini else None,
            )
            scheduler = DeliveryScheduler(
                config,
                settings.intelligence_database_path,
                delivery,
                client,
                storage=storage,
            )
            stack.callback(scheduler.close)
            next_tick = 0.0
            next_recovery_poll = 0.0
            while not stop.is_set():
                if time.monotonic() >= next_tick:
                    scheduler.tick()
                    next_tick = time.monotonic() + 60
                try:
                    event, binding = inbox.get(timeout=0.5)
                except queue.Empty:
                    if time.monotonic() >= next_recovery_poll:
                        durable = ledger.pending_events(recover=False, limit=1)
                        next_recovery_poll = time.monotonic() + 0.5
                        if durable:
                            handler.process(*durable[0])
                    continue
                try:
                    handler.process(event, binding)
                finally:
                    inbox.task_done()
    except Exception as error:
        log.error("Lark local worker unavailable", error_type=type(error).__name__)
        if failure is not None:
            failure.append(error)
        stop.set()


async def _run_combined(settings, config, client):
    inbox, stop = queue.Queue(maxsize=EVENT_QUEUE_CAPACITY), threading.Event()
    worker_failure = []
    normalizer = FeishuHandler(config, client, None)
    intake_ledger = _ledger(settings, config)
    callback = _intake_callback(normalizer, intake_ledger)
    worker = threading.Thread(
        target=run_worker,
        args=(settings, config, client, inbox, stop, worker_failure),
        name="feishu-worker",
        daemon=True,
    )
    for prepared in intake_ledger.pending_events(limit=EVENT_QUEUE_CAPACITY):
        try:
            inbox.put_nowait(prepared)
        except queue.Full:
            break
    worker.start()
    transport = FeishuTransport(config, lambda: SdkConnection(config, callback))
    task = asyncio.create_task(transport.run())
    try:
        previous = None
        while not stop.is_set() and not task.done():
            if transport.state != previous:
                log.info("Lark connection state", state=transport.state)
                previous = transport.state
            await asyncio.sleep(0.5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        stop.set()
        await asyncio.to_thread(worker.join, config.request_timeout_seconds + 5)
        if worker.is_alive():
            log.warning("Lark local worker did not stop before shutdown deadline")
        intake_ledger.close()
        if worker_failure:
            raise RuntimeError("Lark local worker failed") from worker_failure[0]
        if task.done() and not task.cancelled():
            error = task.exception()
            if error is not None:
                raise RuntimeError("Lark transport failed") from error


async def run_bot(settings, config, client):
    """Compatibility combined mode; all three local roles are held together."""
    if read_guard(settings.intelligence_database_path) is not None:
        raise RuntimeError("runtime is in maintenance mode")
    with runtime_locks(settings.intelligence_database_path, "bot", "scheduler", "worker"):
        await _run_combined(settings, config, client)


async def run_bot_role(settings, config, client):
    """Persist authorized events and own the only Lark WebSocket connection."""
    if read_guard(settings.intelligence_database_path) is not None:
        raise RuntimeError("runtime is in maintenance mode")
    with runtime_locks(settings.intelligence_database_path, "bot"):
        intake_ledger = _ledger(settings, config)
        heartbeat = RoleHeartbeat("bot", settings.intelligence_database_path)
        task = None
        try:
            normalizer = FeishuHandler(config, client, None)
            callback = _intake_callback(normalizer, intake_ledger)
            transport = FeishuTransport(config, lambda: SdkConnection(config, callback))
            task = asyncio.create_task(transport.run())
            while not task.done():
                heartbeat.write(
                    state=getattr(transport, "state", "running"),
                    sqlite_synchronous=_actual_synchronous(intake_ledger.storage, settings),
                )
                await asyncio.sleep(5)
            await task
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            heartbeat.stop()
            intake_ledger.close()


def run_worker_role(settings, config, client, stop=None, *, poll_seconds=WORKER_POLL_SECONDS):
    """Consume durable events without opening a WebSocket or running Scheduler."""
    if read_guard(settings.intelligence_database_path) is not None:
        raise RuntimeError("runtime is in maintenance mode")
    stop = stop or threading.Event()
    heartbeat = RoleHeartbeat("worker", settings.intelligence_database_path)
    with runtime_locks(settings.intelligence_database_path, "worker"), ExitStack() as stack:
        try:
            storage = stack.enter_context(
                IntelligenceStorage(
                    settings.intelligence_database_path,
                    synchronous=_synchronous(settings),
                    allow_create=not _require_existing(settings),
                    allow_migrate=not _require_existing(settings),
                )
            )
            gemini = build_gemini_client(settings)
            assistant = build_assistant_service(settings, storage=storage, gemini_client=gemini)
            if assistant:
                stack.callback(assistant.close)
            ledger = _ledger(settings, config, storage=storage)
            stack.callback(ledger.close)
            handler = FeishuHandler(config, client, assistant, ledger=ledger)
            heartbeat.write(
                state="running",
                sqlite_synchronous=_actual_synchronous(storage, settings),
            )
            while not stop.is_set():
                if read_guard(settings.intelligence_database_path) is not None:
                    heartbeat.write(
                        state="maintenance",
                        sqlite_synchronous=_actual_synchronous(storage, settings),
                    )
                    break
                heartbeat.write(
                    state="running",
                    sqlite_synchronous=_actual_synchronous(storage, settings),
                )
                pending = ledger.pending_events(recover=True, limit=1)
                if pending:
                    result = handler.process(*pending[0])
                    heartbeat.write(
                        state="running",
                        last_result=result,
                        sqlite_synchronous=_actual_synchronous(storage, settings),
                    )
                    continue
                stop.wait(max(0.1, min(10.0, poll_seconds)))
        finally:
            heartbeat.stop()


def run_scheduler_once(settings, config, client) -> str:
    """Execute one durable daily-delivery tick and return its status."""
    heartbeat = RoleHeartbeat("scheduler", settings.intelligence_database_path)
    if read_guard(settings.intelligence_database_path) is not None:
        heartbeat.write(
            state="maintenance",
            sqlite_synchronous=_synchronous(settings),
        )
        heartbeat.stop(reason="maintenance")
        return "maintenance"
    with runtime_locks(settings.intelligence_database_path, "scheduler"), ExitStack() as stack:
        try:
            storage = stack.enter_context(
                IntelligenceStorage(
                    settings.intelligence_database_path,
                    synchronous=_synchronous(settings),
                    allow_create=not _require_existing(settings),
                    allow_migrate=not _require_existing(settings),
                )
            )
            heartbeat.write(
                state="running",
                sqlite_synchronous=_actual_synchronous(storage, settings),
            )
            delivery = StoryDelivery(storage, max_stories=config.delivery_max_stories)
            scheduler = DeliveryScheduler(
                config,
                settings.intelligence_database_path,
                delivery,
                client,
                storage=storage,
            )
            stack.callback(scheduler.close)
            result = scheduler.tick()
            heartbeat.write(
                state="completed",
                last_result=result,
                sqlite_synchronous=_actual_synchronous(storage, settings),
            )
            return result
        finally:
            heartbeat.stop()


def _validate(config: FeishuConfig, settings, role: str) -> str | None:
    if not config.enabled or not settings.intelligence_enabled:
        return None
    if not config.app_id or not config.app_secret:
        return "Lark requires environment credentials."
    if role == "bot" and not config.identity_fields:
        return "Lark Bot requires an identity allowlist."
    if role == "bot" and "group" in config.allowed_chat_types and not config.bot_id:
        return "LARK_BOT_ID is required for mentioned group messages."
    if role == "scheduler" and config.delivery_enabled and not config.delivery_target:
        return "LARK_DELIVERY_TARGET is required for daily delivery."
    if role == "combined" and not config.identity_fields:
        return "Lark requires an identity allowlist."
    if role == "combined" and "group" in config.allowed_chat_types and not config.bot_id:
        return "LARK_BOT_ID is required for mentioned group messages."
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the opt-in Lark intelligence assistant")
    parser.add_argument("--config", help="YAML path; defaults to CONFIG_PATH or config/config.yaml")
    parser.add_argument(
        "--role",
        choices=("combined", "bot", "worker", "scheduler-once"),
        default="combined",
        help="Runtime role; the default combined mode preserves the local/UAT entry point",
    )
    parser.add_argument(
        "--check", action="store_true", help="Validate configuration without network or database writes"
    )
    args = parser.parse_args(argv)
    role = "scheduler" if args.role == "scheduler-once" else args.role
    settings = load_settings(args.config)
    config = FeishuConfig.from_settings(settings)
    error = _validate(config, settings, role)
    if not config.enabled or not settings.intelligence_enabled:
        print("Lark disabled; existing pipelines are unchanged.")
        return 0
    if error:
        print(error)
        return 2
    if args.check:
        print(f"Lark {role} configuration is ready; no network or storage was accessed.")
        return 0
    if read_guard(settings.intelligence_database_path) is not None:
        print("Lark runtime is in maintenance mode.")
        return 1
    try:
        client = FeishuClient.from_credentials(
            config.app_id,
            config.app_secret,
            timeout_seconds=config.request_timeout_seconds,
            api_domain=config.api_domain,
        )
        if not client.available:
            print("The official Lark SDK is unavailable.")
            return 2
        if args.role == "combined":
            asyncio.run(run_bot(settings, config, client))
        elif args.role == "bot":
            asyncio.run(run_bot_role(settings, config, client))
        elif args.role == "worker":
            run_worker_role(settings, config, client)
        else:
            print(f"Lark scheduler result: {run_scheduler_once(settings, config, client)}")
    except LockUnavailable as exc:
        print(f"Lark role is already running: {exc}")
        return 3
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        log.error(
            "Lark runner unavailable; no legacy pipeline was changed",
            error_type=type(exc).__name__,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
