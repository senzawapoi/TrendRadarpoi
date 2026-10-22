from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trendradar.ai.assistant import AssistantService
from trendradar.ai.client import GeminiResult, GeminiToolCall
from trendradar.ai.models import AssistantRequest, TimeRange
from trendradar.ai.retrieval import LocalRetriever
from trendradar.ai.tools import ToolContext, ToolRegistry
from trendradar.research import (
    ResearchAdapter,
    ResearchDocument,
    ResearchGateway,
    ResearchPolicy,
    ResearchRequest,
    ResearchResult,
)

NOW = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)


class FakeResearch(ResearchAdapter):
    def __init__(self):
        self.calls = 0

    def research(self, request: ResearchRequest, *, timeout: float, max_bytes: int):
        self.calls += 1
        return ResearchResult(request.capability, (
            ResearchDocument("External fact", "https://example.com/research", "A fact", "fake"),
        ))


class FakeGemini:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.results.pop(0)


def _gateway(adapter):
    return ResearchGateway(adapter, policy=ResearchPolicy(
        enabled=True, capabilities=frozenset({"search_web"}),
    ))


def test_assistant_exposes_only_enabled_research_tool_and_server_citation(seeded_intelligence):
    adapter = FakeResearch()
    gateway = _gateway(adapter)
    ref = "research:" + __import__("hashlib").sha256(
        b"search_web\nhttps://example.com/research\nExternal fact"
    ).hexdigest()[:40]
    gemini = FakeGemini(
        GeminiResult(
            text="", model="fake",
            tool_calls=(GeminiToolCall("research_external", {
                "capability": "search_web", "query": "topic", "limit": 1,
            }),),
        ),
        GeminiResult(text=f"External result [{ref}]", model="fake"),
    )
    registry = ToolRegistry(enabled={"research_external": True})
    service = AssistantService(
        seeded_intelligence.storage, gemini_client=gemini,
        tool_registry=registry, research_gateway=gateway,
        enabled_tools={"research_external"},
    )
    reply = service.handle(AssistantRequest("research-1", "owner", "research topic", requested_at=NOW))
    assert reply.degraded is False
    assert ref in reply.text
    assert len(reply.citations) == 1
    assert reply.citations[0].snapshot["external"] is True
    assert reply.citations[0].snapshot["untrusted"] is True
    assert adapter.calls == 1
    assert not seeded_intelligence.storage.search_content_items(
        "External fact", start=NOW - timedelta(days=1), end=NOW + timedelta(days=1)
    )
    service.close()


def test_forged_external_citation_is_removed(seeded_intelligence):
    adapter = FakeResearch()
    gateway = _gateway(adapter)
    gemini = FakeGemini(GeminiResult(
        text="Answer [research:not-returned]", model="fake",
    ))
    service = AssistantService(
        seeded_intelligence.storage, gemini_client=gemini,
        tool_registry=ToolRegistry(enabled={"research_external": True}),
        research_gateway=gateway, enabled_tools={"research_external"},
    )
    reply = service.handle(AssistantRequest("research-1", "owner", "topic", requested_at=NOW))
    assert "research:not-returned" not in reply.text
    assert reply.degraded is True
    assert adapter.calls == 0
    service.close()


def test_gateway_failure_preserves_local_degraded_answer(seeded_intelligence):
    class Failed(ResearchAdapter):
        def research(self, request, *, timeout, max_bytes):
            raise RuntimeError("upstream secret")

    gateway = _gateway(Failed())
    gemini = FakeGemini(
        GeminiResult(text="", model="fake", tool_calls=(GeminiToolCall(
            "research_external", {"capability": "search_web", "query": "topic"}
        ),)),
        GeminiResult(text="Local answer", model="fake"),
    )
    service = AssistantService(
        seeded_intelligence.storage, gemini_client=gemini,
        tool_registry=ToolRegistry(enabled={"research_external": True}),
        research_gateway=gateway, enabled_tools={"research_external"},
    )
    reply = service.handle(AssistantRequest("research-1", "owner", "Alpha", requested_at=NOW))
    assert reply.degraded is True
    assert reply.text == "Local answer"
    assert all("upstream secret" not in message.content for message in service.sessions.load_messages(
        reply.session_id, "owner", now=NOW,
    ))
    service.close()


def test_disabled_gateway_tool_is_not_in_gemini_definitions(seeded_intelligence):
    adapter = FakeResearch()
    gateway = ResearchGateway(adapter)
    gemini = FakeGemini(GeminiResult(text="local", model="fake"))
    service = AssistantService(
        seeded_intelligence.storage, gemini_client=gemini,
        research_gateway=gateway,
    )
    reply = service.handle(AssistantRequest("research-1", "owner", "Alpha", requested_at=NOW))
    definitions = gemini.calls[0][1]["tools"]
    assert all(definition.name != "research_external" for definition in definitions)
    assert adapter.calls == 0
    assert reply.degraded is False
    service.close()


def test_research_tool_direct_permission_and_argument_boundary(seeded_intelligence):
    adapter = FakeResearch()
    gateway = _gateway(adapter)
    context = ToolContext(
        principal_id="owner",
        retriever=LocalRetriever(seeded_intelligence.storage),
        storage=seeded_intelligence.storage,
        time_range=TimeRange.previous_days(NOW),
        research_gateway=gateway,
        permissions=frozenset(),
        enabled_tools=frozenset({"research_external"}),
    )
    registry = ToolRegistry(enabled={"research_external": True})
    denied = registry.execute("research_external", {"capability": "search_web", "query": "x"}, context)
    assert denied.error_code == "permission_denied"
    assert adapter.calls == 0
    context.retriever.close()
