"""Fake-clock connection cooldown and cancellation without live WebSockets."""

import asyncio

import pytest

from trendradar.integrations.feishu.config import FeishuConfig
from trendradar.integrations.feishu.transport import FeishuTransport, SdkConnection


def test_retry_threshold_cooldown_and_single_owner():
    async def scenario():
        delays, connections = [], []

        class Connection:
            async def connect(self):
                connections.append(self)
                with pytest.raises(RuntimeError, match="already running"):
                    await transport.run()
                raise ConnectionError("sensitive-provider-error")

            async def close(self):
                pass

        async def sleep(delay):
            delays.append((transport.state, delay))
            if len(delays) == 4:
                raise asyncio.CancelledError

        transport = FeishuTransport(
            FeishuConfig(reconnect_attempts=3, cooldown_seconds=10),
            Connection,
            sleep=sleep,
            jitter=lambda: 0,
        )
        with pytest.raises(asyncio.CancelledError):
            await transport.run()
        assert delays == [("retrying", 1), ("retrying", 2), ("cooldown", 10), ("retrying", 1)]
        assert transport.state == "stopped" and len(connections) == 4

    asyncio.run(scenario())


def test_only_stable_connection_resets_failures_and_cancel_closes():
    async def scenario():
        now, closed, calls = [0], [], []

        class Connection:
            async def connect(self):
                calls.append(1)

            async def wait_closed(self):
                now[0] += 61

            async def close(self):
                closed.append(True)

        async def sleep(delay):
            assert transport.failures == 1 and delay == 1
            if len(calls) == 2:
                raise asyncio.CancelledError

        transport = FeishuTransport(
            FeishuConfig(reconnect_attempts=2),
            Connection,
            clock=lambda: now[0],
            sleep=sleep,
            jitter=lambda: 0,
        )
        with pytest.raises(asyncio.CancelledError):
            await transport.run()
        assert len(closed) == 2

    asyncio.run(scenario())


def test_sdk_connection_cleans_cache_and_ping_tasks(monkeypatch):
    pytest.importorskip("lark_oapi")
    import lark_oapi.ws.client as ws

    async def connect(client):
        assert client._auto_reconnect is False

    monkeypatch.setattr(ws.Client, "_connect", connect)

    async def scenario():
        baseline = asyncio.all_tasks()
        connection = SdkConnection(
            FeishuConfig(app_id="test", app_secret="test"), lambda event: None
        )
        await connection.connect()
        assert len(connection.tasks) == 2
        await connection.close()
        await asyncio.sleep(0)
        assert not connection.tasks
        assert asyncio.all_tasks() == baseline

    asyncio.run(scenario())


def test_sdk_endpoint_discovery_timeout_and_server_config(monkeypatch):
    import json
    from unittest.mock import Mock

    pytest.importorskip("lark_oapi")
    import lark_oapi.ws.client as ws
    import requests

    body = {
        "code": 0,
        "data": {
            "URL": "wss://example.invalid/connection",
            "ClientConfig": {
                "ReconnectCount": -1,
                "ReconnectInterval": 1,
                "ReconnectNonce": 0,
                "PingInterval": 10,
            },
        },
    }
    response = Mock(status_code=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [json.dumps(body).encode()]
    post = Mock(return_value=response)
    monkeypatch.setattr(requests, "post", post)

    async def connect(client):
        assert client._get_conn_url() == "wss://example.invalid/connection"
        assert client._auto_reconnect is False

    monkeypatch.setattr(ws.Client, "_connect", connect)

    async def scenario():
        connection = SdkConnection(
            FeishuConfig(app_id="test", app_secret="test", request_timeout_seconds=2),
            lambda event: None,
        )
        await connection.connect()
        await connection.close()

    asyncio.run(scenario())
    assert post.call_args.kwargs["timeout"] == 2
    assert post.call_args.kwargs["allow_redirects"] is False
    assert post.call_args.args[0].startswith("https://open.larksuite.com/")
