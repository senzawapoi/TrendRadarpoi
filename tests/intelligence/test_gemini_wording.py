from types import SimpleNamespace

import pytest

from trendradar.ai import GeminiClient, GeminiConfig
from trendradar.core.settings import load_settings
from trendradar.intelligence import gemini_wording
from trendradar.intelligence.gemini_wording import GeminiStoryWordingClient


@pytest.fixture(autouse=True)
def isolated_model_cooldowns(monkeypatch):
    monkeypatch.setattr("trendradar.ai.client._MODEL_COOLDOWNS", {})


class _FakeModels:
    def __init__(self, text: str):
        self.text = text
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.text)


class _FakeClient:
    def __init__(self, text: str):
        self.models = _FakeModels(text)


def _settings(tmp_path, *, enabled: bool, key: str = ""):
    config = tmp_path / "config.yaml"
    config.write_text(
        "intelligence:\n"
        f"  enabled: {str(enabled).lower()}\n"
        "  story:\n"
        "    wording:\n"
        "      enabled: true\n",
        encoding="utf-8",
    )
    environ = {"GEMINI_API_KEY": key} if key else {}
    return load_settings(config, environ=environ)


def test_wording_client_parses_json_and_sends_only_wording_context():
    fake = _FakeClient('{"title":"Edited title","summary":"Edited summary"}')
    client = GeminiStoryWordingClient("test-key", client=fake)

    result = client.enhance(title="Base title", summary="Base summary")

    assert result == {"title": "Edited title", "summary": "Edited summary"}
    request = fake.models.calls[0]
    assert request["model"] == "gemini-3.8-flash"
    serialized = str(request["contents"])
    assert "Base title" in serialized
    assert "Base summary" in serialized
    assert "member_ids" not in serialized
    assert "importance" not in serialized
    assert request["config"]["response_mime_type"] == "application/json"


def test_wording_client_accepts_markdown_fenced_json():
    fake = _FakeClient('```json\n{"title":"T","summary":"S"}\n```')
    assert GeminiStoryWordingClient("test-key", client=fake).enhance(
        title="Base", summary="Summary"
    ) == {"title": "T", "summary": "S"}


@pytest.mark.parametrize("text", ["", "[]", '{"title":"", "summary":"S"}', "not json"])
def test_wording_client_rejects_invalid_response(text):
    with pytest.raises(ValueError):
        GeminiStoryWordingClient("test-key", client=_FakeClient(text)).enhance(
            title="Base", summary="Summary"
        )


def test_builder_is_lazy_and_requires_key_and_all_enablement_gates(tmp_path, monkeypatch):
    disabled = _settings(tmp_path, enabled=False, key="test-key")
    assert gemini_wording.build_story_wording_client(disabled) is None

    no_key = _settings(tmp_path, enabled=True)
    assert gemini_wording.build_story_wording_client(no_key) is None

    captured = {}

    def fake_constructor(api_key, **kwargs):
        captured.update(api_key=api_key, options=kwargs)
        return "client"

    monkeypatch.setattr(gemini_wording, "GeminiStoryWordingClient", fake_constructor)
    enabled = _settings(tmp_path, enabled=True, key="test-key")

    assert gemini_wording.build_story_wording_client(enabled) == "client"
    assert captured["api_key"] == "test-key"
    assert captured["options"]["gemini_client"].config.models == (
        "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
    )


def test_empty_key_is_rejected_before_sdk_creation():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiStoryWordingClient("", client=_FakeClient("{}"))


def test_builder_reuses_injected_shared_core_client(tmp_path):
    settings = _settings(tmp_path, enabled=True, key="test-key")
    sdk = _FakeClient('{"title":"T","summary":"S"}')
    shared = GeminiClient(
        GeminiConfig(
            api_key="test-key",
            max_attempts=1,
            min_request_interval_seconds=0,
        ),
        client=sdk,
    )

    wording = gemini_wording.build_story_wording_client(settings, gemini_client=shared)

    assert wording is not None
    assert wording.client is shared
    assert wording.enhance(title="Base", summary="Summary") == {"title": "T", "summary": "S"}
