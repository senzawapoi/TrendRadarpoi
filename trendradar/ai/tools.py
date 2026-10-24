"""Deny-by-default local tools for the Phase 4 Assistant.

The registry is intentionally boring: every exposed capability is declared in
this module and points at a known handler.  Configuration can disable a tool,
but it cannot create a handler or import a module.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any
from uuid import UUID

from trendradar.ai.client import GeminiToolDefinition
from trendradar.ai.models import Citation, TimeRange
from trendradar.ai.retrieval import LocalRetriever, content_item_citation
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.research.gateway import ResearchGateway
from trendradar.research.models import ERROR_CODES as RESEARCH_ERROR_CODES
from trendradar.research.models import ResearchRequest

MAX_TOOL_RESULT_CHARS = 4_000
MAX_TOOL_ARGUMENT_CHARS = 8_000
MAX_TOOL_RANGE_DAYS = 3650
_PERMISSION_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_LOGGER = logging.getLogger(__name__)
_SEARCH_TOOLS = frozenset({"search_stories", "search_content_items"})
_TIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?"
    r"(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
)
_HANDLER_ERROR_CODES = RESEARCH_ERROR_CODES | {
    "research_unavailable", "handler_failed", "handler_denied", "tool_disabled", "unknown_tool",
}
_DENIAL_CODES = frozenset({
    "permission_denied", "disabled", "tool_disabled", "unknown_tool", "handler_denied",
    "authentication",
})
_ARGUMENT_DETAILS = {
    "schema_mismatch": "Use the declared argument types, fields and limits.",
    "range_pair_required": "Supply time_range with both start and end, or omit it entirely.",
    "range_conflict": "Do not combine time_range with legacy start/end.",
    "invalid_time": "Use valid ISO 8601 timestamps with an explicit timezone.",
    "range_order": "time_range.start must be before time_range.end.",
    "range_too_wide": f"The time range must not exceed {MAX_TOOL_RANGE_DAYS} days.",
}


class ToolError(RuntimeError):
    """Base class for safe, transport-neutral tool failures."""


class ToolDeniedError(ToolError):
    """A request was rejected before its handler was invoked."""


class ToolValidationError(ToolDeniedError):
    """Tool arguments do not match the registered exact schema."""

    def __init__(self, message: str = "", *, code: str = "schema_mismatch") -> None:
        super().__init__(message)
        self.code = code if code in _ARGUMENT_DETAILS else "schema_mismatch"


class ToolPermissionError(ToolDeniedError):
    """The caller does not hold the tool's named permission."""


class ToolExecutionError(ToolError):
    """A known handler failed; the raw exception is never exposed."""


def _bounded_text(value: Any, *, maximum: int, field_name: str) -> str:
    if not isinstance(value, str):
        raise ToolValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ToolValidationError(f"{field_name} exceeds its limit")
    return normalized


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ToolValidationError(code="invalid_time")
    return value.astimezone(timezone.utc)


def _parse_time(value: Any, field_name: str) -> datetime:
    text = _bounded_text(value, maximum=80, field_name=field_name)
    if not _TIME_RE.fullmatch(text):
        raise ToolValidationError(code="invalid_time")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return _utc(parsed, field_name)
    except (ValueError, OverflowError) as exc:
        raise ToolValidationError(code="invalid_time") from exc


def _parse_uuid(value: Any, field_name: str) -> str:
    text = _bounded_text(value, maximum=64, field_name=field_name)
    try:
        return str(UUID(text))
    except ValueError as exc:
        raise ToolValidationError(f"{field_name} is invalid") from exc


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise ValueError("tool schema contains a non-JSON value")


def _serialize(value: Any, *, maximum: int = MAX_TOOL_RESULT_CHARS) -> str:
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 32:
        raise ValueError("maximum must be an integer of at least 32")
    maximum = min(MAX_TOOL_RESULT_CHARS, maximum)
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        rendered = json.dumps({"error": "tool result is not serializable"})
    if len(rendered) <= maximum:
        return rendered

    # A raw string slice is not valid JSON. Keep a bounded preview in a valid
    # envelope so provider adapters can always decode a tool result.
    low = 0
    high = min(len(rendered), maximum)
    best = json.dumps({"truncated": True}, separators=(",", ":"))
    while low <= high:
        midpoint = (low + high) // 2
        candidate = json.dumps(
            {"preview": rendered[:midpoint], "truncated": True},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(candidate) <= maximum:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best


def _validate_value(schema: Mapping[str, Any], value: Any, field_name: str) -> Any:
    expected = schema.get("type")
    if expected not in {"object", "array", "string", "integer", "number", "boolean"}:
        raise ToolValidationError("registered schema is invalid")

    if expected == "object":
        if not isinstance(value, Mapping):
            raise ToolValidationError(f"{field_name} has the wrong type")
        if any(not isinstance(key, str) for key in value):
            raise ToolValidationError(f"{field_name} has a non-string key")
        properties = schema.get("properties", {})
        required = schema.get("required", ())
        if not isinstance(properties, Mapping) or not (
            isinstance(required, Sequence) and not isinstance(required, str | bytes)
        ):
            raise ToolValidationError("registered schema is invalid")
        required_names = set(required)
        if any(not isinstance(name, str) for name in required_names):
            raise ToolValidationError("registered schema is invalid")
        unknown = set(value) - set(properties)
        if unknown and schema.get("additionalProperties", True) is False:
            raise ToolValidationError("unknown tool argument")
        missing = required_names - set(value)
        if missing:
            raise ToolValidationError("required tool argument is missing")
        normalized: dict[str, Any] = {}
        for name, item in value.items():
            definition = properties.get(name)
            if not isinstance(definition, Mapping):
                raise ToolValidationError("registered schema is invalid")
            normalized[name] = _validate_value(definition, item, f"{field_name}.{name}")
        return normalized

    if expected == "array":
        if isinstance(value, str | bytes) or not isinstance(value, list | tuple):
            raise ToolValidationError(f"{field_name} has the wrong type")
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if minimum is not None and len(value) < int(minimum):
            raise ToolValidationError(f"{field_name} is too short")
        if maximum is not None and len(value) > int(maximum):
            raise ToolValidationError(f"{field_name} is too long")
        item_schema = schema.get("items")
        if not isinstance(item_schema, Mapping):
            raise ToolValidationError("registered schema is invalid")
        return [
            _validate_value(item_schema, item, f"{field_name}[{index}]")
            for index, item in enumerate(value)
        ]

    if expected == "string":
        normalized = _bounded_text(value, maximum=MAX_TOOL_ARGUMENT_CHARS, field_name=field_name)
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if minimum is not None and len(normalized) < int(minimum):
            raise ToolValidationError(f"{field_name} is too short")
        if maximum is not None and len(normalized) > int(maximum):
            raise ToolValidationError(f"{field_name} is too long")
        enum = schema.get("enum")
        if enum is not None:
            if isinstance(enum, str | bytes) or not isinstance(enum, Sequence):
                raise ToolValidationError("registered schema is invalid")
            if normalized not in enum:
                raise ToolValidationError(f"{field_name} has an unsupported value")
        return normalized

    if expected == "boolean":
        if not isinstance(value, bool):
            raise ToolValidationError(f"{field_name} has the wrong type")
        return value

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ToolValidationError(f"{field_name} has the wrong type")
    if expected == "integer" and not isinstance(value, int):
        raise ToolValidationError(f"{field_name} has the wrong type")
    if not math.isfinite(float(value)):
        raise ToolValidationError(f"{field_name} must be finite")
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if minimum is not None and value < minimum:
        raise ToolValidationError(f"{field_name} is below its limit")
    if maximum is not None and value > maximum:
        raise ToolValidationError(f"{field_name} exceeds its limit")
    enum = schema.get("enum")
    if enum is not None and value not in enum:
        raise ToolValidationError(f"{field_name} has an unsupported value")
    return value


def validate_arguments(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a small JSON-schema subset with closed object properties."""
    if not isinstance(arguments, Mapping):
        raise ToolValidationError("arguments must be an object")
    try:
        rendered = json.dumps(arguments, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        raise ToolValidationError("arguments are not serializable") from exc
    if len(rendered) > MAX_TOOL_ARGUMENT_CHARS:
        raise ToolValidationError("arguments exceed their limit")
    normalized = _validate_value(schema, arguments, "arguments")
    if not isinstance(normalized, dict):
        raise ToolValidationError("registered schema is invalid")
    return normalized


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Explicit capabilities and local dependencies available to a handler."""

    principal_id: str
    retriever: LocalRetriever
    time_range: TimeRange
    storage: IntelligenceStorage | None = None
    research_gateway: ResearchGateway | None = None
    permissions: frozenset[str] = frozenset()
    enabled_tools: frozenset[str] | None = None
    max_result_chars: int = MAX_TOOL_RESULT_CHARS

    def __post_init__(self) -> None:
        if not isinstance(self.principal_id, str) or not self.principal_id.strip():
            raise ValueError("principal_id is required")
        if not isinstance(self.retriever, LocalRetriever) and not callable(
            getattr(self.retriever, "retrieve", None)
        ):
            raise ValueError("retriever must provide retrieve()")
        if not isinstance(self.time_range, TimeRange):
            raise ValueError("time_range must be a TimeRange")
        if self.storage is not None and not isinstance(self.storage, IntelligenceStorage):
            raise ValueError("storage must be IntelligenceStorage")
        permissions = frozenset(str(value).strip() for value in self.permissions if str(value).strip())
        if any(not _PERMISSION_RE.fullmatch(value) for value in permissions):
            raise ValueError("invalid permission name")
        object.__setattr__(self, "permissions", permissions)
        if self.enabled_tools is not None:
            object.__setattr__(
                self,
                "enabled_tools",
                frozenset(str(value).strip() for value in self.enabled_tools if str(value).strip()),
            )
        if isinstance(self.max_result_chars, bool) or not isinstance(self.max_result_chars, int):
            raise ValueError("max_result_chars must be an integer")
        object.__setattr__(
            self,
            "max_result_chars",
            max(256, min(MAX_TOOL_RESULT_CHARS, self.max_result_chars)),
        )


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Normalized result returned to the Assistant loop."""

    name: str
    allowed: bool
    success: bool
    text: str
    citations: tuple[Citation, ...] = ()
    error_code: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _bounded_text(self.name, maximum=128, field_name="name"))
        object.__setattr__(self, "text", _bounded_text(self.text, maximum=MAX_TOOL_RESULT_CHARS, field_name="text"))
        citations = tuple(self.citations)
        if any(not isinstance(item, Citation) for item in citations):
            raise ValueError("citations must contain Citation values")
        object.__setattr__(self, "citations", citations)
        if self.error_code:
            object.__setattr__(self, "error_code", _bounded_text(self.error_code, maximum=128, field_name="error_code"))

    @property
    def ok(self) -> bool:
        return self.allowed and self.success

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "allowed": self.allowed,
            "success": self.success,
            "text": self.text,
            "citations": [citation.to_dict() for citation in self.citations],
            "error_code": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Immutable declaration for one statically registered capability."""

    name: str
    description: str
    parameters: Mapping[str, Any]
    permission: str
    handler: Callable[[ToolContext, Mapping[str, Any]], ToolResult]
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _bounded_text(self.name, maximum=128, field_name="name"))
        object.__setattr__(self, "description", _bounded_text(self.description, maximum=2_000, field_name="description"))
        if not isinstance(self.parameters, Mapping):
            raise ValueError("parameters must be a mapping")
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        if not isinstance(self.permission, str) or not _PERMISSION_RE.fullmatch(self.permission):
            raise ValueError("permission is invalid")
        if not callable(self.handler):
            raise ValueError("handler must be callable")

    @property
    def input_schema(self) -> Mapping[str, Any]:
        return self.parameters

    def definition(self) -> GeminiToolDefinition:
        return GeminiToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )


def _context_range(arguments: Mapping[str, Any], context: ToolContext) -> TimeRange:
    normalized = _normalize_search_range(arguments)
    if "time_range" not in normalized:
        interval = context.time_range
    else:
        raw_range = normalized["time_range"]
        if not isinstance(raw_range, Mapping) or set(raw_range) != {"start", "end"}:
            raise ToolValidationError(code="range_pair_required")
        start = _parse_time(raw_range["start"], "start")
        end = _parse_time(raw_range["end"], "end")
        if start >= end:
            raise ToolValidationError(code="range_order")
        interval = TimeRange(start, end)
    if interval.end - interval.start > timedelta(days=MAX_TOOL_RANGE_DAYS):
        raise ToolValidationError(code="range_too_wide")
    return interval


def _normalize_search_range(arguments: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, Mapping):
        raise ToolValidationError("arguments must be an object")
    normalized = dict(arguments)
    if "start" in normalized or "end" in normalized:
        if "time_range" in normalized:
            raise ToolValidationError(code="range_conflict")
        if "start" not in normalized or "end" not in normalized:
            raise ToolValidationError(code="range_pair_required")
        normalized["time_range"] = {
            "start": normalized.pop("start"), "end": normalized.pop("end"),
        }
    return normalized


def tool_argument_shape(arguments: Any) -> str:
    """Audit field presence using fixed labels, without rendering any arguments."""
    if not isinstance(arguments, Mapping):
        return "invalid"
    start, end = "start" in arguments, "end" in arguments
    if "time_range" in arguments:
        return "mixed" if start or end else "nested"
    if start and end:
        return "legacy"
    if start:
        return "start-only"
    return "end-only" if end else "default"


def search_recovery_matches(
    failed: Mapping[str, Any], corrected: Mapping[str, Any], context: ToolContext,
) -> bool:
    """Require the same search and preserve every valid originally supplied bound."""
    for field_name, default in (("query", ""), ("domain", None)):
        before, after = failed.get(field_name, default), corrected.get(field_name, default)
        if isinstance(before, str) and isinstance(after, str):
            before, after = before.strip(), after.strip()
        if before != after or (before is not None and not isinstance(before, str)):
            return False
    try:
        interval = _context_range(corrected, context)
        old_range = failed.get("time_range", failed)
        if not isinstance(old_range, Mapping):
            return False
        has_range = "time_range" in failed or "start" in failed or "end" in failed
        if has_range and not any(key in corrected for key in ("time_range", "start", "end")):
            return False
        if not has_range:
            return interval == context.time_range
        if "time_range" in failed and ("start" in failed or "end" in failed):
            return False  # Conflicting representations leave the original need ambiguous.
        for field_name in ("start", "end"):
            if field_name in old_range:
                try:
                    original = _parse_time(old_range[field_name], field_name)
                except ToolValidationError:
                    continue
                if original != getattr(interval, field_name):
                    return False
    except ToolValidationError:
        return False
    return True


def _search_stories(context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
    interval = _context_range(arguments, context)
    query = str(arguments.get("query", ""))
    limit = int(arguments.get("limit", 20))
    domain = arguments.get("domain")
    result = context.retriever.retrieve(
        query,
        time_range=interval,
        domain=str(domain) if domain is not None else None,
    )
    # Keep the tool payload focused; the full immutable citations stay in the
    # normalized result for Assistant-side validation.
    citable_story_ids = {
        citation.story_id
        for citation in result.citations
        if citation.ref.startswith("story:") and citation.story_id is not None
    }
    selected = tuple(
        bundle for bundle in result.stories if bundle.story.id in citable_story_ids
    )[:limit]
    story_ids = {bundle.story.id for bundle in selected}
    citations = tuple(
        citation for citation in result.citations if citation.story_id in story_ids
    )
    payload = {
        "time_range": interval.to_dict(),
        "stories": [
            {
                "id": bundle.story.id,
                "title": bundle.story.title,
                "summary": bundle.story.summary[:500],
                "importance": bundle.story.importance.score,
                "citation_ref": f"story:{bundle.story.id}",
            }
            for bundle in selected
        ],
        "truncation": result.truncation.to_dict(),
    }
    return ToolResult(
        "search_stories",
        True,
        True,
        _serialize(payload, maximum=context.max_result_chars),
        citations,
    )


def _search_content_items(context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
    interval = _context_range(arguments, context)
    query = str(arguments.get("query", ""))
    limit = int(arguments.get("limit", 20))
    domain = arguments.get("domain")
    storage = context.storage or context.retriever.storage
    items = storage.search_content_items(
        query,
        start=interval.start,
        end=interval.end,
        domain=str(domain) if domain is not None else None,
        limit=limit + 1,
    )
    effective_limit = min(limit, context.retriever.limits.max_citations)
    truncated = len(items) > effective_limit
    selected = items[:effective_limit]
    citations = tuple(
        content_item_citation(item)
        for item in selected
    )
    payload = {
        "time_range": interval.to_dict(),
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "event_time": (item.published_time or item.collected_at).isoformat(),
                "citation_ref": f"item:{item.id}",
            }
            for item in selected
        ],
        "truncation": {"items": truncated},
    }
    return ToolResult(
        "search_content_items",
        True,
        True,
        _serialize(payload, maximum=context.max_result_chars),
        citations,
    )


def _story_evidence(context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
    story_id = _parse_uuid(arguments["story_id"], "story_id")
    result = context.retriever.retrieve_story_evidence(
        story_id,
        time_range=context.time_range,
    )
    if not result.stories:
        return ToolResult("get_story_evidence", True, True, _serialize({"story": None}), ())
    bundle = result.stories[0]
    story = bundle.story
    payload = {
        "story": {
            "id": story.id,
            "title": story.title,
            "summary": story.summary[:800],
            "importance": story.importance.to_dict(),
        },
        "members": [
            {"id": item.id, "title": item.title, "url": item.url, "source": item.source}
            for item in bundle.members
        ],
        "observations": [
            {
                "id": int(row["id"]),
                "source": str(row["source"]),
                "title": str(row["title"]),
                "url": str(row["url"] or ""),
            }
            for row in bundle.observations
        ],
        "truncation": result.truncation.to_dict(),
    }
    return ToolResult(
        "get_story_evidence",
        True,
        True,
        _serialize(payload, maximum=context.max_result_chars),
        result.citations,
    )


def _research_tool(context: ToolContext, arguments: Mapping[str, Any]) -> ToolResult:
    gateway = context.research_gateway
    capability = str(arguments["capability"])
    if gateway is None:
        return ToolResult(
            "research_external", True, False,
            _serialize({"ok": False, "error": "research_unavailable"}),
            error_code="research_unavailable",
        )
    request = ResearchRequest(
        capability,
        query=str(arguments.get("query", "")),
        url=str(arguments.get("url", "")),
        limit=int(arguments.get("limit", 5)),
    )
    outcome = gateway.research(
        request,
        principal_id=context.principal_id,
        permissions=context.permissions,
    )
    if not outcome.ok:
        return ToolResult(
            "research_external", True, False,
            _serialize({"ok": False, "error": outcome.error_code}),
            error_code=outcome.error_code,
        )
    citations = []
    items = []
    for item in outcome.items:
        ref = "research:" + hashlib.sha256(
            f"{capability}\n{item.url}\n{item.title}".encode()
        ).hexdigest()[:40]
        citations.append(Citation(
            ref=ref,
            title=item.title,
            source=item.source,
            url=item.url,
            observed_at=datetime.now(timezone.utc),
            snapshot={"external": True, "untrusted": True, "capability": capability},
        ))
        items.append({
            "title": item.title,
            "url": item.url,
            "content": item.content[:800],
            "source": item.source,
            "citation_ref": ref,
        })
    return ToolResult(
        "research_external", True, True,
        _serialize({"ok": True, "capability": capability, "items": items,
                    "truncated": outcome.truncated}, maximum=context.max_result_chars),
        tuple(citations),
    )


def _default_specs() -> tuple[ToolSpec, ...]:
    search_properties = {
        "query": {"type": "string", "maxLength": 500},
        "time_range": {
            "type": "object",
            "description": (
                "Optional complete range; omit to use the server range. Both timestamps "
                f"need explicit timezones, start < end, at most {MAX_TOOL_RANGE_DAYS} days."
            ),
            "properties": {
                "start": {"type": "string", "minLength": 1, "maxLength": 80},
                "end": {"type": "string", "minLength": 1, "maxLength": 80},
            },
            "required": ["start", "end"],
            "additionalProperties": False,
        },
        "domain": {"type": "string", "enum": ["general", "ai", "security"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    }
    specs = [
        ToolSpec(
            name="search_stories",
            description="Search local Stories in the supplied UTC time range.",
            parameters={
                "type": "object",
                "properties": search_properties,
                "required": [],
                "additionalProperties": False,
            },
            permission="intelligence.read",
            handler=_search_stories,
        ),
        ToolSpec(
            name="search_content_items",
            description="Search local canonical ContentItems in the supplied UTC time range.",
            parameters={
                "type": "object",
                "properties": search_properties,
                "required": [],
                "additionalProperties": False,
            },
            permission="intelligence.read",
            handler=_search_content_items,
        ),
        ToolSpec(
            name="get_story_evidence",
            description="Read bounded members and source observations for one local Story.",
            parameters={
                "type": "object",
                "properties": {"story_id": {"type": "string", "minLength": 1, "maxLength": 64}},
                "required": ["story_id"],
                "additionalProperties": False,
            },
            permission="intelligence.evidence",
            handler=_story_evidence,
        ),
    ]
    research_schema = {
        "type": "object",
        "properties": {
            "capability": {"type": "string", "enum": [
                "search_web", "search_github", "search_reddit",
                "read_webpage", "get_video_transcript",
            ]},
            "query": {"type": "string", "maxLength": 500},
            "url": {"type": "string", "maxLength": 2048},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        "required": ["capability"],
        "additionalProperties": False,
    }
    specs.append(ToolSpec(
        name="research_external",
        description="Use one bounded external research capability when local evidence is insufficient.",
        parameters=research_schema,
        permission="research.external",
        handler=_research_tool,
        enabled=False,
    ))
    return tuple(specs)


class ToolRegistry:
    """Static registry with validation and authorization before invocation."""

    def __init__(self, specs: Sequence[ToolSpec] | None = None, *, enabled: Mapping[str, bool] | None = None) -> None:
        selected = tuple(specs or _default_specs())
        names = [spec.name for spec in selected]
        if len(names) != len(set(names)):
            raise ValueError("duplicate tool name")
        gates = enabled if isinstance(enabled, Mapping) else {}
        self._specs = {
            spec.name: ToolSpec(
                name=spec.name,
                description=spec.description,
                parameters=spec.parameters,
                permission=spec.permission,
                handler=spec.handler,
                enabled=bool(gates.get(spec.name, spec.enabled)),
            )
            for spec in selected
        }

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs[name] for name in sorted(self._specs))

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._specs)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def definitions(self, *, context: ToolContext | None = None) -> tuple[GeminiToolDefinition, ...]:
        return tuple(
            spec.definition()
            for spec in self.specs
            if spec.enabled
            and (
                context is None
                or (
                    spec.permission in context.permissions
                    and (
                        context.enabled_tools is None
                        or spec.name in context.enabled_tools
                    )
                )
            )
        )

    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        shape = tool_argument_shape(arguments)
        if not isinstance(name, str) or not name.strip():
            return self._denial("unknown", "unknown_tool", shape=shape)
        spec = self._specs.get(name)
        if spec is None:
            return self._denial("unknown", "unknown_tool", shape=shape)
        if not spec.enabled or (context.enabled_tools is not None and name not in context.enabled_tools):
            return self._denial(name, "tool_disabled", shape=shape)
        if spec.permission not in context.permissions:
            return self._denial(name, "permission_denied", shape=shape)
        try:
            if name in _SEARCH_TOOLS:
                arguments = _normalize_search_range(arguments)
            normalized = validate_arguments(spec.parameters, arguments)
            if name in _SEARCH_TOOLS:
                _context_range(normalized, context)
        except ToolValidationError as exc:
            return self._denial(name, "invalid_arguments", exc.code, shape=shape)
        try:
            outcome = spec.handler(context, normalized)
            if not isinstance(outcome, ToolResult):
                raise ToolExecutionError("handler returned an invalid result")
            if outcome.name != name:
                raise ToolExecutionError("handler result name mismatch")
            if not outcome.ok:
                # Handler-controlled exception text and error fields are not an audit API.
                code = outcome.error_code
                if code == "invalid_arguments":
                    return self._denial(name, "invalid_arguments", shape=shape)
                if not outcome.allowed or code in _DENIAL_CODES:
                    return self._denial(
                        name, code if code in _DENIAL_CODES else "handler_denied", shape=shape,
                    )
                return self._failure(
                    name, code if code in _HANDLER_ERROR_CODES else "handler_failed",
                    shape=shape,
                )
            return outcome
        except ToolValidationError as exc:
            return self._denial(name, "invalid_arguments", exc.code, shape=shape)
        except ToolDeniedError:
            return self._denial(name, "handler_denied", shape=shape)
        except ToolExecutionError:
            return self._failure(name, "handler_failed", shape=shape)
        except Exception:
            return self._failure(name, "handler_failed", shape=shape)

    @staticmethod
    def _denial(name: str, code: str, detail: str = "", *, shape: str = "default") -> ToolResult:
        argument_code = detail if detail in _ARGUMENT_DETAILS else "schema_mismatch"
        _LOGGER.warning(
            "tool_attempt_failed tool=%s error=%s shape=%s argument_error=%s",
            name, code, shape, argument_code if code == "invalid_arguments" else "none",
        )
        payload = {"ok": False, "error": code, "retryable": code == "invalid_arguments"}
        if code == "invalid_arguments":
            payload.update(argument_error=argument_code, detail=_ARGUMENT_DETAILS[argument_code])
        else:
            payload["detail"] = "Tool access was denied; do not retry."
        return ToolResult(
            name=name or "unknown",
            allowed=False,
            success=False,
            text=_serialize(payload, maximum=MAX_TOOL_RESULT_CHARS),
            error_code=code,
        )

    @staticmethod
    def _failure(name: str, code: str, *, shape: str = "default") -> ToolResult:
        _LOGGER.warning(
            "tool_attempt_failed tool=%s error=%s shape=%s argument_error=none", name, code, shape,
        )
        return ToolResult(
            name=name,
            allowed=True,
            success=False,
            text=_serialize({"ok": False, "error": code, "detail": "Tool is unavailable.",
                             "retryable": False}, maximum=MAX_TOOL_RESULT_CHARS),
            error_code=code,
        )


def build_tool_registry(
    *,
    enabled_tools: Mapping[str, bool] | None = None,
) -> ToolRegistry:
    """Build only the compiled-in local registry."""
    return ToolRegistry(enabled=enabled_tools)


LocalToolRegistry = ToolRegistry
ToolOutcome = ToolResult


__all__ = [
    "MAX_TOOL_RESULT_CHARS",
    "LocalToolRegistry",
    "ToolContext",
    "ToolDeniedError",
    "ToolError",
    "ToolExecutionError",
    "ToolOutcome",
    "ToolPermissionError",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "ToolValidationError",
    "build_tool_registry",
    "validate_arguments",
]
