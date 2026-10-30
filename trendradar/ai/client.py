"""Provider-neutral, bounded access to the Google Gemini SDK."""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from trendradar.utils.logging import log

from .errors import (
    GeminiAuthenticationError,
    GeminiConfigurationError,
    GeminiCooldownError,
    GeminiError,
    GeminiModelUnavailableError,
    GeminiRateLimitError,
    GeminiRequestError,
    GeminiResponseError,
    GeminiServerError,
    GeminiTimeoutError,
    GeminiUnavailableError,
)
from .media import ImagePart, validate_images

if TYPE_CHECKING:
    from trendradar.core.settings import RuntimeSettings

DEFAULT_GEMINI_MODELS = ("gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
DEFAULT_GEMINI_MODEL = DEFAULT_GEMINI_MODELS[0]
DEFAULT_MODEL_COOLDOWN_SECONDS = 60.0
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 1.0
DEFAULT_MAX_INPUT_CHARS = 32_000
DEFAULT_MAX_OUTPUT_CHARS = 12_000

MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 120.0
MIN_MAX_ATTEMPTS = 1
MAX_MAX_ATTEMPTS = 5
MIN_RETRY_BACKOFF_SECONDS = 0.0
MAX_RETRY_BACKOFF_SECONDS = 30.0
MIN_REQUEST_INTERVAL_SECONDS = 0.0
MAX_REQUEST_INTERVAL_SECONDS = 60.0
MIN_INPUT_CHARS = 1
MAX_INPUT_CHARS = 200_000
MIN_OUTPUT_CHARS = 1
MAX_OUTPUT_CHARS = 50_000
MAX_THOUGHT_SIGNATURE_BYTES = 64 * 1024

# Shared across core clients in this process, isolated by credential and model. Keys never log.
_MODEL_COOLDOWNS: dict[tuple[bytes, str], float] = {}
_MODEL_COOLDOWNS_LOCK = threading.Lock()

SUMMARY_INSTRUCTION = (
    "Summarize the supplied text concisely. Preserve material facts and do not invent evidence."
)
ANALYSIS_INSTRUCTION = (
    "Analyze the supplied material using only the provided evidence. Separate facts from inference."
)

_ALLOWED_ROLES = frozenset({"user", "assistant", "model", "tool"})


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise GeminiConfigurationError()


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _require_non_empty(value: Any, *, maximum: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GeminiConfigurationError()
    normalized = value.strip()
    if maximum is not None and len(normalized) > maximum:
        raise GeminiConfigurationError()
    return normalized


def _require_model(value: Any) -> str:
    model = _require_non_empty(value, maximum=256)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", model):
        raise GeminiConfigurationError()
    return model


def _require_number(
    value: Any,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool):
        raise GeminiConfigurationError()
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        raise GeminiConfigurationError() from None
    if not math.isfinite(normalized) or not minimum <= normalized <= maximum:
        raise GeminiConfigurationError()
    return normalized


def _require_int(value: Any, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise GeminiConfigurationError()
    return value


@dataclass(frozen=True, slots=True, repr=False)
class GeminiToolCall:
    """A normalized provider-requested function call; it is never executed here."""

    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    call_id: str | None = None
    thought_signature: bytes | None = field(default=None, repr=False)
    model: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_non_empty(self.name, maximum=128))
        if not isinstance(self.arguments, Mapping):
            raise GeminiConfigurationError()
        object.__setattr__(self, "arguments", _freeze_json(self.arguments))
        if self.call_id is not None:
            object.__setattr__(
                self,
                "call_id",
                _require_non_empty(self.call_id, maximum=256),
            )
        signature = self.thought_signature
        if isinstance(signature, bytearray | memoryview):
            signature = bytes(signature)
        if signature is not None and (
            not isinstance(signature, bytes)
            or not signature
            or len(signature) > MAX_THOUGHT_SIGNATURE_BYTES
        ):
            raise GeminiConfigurationError()
        object.__setattr__(self, "thought_signature", signature)
        if self.model is not None:
            object.__setattr__(self, "model", _require_model(self.model))

    def __repr__(self) -> str:
        return (
            "GeminiToolCall("
            f"name={self.name!r}, arguments=<redacted>, "
            f"call_id_present={self.call_id is not None!r}, "
            f"thought_signature_present={self.thought_signature is not None!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class GeminiMessage:
    """A provider-neutral conversation message."""

    role: str
    content: str = ""
    tool_calls: tuple[GeminiToolCall, ...] = ()
    name: str | None = None
    tool_call_id: str | None = None
    images: tuple[ImagePart, ...] = ()

    def __post_init__(self) -> None:
        role = str(self.role).strip().lower()
        if role not in _ALLOWED_ROLES:
            raise GeminiConfigurationError()
        content = str(self.content or "").strip()
        calls = tuple(self.tool_calls)
        if any(not isinstance(call, GeminiToolCall) for call in calls):
            raise GeminiConfigurationError()
        images = validate_images(self.images)
        if images and role != "user":
            raise GeminiConfigurationError()
        object.__setattr__(self, "images", images)
        if not content and not calls and not images:
            raise GeminiConfigurationError()
        if calls and role not in {"assistant", "model"}:
            raise GeminiConfigurationError()
        if role == "tool" and not self.name:
            raise GeminiConfigurationError()
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "tool_calls", calls)
        if self.name is not None:
            object.__setattr__(self, "name", _require_non_empty(self.name, maximum=128))
        if self.tool_call_id is not None:
            object.__setattr__(
                self,
                "tool_call_id",
                _require_non_empty(self.tool_call_id, maximum=256),
            )

    def __repr__(self) -> str:
        return (
            "GeminiMessage("
            f"role={self.role!r}, content_chars={len(self.content)!r}, "
            f"tool_call_count={len(self.tool_calls)!r}, "
            f"name_present={self.name is not None!r}, "
            f"tool_call_id_present={self.tool_call_id is not None!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class GeminiToolDefinition:
    """A declarative function schema passed to Gemini without a Python handler."""

    name: str
    description: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_non_empty(self.name, maximum=128))
        object.__setattr__(
            self,
            "description",
            _require_non_empty(self.description, maximum=2_000),
        )
        if not isinstance(self.parameters, Mapping):
            raise GeminiConfigurationError()
        object.__setattr__(self, "parameters", _freeze_json(self.parameters))

    @property
    def input_schema(self) -> Mapping[str, Any]:
        """Alias used by tool registries that call argument schemas input schemas."""
        return self.parameters

    def __repr__(self) -> str:
        return (
            "GeminiToolDefinition("
            f"name={self.name!r}, description=<redacted>, parameters=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class GeminiUsage:
    """Provider-neutral token accounting."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0

    def __post_init__(self) -> None:
        for value in (
            self.input_tokens,
            self.output_tokens,
            self.total_tokens,
            self.cached_tokens,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise GeminiResponseError()

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens

    @property
    def completion_tokens(self) -> int:
        return self.output_tokens


@dataclass(frozen=True, slots=True, repr=False)
class GeminiResult:
    """Bounded generation output with no Google SDK values."""

    text: str
    model: str
    finish_reason: str | None = None
    usage: GeminiUsage | None = None
    tool_calls: tuple[GeminiToolCall, ...] = ()
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not isinstance(self.model, str):
            raise GeminiResponseError()
        calls = tuple(self.tool_calls)
        if any(not isinstance(call, GeminiToolCall) for call in calls):
            raise GeminiResponseError()
        object.__setattr__(self, "tool_calls", calls)

    def __repr__(self) -> str:
        return (
            "GeminiResult("
            f"text_chars={len(self.text)!r}, model={self.model!r}, "
            f"finish_reason={self.finish_reason!r}, usage={self.usage!r}, "
            f"tool_call_count={len(self.tool_calls)!r}, truncated={self.truncated!r})"
        )


@dataclass(frozen=True, slots=True)
class GeminiConfig:
    """Validated configuration for one lazily constructed Gemini client."""

    api_key: str | None = field(default=None, repr=False)
    enabled: bool = True
    model: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS
    min_request_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS
    models: tuple[str, ...] | None = None
    model_cooldown_seconds: float = DEFAULT_MODEL_COOLDOWN_SECONDS

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise GeminiConfigurationError()
        key = str(self.api_key or "").strip() or None
        object.__setattr__(self, "api_key", key)
        if self.model is not None:
            _require_model(self.model)
        candidates = self.models
        if candidates is None:
            candidates = (self.model,) if self.model is not None else DEFAULT_GEMINI_MODELS
        if isinstance(candidates, str | bytes) or not isinstance(candidates, Sequence):
            raise GeminiConfigurationError()
        models = tuple(dict.fromkeys(_require_model(model) for model in candidates))
        if not models:
            raise GeminiConfigurationError()
        object.__setattr__(self, "models", models)
        object.__setattr__(self, "model", models[0])
        object.__setattr__(
            self, "model_cooldown_seconds",
            _require_number(self.model_cooldown_seconds, minimum=0, maximum=3600),
        )
        object.__setattr__(
            self,
            "timeout_seconds",
            _require_number(
                self.timeout_seconds,
                minimum=MIN_TIMEOUT_SECONDS,
                maximum=MAX_TIMEOUT_SECONDS,
            ),
        )
        object.__setattr__(
            self,
            "max_attempts",
            _require_int(
                self.max_attempts,
                minimum=MIN_MAX_ATTEMPTS,
                maximum=MAX_MAX_ATTEMPTS,
            ),
        )
        object.__setattr__(
            self,
            "retry_backoff_seconds",
            _require_number(
                self.retry_backoff_seconds,
                minimum=MIN_RETRY_BACKOFF_SECONDS,
                maximum=MAX_RETRY_BACKOFF_SECONDS,
            ),
        )
        object.__setattr__(
            self,
            "min_request_interval_seconds",
            _require_number(
                self.min_request_interval_seconds,
                minimum=MIN_REQUEST_INTERVAL_SECONDS,
                maximum=MAX_REQUEST_INTERVAL_SECONDS,
            ),
        )
        object.__setattr__(
            self,
            "max_input_chars",
            _require_int(
                self.max_input_chars,
                minimum=MIN_INPUT_CHARS,
                maximum=MAX_INPUT_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "max_output_chars",
            _require_int(
                self.max_output_chars,
                minimum=MIN_OUTPUT_CHARS,
                maximum=MAX_OUTPUT_CHARS,
            ),
        )


def _read_value(value: Any, *names: str) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        try:
            candidate = getattr(value, name)
        except (AttributeError, TypeError, ValueError):
            continue
        return candidate
    return None


def _optional_non_negative_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        raise GeminiResponseError()
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        raise GeminiResponseError() from None
    if normalized < 0:
        raise GeminiResponseError()
    return normalized


def _primitive_text(value: Any) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", value)
    if not isinstance(enum_value, str | int | float | bool):
        raise GeminiResponseError()
    normalized = str(enum_value).strip()
    return normalized or None


class GeminiClient:
    """One synchronous Gemini boundary shared by all core AI capabilities."""

    def __init__(
        self,
        config: GeminiConfig,
        *,
        client: Any | None = None,
        client_factory: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(config, GeminiConfig):
            raise GeminiConfigurationError()
        self._config = config
        self._client = client
        self._client_factory = client_factory
        self._clock = clock
        self._sleeper = sleeper
        self._client_lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._last_request_at: float | None = None
        self._credential_id = hashlib.sha256((config.api_key or "").encode()).digest()

    @property
    def config(self) -> GeminiConfig:
        return self._config

    @property
    def initialized(self) -> bool:
        return self._client is not None

    @property
    def available(self) -> bool:
        return self._config.enabled and bool(self._config.api_key)

    def __repr__(self) -> str:
        return f"GeminiClient(config={self._config!r}, initialized={self.initialized!r})"

    def for_model(self, model: str) -> GeminiClient:
        """Reuse the lazy SDK transport with an independent single-model route."""
        return self.for_models((model,))

    def for_models(self, models: Sequence[str]) -> GeminiClient:
        """Reuse the lazy SDK transport with a fixed route, one attempt per listed model."""
        route = tuple(models)
        if self.config.models == route and self.config.max_attempts == len(route):
            return self
        return GeminiClient(
            replace(self.config, model=route[0], models=route, max_attempts=len(route)),
            client_factory=lambda **_kwargs: self._get_client(),
            clock=self._clock,
            sleeper=self._sleeper,
        )

    def chat(
        self,
        messages: str | Sequence[GeminiMessage],
        *,
        system_instruction: str | None = None,
        tools: Sequence[GeminiToolDefinition] = (),
        response_schema: Mapping[str, Any] | type[Any] | None = None,
        response_mime_type: str | None = None,
        continuation_model: str | None = None,
        fallback_messages: Sequence[GeminiMessage] | None = None,
    ) -> GeminiResult:
        """Generate a conversational response from provider-neutral messages."""
        normalized = self._coerce_messages(messages)
        return self._generate(
            normalized,
            system_instruction=system_instruction,
            tools=tools,
            response_schema=response_schema,
            response_mime_type=response_mime_type,
            temperature=0.3,
            continuation_model=continuation_model,
            fallback_messages=fallback_messages,
        )

    def summary(
        self,
        text: str,
        *,
        instruction: str | None = None,
        response_schema: Mapping[str, Any] | type[Any] | None = None,
        response_mime_type: str | None = None,
    ) -> GeminiResult:
        """Summarize one bounded text input."""
        return self._generate(
            (GeminiMessage(role="user", content=text),),
            system_instruction=instruction or SUMMARY_INSTRUCTION,
            response_schema=response_schema,
            response_mime_type=response_mime_type,
            temperature=0.2,
        )

    def analyze(
        self,
        text: str,
        *,
        instruction: str | None = None,
        tools: Sequence[GeminiToolDefinition] = (),
        response_schema: Mapping[str, Any] | type[Any] | None = None,
        response_mime_type: str | None = None,
    ) -> GeminiResult:
        """Analyze one bounded text input and optionally request declarative tools."""
        return self._generate(
            (GeminiMessage(role="user", content=text),),
            system_instruction=instruction or ANALYSIS_INSTRUCTION,
            tools=tools,
            response_schema=response_schema,
            response_mime_type=response_mime_type,
            temperature=0.1,
        )

    @staticmethod
    def _coerce_messages(
        messages: str | Sequence[GeminiMessage],
    ) -> tuple[GeminiMessage, ...]:
        if isinstance(messages, str):
            return (GeminiMessage(role="user", content=messages),)
        if isinstance(messages, bytes) or not isinstance(messages, Sequence):
            raise GeminiConfigurationError()
        normalized = tuple(messages)
        if not normalized or any(not isinstance(item, GeminiMessage) for item in normalized):
            raise GeminiConfigurationError()
        return normalized

    def _generate(
        self,
        messages: Sequence[GeminiMessage],
        *,
        system_instruction: str | None,
        tools: Sequence[GeminiToolDefinition] = (),
        response_schema: Mapping[str, Any] | type[Any] | None = None,
        response_mime_type: str | None = None,
        temperature: float,
        continuation_model: str | None = None,
        fallback_messages: Sequence[GeminiMessage] | None = None,
    ) -> GeminiResult:
        bounded_messages = self._bound_messages(messages)
        contents = [self._provider_message(message) for message in bounded_messages]
        generation_config = self._generation_config(
            system_instruction=system_instruction,
            tools=tools,
            response_schema=response_schema,
            response_mime_type=response_mime_type,
            temperature=temperature,
        )
        origins = {call.model for message in messages for call in message.tool_calls if call.model}
        if len(origins) > 1 or (origins and continuation_model not in {*origins, None}):
            raise GeminiConfigurationError()
        if continuation_model is None:
            continuation_model = next(iter(origins), None)
        has_tools = any(message.tool_calls or message.role == "tool" for message in messages)
        if has_tools and continuation_model is None:
            # Legacy manually constructed tool transcripts stay on the explicit primary model.
            continuation_model = self.config.model
        if continuation_model is not None and continuation_model not in self.config.models:
            raise GeminiConfigurationError()

        fallback_contents = None
        fallback_config = None
        if fallback_messages is not None:
            fallback = self._coerce_messages(fallback_messages)
            if any(message.tool_calls or message.role == "tool" for message in fallback):
                raise GeminiConfigurationError()
            # Reconstructed evidence must arrive pre-budgeted; prefix truncation can corrupt it.
            if sum(len(message.content) for message in fallback) > self.config.max_input_chars:
                raise GeminiConfigurationError()
            fallback_contents = [self._provider_message(m) for m in self._bound_messages(fallback)]
            fallback_config = self._generation_config(
                system_instruction=system_instruction,
                tools=(),
                response_schema=response_schema,
                response_mime_type=response_mime_type,
                temperature=temperature,
            )
        candidates = self.config.models
        if continuation_model is not None:
            candidates = (continuation_model,)
            if fallback_contents is not None:
                candidates += tuple(m for m in self.config.models if m != continuation_model)
        client = self._get_client()
        if not self._available_models(candidates):
            log.warning("Gemini routing unavailable", error_code=GeminiCooldownError.code)
            raise GeminiCooldownError()
        self._wait_for_request_slot()
        attempted: set[str] = set()
        mapped_error: GeminiError = GeminiCooldownError()
        while len(attempted) < min(3, self.config.max_attempts):
            model = self._next_model(candidates, attempted)
            if model is None:
                break
            rebuilding = continuation_model is not None and model != continuation_model
            started = self._clock()
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=fallback_contents if rebuilding else contents,
                    config=fallback_config if rebuilding else generation_config,
                )
                result = self._normalize_response(response, model=model)
                if rebuilding and result.tool_calls:
                    raise GeminiResponseError()
                if (
                    generation_config.get("response_mime_type") == "application/json"
                    and not result.tool_calls
                ):
                    json_text = result.text
                    if json_text.startswith("```") and json_text.endswith("```"):
                        lines = json_text.splitlines()[1:-1]
                        if lines and lines[0].strip().casefold() in {"json", "javascript"}:
                            lines = lines[1:]
                        json_text = "\n".join(lines)
                    try:
                        json.loads(json_text)
                    except (TypeError, ValueError):
                        raise GeminiResponseError() from None
            except GeminiError as error:
                mapped_error = error
            except Exception as error:
                mapped_error = self._map_provider_error(error)
            else:
                log.info("Gemini request completed", model=model,
                         elapsed_ms=round(max(0, self._clock() - started) * 1000, 1))
                return result
            log.warning("Gemini request failed", model=model,
                        elapsed_ms=round(max(0, self._clock() - started) * 1000, 1),
                        error_code=mapped_error.code)
            if not mapped_error.retryable:
                raise mapped_error from None
            self._cool_down(model)
        if not attempted:
            log.warning("Gemini routing unavailable", error_code=GeminiCooldownError.code)
        raise mapped_error from None

    def _available_models(self, models: Sequence[str]) -> tuple[str, ...]:
        with _MODEL_COOLDOWNS_LOCK:
            now = self._clock()
            for key, until in list(_MODEL_COOLDOWNS.items()):
                if until <= now:
                    del _MODEL_COOLDOWNS[key]
            return tuple(m for m in models if (self._credential_id, m) not in _MODEL_COOLDOWNS)

    def _next_model(self, models: Sequence[str], attempted: set[str]) -> str | None:
        """Select each dispatch against current cooldowns; skips do not spend the call budget."""
        with _MODEL_COOLDOWNS_LOCK:
            now = self._clock()
            for model in models:
                if model in attempted:
                    continue
                if _MODEL_COOLDOWNS.get((self._credential_id, model), float("-inf")) > now:
                    continue
                attempted.add(model)
                return model
        return None

    def _cool_down(self, model: str) -> None:
        until = self._clock() + self.config.model_cooldown_seconds
        key = (self._credential_id, model)
        with _MODEL_COOLDOWNS_LOCK:
            _MODEL_COOLDOWNS[key] = max(until, _MODEL_COOLDOWNS.get(key, until))

    def _get_client(self) -> Any:
        if not self._config.enabled or not self._config.api_key:
            raise GeminiUnavailableError()
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is not None:
                return self._client
            try:
                factory = self._client_factory or self._default_client_factory
                self._client = factory(
                    api_key=self._config.api_key,
                    timeout_seconds=self._config.timeout_seconds,
                )
            except GeminiError:
                raise
            except Exception:
                raise GeminiUnavailableError() from None
            if self._client is None:
                raise GeminiUnavailableError()
            return self._client

    @staticmethod
    def _default_client_factory(*, api_key: str, timeout_seconds: float) -> Any:
        try:
            from google import genai
            from google.genai import types
        except (ImportError, AttributeError):
            raise GeminiUnavailableError() from None
        return genai.Client(
            api_key=api_key,
            vertexai=False,
            http_options=types.HttpOptions(
                base_url="https://generativelanguage.googleapis.com",
                timeout=max(1, int(timeout_seconds * 1_000)),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    def _bound_messages(self, messages: Sequence[GeminiMessage]) -> tuple[GeminiMessage, ...]:
        try:
            validate_images(tuple(image for message in messages for image in message.images))
        except (ValueError, TypeError):
            raise GeminiConfigurationError() from None
        remaining = self._config.max_input_chars
        bounded_reversed: list[GeminiMessage] = []
        for message in reversed(messages):
            tool_chars = sum(
                len(call.name) + len(str(_thaw_json(call.arguments)))
                for call in message.tool_calls
            )
            if tool_chars >= remaining and not message.content:
                raise GeminiConfigurationError()
            content_budget = max(0, remaining - tool_chars)
            bounded_content = message.content[:content_budget].rstrip()
            if not bounded_content and not message.tool_calls and not message.images:
                continue
            bounded_reversed.append(
                GeminiMessage(
                    role=message.role,
                    content=bounded_content,
                    tool_calls=message.tool_calls,
                    name=message.name,
                    tool_call_id=message.tool_call_id,
                    images=message.images,
                )
            )
            remaining -= len(bounded_content) + tool_chars
            if remaining <= 0:
                break
        if not bounded_reversed:
            raise GeminiConfigurationError()
        return tuple(reversed(bounded_reversed))

    @staticmethod
    def _provider_message(message: GeminiMessage) -> dict[str, Any]:
        if message.role == "tool":
            function_response: dict[str, Any] = {
                "name": message.name,
                "response": {"output": message.content},
            }
            if message.tool_call_id:
                function_response["id"] = message.tool_call_id
            return {
                "role": "user",
                "parts": [{"function_response": function_response}],
            }

        parts: list[dict[str, Any]] = []
        if message.content:
            parts.append({"text": message.content})
        parts.extend({"inline_data": {"mime_type": image.mime_type, "data": image.data}}
                     for image in message.images)
        for call in message.tool_calls:
            function_call: dict[str, Any] = {
                "name": call.name,
                "args": _thaw_json(call.arguments),
            }
            if call.call_id:
                function_call["id"] = call.call_id
            function_part: dict[str, Any] = {"function_call": function_call}
            if call.thought_signature is not None:
                function_part["thought_signature"] = call.thought_signature
            parts.append(function_part)
        return {
            "role": "model" if message.role in {"assistant", "model"} else "user",
            "parts": parts,
        }

    @staticmethod
    def _normalize_tools(
        tools: Sequence[GeminiToolDefinition],
    ) -> list[dict[str, Any]]:
        normalized = tuple(tools)
        if any(not isinstance(tool, GeminiToolDefinition) for tool in normalized):
            raise GeminiConfigurationError()
        if not normalized:
            return []
        return [
            {
                "function_declarations": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters_json_schema": _thaw_json(tool.parameters),
                    }
                    for tool in normalized
                ]
            }
        ]

    def _generation_config(
        self,
        *,
        system_instruction: str | None,
        tools: Sequence[GeminiToolDefinition],
        response_schema: Mapping[str, Any] | type[Any] | None,
        response_mime_type: str | None,
        temperature: float,
    ) -> dict[str, Any]:
        config: dict[str, Any] = {"temperature": temperature}
        if system_instruction is not None:
            config["system_instruction"] = _require_non_empty(
                system_instruction,
                maximum=self._config.max_input_chars,
            )
        normalized_tools = self._normalize_tools(tools)
        if normalized_tools:
            config["tools"] = normalized_tools
            config["automatic_function_calling"] = {"disable": True}
        if response_schema is not None:
            if isinstance(response_schema, Mapping):
                config["response_json_schema"] = _thaw_json(_freeze_json(response_schema))
            elif isinstance(response_schema, type):
                config["response_schema"] = response_schema
            else:
                raise GeminiConfigurationError()
            config["response_mime_type"] = response_mime_type or "application/json"
        elif response_mime_type is not None:
            config["response_mime_type"] = _require_non_empty(
                response_mime_type,
                maximum=128,
            )
        return config

    def _wait_for_request_slot(self) -> None:
        interval = self._config.min_request_interval_seconds
        with self._rate_lock:
            now = float(self._clock())
            if not math.isfinite(now):
                raise GeminiConfigurationError()
            request_at = now
            if self._last_request_at is not None:
                request_at = max(now, self._last_request_at + interval)
            delay = request_at - now
            if delay > 0:
                self._sleeper(delay)
            self._last_request_at = request_at

    def _normalize_response(self, response: Any, *, model: str) -> GeminiResult:
        if response is None:
            raise GeminiResponseError()
        try:
            call_parts = self._response_tool_call_parts(response)
            if call_parts:
                calls = self._normalize_tool_calls(
                    tuple(call for call, _signature in call_parts),
                    thought_signatures=tuple(signature for _call, signature in call_parts),
                )
            else:
                raw_calls = _read_value(response, "function_calls", "functionCalls")
                calls = self._normalize_tool_calls(raw_calls)
            raw_text = _read_value(response, "text")
        except GeminiError:
            raise
        except Exception:
            raise GeminiResponseError() from None

        if raw_text is None:
            text = ""
        elif isinstance(raw_text, str):
            text = raw_text.strip()
        else:
            raise GeminiResponseError()
        if not text and not calls:
            raise GeminiResponseError()

        truncated = len(text) > self._config.max_output_chars
        if truncated:
            text = text[: self._config.max_output_chars].rstrip()

        usage_value = _read_value(response, "usage_metadata", "usageMetadata")
        usage = self._normalize_usage(usage_value) if usage_value is not None else None
        finish_reason = self._finish_reason(response)
        return GeminiResult(
            text=text,
            model=model,
            finish_reason=finish_reason,
            usage=usage,
            tool_calls=tuple(replace(call, model=model) for call in calls),
            truncated=truncated,
        )

    @staticmethod
    def _response_tool_call_parts(response: Any) -> tuple[tuple[Any, Any], ...]:
        """Keep Gemini 3 opaque thought signatures attached to their function calls."""
        candidates = _read_value(response, "candidates")
        if candidates is None:
            return ()
        if isinstance(candidates, str | bytes) or not isinstance(candidates, Sequence):
            raise GeminiResponseError()
        call_parts: list[tuple[Any, Any]] = []
        for candidate in candidates:
            content = _read_value(candidate, "content")
            parts = _read_value(content, "parts") if content is not None else None
            if parts is None:
                continue
            if isinstance(parts, str | bytes) or not isinstance(parts, Sequence):
                raise GeminiResponseError()
            for part in parts:
                call = _read_value(part, "function_call", "functionCall")
                if call is not None:
                    call_parts.append(
                        (
                            call,
                            _read_value(part, "thought_signature", "thoughtSignature"),
                        )
                    )
        return tuple(call_parts)

    @staticmethod
    def _normalize_tool_calls(
        value: Any,
        *,
        thought_signatures: Sequence[Any] | None = None,
    ) -> tuple[GeminiToolCall, ...]:
        if value is None:
            return ()
        if isinstance(value, str | bytes) or not isinstance(value, Sequence):
            raise GeminiResponseError()
        raw_calls = tuple(value)
        signatures = (
            (None,) * len(raw_calls)
            if thought_signatures is None
            else tuple(thought_signatures)
        )
        if len(signatures) != len(raw_calls):
            raise GeminiResponseError()
        calls: list[GeminiToolCall] = []
        for raw_call, thought_signature in zip(raw_calls, signatures, strict=True):
            name = _read_value(raw_call, "name")
            arguments = _read_value(raw_call, "args", "arguments")
            call_id = _read_value(raw_call, "id", "call_id", "callId")
            if not isinstance(name, str) or not isinstance(arguments, Mapping):
                raise GeminiResponseError()
            try:
                calls.append(
                    GeminiToolCall(
                        name=name,
                        arguments=arguments,
                        call_id=_primitive_text(call_id),
                        thought_signature=thought_signature,
                    )
                )
            except GeminiConfigurationError:
                raise GeminiResponseError() from None
        return tuple(calls)

    @staticmethod
    def _normalize_usage(value: Any) -> GeminiUsage:
        return GeminiUsage(
            input_tokens=_optional_non_negative_int(
                _read_value(value, "prompt_token_count", "promptTokenCount")
            ),
            output_tokens=_optional_non_negative_int(
                _read_value(value, "candidates_token_count", "candidatesTokenCount")
            ),
            total_tokens=_optional_non_negative_int(
                _read_value(value, "total_token_count", "totalTokenCount")
            ),
            cached_tokens=_optional_non_negative_int(
                _read_value(value, "cached_content_token_count", "cachedContentTokenCount")
            ),
        )

    @staticmethod
    def _finish_reason(response: Any) -> str | None:
        candidates = _read_value(response, "candidates")
        if not candidates:
            return None
        if isinstance(candidates, str | bytes) or not isinstance(candidates, Sequence):
            raise GeminiResponseError()
        return _primitive_text(_read_value(candidates[0], "finish_reason", "finishReason"))

    @staticmethod
    def _map_provider_error(error: Exception) -> GeminiError:
        if isinstance(error, GeminiError):
            return error
        class_names = {item.__name__.lower() for item in type(error).__mro__}
        status = GeminiClient._status_code(error)
        details = _read_value(error, "details")
        payload = _read_value(details, "error") or details
        reason_details = _read_value(payload, "details")
        reasons = (
            [reason for item in reason_details if isinstance(reason := _read_value(item, "reason"), str)]
            if isinstance(reason_details, list | tuple) else set()
        )
        if (
            status in {401, 403}
            or _read_value(error, "status") in ("UNAUTHENTICATED", "PERMISSION_DENIED")
            or set(reasons).intersection({"API_KEY_INVALID", "API_KEY_EXPIRED", "API_KEY_SERVICE_BLOCKED"})
        ):
            return GeminiAuthenticationError()
        if isinstance(error, TimeoutError) or any("timeout" in name for name in class_names):
            return GeminiTimeoutError()
        if status == 408:
            return GeminiTimeoutError()
        if status == 429 or any(
            "ratelimit" in name or "resourceexhausted" in name or "toomanyrequests" in name
            for name in class_names
        ):
            return GeminiRateLimitError()
        if status in {404, 410}:
            return GeminiModelUnavailableError()
        if status is not None and 500 <= status < 600:
            return GeminiServerError()
        if status is not None and 400 <= status < 500:
            return GeminiRequestError(retryable=False)
        if isinstance(error, ImportError):
            return GeminiUnavailableError()
        if isinstance(error, TypeError | ValueError):
            return GeminiRequestError(retryable=False)
        return GeminiRequestError(retryable=True)

    @staticmethod
    def _status_code(error: Exception) -> int | None:
        candidates = (
            _read_value(error, "status_code", "statusCode", "code"),
            _read_value(_read_value(error, "response"), "status_code", "statusCode"),
        )
        for candidate in candidates:
            if callable(candidate) or isinstance(candidate, bool):
                continue
            try:
                return int(candidate)
            except (TypeError, ValueError):
                continue
        return None


def build_gemini_client(
    settings: RuntimeSettings,
    *,
    client: Any | None = None,
    client_factory: Callable[..., Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> GeminiClient | None:
    """Build the optional process-wide client from environment-backed settings.

    The SDK remains lazy until the first request. Missing credentials, disabled settings, and
    malformed configuration are intentionally treated as an unavailable optional service so
    deterministic collection and reporting can continue.
    """
    try:
        if not bool(settings.gemini_enabled):
            return None
        api_key = str(settings.gemini_api_key or "").strip()
        if not api_key:
            return None
        values = settings.gemini_config
        if not isinstance(values, Mapping):
            return None
        config_values = {
            name: values[name]
            for name in (
                "enabled",
                "model",
                "models",
                "model_cooldown_seconds",
                "timeout_seconds",
                "max_attempts",
                "retry_backoff_seconds",
                "min_request_interval_seconds",
                "max_input_chars",
                "max_output_chars",
            )
            if name in values
        }
        return GeminiClient(
            GeminiConfig(api_key=api_key, **config_values),
            client=client,
            client_factory=client_factory,
            clock=clock,
            sleeper=sleeper,
        )
    except Exception:
        return None


__all__ = [
    "ANALYSIS_INSTRUCTION",
    "DEFAULT_GEMINI_MODEL",
    "DEFAULT_GEMINI_MODELS",
    "GeminiClient",
    "GeminiConfig",
    "build_gemini_client",
    "GeminiMessage",
    "GeminiResult",
    "GeminiToolCall",
    "GeminiToolDefinition",
    "GeminiUsage",
    "SUMMARY_INSTRUCTION",
]
