from datetime import datetime, timezone

from trendradar.core.models import (
    Cluster,
    ContentItem,
    ImportanceBreakdown,
    Story,
    deterministic_cluster_id,
    deterministic_story_id,
)
from trendradar.domains.security.analyzer import SourceFreshness
from trendradar.domains.security.report import (
    prepare_security_report,
    render_security_report,
    save_security_report,
)
from trendradar.intelligence.storage import ContentObservation, IntelligenceStorage

NOW = datetime(2026, 9, 4, 8, tzinfo=timezone.utc)


def _persist_story(storage: IntelligenceStorage) -> Story:
    cve_id = "CVE-2026-12345"
    item = ContentItem.create(
        title="Unsafe <script>alert(1)</script>",
        content="Evidence & context",
        url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
        source="security:nvd",
        domain="security",
        published_time=NOW,
        collected_at=NOW,
        metadata={"source_content_id": cve_id, "source_name": "NVD"},
    )
    observations = [
        ContentObservation.from_item(item),
        ContentObservation(
            content_item_id=item.id,
            source="security:cisa-kev",
            source_content_id=cve_id,
            title="CISA <KEV> evidence",
            url="javascript:alert(1)",
            metadata={"source_name": "CISA & KEV"},
            observed_at=NOW,
        ),
    ]
    storage.write_batch([item], observations)
    cluster = Cluster(
        id=deterministic_cluster_id([item.id]),
        member_ids=[item.id],
        domain="security",
        event_time=NOW,
        last_activity_at=NOW,
    )
    identity = f"security:cve:{cve_id}"
    story = Story(
        id=deterministic_story_id(identity),
        identity_key=identity,
        title="Critical <title>",
        summary="Summary & impact",
        domain="security",
        event_time=NOW,
        last_activity_at=NOW,
        member_ids=[item.id],
        importance=ImportanceBreakdown(
            score=92,
            reasons=["Required action: patch <now>"],
            version="security-importance-v1",
        ),
        metadata={
            "cluster_id": cluster.id,
            "security": {
                "cve_ids": [cve_id],
                "severity": "CRITICAL",
                "cvss_score": 9.8,
                "known_exploited": True,
                "due_date": "2026-09-10",
                "required_actions": ["Patch <now>"],
                "references": [
                    "https://vendor.example/advisory?a=1&b=2",
                    "javascript:alert(2)",
                ],
            },
        },
    )
    storage.upsert_story_batch([cluster], [story])
    return story


def test_security_report_contains_actionable_escaped_evidence_and_freshness(tmp_path):
    freshness = [
        SourceFreshness(
            adapter_id="security:nvd",
            status="unhealthy",
            last_attempt_at=NOW,
            last_success_at=NOW,
            age_hours=0,
            stale=False,
            fetched_count=2,
            normalized_count=1,
            error_count=1,
            error_summary="HTTP <429>",
        )
    ]
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        story = _persist_story(storage)
        rendered = render_security_report(
            prepare_security_report([story], storage),
            freshness=freshness,
            generated_at=NOW,
        )

    assert "92.0" in rendered
    assert "CVE-2026-12345" in rendered
    assert "CRITICAL" in rendered
    assert "CVSS: 9.8" in rendered
    assert "KEV: Yes" in rendered
    assert "Patch &lt;now&gt;" in rendered
    assert "Critical &lt;title&gt;" in rendered
    assert "Summary &amp; impact" in rendered
    assert "CISA &amp; KEV" in rendered
    assert "HTTP &lt;429&gt;" in rendered
    assert "Source evidence (2)" in rendered
    assert "https://vendor.example/advisory?a=1&amp;b=2" in rendered
    assert 'href="javascript:' not in rendered


def test_save_security_report_is_additive_and_empty_output_is_valid(tmp_path):
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        story = _persist_story(storage)
        path = save_security_report(
            [story],
            storage,
            output_dir=tmp_path / "security",
            generated_at=NOW,
            timezone_name="Asia/Shanghai",
        )
        empty = render_security_report([], generated_at=NOW)

    assert path == tmp_path / "security" / "2026-09-04.html"
    assert path.exists()
    assert not (tmp_path / "index.html").exists()
    assert "No Security Stories for this period." in empty
    assert "No enabled security sources." in empty


def test_security_report_adds_one_escaped_optional_narrative(tmp_path):
    class Analyzer:
        def __init__(self):
            self.calls = []

        def analyze(self, stories):
            self.calls.append(list(stories))
            return "Patch <now> & verify"

    analyzer = Analyzer()
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        story = _persist_story(storage)
        path = save_security_report(
            [story],
            storage,
            output_dir=tmp_path / "security",
            generated_at=NOW,
            narrative_analyzer=analyzer,
        )

    rendered = path.read_text(encoding="utf-8")
    assert len(analyzer.calls) == 1
    assert analyzer.calls[0] == [story]
    assert "Security narrative" in rendered
    assert "Patch &lt;now&gt; &amp; verify" in rendered


def test_security_report_narrative_failure_matches_default_render(tmp_path):
    class Analyzer:
        def analyze(self, _stories):
            raise RuntimeError("optional failure")

    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        story = _persist_story(storage)
        expected = render_security_report(
            prepare_security_report([story], storage),
            generated_at=NOW,
        )
        path = save_security_report(
            [story],
            storage,
            output_dir=tmp_path / "security",
            generated_at=NOW,
            narrative_analyzer=Analyzer(),
        )

    assert path.read_text(encoding="utf-8") == expected
