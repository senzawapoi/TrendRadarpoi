"""Offline routing contracts with real core clients and deterministic fake transports."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest

from trendradar.ai import (
    GeminiAuthenticationError,
    GeminiClient,
    GeminiConfig,
    GeminiConfigurationError,
    GeminiCooldownError,
    GeminiMessage,
    GeminiModelUnavailableError,
    GeminiRateLimitError,
    GeminiRequestError,
    GeminiResponseError,
    GeminiServerError,
    GeminiTimeoutError,
)
from trendradar.ai.client import DEFAULT_GEMINI_MODELS, build_gemini_client
from trendradar.core.settings import load_settings

from .test_gemini_client import FakeClock, FakeSdkClient, StatusError, _response


def config(**kwargs):
    return GeminiConfig(api_key="routing-test-key", min_request_interval_seconds=0, **kwargs)


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (TimeoutError("private"), GeminiTimeoutError),
        (StatusError(408), GeminiTimeoutError),
        (StatusError(429), GeminiRateLimitError),
        (StatusError(503), GeminiServerError),
        (StatusError(404), GeminiModelUnavailableError),
        (StatusError(410), GeminiModelUnavailableError),
        (_response(""), GeminiResponseError),
    ],
)
def test_retryable_errors_switch_once_per_model_and_report_actual_model(outcome, expected):
    sdk = FakeSdkClient(outcome, _response("recovered", model="untrusted-provider-version"))
    client = GeminiClient(config(), client=sdk)
    result = client.chat("private prompt")
    assert result.text == "recovered"
    assert result.model == DEFAULT_GEMINI_MODELS[1]
    assert [call["model"] for call in sdk.models.calls] == list(DEFAULT_GEMINI_MODELS[:2])
    if isinstance(outcome, Exception):
        assert type(client._map_provider_error(outcome)) is expected


@pytest.mark.parametrize("status", [401, 403])
def test_shared_authentication_never_cycles_or_cools_models(status):
    sdk = FakeSdkClient(StatusError(status), _response("fixed credentials"))
    client = GeminiClient(config(), client=sdk)
    with pytest.raises(GeminiAuthenticationError):
        client.chat("secret input")
    assert len(sdk.models.calls) == 1
    assert client.chat("retry after repair").model == DEFAULT_GEMINI_MODELS[0]


def test_google_invalid_key_400_is_classified_without_raw_details():
    from google.genai.errors import ClientError

    error = ClientError(400, {"error": {
        "message": "private provider content", "details": [{"reason": "API_KEY_INVALID"}],
    }})
    sdk = FakeSdkClient(error)
    with pytest.raises(GeminiAuthenticationError) as caught:
        GeminiClient(config(), client=sdk).chat("question")
    assert "private" not in str(caught.value)
    assert len(sdk.models.calls) == 1


@pytest.mark.parametrize("error", [ValueError("private"), TypeError("private"), StatusError(400)])
def test_invalid_provider_request_does_not_cycle(error):
    sdk = FakeSdkClient(error)
    with pytest.raises(GeminiRequestError) as caught:
        GeminiClient(config(), client=sdk).chat("question")
    assert caught.value.retryable is False
    assert len(sdk.models.calls) == 1


def test_local_invalid_input_fails_before_lazy_sdk_construction():
    def forbidden_factory(**_kwargs):
        pytest.fail("invalid local request must not construct transport")

    client = GeminiClient(config(), client_factory=forbidden_factory)
    for kwargs in ({"tools": [object()]}, {"response_schema": "invalid"}):
        with pytest.raises(GeminiConfigurationError):
            client.chat("question", **kwargs)


def test_oversized_reconstruction_is_rejected_before_any_provider_dispatch():
    sdk = FakeSdkClient(_response("must not send partial evidence"))
    client = GeminiClient(config(max_input_chars=256), client=sdk)
    with pytest.raises(GeminiConfigurationError):
        client.chat(
            "question", continuation_model=DEFAULT_GEMINI_MODELS[0],
            fallback_messages=[GeminiMessage("user", "X" * 257)],
        )
    assert sdk.models.calls == []


def test_three_attempt_hard_cap_deduplicates_candidates_and_raises_precise_last_error():
    sdk = FakeSdkClient(TimeoutError(), StatusError(503), StatusError(429), _response("unused"))
    client = GeminiClient(config(models=("one", "one", "two", "three", "four"), max_attempts=5), client=sdk)
    with pytest.raises(GeminiRateLimitError):
        client.chat("question")
    assert [call["model"] for call in sdk.models.calls] == ["one", "two", "three"]


def test_single_model_legacy_configuration_never_repeats_same_candidate():
    sdk = FakeSdkClient(TimeoutError(), _response("unused"))
    with pytest.raises(GeminiTimeoutError):
        GeminiClient(config(model="legacy", max_attempts=5), client=sdk).chat("question")
    assert [call["model"] for call in sdk.models.calls] == ["legacy"]


def test_cooldowns_are_shared_by_key_monotonic_expiring_and_exhaustion_makes_zero_calls():
    clock = FakeClock()
    sdk = FakeSdkClient(TimeoutError(), StatusError(429), StatusError(503))
    first = GeminiClient(config(), client=sdk, clock=clock)
    with pytest.raises(GeminiServerError):
        first.chat("first request")
    second_sdk = FakeSdkClient(_response("after expiry"))
    second = GeminiClient(config(), client=second_sdk, clock=clock)
    clock.now += 59
    with pytest.raises(GeminiCooldownError):
        second.chat("during cooldown")
    assert second_sdk.models.calls == []
    other = GeminiClient(replace(config(), api_key="different-key"), client=FakeSdkClient(_response()))
    # Use the same monotonic clock domain for all clients in the isolated test.
    other._clock = clock
    assert other.chat("independent credential").model == DEFAULT_GEMINI_MODELS[0]
    clock.now += 1
    assert second.chat("expired").model == DEFAULT_GEMINI_MODELS[0]


def test_concurrent_clients_observe_failed_model_cooldown():
    clock = FakeClock()
    failing = GeminiClient(config(max_attempts=1), client=FakeSdkClient(TimeoutError()), clock=clock)
    with pytest.raises(GeminiTimeoutError):
        failing.chat("fail first")

    def run(_index):
        sdk = FakeSdkClient(_response())
        return GeminiClient(config(), client=sdk, clock=clock).chat("parallel").model

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(run, range(20))) == [DEFAULT_GEMINI_MODELS[1]] * 20


@pytest.mark.parametrize("cool_all", [False, True])
def test_limiter_wait_rechecks_concurrently_established_cooldowns(cool_all):
    clock = FakeClock()
    waiting, resume = Event(), Event()
    sdk = FakeSdkClient(_response("warmup"), _response("queued"))

    def wait_for_other_failure(delay):
        waiting.set()
        assert resume.wait(5), "test did not release the rate limiter"
        clock.sleep(delay)

    queued = GeminiClient(
        replace(config(models=("primary", "secondary"), max_attempts=1),
                min_request_interval_seconds=10),
        client=sdk, clock=clock, sleeper=wait_for_other_failure,
    )
    queued.chat("warmup")
    failing = GeminiClient(
        config(models=("primary", "secondary") if cool_all else ("primary",)),
        client=FakeSdkClient(TimeoutError(), TimeoutError()), clock=clock,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(queued.chat, "queued before other request failed")
        try:
            assert waiting.wait(5), "queued request did not reach the limiter"
            with pytest.raises(GeminiTimeoutError):
                failing.chat("establish shared cooldown while queued")
        finally:
            resume.set()
        if cool_all:
            with pytest.raises(GeminiCooldownError):
                result.result(timeout=5)
            assert [call["model"] for call in sdk.models.calls] == ["primary"]
        else:
            assert result.result(timeout=5).model == "secondary"
            assert [call["model"] for call in sdk.models.calls] == ["primary", "secondary"]


@pytest.mark.parametrize("cool_all_remaining", [False, True])
def test_each_dispatch_rechecks_cooldowns_established_during_previous_attempt(
    monkeypatch, cool_all_remaining,
):
    clock = FakeClock()
    in_provider, resume = Event(), Event()
    sdk = FakeSdkClient(TimeoutError(), StatusError(503), _response("last healthy model"))
    generate = sdk.models.generate_content

    def controlled_generate(**kwargs):
        if kwargs["model"] == "primary":
            in_provider.set()
            assert resume.wait(5), "test did not release first provider call"
        return generate(**kwargs)

    monkeypatch.setattr(sdk.models, "generate_content", controlled_generate)
    queued = GeminiClient(
        config(models=("primary", "secondary", "third", "fourth")), client=sdk, clock=clock,
    )
    failing = GeminiClient(
        config(models=("secondary", "third", "fourth") if cool_all_remaining else ("secondary",)),
        client=FakeSdkClient(TimeoutError(), TimeoutError(), TimeoutError()), clock=clock,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(queued.chat, "first request")
        try:
            assert in_provider.wait(5), "first request did not reach provider"
            with pytest.raises(GeminiTimeoutError):
                failing.chat("cool later candidates concurrently")
        finally:
            resume.set()
        if cool_all_remaining:
            with pytest.raises(GeminiTimeoutError):
                result.result(timeout=5)
            assert [call["model"] for call in sdk.models.calls] == ["primary"]
        else:
            assert result.result(timeout=5).model == "fourth"
            assert [call["model"] for call in sdk.models.calls] == ["primary", "third", "fourth"]


def test_sdk_uses_google_endpoint_explicitly_and_disables_hidden_retries(monkeypatch):
    from google import genai

    calls = []
    monkeypatch.setattr(genai, "Client", lambda **kwargs: calls.append(kwargs))
    GeminiClient._default_client_factory(api_key="fake-key", timeout_seconds=7)
    assert calls[0]["vertexai"] is False
    options = calls[0]["http_options"]
    assert options.base_url == "https://generativelanguage.googleapis.com"
    assert options.retry_options.attempts == 1
    assert options.timeout == 7000


def test_diagnostics_only_include_model_elapsed_and_sanitized_error(monkeypatch):
    from trendradar.ai import client as module

    logs = []
    logger = SimpleNamespace(
        warning=lambda message, **fields: logs.append((message, fields)),
        info=lambda message, **fields: logs.append((message, fields)),
    )
    monkeypatch.setattr(module, "log", logger)
    sdk = FakeSdkClient(TimeoutError("provider-private"), _response("private reply"))
    GeminiClient(config(), client=sdk).chat("prompt-private")
    assert logs[0][1]["error_code"] == "GEMINI_TIMEOUT"
    assert logs[1][1]["model"] == DEFAULT_GEMINI_MODELS[1]
    assert all("elapsed_ms" in fields for _, fields in logs)
    rendered = repr(logs)
    assert all(secret not in rendered for secret in ("private", "routing-test-key"))


def test_invalid_json_response_switches_model():
    sdk = FakeSdkClient(_response("invalid json"), _response('{"answer": "ok"}'))
    result = GeminiClient(config(), client=sdk).chat("question", response_mime_type="application/json")
    assert result.model == DEFAULT_GEMINI_MODELS[1]


def test_fenced_json_remains_compatible_with_existing_consumers():
    sdk = FakeSdkClient(_response('```json\n{"answer": "ok"}\n```'))
    result = GeminiClient(config(), client=sdk).chat("question", response_mime_type="application/json")
    assert result.text == '```json\n{"answer": "ok"}\n```'
    assert len(sdk.models.calls) == 1


def test_legacy_signed_transcript_is_inferred_and_never_replayed_to_another_model():
    sdk = FakeSdkClient(
        _response("", function_calls=[SimpleNamespace(name="lookup", args={}, id="call")]),
        TimeoutError(),
    )
    client = GeminiClient(config(), client=sdk)
    first = client.chat("question")
    with pytest.raises(GeminiTimeoutError):
        client.chat([
            GeminiMessage(role="user", content="question"),
            GeminiMessage(role="assistant", tool_calls=first.tool_calls),
            GeminiMessage(role="tool", name="lookup", content="evidence"),
        ])
    assert [call["model"] for call in sdk.models.calls] == [first.model, first.model]


@pytest.mark.parametrize(
    ("yaml", "environ", "models"),
    [
        ("", {}, DEFAULT_GEMINI_MODELS),
        ("model: old", {}, ("old",)),
        ("model: old\n    models: [one, two]", {}, ("one", "two")),
        ("models: [one, two]", {"GEMINI_MODEL": "env"}, ("env",)),
        ("models: [one, two]", {"GEMINI_MODEL": "env", "GEMINI_MODELS": " a, b,a "}, ("a", "b")),
    ],
)
def test_model_precedence_and_client_factory(tmp_path, yaml, environ, models):
    path = tmp_path / "config.yaml"
    path.write_text("ai:\n  gemini:\n    " + yaml + "\n", encoding="utf-8")
    settings = load_settings(path, environ={"GEMINI_API_KEY": "test-key", **environ})
    assert settings.gemini_models == models
    client = build_gemini_client(settings)
    assert client.config.models == models
    assert client.config.model_cooldown_seconds == 60
    assert not client.initialized


def test_cooldown_environment_overrides_yaml_and_bad_model_fails_closed(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("ai:\n  gemini:\n    model_cooldown_seconds: 15\n", encoding="utf-8")
    settings = load_settings(path, environ={"GEMINI_API_KEY": "key", "GEMINI_MODEL_COOLDOWN_SECONDS": "7"})
    assert build_gemini_client(settings).config.model_cooldown_seconds == 7
    settings = load_settings(path, environ={"GEMINI_API_KEY": "key", "GEMINI_MODELS": " , "})
    assert build_gemini_client(settings) is None
