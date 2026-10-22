import asyncio
import json
from datetime import datetime, timezone

from trendradar.ai_frontier.sources.base import AIItem, AISource
from trendradar.core.models import ContentItem
from trendradar.intelligence.runner import AdapterRunner, run_newsnow_adapters
from trendradar.sources.ai_frontier import AIFrontierAdapter, build_ai_adapters
from trendradar.sources.base import HealthStatus, SourceAdapter
from trendradar.sources.newsnow import NewsNowAdapter

NOW = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)


def _content(value: str, collected_at: datetime) -> ContentItem:
    return ContentItem.create(
        title=value,
        source="rss:test",
        domain="general",
        collected_at=collected_at,
    )


class FakeAdapter(SourceAdapter[str]):
    domain = "general"

    def __init__(
        self,
        adapter_id: str,
        values: list[str] | None = None,
        *,
        fetch_error: bool = False,
        active: list[int] | None = None,
    ) -> None:
        self.adapter_id = adapter_id
        self.values = values or []
        self.fetch_error = fetch_error
        self.active = active
        super().__init__()

    async def fetch(self) -> list[str]:
        if self.fetch_error:
            raise RuntimeError("fetch failed")
        if self.active is not None:
            self.active[0] += 1
            self.active[1] = max(self.active[1], self.active[0])
            await asyncio.sleep(0.01)
            self.active[0] -= 1
        return self.values

    def normalize(self, raw: str, *, collected_at: datetime) -> ContentItem:
        if raw == "bad":
            raise ValueError("bad item")
        return _content(raw, collected_at)


def test_health_check_is_passive_and_unknown_before_run():
    adapter = FakeAdapter("rss:test", ["one"])
    health = asyncio.run(adapter.health_check())
    assert health.status is HealthStatus.UNKNOWN


def test_runner_limits_concurrency_and_isolates_fetch_failure():
    active = [0, 0]
    adapters = [FakeAdapter(f"rss:{i}", [str(i)], active=active) for i in range(5)]
    adapters.append(FakeAdapter("rss:failed", fetch_error=True))
    results = asyncio.run(AdapterRunner(max_concurrency=2).run(adapters, collected_at=NOW))
    assert active[1] == 2
    assert sum(len(result.items) for result in results) == 5
    assert results[-1].health.status is HealthStatus.UNHEALTHY
    assert results[-1].fetch_error == "fetch failed"


def test_runner_marks_empty_and_partial_results_degraded():
    empty = FakeAdapter("rss:empty")
    partial = FakeAdapter("rss:partial", ["good", "bad"])
    results = asyncio.run(AdapterRunner().run([empty, partial], collected_at=NOW))
    assert results[0].health.status is HealthStatus.DEGRADED
    assert results[1].health.status is HealthStatus.DEGRADED
    assert len(results[1].items) == 1
    assert results[1].health.error_count == 1


def test_runner_marks_all_normalize_failures_unhealthy():
    adapter = FakeAdapter("rss:bad", ["bad"])
    result = asyncio.run(AdapterRunner().run([adapter], collected_at=NOW))[0]
    assert result.health.status is HealthStatus.UNHEALTHY


def test_runner_isolates_invalid_fetch_result():
    class InvalidAdapter(FakeAdapter):
        async def fetch(self):
            return None

    valid = FakeAdapter("rss:valid", ["ok"])
    invalid = InvalidAdapter("rss:invalid")
    results = asyncio.run(AdapterRunner().run([valid, invalid], collected_at=NOW))

    assert results[0].health.status is HealthStatus.HEALTHY
    assert results[1].health.status is HealthStatus.UNHEALTHY
    assert "must return a list" in results[1].fetch_error


def test_newsnow_runner_is_strictly_serial():
    active = [0, 0]
    adapters = [FakeAdapter(f"newsnow:{i}", [str(i)], active=active) for i in range(3)]
    results = asyncio.run(
        run_newsnow_adapters(adapters, request_interval_ms=0, collected_at=NOW)
    )
    assert active[1] == 1
    assert [result.adapter_id for result in results] == ["newsnow:0", "newsnow:1", "newsnow:2"]


class FakeDataFetcher:
    def fetch_data(self, _id_info):
        payload = {
            "items": [
                {"title": "A", "url": "https://example.com/a", "mobileUrl": "m"},
                {"title": "A", "url": "https://example.com/a"},
                {"title": None},
            ]
        }
        return json.dumps(payload), "test", "Test"


def test_newsnow_adapter_groups_duplicate_titles_and_normalizes():
    adapter = NewsNowAdapter("test", "Test", fetcher=FakeDataFetcher())
    raw = asyncio.run(adapter.fetch())
    content = adapter.normalize(raw[0], collected_at=NOW)
    assert len(raw) == 1
    assert raw[0].ranks == [1, 2]
    assert content.source == "newsnow:test"
    assert content.metadata["legacy_data"]["mobile_url"] == "m"


class FakeAISource(AISource):
    source_type = "reddit"

    async def fetch(self):
        return [AIItem(source="reddit", source_name="r/ai", title="A", url="https://a")]


def test_ai_frontier_adapter_wraps_existing_source():
    adapter = AIFrontierAdapter("reddit", FakeAISource({}))
    raw = asyncio.run(adapter.fetch())
    content = adapter.normalize(raw[0], collected_at=NOW)
    assert adapter.adapter_id == "ai_frontier:reddit"
    assert content.source == "ai_frontier:reddit"


def test_build_ai_adapters_respects_top_level_enabled_flags():
    adapters = build_ai_adapters(
        {"sources": {"arxiv": {"enabled": True}, "reddit": {"enabled": False}}}
    )
    keys = {adapter.source_key for adapter in adapters}
    assert "arxiv" in keys
    assert "reddit" not in keys
