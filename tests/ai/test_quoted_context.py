"""Untrusted direct replies remain separate, bounded input, never citations."""

import pytest

from trendradar.ai import models


def test_assistant_accepts_distinct_quote_without_changing_question():
    quote = models.QuotedMessageContext("available", text="Budget 37 units", message_type="text")
    request = models.AssistantRequest("r", "p", "Explain this", quoted_context=quote)
    assert request.text == "Explain this"
    assert request.quoted_context.text == "Budget 37 units"
    assert models.AssistantRequest("r", "p", "ordinary").quoted_context is None


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "available", "text": "x" * 4001},
        {"status": "permission_denied", "text": "private content"},
        {"status": "unknown status"},
        {"status": []},
        {"status": "available", "text": "news", "truncated": "false"},
    ],
)
def test_quote_model_rejects_unbounded_or_inconsistent_state(fields):
    with pytest.raises(ValueError):
        models.QuotedMessageContext(**fields)


def test_combined_input_limit_is_checked_before_session_or_provider(tmp_path):
    from unittest.mock import Mock

    from trendradar.ai.assistant import AssistantLimits, AssistantService
    from trendradar.ai.session import SessionLimits

    gemini = Mock()
    assistant = AssistantService(
        tmp_path / "bounded.db",
        gemini,
        limits=AssistantLimits(session=SessionLimits(max_input_chars=20)),
    )
    try:
        with pytest.raises(ValueError, match="input limit"):
            assistant.handle(
                models.AssistantRequest(
                    "r",
                    "p",
                    "Current question",
                    quoted_context=models.QuotedMessageContext("available", "quoted text"),
                )
            )
        gemini.chat.assert_not_called()
        assert assistant.storage.count("assistant_sessions") == 0
    finally:
        assistant.close()
