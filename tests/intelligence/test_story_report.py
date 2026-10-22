from datetime import datetime, timezone

from trendradar.core.models import (
    Cluster,
    ContentItem,
    ImportanceBreakdown,
    Story,
    deterministic_cluster_id,
    deterministic_story_id,
)
from trendradar.intelligence.storage import ContentObservation, IntelligenceStorage
from trendradar.intelligence.story_report import (
    prepare_story_report,
    render_story_report,
    save_story_report,
)

NOW = datetime(2026, 9, 4, 6, tzinfo=timezone.utc)


def _persist_story(storage: IntelligenceStorage) -> Story:
    item = ContentItem.create(
        title="Unsafe <script>alert(1)</script>",
        content="Evidence & context",
        url="https://example.com/story",
        source="rss:first",
        domain="ai",
        published_time=NOW,
        collected_at=NOW,
        metadata={"source_content_id": "first", "source_name": "First & Feed"},
    )
    observations = [
        ContentObservation.from_item(item),
        ContentObservation(
            content_item_id=item.id,
            source="ai_frontier:blog",
            source_content_id="second",
            title="Second <source>",
            url="javascript:alert(1)",
            metadata={"source_name": "Official <Blog>"},
            observed_at=NOW,
        ),
    ]
    storage.write_batch([item], observations)
    cluster = Cluster(
        id=deterministic_cluster_id([item.id]),
        member_ids=[item.id],
        domain="ai",
        event_time=NOW,
        last_activity_at=NOW,
    )
    key = "report-story"
    story = Story(
        id=deterministic_story_id(key),
        identity_key=key,
        title="Story <title>",
        summary="Summary & context",
        domain="ai",
        event_time=NOW,
        last_activity_at=NOW,
        member_ids=[item.id],
        importance=ImportanceBreakdown(score=80, reasons=["Two & sources"]),
        metadata={"cluster_id": cluster.id},
    )
    storage.upsert_story_batch([cluster], [story])
    return story


def test_story_report_contains_rank_reasons_and_all_escaped_evidence(tmp_path):
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        story = _persist_story(storage)
        rendered = render_story_report(
            prepare_story_report([story], storage),
            generated_at=NOW,
        )

    assert "80.0" in rendered
    assert "Two &amp; sources" in rendered
    assert "First &amp; Feed" in rendered
    assert "Official &lt;Blog&gt;" in rendered
    assert "Unsafe &lt;script&gt;" in rendered
    assert "Sources (2)" in rendered
    assert 'href="javascript:' not in rendered


def test_save_story_report_is_additive_and_empty_report_is_valid(tmp_path):
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        story = _persist_story(storage)
        path = save_story_report(
            [story],
            storage,
            output_dir=tmp_path / "stories",
            generated_at=NOW,
            timezone_name="Asia/Shanghai",
        )
        empty = render_story_report([], generated_at=NOW)

    assert path == tmp_path / "stories" / "2026-09-04.html"
    assert path.exists()
    assert not (tmp_path / "index.html").exists()
    assert "No Stories for this period." in empty


def test_story_report_adds_one_escaped_digest_without_changing_story_data(tmp_path):
    class Analyzer:
        def __init__(self):
            self.calls = []

        def analyze(self, stories):
            self.calls.append(list(stories))
            return "Digest <script>alert(1)</script> & facts"

    analyzer = Analyzer()
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        story = _persist_story(storage)
        path = save_story_report(
            [story],
            storage,
            output_dir=tmp_path / "stories",
            generated_at=NOW,
            digest_analyzer=analyzer,
        )

    rendered = path.read_text(encoding="utf-8")
    assert len(analyzer.calls) == 1
    assert analyzer.calls[0] == [story]
    assert "Daily digest" in rendered
    assert "Digest &lt;script&gt;alert(1)&lt;/script&gt; &amp; facts" in rendered
    assert "<script>alert(1)</script>" not in rendered


def test_story_report_analyzer_failure_matches_default_render(tmp_path):
    class Analyzer:
        def analyze(self, _stories):
            raise RuntimeError("optional failure")

    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        story = _persist_story(storage)
        expected = render_story_report(
            prepare_story_report([story], storage),
            generated_at=NOW,
        )
        path = save_story_report(
            [story],
            storage,
            output_dir=tmp_path / "stories",
            generated_at=NOW,
            digest_analyzer=Analyzer(),
        )

    assert path.read_text(encoding="utf-8") == expected
