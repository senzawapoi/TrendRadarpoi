"""Bounded local retrieval and server-owned evidence citations.

The retriever deliberately talks to ``IntelligenceStorage`` only.  It does not use MCP,
perform network requests, or trust citation references supplied by a model.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

from trendradar.ai.models import Citation, TimeRange, TruncationState
from trendradar.core.models import ContentItem, Story, normalize_text
from trendradar.intelligence.storage import IntelligenceStorage


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _escape_like(value: str) -> str:
    """Escape user-controlled LIKE metacharacters before binding a pattern."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _json_mapping(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}") if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _bounded_json_mapping(value: Any, *, maximum: int = 4_000) -> dict[str, Any]:
    """Keep complete JSON values while dropping metadata keys beyond the byte budget."""
    source = _json_mapping(value)
    bounded: dict[str, Any] = {}
    for key in sorted(source, key=str):
        candidate = {**bounded, str(key): source[key]}
        try:
            rendered = json.dumps(candidate, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            continue
        if len(rendered) <= maximum:
            bounded = candidate
    return bounded


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def content_item_citation(item: ContentItem) -> Citation:
    """Build a bounded immutable citation for one canonical item."""
    return Citation(
        ref=f"item:{item.id}",
        title=item.title,
        source=item.source,
        url=item.url,
        content_item_id=item.id,
        event_time=item.published_time or item.collected_at,
        observed_at=item.collected_at,
        snapshot={
            "kind": "content_item",
            "item": {
                "id": item.id,
                "title": item.title[:2_000],
                "content": item.content[:2_000],
                "url": item.url[:4_000],
                "source": item.source,
                "domain": item.domain,
                "published_time": (
                    item.published_time.isoformat() if item.published_time else None
                ),
                "collected_at": item.collected_at.isoformat(),
                "tags": list(item.tags[:50]),
                "metadata": _bounded_json_mapping(item.metadata),
            },
        },
    )


def _json_values(value: Any) -> list[Any]:
    if isinstance(value, list | tuple):
        return list(value)
    return [] if value is None else [value]


def _stored_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class RetrievalLimits:
    """Hard bounds for one local Assistant retrieval."""

    max_stories: int = 20
    max_members_per_story: int = 8
    max_observations_per_story: int = 16
    max_items: int = 20
    max_citations: int = 12
    max_context_chars: int = 24_000

    def __post_init__(self) -> None:
        bounds = {
            "max_stories": (1, 100),
            "max_members_per_story": (1, 50),
            "max_observations_per_story": (1, 100),
            "max_items": (0, 100),
            "max_citations": (1, 100),
            "max_context_chars": (512, 200_000),
        }
        for name, (minimum, maximum) in bounds.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            object.__setattr__(self, name, max(minimum, min(maximum, value)))

    @property
    def max_members(self) -> int:
        return self.max_members_per_story

    @property
    def max_observations(self) -> int:
        return self.max_observations_per_story


@dataclass(frozen=True, slots=True)
class StoryBundle:
    """A bounded Story plus its canonical members and persisted observations."""

    story: Story
    members: tuple[ContentItem, ...] = ()
    observations: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.story, Story):
            raise ValueError("story must be a Story")
        members = tuple(self.members)
        if any(not isinstance(item, ContentItem) for item in members):
            raise ValueError("members must contain ContentItem values")
        observations = tuple(_freeze(dict(row)) for row in self.observations)
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "observations", observations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "story": self.story.to_dict(),
            "members": [item.to_dict() for item in self.members],
            "observations": [_thaw(row) for row in self.observations],
        }

    @property
    def story_id(self) -> str:
        return self.story.id


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Complete, bounded local evidence selected for one question."""

    time_range: TimeRange
    stories: tuple[StoryBundle, ...] = ()
    items: tuple[ContentItem, ...] = ()
    citations: tuple[Citation, ...] = ()
    truncation: TruncationState = field(default_factory=TruncationState)
    query: str = ""
    max_context_chars: int = 24_000

    def __post_init__(self) -> None:
        if not isinstance(self.time_range, TimeRange):
            raise ValueError("time_range must be a TimeRange")
        stories = tuple(self.stories)
        items = tuple(self.items)
        citations = tuple(self.citations)
        if any(not isinstance(item, StoryBundle) for item in stories):
            raise ValueError("stories must contain StoryBundle values")
        if any(not isinstance(item, ContentItem) for item in items):
            raise ValueError("items must contain ContentItem values")
        if any(not isinstance(item, Citation) for item in citations):
            raise ValueError("citations must contain Citation values")
        if isinstance(self.max_context_chars, bool) or not isinstance(
            self.max_context_chars, int
        ):
            raise ValueError("max_context_chars must be an integer")
        if not 2 <= self.max_context_chars <= 200_000:
            raise ValueError("max_context_chars is out of range")
        object.__setattr__(self, "stories", stories)
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "citations", citations)
        object.__setattr__(self, "query", normalize_text(self.query))

    @property
    def effective_range(self) -> TimeRange:
        return self.time_range

    @property
    def story_bundles(self) -> tuple[StoryBundle, ...]:
        return self.stories

    @property
    def standalone_items(self) -> tuple[ContentItem, ...]:
        return self.items

    @property
    def citation_refs(self) -> frozenset[str]:
        return frozenset(citation.ref for citation in self.citations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "time_range": self.time_range.to_dict(),
            "stories": [bundle.to_dict() for bundle in self.stories],
            "items": [item.to_dict() for item in self.items],
            "citations": [citation.to_dict() for citation in self.citations],
            "truncation": self.truncation.to_dict(),
        }

    def to_prompt(self, *, maximum: int | None = None) -> str:
        """Return a bounded deterministic context representation for a provider."""
        limit = self.max_context_chars if maximum is None else maximum
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 2:
            raise ValueError("maximum must be an integer of at least 2")
        payload = self.to_dict()
        rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        if len(rendered) <= limit:
            return rendered

        # Keep the range and evidence identifiers while progressively dropping
        # verbose fields.  Every candidate is serialized afresh, so the provider
        # never receives malformed JSON merely because a character cap was hit.
        compact: dict[str, Any] = {
            "query": self.query[:256],
            "time_range": self.time_range.to_dict(),
            "stories": [],
            "items": [],
            "citations": [],
            "truncation": {**self.truncation.to_dict(), "context": True},
        }
        for bundle in self.stories:
            story = bundle.story
            compact["stories"].append(
                {
                    "id": story.id,
                    "title": story.title[:300],
                    "summary": story.summary[:500],
                    "domain": story.domain,
                    "event_time": story.event_time.isoformat(),
                    "importance": story.importance.score,
                    "members": [
                        {
                            "id": item.id,
                            "title": item.title[:200],
                            "url": item.url,
                            "source": item.source,
                        }
                        for item in bundle.members
                    ],
                    "observations": [
                        {
                            "id": row.get("id"),
                            "source": row.get("source"),
                            "title": str(row.get("title") or "")[:200],
                            "url": row.get("url", ""),
                        }
                        for row in bundle.observations
                    ],
                }
            )
        compact["items"] = [
            {
                "id": item.id,
                "title": item.title[:200],
                "url": item.url,
                "source": item.source,
                "event_time": (item.published_time or item.collected_at).isoformat(),
            }
            for item in self.items
        ]
        compact["citations"] = [
            {
                "ref": citation.ref,
                "title": citation.title[:200],
                "source": citation.source,
                "url": citation.url,
                "story_id": citation.story_id,
                "content_item_id": citation.content_item_id,
                "observation_id": citation.observation_id,
            }
            for citation in self.citations
        ]

        # Trim the least useful layers first until the complete JSON fits.
        def render() -> str:
            return json.dumps(compact, ensure_ascii=False, separators=(",", ":"), default=str)

        while len(render()) > limit and compact["citations"]:
            compact["citations"].pop()
        while len(render()) > limit and compact["items"]:
            compact["items"].pop()
        while len(render()) > limit and compact["stories"]:
            story = compact["stories"][-1]
            if story["observations"]:
                story["observations"].pop()
            elif story["members"]:
                story["members"].pop()
            else:
                compact["stories"].pop()
        rendered = render()
        if len(rendered) <= limit:
            return rendered
        minimal = json.dumps(
            {"time_range": self.time_range.to_dict(), "truncated": True},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(minimal) <= limit:
            return minimal
        return "{}"


class RetrievalError(RuntimeError):
    """Raised when local retrieval cannot safely produce a result."""


class LocalRetriever:
    """Perform bounded, deterministic searches over the unified SQLite store."""

    def __init__(
        self,
        storage: IntelligenceStorage | sqlite3.Connection | str | Path,
        *,
        limits: RetrievalLimits | None = None,
    ) -> None:
        if isinstance(storage, IntelligenceStorage):
            self.storage = storage
            self._owns_storage = False
        elif isinstance(storage, sqlite3.Connection):
            self.storage = IntelligenceStorage.from_connection(storage)
            self._owns_storage = False
        else:
            self.storage = IntelligenceStorage(storage)
            self._owns_storage = True
        self.connection = self.storage.connection
        self.limits = limits or RetrievalLimits()

    def close(self) -> None:
        if self._owns_storage:
            self.storage.close()

    def retrieve(
        self,
        query: str = "",
        *,
        time_range: TimeRange | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        now: datetime | None = None,
        days: int = 7,
        domain: str | None = None,
    ) -> RetrievalResult:
        interval = self._resolve_range(time_range, start, end, now=now, days=days)
        normalized_query = normalize_text(query or "")
        normalized_domain = normalize_text(domain or "").casefold() or None
        terms = [term for term in normalized_query.casefold().split() if term]

        story_rows, stories_truncated = self._story_rows(
            terms, interval, normalized_domain
        )
        bundles: list[StoryBundle] = []
        represented_ids: set[str] = set()
        members_truncated = False
        observations_truncated = False
        for row in story_rows:
            story = self._row_to_story(row)
            members, member_truncated = self._members(story.id, self.limits.max_members_per_story)
            observations, observation_truncated = self._observations(
                story.id, self.limits.max_observations_per_story
            )
            members_truncated |= member_truncated
            observations_truncated |= observation_truncated
            represented_ids.update(story.member_ids)
            bundles.append(StoryBundle(story, tuple(members), tuple(observations)))

        items, items_truncated = self._item_rows(
            terms,
            interval,
            normalized_domain,
            represented_ids,
        )

        citations, citations_truncated = self._citations(bundles, items)
        truncation = TruncationState(
            stories=stories_truncated,
            members=members_truncated,
            items=items_truncated,
            observations=observations_truncated,
            citations=citations_truncated,
        )
        result = RetrievalResult(
            time_range=interval,
            stories=tuple(bundles),
            items=tuple(items),
            citations=tuple(citations),
            truncation=truncation,
            query=normalized_query,
            max_context_chars=self.limits.max_context_chars,
        )
        full_context = json.dumps(
            result.to_dict(), ensure_ascii=False, sort_keys=True, default=str
        )
        if len(full_context) > self.limits.max_context_chars:
            result = RetrievalResult(
                time_range=result.time_range,
                stories=result.stories,
                items=result.items,
                citations=result.citations,
                truncation=TruncationState(
                    history=result.truncation.history,
                    stories=result.truncation.stories,
                    members=result.truncation.members,
                    items=result.truncation.items,
                    observations=result.truncation.observations,
                    citations=result.truncation.citations,
                    context=True,
                    tool_calls=result.truncation.tool_calls,
                ),
                query=result.query,
                max_context_chars=self.limits.max_context_chars,
            )
        return result

    def retrieve_story_evidence(
        self,
        story_id: str,
        *,
        time_range: TimeRange,
    ) -> RetrievalResult:
        """Return one bounded Story detail bundle and citations built from those rows."""
        if not isinstance(time_range, TimeRange):
            raise ValueError("time_range must be a TimeRange")
        row = self.connection.execute(
            """
            SELECT * FROM stories
            WHERE id = ? AND event_time >= ? AND event_time < ?
            """,
            (story_id, time_range.start.isoformat(), time_range.end.isoformat()),
        ).fetchone()
        if row is None:
            return RetrievalResult(
                time_range=time_range,
                max_context_chars=self.limits.max_context_chars,
            )
        story = self._row_to_story(row)
        members, members_truncated = self._members(
            story.id,
            self.limits.max_members_per_story,
        )
        observations, observations_truncated = self._observations(
            story.id,
            self.limits.max_observations_per_story,
        )
        bundle = StoryBundle(story, tuple(members), tuple(observations))
        citations, citations_truncated = self._citations([bundle], [])
        return RetrievalResult(
            time_range=time_range,
            stories=(bundle,),
            citations=tuple(citations),
            truncation=TruncationState(
                members=members_truncated,
                observations=observations_truncated,
                citations=citations_truncated,
            ),
            max_context_chars=self.limits.max_context_chars,
        )

    # ``search`` is a convenient compatibility spelling for transport adapters.
    search = retrieve

    def _resolve_range(
        self,
        time_range: TimeRange | None,
        start: datetime | None,
        end: datetime | None,
        *,
        now: datetime | None,
        days: int,
    ) -> TimeRange:
        if time_range is not None and (start is not None or end is not None):
            raise ValueError("time_range cannot be combined with start/end")
        if time_range is not None:
            if not isinstance(time_range, TimeRange):
                raise ValueError("time_range must be a TimeRange")
            return time_range
        timestamp = _utc(now or datetime.now(tz=timezone.utc), "now")
        if start is None and end is None:
            try:
                lookback = max(1, min(3650, int(days)))
            except (TypeError, ValueError):
                lookback = 7
            return TimeRange.previous_days(timestamp, lookback)
        if start is None or end is None:
            raise ValueError("start and end must be supplied together")
        return TimeRange(_utc(start, "start"), _utc(end, "end"))

    def _story_rows(
        self,
        terms: list[str],
        interval: TimeRange,
        domain: str | None,
    ) -> tuple[list[sqlite3.Row], bool]:
        clauses = ["event_time >= ?", "event_time < ?"]
        parameters: list[Any] = [interval.start.isoformat(), interval.end.isoformat()]
        if domain:
            clauses.append("domain = ?")
            parameters.append(domain)
        self._append_search_clause(
            clauses, parameters, terms, ("title", "summary", "tags_json", "entities_json")
        )
        sql = (
            "SELECT * FROM stories WHERE "
            + " AND ".join(clauses)
            + " ORDER BY importance_score DESC, event_time DESC, id LIMIT ?"
        )
        parameters.append(self.limits.max_stories + 1)
        rows = self.connection.execute(sql, parameters).fetchall()
        return rows[: self.limits.max_stories], len(rows) > self.limits.max_stories

    def _item_rows(
        self,
        terms: list[str],
        interval: TimeRange,
        domain: str | None,
        represented_ids: set[str],
    ) -> tuple[list[ContentItem], bool]:
        clauses = [
            "COALESCE(published_time, collected_at) >= ?",
            "COALESCE(published_time, collected_at) < ?",
        ]
        parameters: list[Any] = [interval.start.isoformat(), interval.end.isoformat()]
        if domain:
            clauses.append("domain = ?")
            parameters.append(domain)
        self._append_search_clause(clauses, parameters, terms, ("title", "content", "tags_json"))
        # Fetch enough rows to fill the standalone cap after removing Story members.
        fetch_limit = self.limits.max_items + len(represented_ids) + 1
        sql = (
            "SELECT * FROM content_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY COALESCE(published_time, collected_at) DESC, id LIMIT ?"
        )
        parameters.append(max(1, fetch_limit))
        rows = self.connection.execute(sql, parameters).fetchall()
        available = [
            self._row_to_item(row)
            for row in rows
            if str(row["id"]) not in represented_ids
        ]
        selected = available[: self.limits.max_items]
        return selected, len(available) > self.limits.max_items or len(rows) >= fetch_limit

    @staticmethod
    def _append_search_clause(
        clauses: list[str],
        parameters: list[Any],
        terms: list[str],
        fields: tuple[str, ...],
    ) -> None:
        for term in terms:
            pattern = f"%{_escape_like(term)}%"
            clauses.append(
                "(" + " OR ".join(f"lower({field}) LIKE ? ESCAPE '\\'" for field in fields) + ")"
            )
            parameters.extend(pattern for _ in fields)

    def _members(self, story_id: str, limit: int) -> tuple[list[ContentItem], bool]:
        rows = self.connection.execute(
            "SELECT content_item_id FROM story_members WHERE story_id = ? "
            "ORDER BY ordinal, content_item_id LIMIT ?",
            (story_id, limit + 1),
        ).fetchall()
        items: list[ContentItem] = []
        for row in rows[:limit]:
            item_id = str(row["content_item_id"])
            item = self.storage.get_security_item_view(item_id)
            if item is None:
                item = self._row_to_item_by_id(item_id)
            if item is not None:
                items.append(item)
        return items, len(rows) > limit

    def _row_to_item_by_id(self, item_id: str) -> ContentItem | None:
        row = self.connection.execute(
            "SELECT * FROM content_items WHERE id = ?", (item_id,)
        ).fetchone()
        return self._row_to_item(row) if row else None

    def _observations(self, story_id: str, limit: int) -> tuple[list[dict[str, Any]], bool]:
        rows = self.connection.execute(
            """
            SELECT content_observations.*
            FROM story_members
            JOIN content_observations
              ON content_observations.content_item_id = story_members.content_item_id
            WHERE story_members.story_id = ?
            ORDER BY story_members.ordinal, content_observations.id
            LIMIT ?
            """,
            (story_id, limit + 1),
        ).fetchall()
        return [self._observation_snapshot(row) for row in rows[:limit]], len(rows) > limit

    @staticmethod
    def _observation_snapshot(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "content_item_id": str(row["content_item_id"]),
            "source": str(row["source"]),
            "source_content_id": str(row["source_content_id"]),
            "title": str(row["title"])[:2_000],
            "content": str(row["content"] or "")[:2_000],
            "url": str(row["url"] or "")[:4_000],
            "metadata": _bounded_json_mapping(row["metadata_json"]),
            "first_observed_at": str(row["first_observed_at"]),
            "last_observed_at": str(row["last_observed_at"]),
        }

    def _citations(
        self,
        bundles: list[StoryBundle],
        items: list[ContentItem],
    ) -> tuple[list[Citation], bool]:
        citations: list[Citation] = []
        seen: set[str] = set()

        def add(citation: Citation) -> bool:
            if citation.ref in seen:
                return True
            if len(citations) >= self.limits.max_citations:
                return False
            seen.add(citation.ref)
            citations.append(citation)
            return True

        truncated = False
        # Reserve the first citation slots for top-level Stories so lower-ranked
        # observation rows cannot starve later Story evidence.
        for bundle in bundles:
            story = bundle.story
            if not add(
                Citation(
                    ref=f"story:{story.id}",
                    title=story.title,
                    source=f"story:{story.domain}",
                    story_id=story.id,
                    event_time=story.event_time,
                    observed_at=story.last_activity_at,
                    snapshot={
                        "kind": "story",
                        "story_id": story.id,
                        "summary": story.summary[:2_000],
                        "importance": story.importance.to_dict(),
                        "tags": list(story.tags[:50]),
                        "entities": list(story.entities[:50]),
                        "member_ids": list(story.member_ids[:50]),
                    },
                )
            ):
                truncated = True
        for bundle in bundles:
            story = bundle.story
            for row in bundle.observations:
                observation = Citation(
                    ref=f"observation:{row['id']}",
                    title=str(row["title"] or story.title),
                    source=str(row["source"]),
                    url=str(row["url"] or ""),
                    story_id=story.id,
                    content_item_id=str(row["content_item_id"]),
                    observation_id=int(row["id"]),
                    event_time=_stored_time(
                        _json_mapping(row.get("metadata")).get("published_time")
                    ),
                    observed_at=_stored_time(row.get("last_observed_at")),
                    snapshot={"kind": "observation", **dict(row)},
                )
                if not add(observation):
                    truncated = True
                    break
            if len(citations) >= self.limits.max_citations:
                truncated = True
                break

        for item in items:
            if not add(content_item_citation(item)):
                truncated = True
                break
        return citations, truncated

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> ContentItem:
        return ContentItem.from_dict(
            {
                "id": row["id"],
                "title": row["title"],
                "content": row["content"],
                "url": row["url"],
                "source": row["source"],
                "domain": row["domain"],
                "published_time": row["published_time"],
                "collected_at": row["collected_at"],
                "tags": json.loads(row["tags_json"] or "[]"),
                "metadata": json.loads(row["metadata_json"] or "{}"),
            }
        )

    @staticmethod
    def _row_to_story(row: sqlite3.Row) -> Story:
        return Story.from_dict(
            {
                "id": row["id"],
                "identity_key": row["identity_key"],
                "title": row["title"],
                "summary": row["summary"],
                "domain": row["domain"],
                "event_time": row["event_time"],
                "last_activity_at": row["last_activity_at"],
                "member_ids": json.loads(row["member_ids_json"] or "[]"),
                "tags": json.loads(row["tags_json"] or "[]"),
                "entities": json.loads(row["entities_json"] or "[]"),
                "importance": json.loads(row["importance_json"] or "{}"),
                "generator_version": row["generator_version"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
            }
        )


# Names used by a few transport-facing callers and early design notes.
IntelligenceRetriever = LocalRetriever
LocalIntelligenceRetriever = LocalRetriever
RetrievalBundle = RetrievalResult


__all__ = [
    "IntelligenceRetriever",
    "LocalIntelligenceRetriever",
    "LocalRetriever",
    "RetrievalBundle",
    "RetrievalError",
    "RetrievalLimits",
    "RetrievalResult",
    "StoryBundle",
    "content_item_citation",
]
