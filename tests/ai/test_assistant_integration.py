"""End-to-end offline tests for Assistant tools, factory, and persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trendradar.ai import (
    AssistantLimits,
    AssistantRequest,
    AssistantService,
    GeminiResult,
    GeminiToolCall,
    build_assistant_service,
)
from trendradar.core.settings import load_settings

NOW = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)


class SequenceGemini:
    def __init__(self, *results: GeminiResult) -> None:
        self.results = list(results)
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def chat(self, messages: Any, **kwargs: Any) -> GeminiResult:
        self.calls.append((messages, kwargs))
        return self.results.pop(0)


def test_local_question_runs_registered_tool_then_persists_grounded_reply(
    seeded_intelligence,
) -> None:
    story_ref = f"story:{seeded_intelligence.story.id}"
    gemini = SequenceGemini(
        GeminiResult(
            text="",
            model="fake",
            tool_calls=(
                GeminiToolCall(
                    name="search_stories",
                    arguments={"query": "Alpha", "limit": 1},
                    call_id="call-1",
                ),
            ),
        ),
        GeminiResult(
            text=f'{{"answer":"Alpha is grounded [{story_ref}]","citations":["{story_ref}"]}}',
            model="fake",
        ),
    )
    service = AssistantService(seeded_intelligence.storage, gemini_client=gemini)

    reply = service.handle(
        AssistantRequest("request-1", "owner", "What changed in Alpha?", requested_at=NOW)
    )

    assert reply.degraded is False
    assert [citation.ref for citation in reply.citations] == [story_ref]
    assert [call.name for call in reply.tool_calls] == ["search_stories"]
    assert reply.tool_calls[0].allowed is True
    assert len(gemini.calls) == 2
    second_messages = gemini.calls[1][0]
    assert second_messages[-1].role == "tool"
    assert seeded_intelligence.storage.count("assistant_messages") == 2


def test_unknown_tool_is_denied_before_dispatch_and_marks_final_reply_degraded(
    seeded_intelligence,
) -> None:
    gemini = SequenceGemini(
        GeminiResult(
            text="",
            model="fake",
            tool_calls=(GeminiToolCall(name="read_file", arguments={}),),
        ),
        GeminiResult(text="No local tool was used.", model="fake"),
    )
    service = AssistantService(seeded_intelligence.storage, gemini_client=gemini)

    reply = service.handle(
        AssistantRequest("request-1", "owner", "Read a file", requested_at=NOW)
    )

    assert reply.degraded is True
    assert "unknown_tool" in reply.degraded_reason
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].allowed is False
    assert reply.tool_calls[0].error == "unknown_tool"


def test_duplicate_tool_call_is_explicitly_denied_but_loop_can_finish(
    seeded_intelligence,
) -> None:
    call = GeminiToolCall(name="search_stories", arguments={"query": "Alpha"})
    gemini = SequenceGemini(
        GeminiResult(text="", model="fake", tool_calls=(call,)),
        GeminiResult(text="", model="fake", tool_calls=(call,)),
        GeminiResult(text="Finished after duplicate denial.", model="fake"),
    )
    service = AssistantService(seeded_intelligence.storage, gemini_client=gemini)

    reply = service.handle(
        AssistantRequest("request-1", "owner", "Alpha", requested_at=NOW)
    )

    assert reply.degraded is True
    assert "duplicate" in reply.degraded_reason
    assert len(reply.tool_calls) == 2
    assert reply.tool_calls[0].allowed is True
    assert reply.tool_calls[1].allowed is False


def test_tool_call_limit_returns_bounded_fallback_and_truncation(
    seeded_intelligence,
) -> None:
    gemini = SequenceGemini(
        GeminiResult(
            text="",
            model="fake",
            tool_calls=(GeminiToolCall(name="search_stories", arguments={}),),
        ),
        GeminiResult(
            text="",
            model="fake",
            tool_calls=(GeminiToolCall(name="search_content_items", arguments={}),),
        ),
    )
    limits = AssistantLimits.from_mapping({"max_tool_calls": 1})
    service = AssistantService(
        seeded_intelligence.storage,
        gemini_client=gemini,
        limits=limits,
    )

    reply = service.handle(
        AssistantRequest("request-1", "owner", "Alpha", requested_at=NOW)
    )

    assert reply.degraded is True
    assert "tool call limit" in reply.degraded_reason
    assert reply.truncation.tool_calls is True
    assert len(reply.tool_calls) == 1
    assert len(gemini.calls) == 2


def test_oversized_tool_batch_is_rejected_without_partial_dispatch(
    seeded_intelligence,
) -> None:
    calls = tuple(
        GeminiToolCall(name="search_stories", arguments={"query": str(index)})
        for index in range(4)
    )
    gemini = SequenceGemini(
        GeminiResult(text="", model="fake", tool_calls=calls),
    )
    service = AssistantService(seeded_intelligence.storage, gemini_client=gemini)

    reply = service.handle(
        AssistantRequest("request-1", "owner", "Alpha", requested_at=NOW)
    )

    assert reply.degraded is True
    assert reply.truncation.tool_calls is True
    assert reply.tool_calls == ()
    assert len(gemini.calls) == 1


def test_factory_reuses_storage_and_allows_no_gemini_local_degradation(
    seeded_intelligence,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
intelligence:
  enabled: true
  assistant:
    enabled: true
    default_lookback_days: 2
    max_tool_calls: 1
    tools:
      search_stories: true
      search_content_items: false
      get_story_evidence: false
""".lstrip(),
        encoding="utf-8",
    )
    settings = load_settings(config_path, environ={})

    service = build_assistant_service(
        settings,
        storage=seeded_intelligence.storage,
        gemini_client=None,
    )

    assert service is not None
    assert service.storage is seeded_intelligence.storage
    assert service.gemini_client is None
    assert service.limits.default_lookback_days == 2
    assert {definition.name for definition in service.tool_registry.definitions()} == {
        "search_stories"
    }
    service.close()
    assert seeded_intelligence.storage.count("assistant_sessions") == 0


def test_factory_fails_closed_without_enabled_local_storage(tmp_path: Path) -> None:
    disabled_path = tmp_path / "disabled.yaml"
    disabled_path.write_text("intelligence:\n  enabled: false\n", encoding="utf-8")
    disabled = load_settings(disabled_path, environ={})

    assert build_assistant_service(disabled, storage=None) is None
