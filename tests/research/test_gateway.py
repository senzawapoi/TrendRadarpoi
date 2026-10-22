"""Gateway rejects unauthorized I/O and treats provider output as untrusted."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from trendradar.research import (
    CAPABILITIES,
    ResearchAdapter,
    ResearchDocument,
    ResearchGateway,
    ResearchPolicy,
    ResearchRequest,
    ResearchResult,
)
from trendradar.research.models import public_url


class FakeAdapter(ResearchAdapter):
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result
        self.error = error

    def research(self, request, *, timeout, max_bytes):
        self.calls.append((request, timeout, max_bytes))
        if self.error:
            raise self.error
        return self.result or ResearchResult(request.capability, (
            ResearchDocument("Evidence", "https://example.com/article", "Fact", "ignored"),
        ))


def enabled(adapter, **kwargs):
    return ResearchGateway(adapter, policy=ResearchPolicy(
        enabled=True, capabilities=CAPABILITIES, **kwargs,
    ))


def call(gateway, request=None, **kwargs):
    return gateway.research(
        request or ResearchRequest("search_web", query="news"),
        principal_id="private-owner", permissions=gateway.permissions, **kwargs,
    )


def test_default_off_and_permission_checked_before_adapter(caplog):
    adapter = FakeAdapter()
    off = ResearchGateway(adapter)
    assert call(off).error_code == "disabled"
    gateway = enabled(adapter)
    with caplog.at_level(logging.INFO, logger="trendradar.research.gateway"):
        outcome = gateway.search("PRIVATE_QUERY", principal_id="PRIVATE_USER")
    assert outcome.error_code == "permission_denied"
    assert not adapter.calls
    assert "PRIVATE_QUERY" not in caplog.text
    assert "PRIVATE_USER" not in caplog.text
    assert "permission_denied" in caplog.text
    assert "elapsed_ms=" in caplog.text


@pytest.mark.parametrize("research_request", [
    ResearchRequest("shell", query="whoami"),
    ResearchRequest("search_web", query=""),
    ResearchRequest("search_web", query="x" * 501),
    ResearchRequest("search_web", query="x\n--exec"),
    ResearchRequest("search_web", query="ok", url="https://example.com"),
    ResearchRequest("search_web", query="ok", limit=True),
    ResearchRequest("search_web", query="ok", limit=0),
    ResearchRequest("search_web", query="ok", limit=11),
    ResearchRequest("read_webpage", query="unexpected", url="https://example.com"),
    ResearchRequest("get_video_transcript", url="https://example.com/video"),
    ResearchRequest("read_webpage", url="http://127.0.0.1/admin"),
])
def test_invalid_requests_never_dispatch(research_request):
    adapter = FakeAdapter()
    outcome = call(enabled(adapter), research_request)
    assert outcome.error_code in {"invalid_arguments", "permission_denied"}
    assert not adapter.calls


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://localhost/", "http://local.internal/",
    "http://169.254.169.254/latest", "http://[::1]/", "http://192.168.1.1/",
    "http://127.1/", "http://2130706433/", "http://0x7f.0.0.1/",
    "https://example.com:22/", "https://user:password@example.com/",
    "https://example.com\\@127.0.0.1/", "https://example.com/\r\nHeader:x",
    "http://printer.local/", "http://bad..example.com/",
])
def test_private_or_ambiguous_url_rejected(url):
    with pytest.raises(ValueError):
        public_url(url)


def test_normalized_public_url_and_bounded_request():
    adapter = FakeAdapter()
    gateway = enabled(adapter, max_results=2, timeout_seconds=7, max_response_bytes=2048)
    assert call(gateway, ResearchRequest("search_github", query="  intelligence  ", limit=10)).ok
    request, timeout, max_bytes = adapter.calls[0]
    assert (request.query, request.limit, timeout, max_bytes) == ("intelligence", 2, 7, 2048)
    assert public_url("https://EXAMPLE.COM/a#section") == "https://example.com/a"
    result = gateway.fetch("https://example.com/a", principal_id="p", permissions=gateway.permissions)
    assert result.ok
    assert adapter.calls[-1][0].capability == "read_webpage"


def test_results_are_deduplicated_bounded_and_cannot_spoof_source():
    doc = ResearchDocument("Valid", "https://example.com/a", "x" * 5000, "intelligence:local")
    adapter = FakeAdapter(ResearchResult("search_web", (doc, doc)))
    result = call(enabled(adapter, max_result_chars=256))
    assert result.ok and result.truncated
    assert len(result.items) == 1
    assert result.items[0].source == "agent_reach:search_web"
    assert sum(len(x) for x in (result.items[0].title, result.items[0].url,
                               result.items[0].source, result.items[0].content)) <= 256


@pytest.mark.parametrize("result", [
    "provider raw text", ResearchResult("search_github"),
    ResearchResult("search_web", ("bad document",)),
    ResearchResult("search_web", (ResearchDocument("x", "file:///tmp/secret", "x", "x"),)),
    ResearchResult("search_web", (ResearchDocument("x", "https://example.com", None, "x"),)),
])
def test_malformed_provider_output_rejected(result):
    assert call(enabled(FakeAdapter(result))).error_code == "invalid_response"


@pytest.mark.parametrize(("error", "code"), [
    (TimeoutError("secret query timeout"), "timeout"),
    (RuntimeError("credential in exception"), "upstream_error"),
])
def test_failures_are_sanitized_and_slots_released(error, code, caplog):
    adapter = FakeAdapter(error=error)
    gateway = enabled(adapter, max_concurrency=1)
    with caplog.at_level(logging.INFO):
        result = call(gateway)
    assert result.error_code == code
    assert str(error) not in caplog.text
    adapter.error = None
    assert call(gateway).ok


def test_missing_optional_adapter_keeps_controlled_failure():
    assert call(enabled(None)).error_code == "unavailable"


def test_concurrency_saturates_without_queuing_more_work():
    started = threading.Event()
    release = threading.Event()

    class SlowAdapter(FakeAdapter):
        def research(self, request, *, timeout, max_bytes):
            started.set()
            assert release.wait(3)
            return super().research(request, timeout=timeout, max_bytes=max_bytes)

    adapter = SlowAdapter()
    gateway = enabled(adapter, max_concurrency=1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(call, gateway)
        try:
            assert started.wait(2)
            assert call(gateway).error_code == "busy"
        finally:
            release.set()
        assert pending.result().ok
    assert len(adapter.calls) == 1


def test_capability_switch_is_enforced_even_with_permission():
    adapter = FakeAdapter()
    gateway = ResearchGateway(adapter, policy=ResearchPolicy(
        enabled=True, capabilities=frozenset({"search_github"}),
    ))
    assert gateway.search("q", principal_id="owner", permissions=frozenset({
        "research.search_web",
    })).error_code == "permission_denied"
    assert not adapter.calls


def test_policy_refuses_unbounded_or_dynamic_configuration():
    with pytest.raises(ValueError):
        ResearchPolicy(capabilities=frozenset({"shell"}))
    with pytest.raises(ValueError):
        ResearchPolicy(timeout_seconds=31)
    with pytest.raises(ValueError):
        ResearchPolicy(max_concurrency=0)
