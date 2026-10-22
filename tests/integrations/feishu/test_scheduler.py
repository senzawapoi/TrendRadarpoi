"""Persistent per-window success and partial-send checkpoints with a fake clock."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from trendradar.integrations.feishu.config import FeishuConfig
from trendradar.integrations.feishu.scheduler import DeliveryScheduler, window_key

NOW = datetime(2026, 9, 12, 0, 30, tzinfo=timezone.utc)
CONFIG = FeishuConfig(
    enabled=True,
    delivery_enabled=True,
    delivery_target="chat",
    delivery_time="08:00",
    delivery_end="09:00",
)


def test_shanghai_window_edges_and_overnight_date_identity():
    assert window_key(CONFIG, NOW - timedelta(minutes=31)) is None
    assert window_key(CONFIG, NOW - timedelta(minutes=30))
    assert window_key(CONFIG, NOW + timedelta(minutes=30))
    assert window_key(CONFIG, NOW + timedelta(minutes=31)) is None
    overnight = replace(CONFIG, delivery_time="23:00", delivery_end="01:00")
    before = datetime(2026, 9, 12, 15, 30, tzinfo=timezone.utc)
    assert window_key(overnight, before) == window_key(overnight, before + timedelta(hours=1))
    assert window_key(overnight, before + timedelta(hours=2)) is None


def test_duplicate_ticks_restart_and_new_day(tmp_path):
    path = tmp_path / "test.db"
    client, delivery = (
        Mock(send=Mock(return_value=True)),
        Mock(prepare=Mock(return_value=("daily",))),
    )
    first = DeliveryScheduler(CONFIG, path, delivery, client, clock=lambda: NOW)
    assert first.tick() == "sent"
    assert first.tick() == "already_claimed"
    first.close()
    second = DeliveryScheduler(CONFIG, path, delivery, client, clock=lambda: NOW)
    assert second.tick() == "already_claimed"
    assert client.send.call_count == 1 and delivery.prepare.call_count == 1
    assert second.tick(NOW + timedelta(days=1)) == "sent"
    assert client.send.call_count == 2
    second.close()


def test_partial_failure_retry_resumes_saved_chunks_not_regenerated_output(tmp_path):
    client = Mock(send=Mock(side_effect=[True, False, True]))
    delivery = Mock(prepare=Mock(return_value=("first", "second")))
    path = tmp_path / "test.db"
    first = DeliveryScheduler(CONFIG, path, delivery, client, clock=lambda: NOW)
    assert first.tick() == "send_failed"
    first.close()
    second = DeliveryScheduler(
        CONFIG,
        path,
        Mock(prepare=Mock(side_effect=AssertionError("regenerated"))),
        client,
        clock=lambda: NOW,
    )
    assert second.tick() == "sent"
    calls = client.send.call_args_list
    assert [call.args[1] for call in calls] == ["first", "second", "second"]
    assert calls[1].kwargs["message_uuid"] == calls[2].kwargs["message_uuid"]
    assert second.tick() == "already_claimed"
    second.close()


def test_empty_and_failed_output_do_not_consume_window(tmp_path):
    client = Mock(send=Mock(return_value=True))
    delivery = Mock(prepare=Mock(side_effect=[(), RuntimeError("offline"), ("ready",)]))
    scheduler = DeliveryScheduler(CONFIG, tmp_path / "test.db", delivery, client, clock=lambda: NOW)
    assert scheduler.tick() == "empty"
    assert scheduler.tick() == "unavailable"
    assert not client.send.called
    assert scheduler.tick() == "sent"
    scheduler.close()


def test_concurrent_claims_and_disabled_scheduler(tmp_path):
    path = tmp_path / "test.db"
    client, delivery = Mock(), Mock()
    first = DeliveryScheduler(CONFIG, path, delivery, client, clock=lambda: NOW)
    second = DeliveryScheduler(CONFIG, path, delivery, client, clock=lambda: NOW)
    assert first._claim(window_key(CONFIG, NOW), NOW)
    assert second.tick() == "already_claimed"
    assert not client.send.called and not delivery.prepare.called
    second.config = replace(CONFIG, enabled=False)
    assert second.tick() == "disabled"
    first.close()
    second.close()
