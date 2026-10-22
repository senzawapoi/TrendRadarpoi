"""Tests for the deny-by-default local Assistant tool registry."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from trendradar.ai.models import TimeRange
from trendradar.ai.retrieval import LocalRetriever
from trendradar.ai.tools import (
    ToolContext,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    _serialize,
)

NOW = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)


def _context(seeded_intelligence, *, permissions=frozenset()) -> ToolContext:
    retriever = LocalRetriever(seeded_intelligence.storage)
    return ToolContext(
        principal_id="owner",
        retriever=retriever,
        storage=seeded_intelligence.storage,
        time_range=TimeRange.previous_days(NOW, 7),
        permissions=frozenset(permissions),
    )


def test_tool_spec_schema_is_deeply_immutable() -> None:
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string", "enum": ["one"]}},
        "required": ["query"],
        "additionalProperties": False,
    }
    spec = ToolSpec(
        name="lookup",
        description="Known local lookup",
        parameters=schema,
        permission="intelligence.read",
        handler=lambda _context, _arguments: ToolResult(
            "lookup", True, True, "{}"
        ),
    )
    schema["properties"]["query"]["enum"].append("two")

    assert spec.parameters["properties"]["query"]["enum"] == ("one",)
    with pytest.raises(TypeError):
        spec.parameters["properties"]["query"]["type"] = "integer"  # type: ignore[index]


@pytest.mark.parametrize(
    ("arguments", "expected_error"),
    [
        ({}, "invalid_arguments"),
        ({"limit": 1, "extra": True}, "invalid_arguments"),
        ({"limit": True}, "invalid_arguments"),
        ({"limit": 0}, "invalid_arguments"),
        ({"limit": 4}, "invalid_arguments"),
    ],
)
def test_invalid_arguments_never_invoke_handler(
    seeded_intelligence,
    arguments: dict[str, Any],
    expected_error: str,
) -> None:
    calls = []

    def handler(_context: ToolContext, values: dict[str, Any]) -> ToolResult:
        calls.append(values)
        return ToolResult("lookup", True, True, "{}")

    registry = ToolRegistry(
        (
            ToolSpec(
                name="lookup",
                description="Known local lookup",
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 3}
                    },
                    "required": ["limit"],
                    "additionalProperties": False,
                },
                permission="intelligence.read",
                handler=handler,
            ),
        )
    )

    result = registry.execute(
        "lookup",
        arguments,
        _context(seeded_intelligence, permissions={"intelligence.read"}),
    )

    assert result.allowed is False
    assert result.error_code == expected_error
    assert calls == []


def test_unknown_disabled_and_unauthorized_tools_are_not_exposed_or_called(
    seeded_intelligence,
) -> None:
    registry = ToolRegistry(enabled={"search_content_items": False})
    no_permissions = _context(seeded_intelligence)
    read_only = _context(seeded_intelligence, permissions={"intelligence.read"})

    assert registry.definitions(context=no_permissions) == ()
    assert {definition.name for definition in registry.definitions(context=read_only)} == {
        "search_stories"
    }
    assert registry.execute("unknown", {}, read_only).error_code == "unknown_tool"
    assert (
        registry.execute("search_content_items", {}, read_only).error_code
        == "tool_disabled"
    )
    assert (
        registry.execute("get_story_evidence", {"story_id": "bad"}, read_only).error_code
        == "permission_denied"
    )


def test_registered_local_search_and_evidence_tools_return_server_citations(
    seeded_intelligence,
) -> None:
    registry = ToolRegistry()
    context = _context(
        seeded_intelligence,
        permissions={"intelligence.read", "intelligence.evidence"},
    )

    stories = registry.execute(
        "search_stories",
        {"query": "Alpha", "limit": 1},
        context,
    )
    items = registry.execute(
        "search_content_items",
        {"query": "Independent AI chip", "limit": 1},
        context,
    )
    evidence = registry.execute(
        "get_story_evidence",
        {"story_id": seeded_intelligence.story.id},
        context,
    )

    for result in (stories, items, evidence):
        assert result.ok is True
        assert len(result.text) <= context.max_result_chars
        assert isinstance(json.loads(result.text), dict)
        assert result.citations
    assert stories.citations[0].story_id == seeded_intelligence.story.id
    assert items.citations[0].content_item_id == seeded_intelligence.standalone.id
    assert all(
        citation.story_id == seeded_intelligence.story.id
        for citation in evidence.citations
    )


def test_large_tool_payload_is_bounded_valid_json() -> None:
    rendered = _serialize({"payload": "x" * 20_000}, maximum=256)

    assert len(rendered) <= 256
    assert json.loads(rendered)["truncated"] is True


def test_tool_module_has_no_dynamic_or_external_execution_path() -> None:
    source = Path("trendradar/ai/tools.py").read_text(encoding="utf-8")

    for forbidden in (
        "import subprocess",
        "os.system",
        "eval(",
        "exec(",
        "__import__(",
        "import requests",
        "import urllib",
        "mcp_server",
        "crawler.",
    ):
        assert forbidden not in source
