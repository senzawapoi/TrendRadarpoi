from datetime import datetime, timedelta, timezone

import pytest

from trendradar.core.models import (
    Cluster,
    ContentItem,
    ImportanceBreakdown,
    Story,
    deterministic_cluster_id,
    deterministic_story_id,
)
from trendradar.domains.security.analyzer import (
    SecurityRankingConfig,
    analyze_security_stories,
    build_source_freshness,
)
from trendradar.intelligence.storage import (
    ContentObservation,
    IntelligenceStorage,
    SourceRunRecord,
)

NOW = datetime(2026, 9, 4, 8, tzinfo=timezone.utc)


def _persist_security_story(
    storage: IntelligenceStorage,
    *,
    key: str,
    cve_id: str,
    cvss_score: float | None,
    severity: str,
    known_exploited: bool,
    action: str = "",
    due_date: str = "",
    base_score: float = 40,
) -> Story:
    item = ContentItem.create(
        title=f"{cve_id}: Example vulnerability",
        content="Remote attackers may execute commands.",
        url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
        source="security:nvd",
        domain="security",
        published_time=NOW - timedelta(days=10),
        collected_at=NOW,
        tags=[cve_id, severity],
        metadata={
            "source_content_id": cve_id,
            "source_name": "NVD",
            "cve_ids": [cve_id],
            "entities": [cve_id],
            "severity": severity,
            "cvss_score": cvss_score,
            "cvss_version": "3.1",
            "cvss_vector": "CVSS:3.1/AV:N/AC:L",
            "references": [f"https://vendor.example/{cve_id}"],
        },
    )
    observations = [ContentObservation.from_item(item)]
    if known_exploited or action or due_date:
        observations.append(
            ContentObservation(
                content_item_id=item.id,
                source="security:cisa-kev",
                source_content_id=cve_id,
                title=f"{cve_id}: Added to KEV",
                url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
                metadata={
                    "source_name": "CISA KEV",
                    "cve_ids": [cve_id.lower()],
                    "known_exploited": known_exploited,
                    "action_required": bool(action or due_date),
                    "required_action": action,
                    "due_date": due_date,
                    "vendor": "Example Corp",
                    "product": "Example Server",
                },
                observed_at=NOW,
            )
        )
    storage.write_batch([item], observations)
    cluster = Cluster(
        id=deterministic_cluster_id([item.id]),
        member_ids=[item.id],
        domain="security",
        event_time=item.published_time,
        last_activity_at=NOW,
        tags=item.tags,
        entities=[cve_id],
    )
    identity_key = f"security:cve:{cve_id}"
    story = Story(
        id=deterministic_story_id(identity_key),
        identity_key=identity_key,
        title=item.title,
        summary=item.content,
        domain="security",
        event_time=item.published_time,
        last_activity_at=NOW,
        member_ids=[item.id],
        tags=item.tags,
        entities=[cve_id],
        importance=ImportanceBreakdown(score=base_score),
        metadata={"cluster_id": cluster.id},
    )
    storage.upsert_story_batch([cluster], [story])
    return story


def test_security_importance_aggregates_evidence_and_prioritizes_action(tmp_path):
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        urgent = _persist_security_story(
            storage,
            key="urgent",
            cve_id="CVE-2026-12345",
            cvss_score=9.8,
            severity="CRITICAL",
            known_exploited=True,
            action="Apply the vendor update.",
            due_date="2026-09-10",
        )
        ordinary = _persist_security_story(
            storage,
            key="ordinary",
            cve_id="CVE-2026-54321",
            cvss_score=5.3,
            severity="MEDIUM",
            known_exploited=False,
        )

        analyzed = analyze_security_stories([ordinary, urgent], storage, now=NOW)

    assert [story.id for story in analyzed] == [urgent.id, ordinary.id]
    result = analyzed[0]
    assert result.importance.score == pytest.approx(91.0)
    assert result.importance.components == {
        "base": 0.4,
        "severity": 1.0,
        "known_exploited": 1.0,
        "action": 1.0,
    }
    assert result.metadata["security"]["cve_ids"] == ["CVE-2026-12345"]
    assert result.metadata["security"]["vendors"] == ["Example Corp"]
    assert result.metadata["security"]["products"] == ["Example Server"]
    assert result.metadata["security"]["references"] == [
        "https://vendor.example/CVE-2026-12345"
    ]
    assert any("CVSS 9.8 CRITICAL" in reason for reason in result.importance.reasons)
    assert any("Known exploited" in reason for reason in result.importance.reasons)
    assert any("Apply the vendor update" in reason for reason in result.importance.reasons)
    assert any("in 6 day(s)" in reason for reason in result.importance.reasons)


def test_security_analysis_is_idempotent_and_tolerates_malformed_metadata(tmp_path):
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        story = _persist_security_story(
            storage,
            key="stable",
            cve_id="CVE-2026-12345",
            cvss_score=None,
            severity="HIGH",
            known_exploited=False,
            base_score=60,
        )
        storage.connection.execute(
            "UPDATE content_observations SET metadata_json = ?",
            ("{broken",),
        )
        first = analyze_security_stories([story], storage, now=NOW)[0]
        storage.upsert_story_batch([], [first])
        restored = storage.get_story(story.id)
        second = analyze_security_stories([restored], storage, now=NOW)[0]

    assert first.importance == second.importance
    assert first.metadata == second.metadata
    assert first.importance.components["severity"] == 0.8
    assert any("Severity HIGH" in reason for reason in first.importance.reasons)


def test_security_analysis_prefers_newer_cvss_version_over_higher_legacy_score(tmp_path):
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        story = _persist_security_story(
            storage,
            key="cvss-version",
            cve_id="CVE-2026-12345",
            cvss_score=9.9,
            severity="CRITICAL",
            known_exploited=False,
        )
        storage.connection.execute(
            "UPDATE content_items SET metadata_json = ? WHERE id = ?",
            (
                '{"cve_ids":["CVE-2026-12345"],"cvss_score":9.9,'
                '"cvss_version":"2.0","severity":"CRITICAL"}',
                story.member_ids[0],
            ),
        )
        storage.connection.execute(
            "UPDATE content_observations SET metadata_json = ? WHERE source = ?",
            (
                '{"cve_ids":["CVE-2026-12345"],"cvss_score":8.1,'
                '"cvss_version":"4.0","severity":"HIGH",'
                '"cvss_vector":"CVSS:4.0/AV:N"}',
                "security:nvd",
            ),
        )

        analyzed = analyze_security_stories([story], storage, now=NOW)[0]

    security = analyzed.metadata["security"]
    assert security["cvss_score"] == 8.1
    assert security["cvss_version"] == "4.0"
    assert security["cvss_vector"] == "CVSS:4.0/AV:N"
    assert security["severity"] == "HIGH"


def test_security_ranking_config_normalizes_or_falls_back():
    custom = SecurityRankingConfig.from_mapping(
        {"weights": {"base": 0, "severity": 1, "known_exploited": 0, "action": 0}}
    )
    malformed = SecurityRankingConfig.from_mapping({"weights": "bad"})
    assert custom.weights == {
        "base": 0,
        "severity": 1,
        "known_exploited": 0,
        "action": 0,
    }
    assert sum(malformed.weights.values()) == pytest.approx(1.0)


def _run(adapter_id: str, status: str, finished_at: datetime, error: str = ""):
    return SourceRunRecord(
        adapter_id=adapter_id,
        status=status,
        started_at=finished_at - timedelta(seconds=1),
        finished_at=finished_at,
        duration_ms=1000,
        fetched_count=2,
        normalized_count=1,
        error_count=bool(error),
        error_summary=error,
    )


def test_source_freshness_keeps_last_success_when_current_run_fails(tmp_path):
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        storage.record_source_run(_run("security:nvd", "healthy", NOW - timedelta(hours=10)))
        storage.record_source_run(_run("security:nvd", "unhealthy", NOW, "rate limited"))
        storage.record_source_run(_run("security:cisa-kev", "healthy", NOW - timedelta(hours=50)))

        freshness = {
            value.adapter_id: value
            for value in build_source_freshness(
                storage,
                ["security:nvd", "security:cisa-kev", "security:rss:new"],
                now=NOW,
                stale_after_hours=48,
            )
        }

    nvd = freshness["security:nvd"]
    assert nvd.status == "unhealthy"
    assert nvd.last_attempt_at == NOW
    assert nvd.last_success_at == NOW - timedelta(hours=10)
    assert nvd.age_hours == 10
    assert nvd.stale is False
    assert nvd.error_summary == "rate limited"
    assert freshness["security:cisa-kev"].stale is True
    assert freshness["security:rss:new"].status == "unknown"
    assert freshness["security:rss:new"].stale is True


def test_security_analysis_and_freshness_reject_naive_now(tmp_path):
    with IntelligenceStorage(tmp_path / "intelligence.db") as storage:
        with pytest.raises(ValueError, match="timezone-aware"):
            analyze_security_stories([], storage, now=NOW.replace(tzinfo=None))
        with pytest.raises(ValueError, match="timezone-aware"):
            build_source_freshness(storage, [], now=NOW.replace(tzinfo=None))
