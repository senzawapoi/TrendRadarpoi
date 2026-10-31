"""NVD collection-time significance filter and published-date window."""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

from trendradar.domains.security.collector import parse_nvd_page
from trendradar.intelligence.runner import AdapterRunner
from trendradar.sources.base import HealthStatus
from trendradar.sources.security import NvdCveAdapter, NvdSignificanceFilter

NOW = datetime(2026, 10, 31, 8, tzinfo=timezone.utc)


def _cve(cve_id: str, description: str, score: float | None) -> dict:
    metrics = {}
    if score is not None:
        metrics = {"cvssMetricV31": [{
            "type": "Primary",
            "cvssData": {
                "baseScore": score, "baseSeverity": "CRITICAL" if score >= 9 else "HIGH",
                "version": "3.1", "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            },
        }]}
    return {"cve": {
        "id": cve_id, "sourceIdentifier": "cna@example.com",
        "published": "2026-10-30T01:02:03.000Z", "lastModified": "2026-10-30T04:05:06.000Z",
        "vulnStatus": "Received",
        "descriptions": [{"lang": "en", "value": description}],
        "metrics": metrics, "weaknesses": [], "references": [],
    }}


PAGE = {
    "totalResults": 6, "startIndex": 0, "resultsPerPage": 6,
    "vulnerabilities": [
        _cve("CVE-2026-1", "Langflow before 1.9 allows remote code execution.", 8.8),
        _cve("CVE-2026-2", "Langflow before 1.9 leaks a token.", 6.5),
        _cve("CVE-2026-3", "OpenSSH sshd allows unauthenticated RCE.", 9.8),
        _cve("CVE-2026-4", "Insecure permissions in Shopping List app.", 9.1),
        _cve("CVE-2026-5", "X-ray viewer plugin overflow.", 9.9),
        _cve("CVE-2026-6", "Ollama path traversal.", None),
    ],
}


def _records():
    return parse_nvd_page(PAGE)[0]


def test_default_rules_keep_ai_stack_high_and_major_platform_critical_only():
    rule = NvdSignificanceFilter({"enabled": True})
    reasons = {record.external_id: rule.reason(record) for record in _records()}
    assert reasons == {
        "CVE-2026-1": "ai_stack",          # AI stack and CVSS >= 8.0
        "CVE-2026-2": None,                # AI stack but below 8.0
        "CVE-2026-3": "major_platform",    # widely deployed platform and CVSS >= 9.0
        "CVE-2026-4": None,                # critical, but neither AI nor major platform
        "CVE-2026-5": None,                # no keyword ("X-ray" is not "Ray")
        "CVE-2026-6": None,                # unscored records are skipped by default
    }


def test_disabled_filter_keeps_everything_and_known_exploited_bypasses_rules():
    records = _records()
    assert all(NvdSignificanceFilter({}).reason(record) for record in records)
    exploited = replace(records[3], known_exploited=True)
    assert NvdSignificanceFilter({"enabled": True}).reason(exploited) == "known_exploited"
    assert NvdSignificanceFilter(
        {"enabled": True, "keep_known_exploited": False}
    ).reason(exploited) is None


def test_incidental_platform_words_do_not_match_major_platform_rule():
    page = {**PAGE, "vulnerabilities": [
        _cve("CVE-2026-7", "Path traversal in Acme FTP Server running on Windows.", 9.8),
        _cve("CVE-2026-8", "SOCFortress CoPilot allows SQL injection.", 9.9),
        _cve("CVE-2026-9", "Microsoft Windows SMB server allows RCE.", 9.8),
    ]}
    rule = NvdSignificanceFilter({"enabled": True})
    assert [rule.match(record) for record in parse_nvd_page(page)[0]] == [
        None, None, ("major_platform", "Microsoft Windows"),
    ]


def test_per_keyword_cap_keeps_highest_scores_in_source_order():
    page = {**PAGE, "vulnerabilities": [
        _cve(f"CVE-2026-{index}", "Langflow remote code execution.", score)
        for index, score in enumerate((8.1, 9.8, 8.8, 9.1, 8.0), start=10)
    ] + [_cve("CVE-2026-20", "Ollama RCE.", 8.5)]}
    rule = NvdSignificanceFilter({"enabled": True, "max_per_keyword": 2})
    matches = [(record, *rule.match(record)) for record in parse_nvd_page(page)[0]]
    assert [record.external_id for record, *_ in rule.cap(matches)] == [
        "CVE-2026-11", "CVE-2026-13", "CVE-2026-20",
    ]
    assert len(NvdSignificanceFilter({"enabled": True}).cap(matches)) == 6


def test_configured_rules_replace_defaults_and_can_include_unscored():
    rule = NvdSignificanceFilter({
        "enabled": "true",
        "rules": [
            {"name": "watch", "min_cvss": 5, "keywords": "langflow, ollama",
             "include_unscored": True},
            {"name": "everything_critical", "min_cvss": 9.5},
        ],
    })
    reasons = {record.external_id: rule.reason(record) for record in _records()}
    assert reasons["CVE-2026-2"] == "watch"
    assert reasons["CVE-2026-6"] == "watch"
    assert reasons["CVE-2026-3"] == "everything_critical"
    assert reasons["CVE-2026-4"] is None


class _Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    async def json(self, *, content_type=None):
        return self.payload

    def release(self):
        pass


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _install(monkeypatch, payload):
    import trendradar.sources.security as source_module

    calls = []

    async def fake_request(session, method, url, **kwargs):
        calls.append(kwargs["params"])
        return _Response(payload)

    monkeypatch.setattr(source_module, "make_session", lambda **kwargs: _Session())
    monkeypatch.setattr(source_module, "request_with_retry", fake_request)
    return calls


def test_adapter_uses_published_window_and_filters_before_the_item_cap(monkeypatch):
    calls = _install(monkeypatch, PAGE)
    adapter = NvdCveAdapter(
        {"date_field": "published", "max_items": 1, "request_interval_seconds": 0,
         "significance": {"enabled": True}},
        now=NOW,
    )
    records = asyncio.run(adapter.fetch())
    # Filtering happens before max_items, so the cap keeps the first significant CVE.
    assert [record.external_id for record in records] == ["CVE-2026-1"]
    assert set(calls[0]) == {"pubStartDate", "pubEndDate", "resultsPerPage", "startIndex"}
    assert calls[0]["pubEndDate"].startswith("2026-10-31T08:00:00")


def test_adapter_defaults_remain_modified_window_without_filter(monkeypatch):
    calls = _install(monkeypatch, PAGE)
    adapter = NvdCveAdapter({"request_interval_seconds": 0, "date_field": "bogus"}, now=NOW)
    assert adapter.date_field == "modified"
    assert len(asyncio.run(adapter.fetch())) == 6
    assert "lastModStartDate" in calls[0]


def test_run_with_nothing_significant_is_degraded_not_failed(monkeypatch):
    _install(monkeypatch, {**PAGE, "totalResults": 1, "resultsPerPage": 1,
                           "vulnerabilities": [PAGE["vulnerabilities"][3]]})
    adapter = NvdCveAdapter(
        {"significance": {"enabled": True}, "request_interval_seconds": 0}, now=NOW
    )
    result = asyncio.run(AdapterRunner().run([adapter], collected_at=NOW))[0]
    assert result.items == []
    assert result.fetch_error == ""
    # Health accepts degraded runs without errors, so readiness is not blocked.
    assert result.health.status == HealthStatus.DEGRADED
    assert result.health.error_count == 0
