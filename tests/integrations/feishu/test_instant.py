"""Offline instant outbox acceptance, including process and restore boundaries."""

import json
import subprocess
import sys
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from trendradar.core.models import ContentItem, Story, deterministic_story_id
from trendradar.integrations.feishu.config import FeishuConfig
from trendradar.integrations.feishu.delivery import StoryDelivery
from trendradar.integrations.feishu.instant import InstantDeliveryScheduler
from trendradar.integrations.feishu.models import stable_digest
from trendradar.integrations.feishu.scheduler import DeliveryScheduler
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops.backup import activate_restore, create_snapshot, restore_snapshot
from trendradar.ops.maintenance import clear_guard, recovery_cutover_path, set_guard

NOW = datetime(2026, 10, 23, 4, tzinfo=timezone.utc)
CONFIG = FeishuConfig(
    enabled=True, delivery_enabled=True, delivery_mode="instant", delivery_target="chat",
    delivery_time="08:00", delivery_end="09:00",
)


def seed(storage, count=1, *, offset=0, persisted=NOW, long=False):
    stories = []
    for index in range(offset, offset + count):
        item = ContentItem.create(
            title=f"Story {index:03d} marker", content="evidence", source="rss:test",
            url=f"https://example.test/{index}", domain="general",
            collected_at=NOW - timedelta(days=300),
        )
        storage.write_batch([item])
        story = Story(
            id=deterministic_story_id(item.id), identity_key=item.id, title=item.title,
            summary="x" * 2000 if long else "original summary", domain="general",
            member_ids=[item.id], event_time=item.collected_at, last_activity_at=item.collected_at,
        )
        if long:
            story.title += "z" * 980
            story.importance.reasons = [str(i) + "y" * 499 for i in range(5)]
        storage.upsert_story_batch([], [story])
        storage.connection.execute(
            "UPDATE stories SET created_at=? WHERE id=?", (persisted.isoformat(), story.id)
        )
        stories.append(story)
    return stories


def scheduler(storage, client=None, *, config=CONFIG, delivery=None, clock=lambda: NOW):
    return DeliveryScheduler(
        config, storage.db_path, delivery or StoryDelivery(storage),
        client or Mock(send=Mock(return_value=True)), storage=storage, clock=clock,
    )


def test_first_persistence_not_event_date_edits_reobservations_and_restart(tmp_path):
    path = tmp_path / "intelligence.db"
    client = Mock(send=Mock(return_value=True))
    with IntelligenceStorage(path) as storage:
        story = seed(storage)[0]
        assert scheduler(storage, client).tick() == "sent"  # Outside the daily window.
        story.title = "edited title"
        story.event_time -= timedelta(days=10)
        storage.write_batch(storage.list_story_items(story.id))
        storage.upsert_story_batch([], [story])
        assert storage.connection.execute("SELECT created_at FROM stories").fetchone()[0] == NOW.isoformat()
        assert scheduler(storage, client).tick() == "empty"
    with IntelligenceStorage.open_existing(path) as storage:
        assert scheduler(storage, client).tick() == "empty"
        assert storage.connection.execute("SELECT COUNT(*) FROM feishu_deliveries").fetchone()[0] == 0
    assert client.send.call_count == 1


def test_overflow_is_retained_and_target_story_identity_is_durable(tmp_path):
    client = Mock(send=Mock(return_value=True))
    with IntelligenceStorage(tmp_path / "db") as storage:
        seed(storage, 45)
        run = scheduler(storage, client, config=replace(CONFIG, delivery_max_stories=100))
        for expected in (20, 40, 45):
            assert run.tick() == "sent"
            assert storage.connection.execute("SELECT COUNT(*) FROM lark_story_deliveries").fetchone()[0] == expected
        assert run.tick() == "empty"
        sizes = storage.connection.execute(
            "SELECT COUNT(*) FROM lark_story_deliveries GROUP BY delivery_key"
        ).fetchall()
        assert sorted(row[0] for row in sizes) == [5, 20, 20]
        sent = "".join(call.args[1] for call in client.send.call_args_list)
        assert all(f"Story {i:03d} marker" in sent for i in range(45))
        assert scheduler(storage, config=replace(CONFIG, delivery_target="other")).tick() == "sent"
        assert storage.connection.execute("SELECT COUNT(*) FROM lark_story_deliveries").fetchone()[0] == 65


def test_late_story_after_a_completed_batch_is_not_hidden_by_updated_at(tmp_path):
    with IntelligenceStorage(tmp_path / "db") as storage:
        seed(storage)
        run = scheduler(storage)
        assert run.tick() == "sent"
        seed(storage, offset=1, persisted=NOW - timedelta(days=1))
        assert run.tick() == "sent"
        assert run.tick() == "empty"


def test_long_batch_contains_every_registered_story_without_digest_provider(tmp_path):
    with IntelligenceStorage(tmp_path / "db") as storage:
        seed(storage, 20, long=True)
        digest = Mock(analyze=Mock(side_effect=AssertionError("provider not allowed")))
        delivery = StoryDelivery(storage, digest_analyzer=digest)
        run = scheduler(storage, delivery=delivery)
        assert run.tick() == "sent"
        batch = storage.connection.execute("SELECT * FROM lark_instant_batches").fetchone()
        chunks = json.loads(batch["chunks_json"])
        assert len(chunks) > 1
        assert len("".join(chunks)) > 100_000
        assert all(f"Story {i:03d} marker" in "".join(chunks) for i in range(20))
        digest.analyze.assert_not_called()


def test_snapshot_committed_before_send_and_retry_uses_original_chunks_and_uuid(tmp_path):
    path = tmp_path / "db"
    delivery = Mock(prepare_stories=Mock(return_value=("first", "second")))
    observed = []

    def send(target, text, **kwargs):
        with IntelligenceStorage.open_existing(path) as reader:
            row = reader.connection.execute("SELECT * FROM lark_instant_batches").fetchone()
            assert json.loads(row["chunks_json"]) == ["first", "second"]
            assert reader.connection.execute("SELECT COUNT(*) FROM lark_story_deliveries").fetchone()[0] == 1
        observed.append((target, text, kwargs["message_uuid"]))
        return text != "second" or len(observed) == 3

    client = Mock(send=Mock(side_effect=send))
    with IntelligenceStorage(path) as storage:
        story = seed(storage)[0]
        assert scheduler(storage, client, delivery=delivery).tick() == "send_failed"
        story.title = "edited after failure"
        storage.upsert_story_batch([], [story])
    with IntelligenceStorage.open_existing(path) as storage:
        forbidden = Mock(prepare_stories=Mock(side_effect=AssertionError("regenerated")))
        assert scheduler(storage, client, delivery=forbidden).tick() == "sent"
        forbidden.prepare_stories.assert_not_called()
        row = storage.connection.execute("SELECT * FROM lark_instant_batches").fetchone()
        assert row["next_chunk"] == 2 and row["attempts"] == 2
        assert row["last_error"] == ""
    assert [item[1] for item in observed] == ["first", "second", "second"]
    assert observed[1] == observed[2]


@pytest.mark.parametrize("accepted", [False, True])
def test_crash_before_send_or_after_acceptance_recovers_saved_payload(tmp_path, accepted):
    path = tmp_path / "db"
    client = Mock(send=Mock(return_value=True))
    with IntelligenceStorage(path) as storage:
        seed(storage)
        instant = InstantDeliveryScheduler(
            CONFIG, storage, Mock(prepare_stories=Mock(return_value=("frozen",))), client,
            lock=threading.RLock(), clock=lambda: NOW,
        )
        result, row = instant._claim(NOW)
        assert result == "claimed"
        if accepted:
            # Simulate an accepted provider send followed by death before local checkpoint.
            client.send("chat", "frozen", message_uuid=stable_digest("instant", row["delivery_key"], "0"))
    with IntelligenceStorage.open_existing(path) as storage:
        forbidden = Mock(prepare_stories=Mock(side_effect=AssertionError("regenerated")))
        run = scheduler(storage, client, delivery=forbidden)
        assert run.tick() == "already_claimed"
        run.clock = lambda: NOW + timedelta(seconds=121)
        assert run.tick() == "sent"
        assert run.tick() == "empty"
    assert client.send.call_count == (2 if accepted else 1)
    if accepted:
        assert client.send.call_args_list[0] == client.send.call_args_list[1]


def test_concurrent_schedulers_only_one_claim_and_stale_owner_is_fenced(tmp_path):
    path = tmp_path / "db"
    gate = threading.Barrier(2)
    with IntelligenceStorage(path) as first, IntelligenceStorage(path) as second:
        seed(first)
        client = Mock(send=Mock(return_value=True))
        runs = [scheduler(store, client) for store in (first, second)]

        def tick(run):
            gate.wait(timeout=5)
            return run.tick()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(tick, runs))
        assert results.count("sent") == 1
        assert set(results) <= {"sent", "empty", "already_claimed"}
        assert client.send.call_count == 1
        seed(first, offset=1)
        old = InstantDeliveryScheduler(CONFIG, first, StoryDelivery(first), client,
                                       lock=threading.RLock(), clock=lambda: NOW)
        _, row = old._claim(NOW)
        later = NOW + timedelta(seconds=121)
        new = InstantDeliveryScheduler(CONFIG, second, StoryDelivery(second), client,
                                       lock=threading.RLock(), clock=lambda: later)
        _, replacement = new._claim(later)
        assert replacement["owner"] != row["owner"]
        assert not old._renew(row["delivery_key"], row["owner"])
        assert not old._update(row["delivery_key"], row["owner"], "status='completed'")


def test_maintenance_prevents_registration_and_stops_between_chunks(tmp_path):
    with IntelligenceStorage(tmp_path / "db") as storage:
        seed(storage)
        set_guard(storage.db_path, reason="test")
        client = Mock(send=Mock(return_value=True))
        delivery = Mock(prepare_stories=Mock(return_value=("first", "second")))
        run = scheduler(storage, client, delivery=delivery)
        assert run.tick() == "maintenance"
        delivery.prepare_stories.assert_not_called()
        clear_guard(storage.db_path)

        def send(*args, **kwargs):
            set_guard(storage.db_path, reason="test")
            return True

        client.send.side_effect = send
        assert run.tick() == "maintenance"
        assert client.send.call_count == 1
        clear_guard(storage.db_path)
        client.send.side_effect = None
        run.clock = lambda: NOW + timedelta(seconds=121)
        assert run.tick() == "sent"
        assert [call.args[1] for call in client.send.call_args_list] == ["first", "second"]


def test_restore_quarantines_partial_batch_and_unregistered_overflow_durably(tmp_path):
    with IntelligenceStorage(tmp_path / "db") as storage:
        seed(storage, 25)
        client = Mock(send=Mock(side_effect=[True, False]))
        delivery = Mock(prepare_stories=Mock(return_value=("first", "second")))
        run = scheduler(storage, client, delivery=delivery)
        assert run.tick() == "send_failed"
        set_guard(storage.db_path, reason="restore", recovery_cutover_at=NOW.isoformat())
        assert run.tick() == "maintenance"
        clear_guard(storage.db_path)
        assert run.tick() == "quarantined"
        rows = storage.connection.execute("SELECT status FROM lark_story_deliveries").fetchall()
        assert len(rows) == 25 and all(row[0] == "quarantined" for row in rows)
        assert client.send.call_count == 2
        recovery_cutover_path(storage.db_path).unlink()
        assert run.tick() == "empty"  # Removing the marker cannot revive quarantined work.
        seed(storage, offset=25, persisted=NOW + timedelta(seconds=1))
        client.send.side_effect = None
        client.send.return_value = True
        assert scheduler(storage, client).tick() == "sent"


def test_cutover_rechecked_between_chunks_and_invalid_marker_fails_closed(tmp_path):
    with IntelligenceStorage(tmp_path / "db") as storage:
        seed(storage)
        marker = recovery_cutover_path(storage.db_path)

        def send(*args, **kwargs):
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({"recovery_cutover_at": NOW.isoformat()}))
            return True

        client = Mock(send=Mock(side_effect=send))
        run = scheduler(storage, client, delivery=Mock(prepare_stories=Mock(return_value=("a", "b"))))
        assert run.tick() == "quarantined"
        assert client.send.call_count == 1
        marker.write_text("broken")
        assert run.tick() == "unavailable"
        assert client.send.call_count == 1


def test_failed_prepare_rolls_back_registration_and_payload_errors_never_send(tmp_path):
    with IntelligenceStorage(tmp_path / "db") as storage:
        seed(storage)
        delivery = Mock(prepare_stories=Mock(side_effect=RuntimeError("local failure")))
        client = Mock()
        assert scheduler(storage, client, delivery=delivery).tick() == "unavailable"
        assert storage.connection.execute("SELECT COUNT(*) FROM lark_story_deliveries").fetchone()[0] == 0
        delivery.prepare_stories.side_effect = None
        delivery.prepare_stories.return_value = ["saved"]
        instant = InstantDeliveryScheduler(CONFIG, storage, delivery, client,
                                           lock=threading.RLock(), clock=lambda: NOW)
        instant._claim(NOW)
        storage.connection.execute("UPDATE lark_instant_batches SET chunks_json='invalid', status='failed'")
        assert scheduler(storage, client, delivery=delivery).tick() == "unavailable"
        client.send.assert_not_called()
        row = storage.connection.execute("SELECT status, last_error FROM lark_instant_batches").fetchone()
        assert tuple(row) == ("failed", "unavailable")


@pytest.mark.parametrize("stage", ["before_commit", "before_send", "after_acceptance"])
def test_process_exit_at_transaction_and_send_boundaries(tmp_path, stage):
    path = tmp_path / "db"
    accepted_path = tmp_path / "accepted.json"
    with IntelligenceStorage(path) as storage:
        seed(storage)
    script = textwrap.dedent("""
        import json, os, sys
        from datetime import datetime
        from pathlib import Path
        from trendradar.intelligence.storage import IntelligenceStorage
        from trendradar.integrations.feishu.config import FeishuConfig
        from trendradar.integrations.feishu.scheduler import DeliveryScheduler
        now = datetime.fromisoformat(sys.argv[4])
        class LocalDelivery:
            def prepare_stories(self, now, stories):
                if sys.argv[3] == 'before_commit':
                    os._exit(91)
                return ('frozen before crash',)
        class FakeSender:
            def send(self, target, text, *, message_uuid):
                if sys.argv[3] == 'after_acceptance':
                    with Path(sys.argv[2]).open('w', encoding='utf-8') as stream:
                        json.dump([target, text, message_uuid], stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                os._exit(91)
        with IntelligenceStorage.open_existing(sys.argv[1]) as storage:
            config = FeishuConfig(enabled=True, delivery_enabled=True, delivery_target='chat',
                                  delivery_mode='instant')
            DeliveryScheduler(config, storage.db_path, LocalDelivery(), FakeSender(),
                              storage=storage, clock=lambda: now).tick()
    """)
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), str(accepted_path), stage, NOW.isoformat()],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 91, result.stderr
    with IntelligenceStorage.open_existing(path) as storage:
        rows = storage.connection.execute("SELECT * FROM lark_instant_batches").fetchall()
        assert len(rows) == (0 if stage == "before_commit" else 1)
        client = Mock(send=Mock(return_value=True))
        delivery = (
            StoryDelivery(storage) if stage == "before_commit"
            else Mock(prepare_stories=Mock(side_effect=AssertionError("regenerated")))
        )
        run = scheduler(storage, client, delivery=delivery,
                        clock=lambda: NOW + timedelta(seconds=121))
        assert run.tick() == "sent"
        assert run.tick() == "empty"
        assert client.send.call_count == 1
        if stage == "after_acceptance":
            target, text, message_uuid = json.loads(accepted_path.read_text())
            client.send.assert_called_once_with(target, text, message_uuid=message_uuid)


def test_actual_snapshot_restore_quarantines_lost_completion_and_overflow(tmp_path):
    path = tmp_path / "output" / "intelligence.db"
    with IntelligenceStorage(path) as storage:
        seed(storage, 3, persisted=NOW - timedelta(days=1))
        client = Mock(send=Mock(side_effect=[True, False, True, True]))
        run = scheduler(storage, client, config=replace(CONFIG, delivery_max_stories=1))
        assert run.tick() == "sent"
        assert run.tick() == "send_failed"
        snapshot = create_snapshot([path], tmp_path / "backups", root=path.parent)
        assert run.tick() == "sent"
        assert run.tick() == "sent"
    restored = tmp_path / "restored"
    restore_snapshot(snapshot["path"], restored, guard_database=path)
    activate_restore(restored, path, root=path.parent)
    with IntelligenceStorage.open_existing(path) as storage:
        client = Mock(send=Mock(return_value=True))
        run = scheduler(storage, client)
        assert run.tick() == "maintenance"
        clear_guard(path)
        assert run.tick() == "quarantined"
        client.send.assert_not_called()
        states = dict(storage.connection.execute(
            "SELECT status, COUNT(*) FROM lark_story_deliveries GROUP BY status"
        ).fetchall())
        assert states == {"registered": 1, "quarantined": 2}
        seed(storage, offset=3, persisted=datetime.now(timezone.utc) + timedelta(seconds=1))
        assert run.tick() == "sent"
        assert run.tick() == "empty"
        client.send.assert_called_once()
        assert "Story 003 marker" in client.send.call_args.args[1]
