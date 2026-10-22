"""Offline tests for bounded Story narrative adapters."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from trendradar.ai.analyzer import (
    DailyDigestAnalyzer,
    NarrativeLimits,
    SecurityNarrativeAnalyzer,
)
from trendradar.ai.errors import GeminiTimeoutError
from trendradar.core.models import ImportanceBreakdown, Story, deterministic_story_id

NOW = datetime(2026, 9, 4, 8, tzinfo=timezone.utc)


def _story(index: int, *, domain: str = "ai") -> Story:
    identity = f"story-{domain}-{index}"
    metadata = {"cluster_id": f"cluster-{index}"}
    if domain == "security":
        metadata["security"] = {
            "cve_ids": [f"CVE-2026-{index:05d}"],
            "severity": "HIGH",
            "cvss_score": 8.1,
            "known_exploited": index == 1,
            "due_date": "2026-09-10",
            "required_actions": ["Apply vendor update"],
            "references": ["https://must-not-be-sent.example"],
        }
    return Story(
        id=deterministic_story_id(identity),
        identity_key=identity,
        title=f"Story {index}",
        summary=f"Evidence summary {index}",
        domain=domain,
        event_time=NOW - timedelta(hours=index),
        last_activity_at=NOW,
        member_ids=[deterministic_story_id(f"private-member-{index}")],
        tags=["AI", "security" if domain == "security" else "general"],
        importance=ImportanceBreakdown(
            score=100 - index,
            reasons=[f"Reason {index}"],
        ),
        metadata=metadata,
    )


class FakeGemini:
    def __init__(self, *, summary: object = "digest", analysis: object = "narrative") -> None:
        self.summary_outcome = summary
        self.analysis_outcome = analysis
        self.summary_calls = []
        self.analysis_calls = []

    def summary(self, text, **kwargs):
        self.summary_calls.append((text, kwargs))
        if isinstance(self.summary_outcome, Exception):
            raise self.summary_outcome
        return SimpleNamespace(text=self.summary_outcome)

    def analyze(self, text, **kwargs):
        self.analysis_calls.append((text, kwargs))
        if isinstance(self.analysis_outcome, Exception):
            raise self.analysis_outcome
        return SimpleNamespace(text=self.analysis_outcome)


def test_daily_digest_uses_one_bounded_ranked_projection_without_mutation() -> None:
    stories = [_story(index) for index in range(1, 5)]
    before = deepcopy(stories)
    client = FakeGemini(summary=" concise digest ")
    analyzer = DailyDigestAnalyzer(
        client,  # type: ignore[arg-type]
        limits=NarrativeLimits(max_stories=2, max_prompt_chars=2_000, max_output_chars=500),
    )

    result = analyzer.analyze(stories)

    assert result == "concise digest"
    assert stories == before
    assert len(client.summary_calls) == 1
    payload, options = client.summary_calls[0]
    assert "Story 1" in payload and "Story 2" in payload
    assert "Story 3" not in payload
    assert "private-member" not in payload
    assert "identity_key" not in payload
    assert "only the ranked Story facts" in options["instruction"]


def test_daily_digest_failure_or_empty_batch_degrades_to_none() -> None:
    client = FakeGemini(summary=GeminiTimeoutError())
    analyzer = DailyDigestAnalyzer(client)  # type: ignore[arg-type]

    assert analyzer.analyze([]) is None
    assert analyzer.analyze([_story(1)]) is None
    assert len(client.summary_calls) == 1


def test_security_narrative_sends_whitelisted_facts_once_and_caps_output() -> None:
    security = _story(1, domain="security")
    general = _story(2)
    before = deepcopy(security)
    client = FakeGemini(analysis="x" * 500)
    analyzer = SecurityNarrativeAnalyzer(
        client,  # type: ignore[arg-type]
        limits=NarrativeLimits(max_stories=5, max_prompt_chars=4_000, max_output_chars=200),
    )

    result = analyzer.analyze([security, general])

    assert result == "x" * 200
    assert security == before
    assert len(client.analysis_calls) == 1
    payload, options = client.analysis_calls[0]
    assert "CVE-2026-00001" in payload
    assert "8.1" in payload
    assert "Apply vendor update" in payload
    assert "must-not-be-sent" not in payload
    assert "private-member" not in payload
    assert "Do not alter CVE identifiers" in options["instruction"]


def test_narrative_limits_are_bounded() -> None:
    limits = NarrativeLimits.from_mapping(
        {"max_stories": 999, "max_prompt_chars": 1, "max_output_chars": 99_999}
    )
    assert limits == NarrativeLimits(max_stories=100, max_prompt_chars=1_000, max_output_chars=12_000)
