"""Sanitized errors exposed by the core Gemini boundary."""

from __future__ import annotations

from typing import ClassVar


class GeminiError(Exception):
    """Base error with a stable public code and retry classification."""

    code: ClassVar[str] = "GEMINI_ERROR"
    default_message: ClassVar[str] = "Gemini operation failed."
    default_retryable: ClassVar[bool] = False

    def __init__(self, *, retryable: bool | None = None) -> None:
        self.retryable = self.default_retryable if retryable is None else bool(retryable)
        super().__init__(self.default_message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, retryable={self.retryable!r})"

    def as_dict(self) -> dict[str, str | bool]:
        """Return a provider-neutral representation safe for logs and API adapters."""
        return {
            "code": self.code,
            "message": self.default_message,
            "retryable": self.retryable,
        }


class GeminiConfigurationError(GeminiError):
    """Raised for invalid client or request configuration."""

    code = "GEMINI_CONFIGURATION_ERROR"
    default_message = "Gemini configuration is invalid."


class GeminiUnavailableError(GeminiError):
    """Raised when Gemini is disabled, unconfigured, or cannot be constructed."""

    code = "GEMINI_UNAVAILABLE"
    default_message = "Gemini is unavailable."


class GeminiTimeoutError(GeminiError):
    """Raised when a provider request times out."""

    code = "GEMINI_TIMEOUT"
    default_message = "Gemini request timed out."
    default_retryable = True


class GeminiRateLimitError(GeminiError):
    """Raised when the provider rejects a request for rate limiting."""

    code = "GEMINI_RATE_LIMIT"
    default_message = "Gemini rate limit was reached."
    default_retryable = True


class GeminiRequestError(GeminiError):
    """Raised for provider request failures not covered by a narrower type."""

    code = "GEMINI_REQUEST_ERROR"
    default_message = "Gemini request failed."
    default_retryable = True


class GeminiResponseError(GeminiError):
    """Raised when the provider returns an empty or malformed response."""

    code = "GEMINI_RESPONSE_ERROR"
    default_message = "Gemini response was invalid."


# Compatibility-friendly explicit name for callers that prefer the failure condition.
GeminiInvalidResponseError = GeminiResponseError


__all__ = [
    "GeminiConfigurationError",
    "GeminiError",
    "GeminiInvalidResponseError",
    "GeminiRateLimitError",
    "GeminiRequestError",
    "GeminiResponseError",
    "GeminiTimeoutError",
    "GeminiUnavailableError",
]
