"""TRP-AI-002 regressions: bounded arguments, honest recovery, safe audit."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from trendradar.ai.assistant import AssistantService
from trendradar.ai.client import GeminiClient, GeminiConfig, GeminiResult, GeminiToolCall
from trendradar.ai.models import AssistantRequest, TimeRange
from trendradar.ai.retrieval import LocalRetriever
from trendradar.ai.tools import (
    ToolContext,
    ToolDeniedError,
    ToolExecutionError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    ToolValidationError,
)

NOW = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
START = "2026-08-28T12:00:00+00:00"
END = "2026-09-04T12:00:00+00:00"
RANGE = {"start": START, "end": END}


class SequenceGemini:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((tuple(messages), kwargs))
        return self.outcomes.pop(0)


def tool_call(arguments, name="search_stories"):
    return GeminiResult(
        text="",
        model="fake",
        tool_calls=(GeminiToolCall(name=name, arguments=arguments),),
    )


def run_turn(seeded, *outcomes, **kwargs):
    gemini = SequenceGemini(*outcomes)
    service = AssistantService(seeded.storage, gemini_client=gemini, **kwargs)
    reply = service.handle(AssistantRequest("repair", "owner", "Alpha", requested_at=NOW))
    return reply, gemini, service


def context(seeded):
    return ToolContext(
        principal_id="owner",
        retriever=LocalRetriever(seeded.storage),
        storage=seeded.storage,
        time_range=TimeRange.previous_days(NOW),
        permissions=frozenset({"intelligence.read", "intelligence.evidence"}),
    )


@pytest.mark.parametrize("name", ["search_stories", "search_content_items"])
@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"start": START, "end": END},
        {"time_range": RANGE},
        {"time_range": {"start": "2026-08-28T20:00:00+08:00", "end": END}},
    ],
)
def test_search_range_defaults_legacy_and_nested(seeded_intelligence, name, arguments):
    result = ToolRegistry().execute(
        name, {"query": "Alpha", **arguments}, context(seeded_intelligence)
    )
    assert result.ok
    assert json.loads(result.text)["time_range"] == RANGE
    assert result.citations


@pytest.mark.parametrize("name", ["search_stories", "search_content_items"])
@pytest.mark.parametrize(
    "arguments",
    [
        {"start": START},
        {"end": END},
        {"start": "2026-08-28T12:00:00", "end": END},
        {"start": END, "end": START},
        {"start": END, "end": END},
        {"start": "2026-02-30T00:00:00Z", "end": END},
        {"start": "0001-01-01T00:00:00+01:00", "end": END},
        {"start": "2000-01-01T00:00:00Z", "end": END},
        {"time_range": {"start": START}},
        {"time_range": {"end": END}},
        {"time_range": {"start": START, "end": END, "extra": 1}},
        {"time_range": {"start": "x" * 81, "end": END}},
        {"time_range": RANGE, "start": START, "end": END},
        {"limit": 21},
    ],
)
def test_bad_ranges_are_correctable_argument_errors(seeded_intelligence, name, arguments):
    result = ToolRegistry().execute(name, arguments, context(seeded_intelligence))
    assert result.error_code == "invalid_arguments"
    payload = json.loads(result.text)
    assert payload["retryable"] is True
    assert payload["detail"]


def test_nested_schema_survives_core_and_sdk_transport_validation():
    from google.genai import types

    seen = []

    def generate_content(**kwargs):
        # Exercise the actual SDK config model without constructing a live client.
        config = types.GenerateContentConfig.model_validate(kwargs["config"])
        seen.extend(config.tools[0].function_declarations)
        return SimpleNamespace(text="done", candidates=())

    client = GeminiClient(
        GeminiConfig(enabled=True, api_key="offline-placeholder"),
        client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)),
    )
    client.chat("Alpha", tools=ToolRegistry().definitions())
    for declaration in seen:
        if declaration.name.startswith("search_"):
            schema = declaration.parameters_json_schema
            nested = schema["properties"]["time_range"]
            assert set(nested["required"]) == {"start", "end"}
            assert nested["additionalProperties"] is False
            assert "start" not in schema["properties"]
            assert "end" not in schema["properties"]


@pytest.mark.parametrize(
    ("error_type", "code"),
    [
        (ToolValidationError, "invalid_arguments"),
        (ToolDeniedError, "handler_denied"),
        (ToolExecutionError, "handler_failed"),
        (RuntimeError, "handler_failed"),
    ],
)
def test_handler_errors_are_classified_and_audited_without_raw_details(
    seeded_intelligence,
    caplog,
    error_type,
    code,
):
    secret = "private-user-id https://example.test/?token=never-log"

    def fail(_context, _arguments):
        raise error_type(secret)

    registry = ToolRegistry(
        (
            ToolSpec(
                "lookup",
                "Lookup",
                {"type": "object", "properties": {}, "additionalProperties": False},
                "intelligence.read",
                fail,
            ),
        )
    )
    result = registry.execute("lookup", {}, context(seeded_intelligence))
    assert result.error_code == code
    assert secret not in result.text + caplog.text
    assert "tool_attempt_failed" in caplog.text
    assert code in caplog.text


def test_unknown_name_and_arguments_are_not_audited_raw(seeded_intelligence, caplog):
    result = ToolRegistry().execute(
        "private-user-id-https://example.test/?token=never-log",
        {"query": "sensitive message body"},
        context(seeded_intelligence),
    )
    assert result.error_code == "unknown_tool"
    assert "tool_attempt_failed" in caplog.text
    assert "private-user-id" not in result.name + result.text + caplog.text
    assert "sensitive message body" not in caplog.text


def test_one_correction_with_matching_evidence_recovers_and_preserves_failed_audit(
    seeded_intelligence,
    caplog,
):
    ref = f"story:{seeded_intelligence.story.id}"
    reply, gemini, service = run_turn(
        seeded_intelligence,
        tool_call({"query": "Alpha", "start": START}),
        tool_call({"query": "Alpha", "time_range": RANGE}),
        GeminiResult(text=f"Grounded [{ref}].", model="fake"),
    )
    assert not reply.degraded
    assert [item.error for item in reply.tool_calls] == ["invalid_arguments", ""]
    assert [item.ref for item in reply.citations] == [ref]
    assert "tool_attempt_failed" in caplog.text
    assert "Alpha" not in caplog.text
    assert len(gemini.calls) == 3
    stored = service.sessions.get_completed_reply(reply.session_id, "owner", "repair", now=NOW)
    assert stored == reply


@pytest.mark.parametrize(
    "correction",
    [
        {"query": "Unrelated", "time_range": RANGE},
        {"query": "", "time_range": RANGE},
        {"query": "Alpha", "domain": "ai", "time_range": RANGE},
        {"query": "Alpha", "time_range": {"start": "2026-08-29T12:00:00Z", "end": END}},
        {"query": "Alpha"},
    ],
)
def test_different_need_does_not_clear_original_failure(seeded_intelligence, correction):
    reply, _, _ = run_turn(
        seeded_intelligence,
        tool_call({"query": "Alpha", "start": START}),
        tool_call(correction),
        GeminiResult(text="Limited answer.", model="fake"),
    )
    assert reply.degraded
    assert "invalid_arguments" in reply.degraded_reason


def test_empty_success_cannot_recover_from_existing_context_citations(seeded_intelligence):
    spec = ToolRegistry().get("search_stories")
    empty_registry = ToolRegistry(
        (
            ToolSpec(
                spec.name,
                spec.description,
                spec.parameters,
                spec.permission,
                lambda _context, _arguments: ToolResult(
                    "search_stories",
                    True,
                    True,
                    json.dumps(
                        {
                            "stories": [],
                            "time_range": RANGE,
                            "truncation": {"stories": False, "items": False, "citations": False},
                        }
                    ),
                ),
            ),
        )
    )
    reply, _, _ = run_turn(
        seeded_intelligence,
        tool_call({"query": "No matching story", "start": START}),
        tool_call({"query": "No matching story", "start": START, "end": END}),
        GeminiResult(text="I cannot verify that story.", model="fake"),
        tool_registry=empty_registry,
    )
    assert reply.tool_calls[-1].error == ""
    assert reply.degraded
    assert "invalid_arguments" in reply.degraded_reason
    assert "returned no usable evidence" not in reply.degraded_reason


def test_complete_empty_success_is_not_system_degraded(seeded_intelligence):
    reply, _, _ = run_turn(
        seeded_intelligence,
        tool_call({"query": "No matching story"}),
        GeminiResult(
            text="No matching local Stories were found in the selected time range.",
            model="fake",
        ),
    )
    assert reply.tool_calls[0].error == ""
    assert not reply.degraded
    assert reply.degraded_reason == ""
    assert "No matching local Stories" in reply.text


@pytest.mark.parametrize(
    "payload",
    [
        {"stories": [], "time_range": RANGE, "truncated": True, "truncation": {"stories": False}},
        {"stories": [], "time_range": RANGE, "truncation": {"stories": True}},
        {"stories": [], "time_range": RANGE, "truncation": {}},
        {"stories": [], "time_range": {"start": "bad", "end": "bad"},
         "truncation": {"stories": False}},
        {"stories": [], "time_range": {"start": END, "end": START},
         "truncation": {"stories": False}},
        {"stories": [], "time_range": {"start": "2026-08-28T12:00:00", "end": END},
         "truncation": {"stories": False}},
        {"stories": [], "time_range": {"start": "2000-01-01T00:00:00Z", "end": END},
         "truncation": {"stories": False}},
        {"stories": [], "time_range": {"start": "2026-08-29T12:00:00Z", "end": END},
         "truncation": {"stories": False}},
        {"stories": [], "truncation": {"stories": False}},
        {"stories": []},
    ],
)
def test_incomplete_empty_search_is_not_a_normal_no_match(seeded_intelligence, payload):
    spec = ToolRegistry().get("search_stories")
    registry = ToolRegistry(
        (
            ToolSpec(
                spec.name,
                spec.description,
                spec.parameters,
                spec.permission,
                lambda _context, _arguments: ToolResult(
                    "search_stories",
                    True,
                    True,
                    json.dumps(payload),
                ),
            ),
        )
    )
    reply, _, _ = run_turn(
        seeded_intelligence,
        tool_call({"query": "No matching story"}),
        GeminiResult(text="No matching local Stories were found.", model="fake"),
        tool_registry=registry,
    )
    assert reply.degraded
    assert "returned no usable evidence" in reply.degraded_reason


def test_second_invalid_attempt_stops_corrections_even_with_call_budget_left(seeded_intelligence):
    reply, gemini, _ = run_turn(
        seeded_intelligence,
        tool_call({"query": "Alpha", "start": START}),
        tool_call({"query": "Alpha", "end": END}),
        tool_call({"query": "Alpha", "start": START, "end": END}),
        GeminiResult(text="Not reachable.", model="fake"),
    )
    assert len(reply.tool_calls) == 2
    assert reply.degraded
    assert gemini.calls[-1][1]["tools"] == ()
    assert len(gemini.calls) <= 3


@pytest.mark.parametrize(
    ("first", "options", "error"),
    [
        (tool_call({}, "read_file"), {}, "unknown_tool"),
        (
            tool_call({"story_id": "bad"}, "get_story_evidence"),
            {"permissions": frozenset({"intelligence.read"})},
            "permission_denied",
        ),
        (
            tool_call({}, "search_content_items"),
            {"enabled_tools": frozenset({"search_stories"})},
            "tool_disabled",
        ),
    ],
)
def test_permission_unknown_disabled_never_recovered_by_other_success(
    seeded_intelligence,
    first,
    options,
    error,
):
    reply, gemini, _ = run_turn(
        seeded_intelligence,
        first,
        tool_call({"query": "Alpha"}),
        GeminiResult(text="Claim success.", model="fake"),
        **options,
    )
    assert reply.degraded
    assert error in reply.degraded_reason
    assert len(reply.tool_calls) == 1
    assert gemini.calls[-1][1]["tools"] == ()


def test_recovery_keeps_citation_validation(seeded_intelligence):
    reply, _, _ = run_turn(
        seeded_intelligence,
        tool_call({"query": "Alpha", "start": START}),
        tool_call({"query": "Alpha", "start": START, "end": END}),
        GeminiResult(text="Invented [story:not-real].", model="fake"),
    )
    assert reply.degraded
    assert "ungrounded" in reply.degraded_reason
    assert "story:not-real" not in reply.text
    assert reply.citations == ()


def test_whitespace_changes_cannot_buy_a_second_correction(seeded_intelligence):
    reply, gemini, _ = run_turn(
        seeded_intelligence,
        tool_call({"query": "Alpha", "start": START}),
        tool_call({"query": " Alpha ", "end": END}),
        tool_call({"query": "Alpha", "time_range": RANGE}),
        GeminiResult(text="Not reachable.", model="fake"),
    )
    assert len(reply.tool_calls) == 2
    assert reply.degraded
    assert len(gemini.calls) == 3


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-08-28T12:00:00+01:99",
        "2026-08-28T12:00:00+24:00",
        "2026-08-28T12:00:00+08",
        "2026-08-28T12:00:00",
    ],
)
def test_timezone_must_be_an_explicit_valid_offset(seeded_intelligence, stamp):
    result = ToolRegistry().execute(
        "search_stories",
        {"time_range": {"start": stamp, "end": END}},
        context(seeded_intelligence),
    )
    assert result.error_code == "invalid_arguments"


@pytest.mark.parametrize("code", ["permission_denied", "disabled", "unavailable", "timeout"])
def test_handler_result_error_taxonomy_is_preserved_without_details(
    seeded_intelligence,
    code,
    caplog,
):
    registry = ToolRegistry(
        (
            ToolSpec(
                "lookup",
                "Lookup",
                {"type": "object", "properties": {}},
                "intelligence.read",
                lambda _ctx, _args: ToolResult(
                    "lookup",
                    True,
                    False,
                    '{"secret":"private-user-id"}',
                    error_code=code,
                ),
            ),
        )
    )
    result = registry.execute("lookup", {}, context(seeded_intelligence))
    assert result.error_code == code
    assert json.loads(result.text)["retryable"] is False
    assert "private-user-id" not in result.text + caplog.text
    assert "tool_attempt_failed" in caplog.text


@pytest.mark.parametrize("second_name", ["search_content_items", "get_story_evidence"])
def test_other_tool_evidence_cannot_clear_search_failure(seeded_intelligence, second_name):
    arguments = (
        {"story_id": seeded_intelligence.story.id}
        if second_name == "get_story_evidence"
        else {"query": "Alpha", "time_range": RANGE}
    )
    reply, _, _ = run_turn(
        seeded_intelligence,
        tool_call({"query": "Alpha", "start": START}),
        tool_call(arguments, second_name),
        GeminiResult(text="Limited answer.", model="fake"),
    )
    assert reply.tool_calls[-1].error == ""
    assert reply.degraded
    assert "invalid_arguments" in reply.degraded_reason


def test_result_citations_without_visible_evidence_cannot_recover(seeded_intelligence):
    registry = ToolRegistry()
    original = registry.get("search_stories")
    calls = []

    def handler(ctx, arguments):
        calls.append(arguments)
        actual = original.handler(ctx, arguments)
        return ToolResult("search_stories", True, True, '{"stories":[]}', actual.citations)

    registry = ToolRegistry(
        (
            ToolSpec(
                original.name,
                original.description,
                original.parameters,
                original.permission,
                handler,
            ),
        )
    )
    reply, _, _ = run_turn(
        seeded_intelligence,
        tool_call({"query": "Alpha", "start": START}),
        tool_call({"query": "Alpha", "time_range": RANGE}),
        GeminiResult(text="Limited answer.", model="fake"),
        tool_registry=registry,
    )
    assert len(calls) == 1
    assert reply.degraded
    assert "invalid_arguments" in reply.degraded_reason


def test_two_independent_failures_only_matching_need_is_recovered(seeded_intelligence):
    reply, gemini, _ = run_turn(
        seeded_intelligence,
        tool_call({"query": "Alpha", "start": START}),
        tool_call({"query": "Independent AI chip", "start": START}, "search_content_items"),
        tool_call({"query": "Alpha", "time_range": RANGE}),
        GeminiResult(text="One need remains unresolved.", model="fake"),
    )
    assert reply.degraded
    assert "search_content_items" in reply.degraded_reason
    assert "search_stories" not in reply.degraded_reason
    assert len(reply.tool_calls) == 3
    assert len(gemini.calls) == 4


def test_correction_uses_remaining_budget_and_does_not_expand_it(seeded_intelligence):
    from trendradar.ai.assistant import AssistantLimits

    reply, gemini, _ = run_turn(
        seeded_intelligence,
        tool_call({"query": "Alpha", "start": START}),
        tool_call({"query": "Alpha", "time_range": RANGE}),
        limits=AssistantLimits(max_tool_calls=1),
    )
    assert reply.degraded
    assert reply.truncation.tool_calls
    assert len(reply.tool_calls) == 1
    assert len(gemini.calls) == 2


@pytest.mark.parametrize(
    ("arguments", "shape", "argument_error"),
    [
        ({"time_range": RANGE, "limit": 21}, "nested", "schema_mismatch"),
        ({"start": START, "end": END, "limit": 21}, "legacy", "schema_mismatch"),
        ({"start": START}, "start-only", "range_pair_required"),
        ({"end": END}, "end-only", "range_pair_required"),
        ({"limit": 21}, "default", "schema_mismatch"),
        ({"time_range": RANGE, "start": START}, "mixed", "range_conflict"),
        ({"time_range": {"start": "bad", "end": END}}, "nested", "invalid_time"),
    ],
)
def test_failed_tool_audit_contains_only_fixed_shape_and_error_fields(
    seeded_intelligence,
    caplog,
    arguments,
    shape,
    argument_error,
):
    outcome = ToolRegistry().execute(
        "search_stories",
        {"query": "private-user-id https://secret.test/?token=x", **arguments},
        context(seeded_intelligence),
    )
    assert outcome.error_code == "invalid_arguments"
    assert f"shape={shape}" in caplog.text
    assert f"argument_error={argument_error}" in caplog.text
    for private in (START, END, "private-user-id", "secret.test", "token=x"):
        assert private not in caplog.text
