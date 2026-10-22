import asyncio
from datetime import datetime, timezone

import pytest

from trendradar.crawler.rss.fetcher import RSSFeedConfig
from trendradar.crawler.rss.parser import RSSParser
from trendradar.domains.security.collector import (
    NVD_DETAIL_URL,
    build_security_adapters,
    collect_security,
    extract_cve_ids,
    parse_cisa_catalog,
    parse_nvd_page,
    security_record_from_rss,
)
from trendradar.intelligence.runner import AdapterRunner
from trendradar.sources.base import HealthStatus
from trendradar.sources.security import CisaKevAdapter, NvdCveAdapter, SecurityRSSAdapter
from trendradar.storage.base import RSSData, RSSItem

NOW = datetime(2026, 9, 4, 8, tzinfo=timezone.utc)


def _nvd_wrapper(cve_id: str, *, metrics: dict | None = None) -> dict:
    return {
        "cve": {
            "id": cve_id,
            "sourceIdentifier": "security@example.com",
            "published": "2026-09-01T01:02:03.000Z",
            "lastModified": "2026-09-03T04:05:06.000Z",
            "vulnStatus": "Analyzed",
            "descriptions": [
                {"lang": "es", "value": "Descripcion"},
                {"lang": "en", "value": "Remote code execution. More detail."},
            ],
            "metrics": metrics or {},
            "weaknesses": [
                {"description": [{"lang": "en", "value": "CWE-78"}]},
            ],
            "references": [{"url": f"https://vendor.example/{cve_id}"}],
        }
    }


def test_extract_cve_ids_is_exact_case_insensitive_and_stable():
    assert extract_cve_ids(
        "cve-2026-1234 and CVE-2026-12345",
        ["CVE-2026-1234", "not-cve-2026-12"],
    ) == ["CVE-2026-1234", "CVE-2026-12345"]


def test_parse_cisa_catalog_normalizes_complete_provenance():
    records = parse_cisa_catalog(
        {
            "title": "CISA Known Exploited Vulnerabilities Catalog",
            "catalogVersion": "2026.09.04",
            "dateReleased": "2026-09-04T07:00:00Z",
            "count": 1,
            "vulnerabilities": [
                {
                    "cveID": "cve-2026-12345",
                    "vendorProject": "Example Corp",
                    "product": "Example Server",
                    "vulnerabilityName": "Command injection",
                    "dateAdded": "2026-09-03",
                    "shortDescription": "Commands may be executed remotely.",
                    "requiredAction": "Apply the vendor update.",
                    "dueDate": "2026-09-24",
                    "knownRansomwareCampaignUse": "Known",
                    "notes": "https://example.com/advisory",
                    "cwes": ["CWE-78"],
                }
            ],
        },
        source_url="https://cisa.example/kev.json",
    )

    assert len(records) == 1
    item = records[0].to_content_item(collected_at=NOW)
    assert item.domain == "security"
    assert item.source == "security:cisa-kev"
    assert item.url == NVD_DETAIL_URL.format(cve_id="CVE-2026-12345")
    assert item.published_time == datetime(2026, 9, 3, tzinfo=timezone.utc)
    assert item.metadata["raw_url"] == "https://cisa.example/kev.json"
    assert item.metadata["source_content_id"] == "CVE-2026-12345"
    assert item.metadata["catalog_version"] == "2026.09.04"
    assert item.metadata["known_exploited"] is True
    assert item.metadata["required_action"] == "Apply the vendor update."
    assert item.metadata["due_date"] == "2026-09-24"
    assert item.metadata["cve_ids"] == ["CVE-2026-12345"]
    assert {"CVE-2026-12345", "KEV", "CWE-78"} <= set(item.tags)


@pytest.mark.parametrize("payload", [[], {}, {"vulnerabilities": None}])
def test_parse_cisa_catalog_rejects_invalid_contract(payload):
    with pytest.raises(ValueError, match="CISA KEV"):
        parse_cisa_catalog(payload)


def test_parse_nvd_page_prefers_primary_cvss_v4_and_english_description():
    metrics = {
        "cvssMetricV31": [
            {
                "type": "Primary",
                "cvssData": {"version": "3.1", "baseScore": 9.8, "baseSeverity": "CRITICAL"},
            }
        ],
        "cvssMetricV40": [
            {
                "type": "Secondary",
                "cvssData": {"version": "4.0", "baseScore": 5.0, "baseSeverity": "MEDIUM"},
            },
            {
                "type": "Primary",
                "cvssData": {
                    "version": "4.0",
                    "baseScore": 8.7,
                    "baseSeverity": "HIGH",
                    "vectorString": "CVSS:4.0/AV:N/AC:L/AT:N",
                },
            },
        ],
    }
    records, total, start, per_page = parse_nvd_page(
        {
            "totalResults": 1,
            "startIndex": 0,
            "resultsPerPage": 1,
            "vulnerabilities": [_nvd_wrapper("CVE-2026-22222", metrics=metrics)],
        }
    )

    assert (total, start, per_page) == (1, 0, 1)
    record = records[0]
    assert record.summary == "Remote code execution. More detail."
    assert (record.severity, record.cvss_score, record.cvss_version) == ("HIGH", 8.7, "4.0")
    item = record.to_content_item(collected_at=NOW)
    assert item.published_time == datetime(2026, 9, 1, 1, 2, 3, tzinfo=timezone.utc)
    assert item.metadata["cvss_vector"] == "CVSS:4.0/AV:N/AC:L/AT:N"
    assert item.metadata["references"] == ["https://vendor.example/CVE-2026-22222"]


@pytest.mark.parametrize(
    "payload",
    [[], {}, {"vulnerabilities": None}, {"vulnerabilities": [], "totalResults": "bad"}],
)
def test_parse_nvd_page_rejects_invalid_contract(payload):
    with pytest.raises(ValueError, match="NVD"):
        parse_nvd_page(payload)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.status = 200
        self.released = False

    async def json(self, *, content_type=None):
        return self.payload

    def release(self) -> None:
        self.released = True


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def test_nvd_adapter_bounds_pagination_and_sends_optional_key(monkeypatch):
    import trendradar.sources.security as source_module

    calls = []

    async def fake_request(session, method, url, **kwargs):
        calls.append((method, url, kwargs))
        start = kwargs["params"]["startIndex"]
        ids = (
            ["CVE-2026-10001", "CVE-2026-10002"]
            if start == 0
            else ["CVE-2026-10003", "CVE-2026-10004"]
        )
        return _FakeResponse(
            {
                "totalResults": 8,
                "startIndex": start,
                "resultsPerPage": 2,
                "vulnerabilities": [_nvd_wrapper(cve_id) for cve_id in ids],
            }
        )

    monkeypatch.setattr(source_module, "make_session", lambda **kwargs: _FakeSession())
    monkeypatch.setattr(source_module, "request_with_retry", fake_request)
    adapter = NvdCveAdapter(
        {
            "lookback_hours": 24,
            "results_per_page": 2,
            "max_pages": 2,
            "max_items": 3,
            "request_interval_seconds": 0,
        },
        now=NOW,
        api_key="secret-test-key",
    )

    records = asyncio.run(adapter.fetch())

    assert [record.external_id for record in records] == [
        "CVE-2026-10001",
        "CVE-2026-10002",
        "CVE-2026-10003",
    ]
    assert len(calls) == 2
    assert [call[2]["params"]["startIndex"] for call in calls] == [0, 2]
    assert all(call[2]["headers"] == {"apiKey": "secret-test-key"} for call in calls)
    assert calls[0][2]["params"]["lastModEndDate"].startswith("2026-09-04T08:00:00")
    assert NvdCveAdapter(
        {"request_interval_seconds": 9999}, now=NOW
    ).request_interval == 60


def test_cisa_adapter_applies_limit_to_newest_records(monkeypatch):
    import trendradar.sources.security as source_module

    payload = {
        "vulnerabilities": [
            {
                "cveID": "CVE-2026-10001",
                "vulnerabilityName": "Older",
                "dateAdded": "2026-01-01",
            },
            {
                "cveID": "CVE-2026-10002",
                "vulnerabilityName": "Newest",
                "dateAdded": "2026-09-03",
            },
        ]
    }

    async def fake_request(*_args, **_kwargs):
        return _FakeResponse(payload)

    monkeypatch.setattr(source_module, "make_session", lambda **kwargs: _FakeSession())
    monkeypatch.setattr(source_module, "request_with_retry", fake_request)

    records = asyncio.run(CisaKevAdapter({"max_items": 1}).fetch())

    assert [record.external_id for record in records] == ["CVE-2026-10002"]


def test_rss_parser_accepts_plain_string_guid():
    parser = RSSParser.__new__(RSSParser)
    parser.max_summary_length = 500

    parsed = parser._parse_entry(
        {
            "title": "Security advisory",
            "link": "https://example.com/advisory",
            "guid": "stable-guid",
        }
    )

    assert parsed is not None
    assert parsed.guid == "stable-guid"


def test_security_rss_record_extracts_cves_and_adapter_uses_existing_fetcher():
    item = RSSItem(
        title="CISA warns about CVE-2026-45678",
        feed_id="cisa-advisories",
        feed_name="CISA Advisories",
        url="https://www.cisa.gov/news-events/alerts/example",
        published_at="2026-09-04T07:00:00Z",
        summary="Also addresses cve-2026-45679.",
        author="CISA",
    )
    record = security_record_from_rss(item)
    assert record.cve_ids == ("CVE-2026-45678", "CVE-2026-45679")

    class FakeFetcher:
        async def async_fetch_all(self, max_workers):
            assert max_workers == 1
            return RSSData(
                date="2026-09-04",
                crawl_time="16:00",
                items={"cisa-advisories": [item]},
                failed_ids=[],
            )

        def _filter_by_freshness(self, items, feed):
            return items, 0

    adapter = SecurityRSSAdapter(
        RSSFeedConfig(
            id="cisa-advisories",
            name="CISA Advisories",
            url="https://www.cisa.gov/cybersecurity-advisories/all.xml",
        )
    )
    adapter.fetcher = FakeFetcher()
    fetched = asyncio.run(adapter.fetch())
    content = adapter.normalize(fetched[0], collected_at=NOW)
    assert content.source == "security:rss:cisa-advisories"
    assert content.domain == "security"
    assert content.metadata["source_name"] == "CISA Advisories"
    assert content.metadata["author"] == "CISA"
    assert content.metadata["cve_ids"] == ["CVE-2026-45678", "CVE-2026-45679"]


def test_build_and_collect_security_respect_disabled_and_storage_boundaries():
    disabled = {
        "enabled": True,
        "sources": {
            "cisa_kev": {"enabled": False},
            "nvd": {"enabled": False},
            "rss": {"enabled": False},
        },
    }
    assert build_security_adapters(disabled, now=NOW) == []
    assert asyncio.run(collect_security({}, storage=None, collected_at=NOW)) == []
    assert asyncio.run(
        collect_security({"enabled": False}, storage=object(), collected_at=NOW)
    ) == []
    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(collect_security(disabled, storage=object(), collected_at=NOW.replace(tzinfo=None)))


def test_build_security_adapters_isolates_one_invalid_rss_feed(monkeypatch):
    import trendradar.sources.security as source_module

    built = []

    class FakeRSSAdapter:
        def __init__(self, feed, **_options):
            if feed.id == "bad":
                raise ValueError("invalid feed")
            self.feed = feed
            built.append(feed.id)

    monkeypatch.setattr(source_module, "SecurityRSSAdapter", FakeRSSAdapter)
    config = {
        "sources": {
            "cisa_kev": {"enabled": "false"},
            "nvd": {"enabled": "false"},
            "rss": {
                "enabled": "true",
                "feeds": [
                    {"id": "bad", "name": "Bad", "url": "https://bad.example/rss"},
                    {"id": "good", "name": "Good", "url": "https://good.example/rss"},
                ],
            },
        }
    }

    adapters = build_security_adapters(config, now=NOW)

    assert len(adapters) == 1
    assert built == ["good"]


def test_runner_isolates_invalid_cisa_record_as_partial_normalization_failure():
    records = parse_cisa_catalog(
        {
            "vulnerabilities": [
                {
                    "cveID": "CVE-2026-90001",
                    "vulnerabilityName": "Valid entry",
                    "dateAdded": "2026-09-04",
                },
                {},
            ]
        }
    )

    class StaticCisaAdapter(CisaKevAdapter):
        async def fetch(self):
            return records

    result = asyncio.run(AdapterRunner().run([StaticCisaAdapter()], collected_at=NOW))[0]
    assert len(result.items) == 1
    assert result.health.status is HealthStatus.DEGRADED
    assert result.health.error_count == 1
    assert "external_id" in result.normalize_errors[0]
