"""Official Lark SDK WebSocket lifecycle with one bounded reconnect owner."""

from __future__ import annotations

import asyncio
import random
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from .config import FeishuConfig


def build_dispatcher(callback: Callable[[Any], None]):
    import lark_oapi as lark

    return (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(callback)
        .build()
    )


class SdkConnection:
    """Version-pinned SDK lifecycle bridge. No WebSocket framing is implemented here."""

    def __init__(self, config: FeishuConfig, callback: Callable[[Any], None]) -> None:
        self.config, self.callback = config, callback
        self.client = None
        self.tasks: set[asyncio.Task] = set()

    async def connect(self) -> None:
        import lark_oapi as lark
        import lark_oapi.ws.client as ws
        import requests

        config, tasks = self.config, self.tasks
        ws.loop = asyncio.get_running_loop()

        class BoundedSdkClient(ws.Client):
            def _get_conn_url(self):
                # SDK 1.7.3 has no endpoint-discovery timeout. Keep its DTO and
                # server configuration, while bounding the fixed HTTP handshake.
                with requests.post(
                    self._domain + ws.GEN_ENDPOINT_URI,
                    json={"AppID": self._app_id, "AppSecret": self._app_secret},
                    headers={"User-Agent": self._user_agent, "locale": "zh"},
                    timeout=config.request_timeout_seconds,
                    stream=True,
                    allow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        raise ConnectionError("Lark endpoint unavailable")
                    data = bytearray()
                    deadline = time.monotonic() + config.request_timeout_seconds
                    for chunk in response.iter_content(4096):
                        if len(data) + len(chunk) > 65536 or time.monotonic() > deadline:
                            raise ConnectionError("Lark endpoint response exceeded bounds")
                        data.extend(chunk)
                result = ws.JSON.unmarshal(bytes(data).decode("utf-8"), ws.EndpointResp)
                if result.code != 0 or not result.data or not result.data.URL:
                    raise ConnectionError("Lark endpoint rejected connection")
                if result.data.ClientConfig:
                    self._configure(result.data.ClientConfig)
                return result.data.URL

            async def _receive_message_loop(self):
                task = asyncio.current_task()
                tasks.add(task)
                try:
                    await super()._receive_message_loop()
                except Exception:
                    pass
                finally:
                    tasks.discard(task)

            async def _handle_message(self, message):
                task = asyncio.current_task()
                tasks.add(task)
                try:
                    await super()._handle_message(message)
                finally:
                    tasks.discard(task)

        self.client = BoundedSdkClient(
            config.app_id,
            config.app_secret,
            event_handler=build_dispatcher(self.callback),
            domain=config.api_domain,
            auto_reconnect=False,
            log_level=lark.LogLevel.ERROR,
        )
        self.tasks.add(self.client._cache._cron)
        # The SDK logs connection URLs and event payloads on its own logger.
        # Suppress that logger; the outer lifecycle exposes sanitized state only.
        ws.logger.disabled = True
        await asyncio.wait_for(self.client._connect(), config.request_timeout_seconds)
        self.tasks.add(asyncio.create_task(self.client._ping_loop()))

    async def wait_closed(self) -> None:
        while self.client and self.client._conn is not None:
            await asyncio.sleep(0.25)

    async def close(self) -> None:
        for task in tuple(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        self.tasks.clear()
        if self.client:
            await self.client._disconnect()
            self.client = None


class FeishuTransport:
    _owner = threading.Lock()

    def __init__(
        self,
        config: FeishuConfig,
        connection_factory: Callable[[], Any],
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.config, self.factory = config, connection_factory
        self.clock, self.sleep, self.jitter = clock, sleep, jitter
        self.state = "stopped"
        self.failures = 0
        self._running = False

    async def run(self) -> None:
        if self._running or not self._owner.acquire(blocking=False):
            raise RuntimeError("Feishu transport is already running")
        self._running = True
        try:
            while True:
                connection = self.factory()
                connected_at = None
                self.state = "connecting"
                try:
                    await connection.connect()
                    connected_at = self.clock()
                    self.state = "connected"
                    await connection.wait_closed()
                except Exception:
                    pass
                finally:
                    with suppress(Exception):
                        await asyncio.wait_for(
                            connection.close(), self.config.request_timeout_seconds
                        )
                if connected_at is not None and self.clock() - connected_at >= 60:
                    self.failures = 0
                self.failures += 1
                if self.failures >= self.config.reconnect_attempts:
                    self.state = "cooldown"
                    await self.sleep(self.config.cooldown_seconds)
                    self.failures = 0
                else:
                    self.state = "retrying"
                    await self.sleep(min(60, 2 ** (self.failures - 1)) + self.jitter())
        finally:
            self._running = False
            self.state = "stopped"
            self._owner.release()
