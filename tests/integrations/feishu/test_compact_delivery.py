"""Compact linked posts, complete durable chunks and legacy retry compatibility."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from trendradar.integrations.feishu.client import FeishuClient, _SdkOperations
from trendradar.integrations.feishu.delivery import StoryDelivery
from trendradar.integrations.feishu.post import POST_PREFIX, encode_post, message_content
from trendradar.intelligence.storage import IntelligenceStorage

from .test_instant import NOW, scheduler, seed


def post_body(chunk):
    kind, content = message_content(chunk)
    assert kind == "post"
    assert len(content.encode("utf-8")) <= 20_000
    return json.loads(content)["zh_cn"]


def test_compact_source_groups_link_each_story_once_without_analysis(tmp_path):
    with IntelligenceStorage(tmp_path / "db") as storage:
        stories = seed(storage, 3)
        for index, story in enumerate(stories):
            storage.connection.execute(
                "UPDATE content_observations SET metadata_json=? WHERE content_item_id=?",
                (json.dumps({"source_name": "Feed B" if index == 1 else "Feed A"}),
                 story.member_ids[0]),
            )
        chunks = StoryDelivery(storage).prepare_stories(NOW, stories)
        assert len(chunks) == 1
        body = post_body(chunks[0])
        assert body["title"] == "Story Intelligence | 10-23 12:00"
        lines = body["content"]
        assert lines[0][0]["text"] == "\u672c\u6b21\u65b0\u589e\uff1a3 \u6761"
        assert lines[1][0]["text"] == "[1/2] Feed A \u00b7 2 \u6761"
        assert lines[4][0]["text"] == "[2/2] Feed B \u00b7 1 \u6761"
        links = [part for line in lines for part in line if part["tag"] == "a"]
        assert [part["text"] for part in links] == [stories[i].title for i in [0, 2, 1]]
        assert [part["href"] for part in links] == [f"https://example.test/{i}" for i in [0, 2, 1]]
        text = "".join(chunks)
        assert "Importance" not in text and "original summary" not in text


def test_compact_markup_urls_and_missing_evidence_are_safe(tmp_path):
    with IntelligenceStorage(tmp_path / "db") as storage:
        stories = seed(storage, 3)
        stories[0].title = '<at user_id="all">ALL</at>\nsecond line'
        storage.connection.execute("UPDATE content_observations SET url='javascript:alert(1)'")
        storage.connection.execute(
            "DELETE FROM content_observations WHERE content_item_id=?", (stories[1].member_ids[0],)
        )
        storage.connection.execute(
            "UPDATE content_observations SET url=? WHERE content_item_id=?",
            ("https://example.test/" + "a" * 2000, stories[2].member_ids[0]),
        )
        chunks = StoryDelivery(storage).prepare_stories(NOW, stories)
        parts = [part for chunk in chunks for line in post_body(chunk)["content"] for part in line]
        assert all(part["tag"] == "text" for part in parts)
        assert all("<at" not in part["text"] and "\n" not in part["text"] for part in parts)
        assert 'second line' in str(parts)
        assert 'javascript:' not in str(parts)
        assert "Story 001 marker" in str(parts) and "Story 002 marker" in str(parts)


def test_large_unicode_posts_split_only_between_entries_and_keep_all_links(tmp_path):
    with IntelligenceStorage(tmp_path / "db") as storage:
        stories = seed(storage, 20)
        for index, story in enumerate(stories):
            story.title = f"{index:02d} " + "\u4e2d" * 1000
            storage.connection.execute(
                "UPDATE content_observations SET url=? WHERE content_item_id=?",
                (f"https://example.test/{index}/" + "\U0001f600" * 1800, story.member_ids[0]),
            )
        chunks = StoryDelivery(storage).prepare_stories(NOW, stories)
        assert len(chunks) > 1
        links = []
        for index, chunk in enumerate(chunks, 1):
            body = post_body(chunk)
            assert body["title"].endswith(f"({index}/{len(chunks)})")
            links.extend(part for line in body["content"] for part in line if part["tag"] == "a")
        assert len(links) == 20
        assert [part["text"][:2] for part in links] == [f"{i:02d}" for i in range(20)]
        assert all(part["href"].endswith("\U0001f600" * 1800) for part in links)


def test_post_retry_reuses_saved_content_and_uuid_after_restart(tmp_path):
    path = tmp_path / "db"
    sender = Mock(send=Mock(return_value=False))
    with IntelligenceStorage(path) as storage:
        seed(storage, 2)
        assert scheduler(storage, sender).tick() == "send_failed"
        original_call = sender.send.call_args
        assert original_call.args[1].startswith(POST_PREFIX)
        saved = storage.connection.execute("SELECT chunks_json FROM lark_instant_batches").fetchone()[0]
        storage.connection.execute("UPDATE stories SET title='changed after failed delivery'")
    with IntelligenceStorage.open_existing(path) as storage:
        sender.send.return_value = True
        delivery = Mock(prepare_stories=Mock(side_effect=AssertionError("must use snapshot")))
        assert scheduler(storage, sender, delivery=delivery).tick() == "sent"
        assert sender.send.call_args == original_call
        assert storage.connection.execute("SELECT chunks_json FROM lark_instant_batches").fetchone()[0] == saved
        delivery.prepare_stories.assert_not_called()


def test_sdk_sends_native_post_and_preserves_legacy_text_and_uuid(monkeypatch):
    lark = pytest.importorskip("lark_oapi")
    operations = _SdkOperations(lark, "test-app", "test-secret")
    requests = []

    def capture(request):
        requests.append(request)
        return SimpleNamespace(success=lambda: True)

    monkeypatch.setattr(operations._client.im.v1.message, "create", capture)
    snapshot = encode_post("Compact", [[{"tag": "a", "text": "Headline", "href": "https://example.test/1"}]])
    client = FeishuClient(operations)
    assert client.send("chat", snapshot, message_uuid="stable-post-uuid")
    assert client.send("chat", "saved legacy text", message_uuid="stable-text-uuid")
    assert requests[0].body.msg_type == "post"
    assert requests[0].body.content == message_content(snapshot)[1]
    assert requests[0].body.uuid == "stable-post-uuid"
    assert requests[1].body.msg_type == "text"
    assert json.loads(requests[1].body.content) == {"text": "saved legacy text"}
    assert requests[1].body.uuid == "stable-text-uuid"


@pytest.mark.parametrize("payload", [
    "not json", '[]', '{"zh_cn": []}',
    json.dumps({"zh_cn": {"title": "bad", "content": [[{"tag": "at", "user_id": "all"}]]}}),
    json.dumps({"zh_cn": {"title": "bad", "content": [[{"tag": "a", "text": "bad", "href": "javascript:alert(1)"}]]}}),
])
def test_corrupt_or_unsafe_post_never_reaches_provider(tmp_path, payload):
    with IntelligenceStorage(tmp_path / "db") as storage:
        seed(storage)
        sender = Mock()
        delivery = Mock(prepare_stories=Mock(return_value=[POST_PREFIX + payload]))
        assert scheduler(storage, sender, delivery=delivery).tick() == "unavailable"
        sender.send.assert_not_called()
        assert storage.connection.execute("SELECT count(*) FROM lark_story_deliveries").fetchone()[0] == 0
