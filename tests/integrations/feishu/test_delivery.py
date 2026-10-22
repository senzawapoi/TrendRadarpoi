"""Story baseline rendering, safe links and Feishu UTF-8 payload limits."""

import json
from datetime import datetime, timezone
from unittest.mock import Mock

from trendradar.core.models import ContentItem
from trendradar.integrations.feishu.client import FeishuClient
from trendradar.integrations.feishu.delivery import StoryDelivery, text_chunks
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.intelligence.stories import StoryService

NOW = datetime(2026, 9, 12, 4, tzinfo=timezone.utc)


def test_json_and_unicode_chunk_limits_and_escape_transport_mentions():
    text = "\u4e2d" * 20000 + '\\"\n\t' * 10000
    chunks = text_chunks(text)
    assert "".join(chunks) == text
    assert all(
        len(json.dumps({"text": chunk}, ensure_ascii=False).encode()) < 20_000 for chunk in chunks
    )
    operations = Mock(reply=Mock(return_value=True))
    assert FeishuClient(operations).reply("msg", '<at user_id="all">ALL</at>' + text)
    assert all("<at" not in call.args[1] for call in operations.reply.call_args_list)


def test_story_delivery_preserves_persisted_ranking_and_safe_evidence(tmp_path):
    with IntelligenceStorage(tmp_path / "test.db", story_config={"enabled": True}) as storage:
        items = [
            ContentItem.create(
                title="<at user_id='all'>Alpha</at> model release",
                url="https://example.com/story",
                source="rss:feed",
                domain="ai",
                collected_at=NOW,
            ),
            ContentItem.create(
                title="Unrelated security bulletin",
                url="https://example.com/security",
                source="rss:other",
                domain="security",
                collected_at=NOW,
            ),
        ]
        storage.write_batch(items)
        StoryService(storage).process(items)
        stories = storage.list_stories()
        for index, story in enumerate(stories):
            story.importance.score = 99 - index
            storage.connection.execute(
                "UPDATE stories SET importance_score=?, importance_json=? WHERE id=?",
                (99 - index, json.dumps(story.importance.to_dict()), story.id),
            )
        delivery = StoryDelivery(
            storage, digest_analyzer=Mock(analyze=Mock(side_effect=RuntimeError("offline")))
        )
        text = "\n".join(delivery.prepare(NOW))
        assert "Asia/Shanghai" in text and "12:00" in text
        assert "Importance: 99.0" in text
        assert "https://example.com/story" in text
        assert "<at" not in text and "&lt;at" in text
        assert text.index("Importance: 99.0") < text.index("Importance: 98.0")


def test_empty_story_day_does_not_call_digest(tmp_path):
    with IntelligenceStorage(tmp_path / "test.db") as storage:
        digest = Mock()
        assert StoryDelivery(storage, digest_analyzer=digest).prepare(NOW) == ()
        digest.analyze.assert_not_called()
