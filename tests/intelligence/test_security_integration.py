from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trendradar import __main__ as main_module
from trendradar.core.models import ContentItem
from trendradar.domains.security import collector
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.intelligence.stories import StoryService
from trendradar.sources.base import AdapterResult

NOW = datetime(2026, 9, 4, 8, tzinfo=timezone.utc)


def _security_config(tmp_path, *, report_enabled: bool = False) -> dict:
    return {
        "enabled": True,
        "output_dir": str(tmp_path / "security"),
        "timezone": "Asia/Shanghai",
        "sources": {
            "cisa_kev": {"enabled": False},
            "nvd": {"enabled": True},
            "rss": {
                "enabled": True,
                "feeds": [
                    {
                        "id": "vendor",
                        "name": "Vendor Advisories",
                        "url": "https://vendor.example/rss",
                    }
                ],
            },
        },
        "report": {
            "enabled": report_enabled,
            "lookback_days": 30,
            "max_candidates": 25,
            "max_stories": 10,
        },
    }


def _security_item(*, url: str) -> ContentItem:
    return ContentItem.create(
        title="CVE-2026-12345: remote code execution",
        content="Remote attackers may execute commands.",
        url=url,
        source="security:nvd",
        domain="security",
        published_time=NOW - timedelta(days=1),
        collected_at=NOW,
        tags=["CVE-2026-12345", "HIGH"],
        metadata={
            "source_content_id": "CVE-2026-12345",
            "source_name": "NVD",
            "raw_url": url,
            "published_time": (NOW - timedelta(days=1)).isoformat(),
            "cve_ids": ["CVE-2026-12345"],
            "entities": ["CVE-2026-12345"],
            "severity": "HIGH",
            "cvss_score": 8.8,
            "cvss_version": "4.0",
        },
    )


def _adapter_result(item: ContentItem) -> AdapterResult[object]:
    return AdapterResult(adapter_id="security:nvd", items=[item])


def test_pipeline_creates_security_story_from_observation_on_general_canonical(
    tmp_path, monkeypatch
):
    url = "https://nvd.nist.gov/vuln/detail/CVE-2026-12345"
    general = ContentItem.create(
        title="Vendor publishes an advisory",
        content="General feed evidence.",
        url=url,
        source="rss:vendor",
        domain="general",
        published_time=NOW - timedelta(days=1),
        collected_at=NOW - timedelta(hours=1),
        metadata={"source_content_id": "vendor-advisory"},
    )
    security = _security_item(url=url)
    calls = 0

    async def fake_collect(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return [_adapter_result(security)]

    monkeypatch.setattr(collector, "collect_security", fake_collect)
    story_config = {"enabled": True, "report": {"enabled": False}}
    with IntelligenceStorage(
        tmp_path / "intelligence.db",
        story_config=story_config,
    ) as storage:
        storage.write_batch([general])
        StoryService(storage).process([general])

        first = collector.run_security_pipeline(
            _security_config(tmp_path),
            storage=storage,
            collected_at=NOW,
        )
        first_counts = {
            table: storage.count(table)
            for table in (
                "content_items",
                "content_observations",
                "clusters",
                "stories",
                "story_members",
            )
        }
        second = collector.run_security_pipeline(
            _security_config(tmp_path),
            storage=storage,
            collected_at=NOW,
        )
        stories = storage.list_stories()
        security_story = next(story for story in stories if story.domain == "security")

        assert calls == 2
        assert first.data_refreshed is True
        assert first.persistence_succeeded is True
        assert first.story_processing_succeeded is True
        assert first.analysis_succeeded is True
        assert first.stories_analyzed == 1
        assert security_story.identity_key == "security:cve:cve-2026-12345"
        assert security_story.member_ids == [general.id]
        assert security_story.metadata["security"]["cvss_score"] == 8.8
        assert {story.domain for story in stories} == {"general", "security"}
        assert second.persistence_succeeded is True
        assert first_counts == {
            table: storage.count(table)
            for table in (
                "content_items",
                "content_observations",
                "clusters",
                "stories",
                "story_members",
            )
        }


def test_pipeline_write_failure_does_not_refetch_or_claim_refresh(tmp_path, monkeypatch):
    security = _security_item(url="https://nvd.nist.gov/vuln/detail/CVE-2026-12345")
    calls = 0

    async def fake_collect(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return [_adapter_result(security)]

    monkeypatch.setattr(collector, "collect_security", fake_collect)
    with IntelligenceStorage(
        tmp_path / "intelligence.db",
        story_config={"enabled": True, "report": {"enabled": False}},
    ) as storage:
        monkeypatch.setattr(
            storage,
            "write_batch",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
        )

        summary = collector.run_security_pipeline(
            _security_config(tmp_path),
            storage=storage,
            collected_at=NOW,
        )

        assert calls == 1
        assert summary.data_refreshed is False
        assert summary.persistence_succeeded is False
        assert summary.story_processing_succeeded is False
        assert any(error.startswith("persistence:") for error in summary.errors)
        assert storage.count("content_items") == 0
        assert storage.count("stories") == 0


def test_pipeline_isolates_story_analysis_freshness_and_report_failures(
    tmp_path, monkeypatch
):
    from trendradar.domains.security import analyzer, report
    from trendradar.intelligence import pipeline

    security = _security_item(url="https://nvd.nist.gov/vuln/detail/CVE-2026-12345")

    async def fake_collect(*_args, **_kwargs):
        return [_adapter_result(security)]

    monkeypatch.setattr(collector, "collect_security", fake_collect)
    monkeypatch.setattr(
        pipeline,
        "process_stories_after_persist_best_effort",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("story failed")),
    )
    monkeypatch.setattr(
        analyzer,
        "analyze_security_stories",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("analysis failed")),
    )
    monkeypatch.setattr(
        analyzer,
        "build_source_freshness",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("freshness failed")),
    )
    monkeypatch.setattr(
        report,
        "save_security_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("report failed")),
    )

    with IntelligenceStorage(
        tmp_path / "intelligence.db",
        story_config={"enabled": True, "report": {"enabled": False}},
    ) as storage:
        summary = collector.run_security_pipeline(
            _security_config(tmp_path, report_enabled=True),
            storage=storage,
            collected_at=NOW,
        )

        assert summary.persistence_succeeded is True
        assert summary.story_processing_succeeded is False
        assert summary.analysis_succeeded is False
        assert summary.freshness_succeeded is False
        assert summary.report_succeeded is False
        assert {error.split(":", 1)[0] for error in summary.errors} == {
            "story",
            "analysis",
            "freshness",
            "report",
        }
        assert storage.count("content_items") == 1


def test_pipeline_reports_every_enabled_source_and_scores_before_output_limit(
    tmp_path, monkeypatch
):
    from trendradar.domains.security import report

    security = _security_item(url="https://nvd.nist.gov/vuln/detail/CVE-2026-12345")

    async def fake_collect(*_args, **_kwargs):
        return [_adapter_result(security)]

    captured = {}

    def fake_report(stories, _storage, **kwargs):
        captured["stories"] = list(stories)
        captured["freshness"] = kwargs["freshness"]
        return tmp_path / "security" / "2026-09-04.html"

    monkeypatch.setattr(collector, "collect_security", fake_collect)
    monkeypatch.setattr(report, "save_security_report", fake_report)
    config = _security_config(tmp_path, report_enabled=True)
    config["sources"]["cisa_kev"]["enabled"] = True
    config["report"]["max_candidates"] = 7
    config["report"]["max_stories"] = 1

    with IntelligenceStorage(
        tmp_path / "intelligence.db",
        story_config={"enabled": True, "report": {"enabled": False}},
    ) as storage:
        list_stories = storage.list_stories

        def capture_list_stories(**kwargs):
            captured["candidate_limit"] = kwargs.get("limit")
            return list_stories(**kwargs)

        monkeypatch.setattr(storage, "list_stories", capture_list_stories)
        summary = collector.run_security_pipeline(config, storage=storage, collected_at=NOW)

    assert summary.report_succeeded is True
    assert captured["candidate_limit"] == 7
    assert len(captured["stories"]) == 1
    assert {entry.adapter_id for entry in captured["freshness"]} == {
        "security:cisa-kev",
        "security:nvd",
        "security:rss:vendor",
    }


def test_main_security_boundary_honors_lowercase_switch_and_contains_exceptions(
    monkeypatch,
):
    from trendradar.domains.security import collector as collector_module

    calls = 0

    def fail_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("isolated")

    monkeypatch.setattr(collector_module, "run_security_pipeline", fail_run)
    common = {
        "intelligence_enabled": True,
        "intelligence_storage": object(),
        "collected_at": NOW,
        "nvd_api_key": "",
        "wording_client": None,
    }

    assert main_module._run_security_best_effort(
        security_config={"enabled": False}, **common
    ) is None
    assert calls == 0
    assert main_module._run_security_best_effort(
        security_config={"enabled": True}, **common
    ) is None
    assert calls == 1
