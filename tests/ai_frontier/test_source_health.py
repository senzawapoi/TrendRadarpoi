"""Transport and child-parser failures must survive the canonical health boundary."""

import asyncio
from datetime import datetime, timedelta, timezone
from importlib import import_module
from types import SimpleNamespace

import pytest

from trendradar.ai_frontier.sources.official_blog import OfficialBlogSource
from trendradar.core.heartbeat import RoleHeartbeat
from trendradar.intelligence.runner import AdapterRunner
from trendradar.intelligence.storage import IntelligenceStorage, SourceRunRecord
from trendradar.ops.health import collect_health
from trendradar.sources.ai_frontier import AIFrontierAdapter


class Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def response(status=200, text="", url="https://example.com/blog/"):
    async def read():
        return text

    return SimpleNamespace(status=status, text=read, url=url, release=lambda: None)


@pytest.fixture
def source_policy(tmp_path, monkeypatch):
    database = tmp_path / "output/intelligence.db"
    config = tmp_path / "config.yaml"
    config.write_text("intelligence:\n  enabled: true\nai_frontier:\n  enabled: false\n")
    values = {
        "INTELLIGENCE_ENABLED": "true", "INTELLIGENCE_DB_PATH": str(database),
        "INTELLIGENCE_SQLITE_SYNCHRONOUS": "FULL", "LARK_ENABLED": "false",
        "GEMINI_ENABLED": "false", "TRENDRADAR_RELEASE_ID": "source-test",
        "TRENDRADAR_HEALTH_DIR": str(tmp_path / "health"),
        "TRENDRADAR_CONTROL_DIR": str(tmp_path / "control"),
        "TRENDRADAR_BACKUP_DIR": str(tmp_path / "backups"),
        "TRENDRADAR_OFFSITE_ENABLED": "false",
        "TRENDRADAR_HEALTH_EXPECTED_ROLES": "bot,worker",
        "TRENDRADAR_HEALTH_EXPECTED_SOURCES": "ai_frontier:official_blog",
        "INTELLIGENCE_HEALTH_REQUIRE_SOURCE_RUNS": "true",
        "INTELLIGENCE_HEALTH_REQUIRE_BACKUP": "false",
        "INTELLIGENCE_HEALTH_SOURCE_MAX_AGE_HOURS": "1",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    with IntelligenceStorage(database, synchronous="FULL"):
        pass
    for role, state in [("bot", "connected"), ("worker", "running")]:
        RoleHeartbeat(role, database).write(state=state, sqlite_synchronous="FULL")
    return database, config


@pytest.mark.parametrize("mode,expected,errors,count", [
    ("all-failed", "unhealthy", 2, 0),
    ("partial", "degraded", 1, 1),
    ("empty", "degraded", 0, 0),
])
def test_fanout_errors_persist_and_gate_readiness(monkeypatch, source_policy, mode,
                                                expected, errors, count):
    module = import_module("trendradar.ai_frontier.sources.official_blog")
    monkeypatch.setattr(module, "make_session", lambda **kwargs: Session())
    calls = []

    async def request(session, method, url, **kwargs):
        calls.append(url)
        failed = mode == "all-failed" or (mode == "partial" and url.endswith("bad"))
        return response(403 if failed else 200, "" if mode == "empty" else
                        '<article><a href="/post">Useful item</a></article>', url)

    monkeypatch.setattr(module, "request_with_retry", request)
    source = OfficialBlogSource({"sites": [
        {"name": "good", "url": "https://example.com/good"},
        {"name": "bad", "url": "https://example.com/bad"},
    ]})
    database, config = source_policy
    with IntelligenceStorage(database, synchronous="FULL") as storage:
        result = asyncio.run(AdapterRunner(storage=storage).run([
            AIFrontierAdapter("official_blog", source),
        ]))[0]
        saved = storage.latest_source_run("ai_frontier:official_blog")
    assert result.health.status.value == expected
    assert result.health.error_count == saved.error_count == errors
    assert len(result.raw_items) == len(result.items) == count
    assert len(calls) == 2
    report = collect_health(config, readiness=True)
    assert report["status"] == ("unhealthy" if errors else "healthy")
    latest = report["source_health"]["ai_frontier:official_blog"]
    if errors:
        assert latest["last_success_at"] is None
    else:
        assert latest["last_success_at"]
    assert len(calls) == 2, "readiness must not refetch sources"


def test_child_exception_is_visible_and_does_not_leak_or_survive_next_run(monkeypatch):
    module = import_module("trendradar.ai_frontier.sources.official_blog")
    monkeypatch.setattr(module, "make_session", lambda **kwargs: Session())
    source = OfficialBlogSource({"sites": [{"name": "site", "url": "https://example.com"}]})

    async def broken(*args):
        raise ValueError("https://example.com?token=private-value")

    monkeypatch.setattr(source, "_fetch_site", broken)
    result = asyncio.run(AdapterRunner().run([AIFrontierAdapter("official_blog", source)]))[0]
    assert result.health.error_count == 1
    assert result.health.error_summary == "site:ValueError"

    async def empty(*args):
        return []

    monkeypatch.setattr(source, "_fetch_site", empty)
    second = asyncio.run(AdapterRunner().run([AIFrontierAdapter("official_blog", source)]))[0]
    assert second.health.error_count == 0
    assert source.fetch_errors == ()


@pytest.mark.parametrize("status,errors", [("unhealthy", 1), ("degraded", 1)])
def test_repeated_failed_attempts_do_not_refresh_last_success(source_policy, status, errors):
    database, config = source_policy
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=3)
    with IntelligenceStorage(database, synchronous="FULL") as storage:
        for stamp, state, count in [(old, "healthy", 0), (now, status, errors)]:
            storage.record_source_run(SourceRunRecord(
                adapter_id="ai_frontier:official_blog", status=state,
                started_at=stamp, finished_at=stamp, duration_ms=1,
                fetched_count=1, normalized_count=1, error_count=count,
            ))
    report = collect_health(config, readiness=True)
    latest = report["source_health"]["ai_frontier:official_blog"]
    assert latest["last_success_at"] == old.isoformat()
    assert "stale_source:ai_frontier:official_blog" in report["errors"]
    assert "source_unhealthy:ai_frontier:official_blog" in report["errors"]


@pytest.mark.parametrize("key,class_name,config", [
    ("arxiv", "ArXivSource", {}),
    ("github_trending", "GitHubTrendingSource", {"languages": ["python"]}),
    ("hackernews", "HackerNewsSource", {"keywords": ["AI"]}),
    ("reddit", "RedditSource", {"subreddits": ["ai"]}),
    ("official_blog", "OfficialBlogSource", {"sites": [{"name": "blog", "url": "https://example.com"}]}),
    ("youtube_podcast", "YouTubePodcastSource", {"feeds": [{"name": "podcast", "channel_id": "UCtest123"}]}),
])
def test_exhausted_http_failure_is_not_successful_empty(monkeypatch, key, class_name, config):
    module = import_module(f"trendradar.ai_frontier.sources.{key}")
    monkeypatch.setattr(module, "make_session", lambda **kwargs: Session())

    async def failure(*args, **kwargs):
        return None

    monkeypatch.setattr(module, "request_with_retry", failure)
    result = asyncio.run(AdapterRunner().run([
        AIFrontierAdapter(key, getattr(module, class_name)(config)),
    ]))[0]
    assert result.health.status.value == "unhealthy"
    assert result.health.error_count == 1
    assert result.health.error_summary


def test_no_nitter_instance_is_a_failure(monkeypatch):
    module = import_module("trendradar.ai_frontier.sources.nitter")
    monkeypatch.setattr(module, "make_session", lambda **kwargs: Session())
    source = module.NitterSource({"accounts": ["example"]})

    async def no_instances(session):
        return []

    monkeypatch.setattr(source, "_probe_instances", no_instances)
    result = asyncio.run(AdapterRunner().run([AIFrontierAdapter("x_nitter", source)]))[0]
    assert result.health.status.value == "unhealthy"
    assert result.health.error_summary == "no_usable_instance"
