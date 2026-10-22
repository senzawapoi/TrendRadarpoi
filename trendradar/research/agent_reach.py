"""Fixed, optional Agent-Reach upstream adapter.

The adapter maps a capability to one known read-only provider tool. Callers cannot
select executables, argv fragments, MCP servers, or provider configuration.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlsplit

from .adapter import ResearchAdapter
from .models import ResearchDocument, ResearchRequest, ResearchResult, public_url
from .transport import FixedHttpClient, ProcessOutput, json_object, run_fixed_process

_PUBLIC_REDDIT_HOSTS = {"reddit.com", "www.reddit.com", "old.reddit.com"}
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


class _InvalidResponseError(ValueError):
    """Provider returned a non-empty payload outside its documented shape."""


class _OutputLimitError(ValueError):
    """The provider exceeded the bounded response budget."""


class _ProviderError(RuntimeError):
    """A provider failure with a safe, non-sensitive result code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class AgentReachAdapter(ResearchAdapter):
    """Use installed optional tools only; absence is a normal controlled failure."""

    def __init__(
        self, *, process_runner: Callable[..., ProcessOutput] = run_fixed_process,
        http_client: FixedHttpClient | None = None,
        github_token: str | None = None,
    ) -> None:
        self._run = process_runner
        self._http = http_client or FixedHttpClient()
        self._github_token = github_token

    def research(self, request: ResearchRequest, *, timeout: float = 15,
                 max_bytes: int = 262_144) -> ResearchResult:
        try:
            request = request.validated(max_results=request.limit)
        except (TypeError, ValueError):
            return ResearchResult(request.capability, success=False, error_code="invalid_arguments")
        try:
            if request.capability == "search_web":
                return self._search_exa(request, timeout=timeout, max_bytes=max_bytes)
            if request.capability == "search_reddit":
                return self._search_exa(request, timeout=timeout, max_bytes=max_bytes, reddit_only=True)
            if request.capability == "search_github":
                return self._search_github(request, timeout=timeout, max_bytes=max_bytes)
            if request.capability == "read_webpage":
                return self._read_webpage(request, timeout=timeout, max_bytes=max_bytes)
            if request.capability == "get_video_transcript":
                return self._video_transcript(request, timeout=timeout, max_bytes=max_bytes)
        except TimeoutError:
            return ResearchResult(request.capability, success=False, error_code="timeout")
        except (_InvalidResponseError, RecursionError):
            return ResearchResult(request.capability, success=False, error_code="invalid_response")
        except _OutputLimitError:
            return ResearchResult(request.capability, success=False, error_code="output_limit")
        except _ProviderError as exc:
            return ResearchResult(request.capability, success=False, error_code=exc.code)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
            return ResearchResult(request.capability, success=False, error_code="unavailable")
        return ResearchResult(request.capability, success=False, error_code="invalid_arguments")

    def _run_tool(self, argv: list[str], *, timeout: float, max_bytes: int) -> ProcessOutput:
        kwargs = {"argv": argv, "timeout": timeout, "max_output_bytes": max_bytes}
        if argv and argv[0] == "gh":
            kwargs["github_auth"] = True
            if self._github_token is not None:
                kwargs["github_token"] = self._github_token
        result = self._run(**kwargs)
        if result.timed_out:
            raise TimeoutError("research command timed out")
        if result.output_limited:
            raise _OutputLimitError("research command output too large")
        if len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8")) > max_bytes:
            raise _OutputLimitError("research command output too large")
        if result.returncode != 0:
            stderr = result.stderr.lower()
            if any(marker in stderr for marker in ("rate limit", "rate_limit", "secondary rate")):
                raise _ProviderError("rate_limited")
            if any(marker in stderr for marker in (
                "authentication", "unauthorized", "not logged in", "bad credentials",
                "authentication required",
            )):
                raise _ProviderError("authentication")
            raise _ProviderError("unavailable")
        return result

    def _search_exa(self, request: ResearchRequest, *, timeout: float,
                    max_bytes: int, reddit_only: bool = False) -> ResearchResult:
        query = f"site:reddit.com {request.query}" if reddit_only else request.query
        args = json.dumps({"query": query, "numResults": request.limit}, ensure_ascii=False)
        # Agent-Reach documents Exa as a fixed public MCP endpoint. An isolated
        # config avoids importing the user's unrelated MCP servers or credentials.
        with tempfile.TemporaryDirectory(prefix="trendradar-exa-") as directory:
            config_path = Path(directory) / "mcporter.json"
            config_path.write_text(
                json.dumps({
                    "mcpServers": {"exa": {"baseUrl": "https://mcp.exa.ai/mcp"}},
                    "imports": [],
                }),
                encoding="utf-8",
            )
            result = self._run_tool(
                ["mcporter", "--config", str(config_path), "call", "exa.web_search_exa",
                 "--args", args, "--output", "json"],
                timeout=timeout, max_bytes=max_bytes,
            )
        payload = None
        try:
            payload = json_object(result.stdout)
        except ValueError:
            if not result.stdout.strip():
                raise _InvalidResponseError("empty Exa response") from None
            documents = self._documents_from_mcp_text(result.stdout, request.capability)
        else:
            _validate_payload_bounds(payload)
            if isinstance(payload, Mapping) and _is_error_envelope(payload):
                raise _ProviderError("upstream_error")
            documents = self._documents_from_json(payload, request.capability)
            if not documents and isinstance(payload, Mapping):
                documents = self._documents_from_mcp_envelope(payload, request.capability)
            if isinstance(payload, Mapping) and _is_error_envelope(payload):
                raise _ProviderError("upstream_error")
        found_shape, has_results = _result_shape_state(payload)
        if not documents and result.stdout.strip() and not (found_shape and not has_results):
            raise _InvalidResponseError("invalid Exa response")
        if reddit_only:
            documents = tuple(item for item in documents if urlsplit(item.url).hostname in _PUBLIC_REDDIT_HOSTS)
        return ResearchResult(
            request.capability, documents[:request.limit], truncated=len(documents) > request.limit
        )

    def _search_github(self, request: ResearchRequest, *, timeout: float,
                       max_bytes: int) -> ResearchResult:
        if not self._github_token or not self._github_token.strip():
            raise _ProviderError("authentication")
        query = f"{request.query} is:public"
        result = self._run_tool(
            ["gh", "search", "repos", query, "--limit", str(request.limit),
             "--json", "name,description,url,updatedAt,stargazersCount"],
            timeout=timeout, max_bytes=max_bytes,
        )
        payload = json_object(result.stdout)
        if not isinstance(payload, list):
            raise ValueError("invalid GitHub response")
        documents = []
        for item in payload[:request.limit]:
            if not isinstance(item, Mapping) or not isinstance(item.get("url"), str):
                continue
            url = item["url"]
            if urlsplit(url).hostname not in {"github.com", "www.github.com"}:
                continue
            documents.append(ResearchDocument(
                str(item.get("name") or url)[:200], public_url(url),
                str(item.get("description") or "")[:3000], "agent-reach:search_github",
            ))
        return ResearchResult(request.capability, tuple(documents))

    def _read_webpage(self, request: ResearchRequest, *, timeout: float,
                      max_bytes: int) -> ResearchResult:
        url = public_url(request.url)
        proxy = "https://r.jina.ai/http://" + urlsplit(url).netloc + urlsplit(url).path
        if urlsplit(url).query:
            proxy += "?" + urlsplit(url).query
        content = self._http.get(proxy, timeout=timeout, max_bytes=max_bytes).decode("utf-8", errors="replace")
        if not content.strip():
            raise ValueError("empty webpage")
        title = next((line.strip("# \t") for line in content.splitlines() if line.strip()), url)
        return ResearchResult(request.capability, (ResearchDocument(title[:200], url, content, "jina"),))

    def _video_transcript(self, request: ResearchRequest, *, timeout: float,
                          max_bytes: int) -> ResearchResult:
        url = public_url(request.url)
        if urlsplit(url).hostname not in _YOUTUBE_HOSTS:
            return ResearchResult(request.capability, success=False, error_code="invalid_arguments")
        with tempfile.TemporaryDirectory(prefix="trendradar-captions-") as directory:
            output = str(Path(directory) / "caption")
            self._run_tool(
                ["yt-dlp", "--ignore-config", "--no-cache-dir", "--no-playlist", "--skip-download",
                 "--write-sub", "--write-auto-sub", "--sub-langs", "en,zh-Hans,zh,ja",
                 "--max-filesize", str(max_bytes), "-o", output, url],
                timeout=timeout, max_bytes=max_bytes,
            )
            files = tuple(Path(directory).glob("caption*.vtt"))
            if not files:
                return ResearchResult(request.capability, success=False, error_code="unavailable")
            content = files[0].read_text(encoding="utf-8", errors="replace")
            content = _clean_vtt(content)
            if not content:
                return ResearchResult(request.capability, success=False, error_code="unavailable")
            return ResearchResult(request.capability, (ResearchDocument(
                "YouTube transcript", url, content[:max_bytes], "yt-dlp",
            ),))

    @staticmethod
    def _documents_from_json(payload: object, source: str) -> tuple[ResearchDocument, ...]:
        candidates = payload if isinstance(payload, list) else _find_result_lists(payload)
        documents = []
        for item in candidates:
            if not isinstance(item, Mapping):
                continue
            url = item.get("url") or item.get("link")
            if not isinstance(url, str):
                continue
            try:
                normalized = public_url(url)
            except ValueError:
                continue
            title = str(item.get("title") or item.get("name") or normalized)[:200]
            content = str(item.get("text") or item.get("snippet") or item.get("description") or "")[:3000]
            documents.append(ResearchDocument(title, normalized, content, source))
        return tuple(documents)

    @staticmethod
    def _documents_from_mcp_text(value: str, source: str) -> tuple[ResearchDocument, ...]:
        """Parse mcporter text output while rejecting prose/error envelopes."""
        documents = []
        blocks = [block.strip() for block in re.split(r"\n\s*---\s*\n", value) if block.strip()]
        for block in blocks:
            try:
                structured = json.loads(block)
            except (TypeError, ValueError):
                structured = None
            if structured is not None:
                _validate_payload_bounds(structured)
                if isinstance(structured, Mapping) and _is_error_envelope(structured):
                    raise _ProviderError("upstream_error")
                parsed = AgentReachAdapter._documents_from_json(structured, source)
                documents.extend(parsed)
                if parsed or _result_shape_state(structured)[0]:
                    continue
            fields: dict[str, str] = {}
            current = ""
            for line in block.splitlines():
                match = re.match(r"^(Title|URL|Published|Author|Highlights|Text):\s*(.*)$", line)
                if match:
                    current = match.group(1).lower()
                    fields[current] = match.group(2).strip()
                elif current in {"highlights", "text"} and line.strip():
                    fields[current] += " " + line.strip()
            url = fields.get("url", "")
            if not url:
                continue
            try:
                normalized = public_url(url)
            except ValueError:
                continue
            title = fields.get("title") or normalized
            content = fields.get("highlights") or fields.get("text") or ""
            documents.append(ResearchDocument(title[:200], normalized, content[:3000], source))
        return tuple(documents)

    @staticmethod
    def _documents_from_mcp_envelope(
        payload: Mapping[str, object], source: str
    ) -> tuple[ResearchDocument, ...]:
        texts = _mcp_texts(payload)
        return AgentReachAdapter._documents_from_mcp_text("\n---\n".join(texts), source)


def _find_result_lists(payload: object) -> list[object]:
    if isinstance(payload, Mapping):
        for key in ("results", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        for value in payload.values():
            found = _find_result_lists(value)
            if found:
                return found
    return []


def _validate_payload_bounds(payload: object) -> None:
    pending = [(payload, 0)]
    nodes = 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if depth > 8 or nodes > 2048:
            raise _InvalidResponseError("provider structure exceeds bounds")
        if isinstance(value, Mapping):
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            if len(value) > 100:
                raise _InvalidResponseError("provider list exceeds bounds")
            pending.extend((child, depth + 1) for child in value)


def _result_shape_state(payload: object) -> tuple[bool, bool]:
    """Return (has result-list shape, has non-empty result-list)."""
    if isinstance(payload, list):
        return True, bool(payload)
    if isinstance(payload, Mapping):
        found = False
        has_results = False
        for key in ("results", "items", "data"):
            if isinstance(payload.get(key), list):
                found = True
                has_results = has_results or bool(payload[key])
        for value in payload.values():
            if isinstance(value, Mapping):
                child_found, child_results = _result_shape_state(value)
                found = found or child_found
                has_results = has_results or child_results
        for text in _mcp_texts(payload):
            try:
                value = json.loads(text)
            except (TypeError, ValueError):
                continue
            _validate_payload_bounds(value)
            child_found, child_results = _result_shape_state(value)
            found = found or child_found
            has_results = has_results or child_results
        return found, has_results
    return False, False


def _is_error_envelope(payload: Mapping[str, object]) -> bool:
    if payload.get("isError") is True:
        return True
    for key in ("error", "errorCode", "error_code", "exception"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, Mapping) and value:
            return True
    for key in ("result", "structuredContent", "data"):
        child = payload.get(key)
        if isinstance(child, Mapping) and _is_error_envelope(child):
            return True
    for text in _mcp_texts(payload):
        try:
            child = json.loads(text)
        except (TypeError, ValueError):
            continue
        _validate_payload_bounds(child)
        if isinstance(child, Mapping) and _is_error_envelope(child):
            return True
    return False


def _mcp_texts(payload: object) -> list[str]:
    if isinstance(payload, Mapping):
        result = []
        if isinstance(payload.get("text"), str):
            result.append(payload["text"])
        content = payload.get("content")
        if isinstance(content, list):
            result.extend(text for item in content for text in _mcp_texts(item))
        for key, value in payload.items():
            if key not in {"text", "content"}:
                result.extend(_mcp_texts(value))
        return result
    if isinstance(payload, list):
        return [text for item in payload for text in _mcp_texts(item)]
    return []


def _clean_vtt(value: str) -> str:
    lines = []
    seen = set()
    for raw in value.splitlines():
        line = raw.strip()
        if (not line or line == "WEBVTT" or line.startswith("NOTE")
                or re.fullmatch(r"\d{2}:\d{2}\.\d{3} --> .*", line)
                or line.isdigit()):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        if line and line not in seen:
            seen.add(line)
            lines.append(line)
    return "\n".join(lines)


__all__ = ["AgentReachAdapter"]
