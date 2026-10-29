"""Offline contract tests for the core Gemini client."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from trendradar.ai import (
    GeminiClient,
    GeminiConfig,
    GeminiConfigurationError,
    GeminiMessage,
    GeminiRateLimitError,
    GeminiRequestError,
    GeminiResult,
    GeminiTimeoutError,
    GeminiToolCall,
    GeminiToolDefinition,
    GeminiUnavailableError,
    GeminiUsage,
)
from trendradar.ai.client import DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_MODELS


def _response(
    text: str | None = "ok",
    *,
    model: str = "gemini-test",
    function_calls: Any = None,
    usage: Any = None,
    finish_reason: Any = None,
) -> SimpleNamespace:
    candidates = []
    if finish_reason is not None:
        candidates = [SimpleNamespace(finish_reason=finish_reason)]
    return SimpleNamespace(
        text=text,
        model_version=model,
        function_calls=function_calls,
        usage_metadata=usage,
        candidates=candidates,
    )


class FakeModels:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.outcomes:
            raise AssertionError("FakeModels has no remaining outcome")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeSdkClient:
    def __init__(self, *outcomes: Any) -> None:
        self.models = FakeModels(*outcomes)


class FakeClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


def _config(**overrides: Any) -> GeminiConfig:
    values: dict[str, Any] = {
        "api_key": "test-api-key",
        "max_attempts": 1,
        "retry_backoff_seconds": 0,
        "min_request_interval_seconds": 0,
    }
    values.update(overrides)
    return GeminiConfig(**values)


def test_contract_values_are_immutable_and_provider_neutral() -> None:
    arguments = {"filters": {"tags": ["ai"]}}
    call = GeminiToolCall(name="search_stories", arguments=arguments, call_id="call-1")
    message = GeminiMessage(role="assistant", content="Checking", tool_calls=(call,))
    definition = GeminiToolDefinition(
        name="search_stories",
        description="Search local Stories",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    usage = GeminiUsage(input_tokens=3, output_tokens=2, total_tokens=5)

    arguments["filters"]["tags"].append("mutated")
    assert call.arguments["filters"]["tags"] == ("ai",)
    assert definition.input_schema["type"] == "object"
    assert usage.prompt_tokens == 3
    assert usage.completion_tokens == 2
    with pytest.raises(TypeError):
        call.arguments["new"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        message.content = "changed"  # type: ignore[misc]


def test_chat_summary_and_analyze_share_one_generation_boundary() -> None:
    sdk = FakeSdkClient(_response("chat"), _response("summary"), _response("analysis"))
    client = GeminiClient(_config(), client=sdk)

    assert client.chat("question").text == "chat"
    assert client.summary("long article").text == "summary"
    assert client.analyze("evidence").text == "analysis"

    assert [call["model"] for call in sdk.models.calls] == [
        DEFAULT_GEMINI_MODEL,
        DEFAULT_GEMINI_MODEL,
        DEFAULT_GEMINI_MODEL,
    ]
    assert "system_instruction" not in sdk.models.calls[0]["config"]
    assert "Summarize" in sdk.models.calls[1]["config"]["system_instruction"]
    assert "Analyze" in sdk.models.calls[2]["config"]["system_instruction"]
    assert [call["config"]["temperature"] for call in sdk.models.calls] == [0.3, 0.2, 0.1]


def test_client_construction_is_lazy_injectable_and_redacted() -> None:
    factory_calls: list[dict[str, Any]] = []
    sdk = FakeSdkClient(_response("ready"))

    def factory(**kwargs: Any) -> FakeSdkClient:
        factory_calls.append(kwargs)
        return sdk

    client = GeminiClient(
        _config(api_key="super-secret", timeout_seconds=12.5),
        client_factory=factory,
    )

    assert client.initialized is False
    assert factory_calls == []
    assert "super-secret" not in repr(client)

    assert client.chat("hello").text == "ready"
    assert client.initialized is True
    assert factory_calls == [{"api_key": "super-secret", "timeout_seconds": 12.5}]


def test_provider_neutral_value_reprs_do_not_expose_content() -> None:
    secret = "never-render-this-value"
    values = (
        GeminiMessage(role="user", content=secret),
        GeminiResult(text=secret, model="gemini-test"),
        GeminiToolCall(name="lookup", arguments={"value": secret}, call_id=secret),
        GeminiToolDefinition(
            name="lookup",
            description=secret,
            parameters={"description": secret},
        ),
    )

    rendered = " ".join(repr(value) for value in values)

    assert secret not in rendered
    assert "content_chars" in rendered
    assert "text_chars" in rendered
    assert "<redacted>" in rendered


def test_request_and_response_are_normalized_without_sdk_values() -> None:
    finish = SimpleNamespace(value="STOP")
    usage = SimpleNamespace(
        prompt_token_count=11,
        candidates_token_count=7,
        total_token_count=18,
        cached_content_token_count=3,
    )
    provider_call = SimpleNamespace(name="lookup", args={"story_id": "story-1"}, id="c-1")
    sdk = FakeSdkClient(
        _response(
            "  answer  ",
            model="gemini-effective",
            function_calls=[provider_call],
            usage=usage,
            finish_reason=finish,
        )
    )
    client = GeminiClient(_config(), client=sdk)

    result = client.chat(
        [
            GeminiMessage(role="user", content="question"),
            GeminiMessage(role="assistant", content="earlier answer"),
        ]
    )

    assert result.text == "answer"
    assert result.model == DEFAULT_GEMINI_MODEL
    assert result.finish_reason == "STOP"
    assert result.usage == GeminiUsage(
        input_tokens=11,
        output_tokens=7,
        total_tokens=18,
        cached_tokens=3,
    )
    assert result.tool_calls == (
        GeminiToolCall(
            name="lookup", arguments={"story_id": "story-1"}, call_id="c-1",
            model=DEFAULT_GEMINI_MODEL,
        ),
    )
    assert sdk.models.calls[0]["contents"] == [
        {"role": "user", "parts": [{"text": "question"}]},
        {"role": "model", "parts": [{"text": "earlier answer"}]},
    ]


def test_structured_response_and_tools_remain_declarative() -> None:
    sdk = FakeSdkClient(
        _response("", function_calls=[SimpleNamespace(name="lookup", args={"limit": 2}, id=None)])
    )
    client = GeminiClient(_config(), client=sdk)
    tool = GeminiToolDefinition(
        name="lookup",
        description="Look up local evidence",
        parameters={
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "required": ["limit"],
        },
    )

    result = client.analyze(
        "evidence",
        tools=[tool],
        response_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )

    assert result.text == ""
    assert result.tool_calls[0].arguments == {"limit": 2}
    config = sdk.models.calls[0]["config"]
    assert config["response_mime_type"] == "application/json"
    assert config["response_json_schema"]["type"] == "object"
    assert config["automatic_function_calling"] == {"disable": True}
    declaration = config["tools"][0]["function_declarations"][0]
    assert declaration == {
        "name": "lookup",
        "description": "Look up local evidence",
        "parameters_json_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "required": ["limit"],
        },
    }


def test_thought_signature_is_preserved_for_tool_continuation() -> None:
    signature = b"opaque-provider-thought-signature"
    provider_call = SimpleNamespace(name="lookup", args={"limit": 2}, id="call-1")
    tool_part = SimpleNamespace(
        function_call=provider_call,
        thought_signature=signature,
    )
    tool_response = SimpleNamespace(
        text="",
        model_version="gemini-test",
        function_calls=[provider_call],
        usage_metadata=None,
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(parts=[tool_part]),
                finish_reason=SimpleNamespace(value="STOP"),
            )
        ],
    )
    sdk = FakeSdkClient(tool_response, _response("done"))
    client = GeminiClient(_config(), client=sdk)
    tool = GeminiToolDefinition(
        name="lookup",
        description="Look up local evidence",
        parameters={"type": "object", "properties": {}},
    )

    first = client.chat("question", tools=(tool,))
    assert first.tool_calls[0].thought_signature == signature

    client.chat(
        (
            GeminiMessage(role="user", content="question"),
            GeminiMessage(
                role="assistant",
                content="Requesting local evidence.",
                tool_calls=first.tool_calls,
            ),
            GeminiMessage(
                role="tool",
                name="lookup",
                tool_call_id="call-1",
                content='{"value":30}',
            ),
        ),
        tools=(tool,),
    )

    function_part = sdk.models.calls[1]["contents"][1]["parts"][1]
    assert function_part == {
        "function_call": {"name": "lookup", "args": {"limit": 2}, "id": "call-1"},
        "thought_signature": signature,
    }
    assert signature.decode() not in repr(first.tool_calls[0])


def test_input_keeps_recent_messages_within_limit_and_output_is_truncated() -> None:
    sdk = FakeSdkClient(_response("abcdefghijk"))
    client = GeminiClient(_config(max_input_chars=8, max_output_chars=5), client=sdk)

    result = client.chat(
        [
            GeminiMessage(role="user", content="older"),
            GeminiMessage(role="user", content="newest"),
        ]
    )

    assert sdk.models.calls[0]["contents"] == [
        {"role": "user", "parts": [{"text": "ol"}]},
        {"role": "user", "parts": [{"text": "newest"}]},
    ]
    assert result.text == "abcde"
    assert result.truncated is True


@pytest.mark.parametrize(
    "response",
    [
        None,
        _response(None),
        _response("   "),
        _response(123),
        _response("", function_calls=[SimpleNamespace(name="", args={})]),
        _response("", function_calls=[SimpleNamespace(name="lookup", args="bad")]),
    ],
)
def test_empty_or_malformed_responses_switch_model(response: Any) -> None:
    sdk = FakeSdkClient(response, _response("recovered"))
    client = GeminiClient(_config(max_attempts=2), client=sdk)

    result = client.chat("question")
    assert result.text == "recovered"
    assert result.model == DEFAULT_GEMINI_MODELS[1]
    assert [call["model"] for call in sdk.models.calls] == list(DEFAULT_GEMINI_MODELS[:2])


def test_retryable_failure_switches_models_without_backoff() -> None:
    sdk = FakeSdkClient(TimeoutError("private request"), RuntimeError("private payload"), _response("ok"))
    clock = FakeClock()
    client = GeminiClient(
        _config(max_attempts=3, retry_backoff_seconds=0.5),
        client=sdk,
        clock=clock,
        sleeper=clock.sleep,
    )

    assert client.chat("private prompt").text == "ok"
    assert clock.sleeps == []
    assert [call["model"] for call in sdk.models.calls] == list(DEFAULT_GEMINI_MODELS)


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"provider payload for {status_code}")


@pytest.mark.parametrize(
    ("provider_error", "expected_type", "retryable"),
    [
        (TimeoutError("payload"), GeminiTimeoutError, True),
        (StatusError(408), GeminiTimeoutError, True),
        (StatusError(429), GeminiRateLimitError, True),
        (StatusError(400), GeminiRequestError, False),
        (StatusError(503), GeminiRequestError, True),
        (ValueError("payload"), GeminiRequestError, False),
    ],
)
def test_provider_errors_have_typed_sanitized_mappings(
    provider_error: Exception,
    expected_type: type[Exception],
    retryable: bool,
) -> None:
    sdk = FakeSdkClient(provider_error)
    client = GeminiClient(_config(), client=sdk)

    with pytest.raises(expected_type) as caught:
        client.chat("private prompt")

    assert caught.value.retryable is retryable
    assert "payload" not in str(caught.value)
    assert "private" not in repr(caught.value)
    assert caught.value.__cause__ is None


def test_minimum_request_interval_uses_injected_monotonic_clock() -> None:
    sdk = FakeSdkClient(_response("first"), _response("second"), _response("third"))
    clock = FakeClock()
    client = GeminiClient(
        _config(min_request_interval_seconds=2.5),
        client=sdk,
        clock=clock,
        sleeper=clock.sleep,
    )

    client.chat("one")
    client.chat("two")
    clock.now += 1.0
    client.chat("three")

    assert clock.sleeps == [2.5, 1.5]


def test_missing_disabled_or_failed_configuration_never_constructs_a_client() -> None:
    factory_calls: list[dict[str, Any]] = []

    def factory(**kwargs: Any) -> FakeSdkClient:
        factory_calls.append(kwargs)
        raise RuntimeError("credential and provider payload")

    for config in (GeminiConfig(), GeminiConfig(api_key="secret", enabled=False)):
        client = GeminiClient(config, client_factory=factory)
        with pytest.raises(GeminiUnavailableError):
            client.chat("private prompt")

    failed = GeminiClient(_config(api_key="secret"), client_factory=factory)
    with pytest.raises(GeminiUnavailableError) as caught:
        failed.chat("private prompt")

    assert len(factory_calls) == 1
    rendered = f"{failed!r} {caught.value!r} {caught.value}"
    assert "secret" not in rendered
    assert "credential" not in rendered
    assert "private prompt" not in rendered


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": " "},
        {"timeout_seconds": 0},
        {"timeout_seconds": float("nan")},
        {"max_attempts": 0},
        {"max_attempts": 6},
        {"retry_backoff_seconds": -1},
        {"min_request_interval_seconds": 61},
        {"max_input_chars": 0},
        {"max_output_chars": 50_001},
    ],
)
def test_direct_configuration_rejects_values_outside_client_bounds(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(GeminiConfigurationError):
        _config(**overrides)


def test_core_ai_source_has_no_mcp_dependency() -> None:
    package_dir = Path("trendradar/ai")
    source = "\n".join(path.read_text(encoding="utf-8") for path in package_dir.glob("*.py"))

    assert "mcp_server" not in source
