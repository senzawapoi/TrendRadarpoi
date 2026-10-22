from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from trendradar.research.agent_reach import AgentReachAdapter
from trendradar.research.models import ResearchRequest
from trendradar.research.transport import FixedHttpClient, ProcessOutput, run_fixed_process


class FakeHTTP:
    def __init__(self, body=b"# Article\n\nA bounded article"):
        self.body = body
        self.calls = []

    def get(self, url, *, timeout, max_bytes):
        self.calls.append((url, timeout, max_bytes))
        return self.body


def runner_for(payload, *, returncode=0, stderr=b""):
    calls = []

    def runner(**kwargs):
        calls.append(kwargs)
        if "--config" in kwargs["argv"]:
            calls[-1]["config_text"] = Path(
                kwargs["argv"][kwargs["argv"].index("--config") + 1]
            ).read_text(encoding="utf-8")
        return ProcessOutput(returncode, payload.decode(), stderr.decode())

    runner.calls = calls
    return runner


def test_web_search_uses_fixed_mcporter_and_parses_json():
    runner = runner_for(json.dumps({"results": [
        {"title": "A", "url": "https://example.com/a", "text": "Fact"},
        {"title": "Private", "url": "file:///secret", "text": "x"},
    ]}).encode())
    result = AgentReachAdapter(process_runner=runner).research(
        ResearchRequest("search_web", query="safe query", limit=2), timeout=4, max_bytes=5000,
    )
    assert result.ok and len(result.items) == 1
    assert runner.calls[0]["argv"][0:2] == ["mcporter", "--config"]
    assert runner.calls[0]["argv"][3:6] == ["call", "exa.web_search_exa", "--args"]
    config = json.loads(runner.calls[0]["config_text"])
    assert config == {
        "mcpServers": {"exa": {"baseUrl": "https://mcp.exa.ai/mcp"}},
        "imports": [],
    }
    assert "safe query" in " ".join(runner.calls[0]["argv"])


def test_web_search_parses_mcporter_text_envelope():
    payload = b"""Title: MCP result
URL: https://example.com/result
Published: 2026-10-12
Author: Example
Highlights: bounded evidence
"""
    runner = runner_for(payload)
    result = AgentReachAdapter(process_runner=runner).research(
        ResearchRequest("search_web", query="safe"), timeout=4, max_bytes=5000,
    )
    assert result.ok and result.items[0].title == "MCP result"
    assert result.items[0].content == "bounded evidence"


def test_web_search_parses_json_inside_mcp_text_block():
    payload = json.dumps({"content": [{"type": "text", "text": json.dumps({
        "results": [{
            "title": "Nested result", "url": "https://example.com/nested", "text": "fact",
        }],
    })}]})
    runner = runner_for(payload.encode())
    result = AgentReachAdapter(process_runner=runner).research(
        ResearchRequest("search_web", query="safe"), timeout=4, max_bytes=5000,
    )
    assert result.ok and result.items[0].title == "Nested result"


def test_mcp_error_envelope_is_not_successful_empty_result():
    runner = runner_for(json.dumps({"isError": True, "content": []}).encode())
    result = AgentReachAdapter(process_runner=runner).research(
        ResearchRequest("search_web", query="safe"), timeout=4, max_bytes=5000,
    )
    assert not result.ok and result.error_code == "upstream_error"


def test_structured_error_field_is_not_a_valid_empty_result():
    runner = runner_for(json.dumps({"results": [], "error": "provider failed"}).encode())
    result = AgentReachAdapter(process_runner=runner).research(
        ResearchRequest("search_web", query="safe"), timeout=4, max_bytes=5000,
    )
    assert not result.ok and result.error_code == "upstream_error"


def test_nonempty_unrecognized_exa_response_is_invalid():
    runner = runner_for(b"provider temporarily unavailable")
    result = AgentReachAdapter(process_runner=runner).research(
        ResearchRequest("search_web", query="safe"), timeout=4, max_bytes=5000,
    )
    assert result.error_code == "invalid_response"


def test_nonempty_malformed_exa_result_list_is_invalid():
    runner = runner_for(json.dumps({"results": [{"title": "missing URL"}]}).encode())
    result = AgentReachAdapter(process_runner=runner).research(
        ResearchRequest("search_web", query="safe"), timeout=4, max_bytes=5000,
    )
    assert result.error_code == "invalid_response"


def test_reddit_search_keeps_only_public_reddit_urls():
    runner = runner_for(json.dumps({"results": [
        {"title": "Reddit", "url": "https://www.reddit.com/r/ai/comments/1", "text": "post"},
        {"title": "Other", "url": "https://example.com", "text": "other"},
    ]}).encode())
    result = AgentReachAdapter(process_runner=runner).research(
        ResearchRequest("search_reddit", query="models"), timeout=4, max_bytes=5000,
    )
    assert result.ok and [item.title for item in result.items] == ["Reddit"]
    args = runner.calls[0]["argv"]
    assert "site:reddit.com models" in args[args.index("--args") + 1]


def test_github_search_has_closed_fixed_fields():
    runner = runner_for(json.dumps([{
        "name": "repo", "description": "A repo", "url": "https://github.com/a/repo",
        "updatedAt": "2026-01-01T00:00:00Z", "stargazersCount": 3,
    }]).encode())
    result = AgentReachAdapter(process_runner=runner, github_token="test-only-token").research(
        ResearchRequest("search_github", query="agent"), timeout=4, max_bytes=5000,
    )
    assert result.ok and result.items[0].url == "https://github.com/a/repo"
    assert "--json" in runner.calls[0]["argv"]
    assert all(value not in runner.calls[0]["argv"] for value in ["--exec", "--shell"])


def test_missing_github_auth_fails_before_starting_a_process():
    runner = runner_for(b"[]")
    result = AgentReachAdapter(process_runner=runner).research(
        ResearchRequest("search_github", query="agent")
    )
    assert result.error_code == "authentication" and not runner.calls


@pytest.mark.parametrize("body", [
    {"content": []}, {"unrecognized": []}, {"unrecognized": {"empty": []}},
])
def test_unknown_empty_array_is_not_a_successful_search(body):
    result = AgentReachAdapter(process_runner=runner_for(json.dumps(body).encode())).research(
        ResearchRequest("search_web", query="safe")
    )
    assert result.error_code == "invalid_response"


def test_nested_mcp_error_is_not_successful_empty_results():
    body = {"result": {"isError": True, "structuredContent": {"results": []}}}
    result = AgentReachAdapter(process_runner=runner_for(json.dumps(body).encode())).research(
        ResearchRequest("search_web", query="safe")
    )
    assert result.error_code == "upstream_error"


def test_excessively_nested_provider_json_is_controlled():
    body = {"results": []}
    for _ in range(12):
        body = {"result": body}
    result = AgentReachAdapter(process_runner=runner_for(json.dumps(body).encode())).research(
        ResearchRequest("search_web", query="safe")
    )
    assert result.error_code == "invalid_response"


@pytest.mark.parametrize("body", [
    [], {"results": []},
    {"content": [{"type": "text", "text": '{"results": []}'}]},
])
def test_known_empty_search_result_succeeds(body):
    result = AgentReachAdapter(process_runner=runner_for(json.dumps(body).encode())).research(
        ResearchRequest("search_web", query="safe")
    )
    assert result.ok and not result.items


def test_webpage_uses_jina_fixed_proxy_and_original_citation_url():
    http = FakeHTTP()
    result = AgentReachAdapter(http_client=http).research(
        ResearchRequest("read_webpage", url="https://example.com/a?b=1"), timeout=4, max_bytes=5000,
    )
    assert result.ok and result.items[0].url == "https://example.com/a?b=1"
    assert http.calls[0][0] == "https://r.jina.ai/http://example.com/a?b=1"


def test_youtube_transcript_reads_only_bounded_caption_fixture(tmp_path: Path):
    def runner(**kwargs):
        output = Path(kwargs["argv"][kwargs["argv"].index("-o") + 1] + ".en.vtt")
        output.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n\n00:01.000 --> 00:02.000\nHello\nWorld", encoding="utf-8")
        return ProcessOutput(0, "", "")

    result = AgentReachAdapter(process_runner=runner).research(
        ResearchRequest("get_video_transcript", url="https://www.youtube.com/watch?v=abc"),
        timeout=4, max_bytes=5000,
    )
    assert result.ok and result.items[0].content == "Hello\nWorld"


def test_missing_process_and_timeout_are_controlled():
    def timed_out(**_kwargs):
        return ProcessOutput(-1, "", "", timed_out=True)

    result = AgentReachAdapter(process_runner=timed_out).research(
        ResearchRequest("search_web", query="x"), timeout=1, max_bytes=1024,
    )
    assert result.error_code == "timeout"

    def missing(**_kwargs):
        raise FileNotFoundError("mcporter")

    result = AgentReachAdapter(process_runner=missing).research(
        ResearchRequest("search_web", query="x"), timeout=1, max_bytes=1024,
    )
    assert result.error_code == "unavailable"


def test_fixed_process_does_not_inherit_secret_and_rejects_shell(tmp_path):
    observed = {}

    def inspect(**kwargs):
        observed.update(kwargs)
        return ProcessOutput(0, "ok", "")

    result = run_fixed_process(["safe-tool", "--", "--not-an-option"], timeout=1,
                               max_output_bytes=1024, cwd=tmp_path, runner=inspect)
    assert result.stdout == "ok"
    assert observed["shell"] is False
    assert "GEMINI_API_KEY" not in observed["env"]
    assert "LARK_APP_SECRET" not in observed["env"]
    assert observed["argv"][-1] == "--not-an-option"


def test_github_process_receives_only_explicit_research_token(tmp_path):
    observed = {}

    def inspect(**kwargs):
        observed.update(kwargs)
        return ProcessOutput(0, "ok", "")

    run_fixed_process(["gh", "search", "repos", "agent"], timeout=1,
                      max_output_bytes=1024, github_auth=True,
                      github_token="research-secret", runner=inspect)
    assert observed["env"]["GH_TOKEN"] == "research-secret"
    assert "GEMINI_API_KEY" not in observed["env"]


def test_github_process_preserves_only_github_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("GH_TOKEN", "github-secret")
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path / "gh-config"))
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    observed = {}

    def inspect(**kwargs):
        observed.update(kwargs)
        return ProcessOutput(0, "ok", "")

    run_fixed_process(["gh", "auth", "status"], timeout=1, max_output_bytes=1024,
                      github_auth=True, runner=inspect)
    assert "GH_TOKEN" not in observed["env"]
    assert observed["env"]["GH_CONFIG_DIR"] != str(tmp_path / "gh-config")
    assert "GEMINI_API_KEY" not in observed["env"]


def test_http_client_enforces_total_wall_clock_timeout(monkeypatch):
    client = FixedHttpClient()

    class SlowHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(0.3)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"late")

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            client.get(f"http://127.0.0.1:{server.server_port}", timeout=0.05, max_bytes=1024)
        assert time.monotonic() - started < 0.2
    finally:
        server.shutdown()
        server.server_close()


def test_fixed_process_marks_oversized_output():
    result = run_fixed_process(
        [sys.executable, "-c", "print('x' * 2000)"], timeout=5, max_output_bytes=1024,
    )
    assert result.output_limited
    assert len(result.stdout.encode()) <= 1024


@pytest.mark.parametrize("url", ["https://youtube.com.evil.example/video", "https://example.com/video"])
def test_video_host_is_allowlisted(url):
    result = AgentReachAdapter().research(ResearchRequest("get_video_transcript", url=url))
    assert result.error_code == "invalid_arguments"
