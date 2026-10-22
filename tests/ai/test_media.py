"""Provider-neutral image bounds and backwards-compatible text requests."""

from datetime import datetime, timedelta, timezone

import pytest

from trendradar.ai.client import GeminiClient, GeminiConfig, GeminiMessage
from trendradar.ai.media import ImagePart, validate_images
from trendradar.ai.models import AssistantRequest
from trendradar.ai.session import SessionAccessError, SessionStore

PNG = b"\x89PNG\r\n\x1a\nfixture"


def test_text_api_unchanged_and_image_only_supported():
    assert AssistantRequest("r", "p", "text").images == ()
    image = ImagePart(PNG, "image/png")
    request = AssistantRequest("r", "p", "", images=(image,))
    assert request.text == "[Image attachment]"
    client = GeminiClient(GeminiConfig(enabled=False))
    bounded = client._bound_messages([GeminiMessage("user", images=(image,))])
    assert client._provider_message(bounded[0])["parts"][0]["inline_data"]["data"] == PNG


def test_image_validation_and_repr():
    image = ImagePart(PNG, "image/png")
    assert "fixture" not in repr(image)
    with pytest.raises(ValueError):
        ImagePart(PNG, "image/jpeg")
    with pytest.raises(ValueError):
        ImagePart(b"bad", "image/png")
    with pytest.raises(ValueError):
        validate_images((image,) * 5)
    large = ImagePart(b"\x89PNG\r\n\x1a\n" + b"x" * 3_000_000, "image/png")
    with pytest.raises(ValueError):
        validate_images((large,) * 3)


def test_explicit_session_open_renews_only_expired_owned_sessions(tmp_path):
    store = SessionStore(tmp_path / "session.db")
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    first = store.open_session("owner", "chat", now=now)
    assert store.open_session("owner", "chat", now=now) == first
    with pytest.raises(SessionAccessError):
        store.open_session("other", "chat", now=now + timedelta(days=100))
    renewed = store.open_session("owner", "chat", now=now + timedelta(days=31))
    assert renewed.created_at > first.created_at
    store.close()
