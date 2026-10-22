"""Deny-first gateway for external evidence, independent of ingestion and storage."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import replace

from .adapter import ResearchAdapter
from .models import (
    CAPABILITIES,
    ERROR_CODES,
    ResearchDocument,
    ResearchPolicy,
    ResearchRequest,
    ResearchResult,
    public_url,
)

logger = logging.getLogger(__name__)


class ResearchGateway:
    def __init__(self, adapter: ResearchAdapter | None = None, *,
                 policy: ResearchPolicy | None = None) -> None:
        self.policy = policy or ResearchPolicy()
        self._adapter = adapter
        self._slots = threading.BoundedSemaphore(self.policy.max_concurrency)

    @property
    def permissions(self) -> frozenset[str]:
        if not self.policy.enabled:
            return frozenset()
        return frozenset(f"research.{name}" for name in self.policy.capabilities)

    def research(self, request: ResearchRequest, *, principal_id: str = "",
                 permissions: frozenset[str] = frozenset()) -> ResearchResult:
        started = time.monotonic()
        capability = (request.capability if isinstance(request, ResearchRequest)
                      and isinstance(request.capability, str)
                      and request.capability in CAPABILITIES else "unknown")
        result = ResearchResult(capability, success=False, error_code="invalid_arguments")
        try:
            if not self.policy.enabled:
                result = replace(result, error_code="disabled")
            elif (not isinstance(principal_id, str) or not principal_id.strip()
                  or capability not in self.policy.capabilities
                  or f"research.{capability}" not in permissions):
                result = replace(result, error_code="permission_denied")
            else:
                result = self._execute(request)
        except Exception:
            result = replace(result, error_code="upstream_error")
        # Never include raw principal, query, URL, output, or exception in audit events.
        principal = (hashlib.sha256(principal_id.encode()).hexdigest()[:16]
                     if isinstance(principal_id, str) else "invalid")
        logger.info("research_call capability=%s principal=%s status=%s count=%d elapsed_ms=%d",
                    capability, principal, result.error_code or "ok", len(result.items),
                    int((time.monotonic() - started) * 1000))
        return result

    def _execute(self, request: ResearchRequest) -> ResearchResult:
        try:
            request = request.validated(max_results=self.policy.max_results)
        except (ValueError, TypeError):
            return ResearchResult(request.capability, success=False, error_code="invalid_arguments")
        if self._adapter is None:
            return ResearchResult(request.capability, success=False, error_code="unavailable")
        if not self._slots.acquire(blocking=False):
            return ResearchResult(request.capability, success=False, error_code="busy")
        try:
            result = self._adapter.research(request, timeout=self.policy.timeout_seconds,
                                            max_bytes=self.policy.max_response_bytes)
            return self._bound(result, request)
        except TimeoutError:
            return ResearchResult(request.capability, success=False, error_code="timeout")
        except Exception:
            return ResearchResult(request.capability, success=False, error_code="upstream_error")
        finally:
            self._slots.release()

    def _bound(self, result: ResearchResult, request: ResearchRequest) -> ResearchResult:
        if (not isinstance(result, ResearchResult) or result.capability != request.capability
                or not isinstance(result.items, tuple | list)):
            return ResearchResult(request.capability, success=False, error_code="invalid_response")
        if not result.ok:
            code = result.error_code if result.error_code in ERROR_CODES else "upstream_error"
            return ResearchResult(request.capability, success=False, error_code=code)
        remaining = self.policy.max_result_chars
        selected = []
        seen = set()
        truncated = result.truncated or len(result.items) > request.limit
        for item in result.items[:request.limit]:
            if not isinstance(item, ResearchDocument) or any(
                not isinstance(value, str) for value in (item.title, item.url, item.content, item.source)
            ):
                return ResearchResult(request.capability, success=False, error_code="invalid_response")
            try:
                url = public_url(item.url)
            except ValueError:
                truncated = True
                continue
            if url in seen:
                continue
            seen.add(url)
            title = item.title.strip()[:200] or url
            source = f"agent_reach:{request.capability}"
            overhead = len(title) + len(url) + len(source)
            if overhead >= remaining:
                truncated = True
                break
            content = item.content[:remaining - overhead]
            truncated |= len(content) != len(item.content)
            selected.append(ResearchDocument(title, url, content, source))
            remaining -= overhead + len(content)
        if result.items and not selected:
            return ResearchResult(request.capability, success=False, error_code="invalid_response")
        return ResearchResult(request.capability, tuple(selected), truncated=truncated)

    def search(self, query: str, *, source: str = "web", limit: int = 5,
               principal_id: str = "", permissions: frozenset[str] = frozenset()) -> ResearchResult:
        return self.research(ResearchRequest(f"search_{source}", query=query, limit=limit),
                             principal_id=principal_id, permissions=permissions)

    def fetch(self, url: str, *, kind: str = "webpage", principal_id: str = "",
              permissions: frozenset[str] = frozenset()) -> ResearchResult:
        capability = {"webpage": "read_webpage", "video": "get_video_transcript"}.get(kind, "")
        return self.research(ResearchRequest(capability, url=url),
                             principal_id=principal_id, permissions=permissions)
