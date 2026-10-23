"""SQLite persistence for canonical intelligence content and source provenance."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from trendradar.core.models import Cluster, ContentItem, Story, normalize_tags

SCHEMA_VERSION = 7
SQLITE_SYNCHRONOUS_MODES = frozenset({"OFF", "NORMAL", "FULL", "EXTRA"})
_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)
BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    domain TEXT NOT NULL,
    published_time TEXT,
    collected_at TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_content_items_url
    ON content_items(url) WHERE url != '';
CREATE INDEX IF NOT EXISTS idx_content_items_source_time
    ON content_items(source, published_time, collected_at);

CREATE TABLE IF NOT EXISTS content_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_content_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    first_observed_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    UNIQUE(source, source_content_id)
);
CREATE INDEX IF NOT EXISTS idx_observations_content ON content_observations(content_item_id);

CREATE TABLE IF NOT EXISTS source_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    adapter_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    normalized_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_source_runs_adapter ON source_runs(adapter_id, finished_at DESC);
"""

STORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS clusters (
    id TEXT PRIMARY KEY,
    signature TEXT NOT NULL,
    domain TEXT NOT NULL,
    event_time TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    member_ids_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    entities_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clusters_domain_time
    ON clusters(domain, event_time, last_activity_at);

CREATE TABLE IF NOT EXISTS stories (
    id TEXT PRIMARY KEY,
    identity_key TEXT NOT NULL UNIQUE,
    cluster_id TEXT REFERENCES clusters(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL,
    event_time TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    member_ids_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    entities_json TEXT NOT NULL DEFAULT '[]',
    importance_score REAL NOT NULL DEFAULT 0,
    importance_json TEXT NOT NULL DEFAULT '{}',
    generator_version TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stories_rank
    ON stories(importance_score DESC, event_time DESC, id);
CREATE INDEX IF NOT EXISTS idx_stories_domain_time
    ON stories(domain, event_time, last_activity_at);

CREATE TABLE IF NOT EXISTS story_members (
    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY(story_id, content_item_id)
);
CREATE INDEX IF NOT EXISTS idx_story_members_content
    ON story_members(content_item_id, story_id);
"""

ASSISTANT_SCHEMA = """
CREATE TABLE IF NOT EXISTS assistant_sessions (
    session_id TEXT PRIMARY KEY CHECK(length(trim(session_id)) BETWEEN 1 AND 256),
    principal_id TEXT NOT NULL CHECK(length(trim(principal_id)) BETWEEN 1 AND 256),
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assistant_sessions_principal
    ON assistant_sessions(principal_id, expires_at);

CREATE TABLE IF NOT EXISTS assistant_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES assistant_sessions(session_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK(sequence >= 0),
    request_id TEXT NOT NULL CHECK(length(trim(request_id)) BETWEEN 1 AND 256),
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL CHECK(length(trim(content)) > 0),
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(session_id, sequence),
    UNIQUE(session_id, request_id, role)
);
CREATE INDEX IF NOT EXISTS idx_assistant_messages_session
    ON assistant_messages(session_id, sequence);
CREATE INDEX IF NOT EXISTS idx_assistant_messages_request
    ON assistant_messages(session_id, request_id);
"""

# Kept as a compatibility export for callers that used the Phase 1 schema constant.
FEISHU_SCHEMA = """
CREATE TABLE IF NOT EXISTS feishu_events (
    event_id TEXT PRIMARY KEY CHECK(length(event_id) BETWEEN 1 AND 256),
    scope TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('processing', 'completed', 'failed')),
    owner TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    lease_until TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reply_json TEXT,
    event_json TEXT,
    binding_json TEXT,
    delivery_attempts INTEGER NOT NULL DEFAULT 0
);
"""
FEISHU_DELIVERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS feishu_deliveries (
    delivery_key TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(status IN ('processing', 'completed', 'failed')),
    owner TEXT NOT NULL,
    lease_until TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    chunks_json TEXT,
    next_chunk INTEGER NOT NULL DEFAULT 0 CHECK(next_chunk >= 0)
);
"""
LARK_INSTANT_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_stories_first_persisted ON stories(created_at, id);
CREATE TABLE IF NOT EXISTS lark_instant_batches (
    delivery_key TEXT PRIMARY KEY,
    target_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('processing', 'completed', 'failed', 'quarantined')),
    owner TEXT NOT NULL,
    lease_until TEXT NOT NULL,
    first_persisted_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    chunks_json TEXT NOT NULL,
    next_chunk INTEGER NOT NULL DEFAULT 0 CHECK(next_chunk >= 0),
    attempts INTEGER NOT NULL DEFAULT 1 CHECK(attempts > 0),
    last_error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_lark_instant_pending
    ON lark_instant_batches(target_key, status, created_at);
CREATE TABLE IF NOT EXISTS lark_story_deliveries (
    target_key TEXT NOT NULL,
    story_id TEXT NOT NULL,
    first_persisted_at TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    delivery_key TEXT REFERENCES lark_instant_batches(delivery_key) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('registered', 'quarantined')),
    PRIMARY KEY(target_key, story_id)
);
CREATE INDEX IF NOT EXISTS idx_lark_story_batch ON lark_story_deliveries(delivery_key);
"""
SCHEMA = (
    BASE_SCHEMA + STORY_SCHEMA + ASSISTANT_SCHEMA + FEISHU_SCHEMA
    + FEISHU_DELIVERY_SCHEMA + LARK_INSTANT_SCHEMA
)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _json_mapping(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}") if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _metadata_values(value: Any) -> list[Any]:
    if isinstance(value, list | tuple | set | frozenset):
        return list(value)
    return [] if value is None or value == "" else [value]


def _metadata_cves(metadata: Mapping[str, Any]) -> set[str]:
    return {
        normalized
        for normalized in (
            str(value).strip().upper()
            for value in _metadata_values(metadata.get("cve_ids"))
        )
        if _CVE_RE.fullmatch(normalized)
    }


def _stored_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass
class ContentObservation:
    """One source's evidence for a canonical ContentItem."""

    content_item_id: str
    source: str
    source_content_id: str
    title: str
    content: str = ""
    url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def __post_init__(self) -> None:
        self.observed_at = _utc(self.observed_at, "observed_at")
        if not self.source or not self.source_content_id:
            raise ValueError("observation source and source_content_id are required")

    @classmethod
    def from_item(cls, item: ContentItem, *, content_item_id: str | None = None) -> ContentObservation:
        metadata = dict(item.metadata)
        legacy = metadata.get("legacy_data")
        raw_title = legacy.get("title", item.title) if isinstance(legacy, dict) else item.title
        raw_content = (
            legacy.get("summary", item.content) if isinstance(legacy, dict) else item.content
        )
        raw_url = str(metadata.get("raw_url", item.url))
        source_content_id = str(metadata.get("source_content_id") or raw_url or item.id)
        return cls(
            content_item_id=content_item_id or item.id,
            source=item.source,
            source_content_id=source_content_id,
            title=str(raw_title),
            content=str(raw_content),
            url=raw_url,
            metadata=metadata,
            observed_at=item.collected_at,
        )


@dataclass(frozen=True)
class SourceRunRecord:
    adapter_id: str
    status: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    fetched_count: int = 0
    normalized_count: int = 0
    error_count: int = 0
    error_summary: str = ""


class IntelligenceStorage:
    """Local SQLite store for the compatibility-first unified data layer."""

    def __init__(
        self,
        db_path: str | Path = "output/intelligence.db",
        *,
        story_config: Mapping[str, Any] | None = None,
        allow_create: bool = True,
        allow_migrate: bool = True,
        synchronous: str = "FULL",
    ) -> None:
        self.db_path = Path(db_path)
        self.allow_create = allow_create
        self.allow_migrate = allow_migrate
        self.synchronous = self._normalize_synchronous(synchronous)
        self.story_config = (
            dict(story_config) if isinstance(story_config, Mapping) else {"enabled": False}
        )
        if not allow_create and not self.db_path.is_file():
            raise FileNotFoundError(f"intelligence database is missing: {self.db_path}")
        if allow_create:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connect_target: str | Path = self.db_path
        connect_kwargs: dict[str, Any] = {}
        if not allow_create:
            connect_target = self.db_path.resolve().as_uri() + "?mode=rw"
            connect_kwargs["uri"] = True
        self._connection = sqlite3.connect(
            connect_target,
            timeout=5,
            isolation_level=None,
            check_same_thread=False,
            **connect_kwargs,
        )
        self._owns_connection = True
        try:
            self._connection.row_factory = sqlite3.Row
            if not self.allow_migrate:
                self._validate_existing_schema()
            self._configure()
            self._initialize_schema()
        except Exception:
            self._connection.close()
            raise

    @classmethod
    def from_connection(
        cls,
        connection: sqlite3.Connection,
        *,
        story_config: Mapping[str, Any] | None = None,
        allow_migrate: bool = True,
        synchronous: str = "FULL",
    ) -> IntelligenceStorage:
        """Attach storage services to an existing SQLite connection.

        Adapters such as the Assistant and local tools sometimes receive a connection
        owned by their caller.  Re-wrapping that connection through the path-based
        constructor would open a second database (and is especially wrong for an
        in-memory test database), so this non-owning constructor initializes the same
        schema and pragmas in place.
        """
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        instance = cls.__new__(cls)
        instance.db_path = Path(":connection:")
        instance.allow_create = False
        instance.allow_migrate = allow_migrate
        instance.synchronous = instance._normalize_synchronous(synchronous)
        instance.story_config = (
            dict(story_config) if isinstance(story_config, Mapping) else {"enabled": False}
        )
        instance._connection = connection
        instance._owns_connection = False
        try:
            instance._connection.row_factory = sqlite3.Row
            if not allow_migrate:
                instance._validate_existing_schema()
            instance._configure()
            instance._initialize_schema()
        except Exception:
            raise
        return instance

    @classmethod
    def open_existing(
        cls,
        db_path: str | Path,
        *,
        story_config: Mapping[str, Any] | None = None,
        synchronous: str = "FULL",
    ) -> IntelligenceStorage:
        """Open a production database without creating or migrating it."""
        return cls(
            db_path,
            story_config=story_config,
            allow_create=False,
            allow_migrate=False,
            synchronous=synchronous,
        )

    @classmethod
    def migrate(
        cls,
        db_path: str | Path,
        *,
        story_config: Mapping[str, Any] | None = None,
        synchronous: str = "FULL",
    ) -> IntelligenceStorage:
        """Open or create a database for the explicit migration command."""
        return cls(db_path, story_config=story_config, synchronous=synchronous)

    @staticmethod
    def _normalize_synchronous(value: str) -> str:
        normalized = str(value or "FULL").strip().upper()
        if normalized not in SQLITE_SYNCHRONOUS_MODES:
            raise ValueError(
                "SQLite synchronous mode must be one of OFF, NORMAL, FULL, or EXTRA"
            )
        return normalized

    def _configure(self) -> None:
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute(f"PRAGMA synchronous = {self.synchronous}")

    @property
    def connection_policy(self) -> dict[str, Any]:
        mode = int(self._connection.execute("PRAGMA synchronous").fetchone()[0])
        return {
            "sqlite_synchronous": ("OFF", "NORMAL", "FULL", "EXTRA")[mode],
            "database_path": str(self.db_path.expanduser().resolve()),
            "schema": int(self._connection.execute("PRAGMA user_version").fetchone()[0]),
        }

    def _validate_existing_schema(self) -> None:
        version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if version != SCHEMA_VERSION:
            raise RuntimeError(
                f"intelligence.db schema {version} requires explicit migration or matching code; "
                "run `python -m trendradar.ops database migrate --database <path>`"
            )
        queries = (
            "SELECT id, title, metadata_json FROM content_items LIMIT 0",
            "SELECT id, content_item_id, source_content_id FROM content_observations LIMIT 0",
            "SELECT adapter_id, finished_at, status FROM source_runs LIMIT 0",
            "SELECT id, member_ids_json FROM clusters LIMIT 0",
            "SELECT id, importance_score FROM stories LIMIT 0",
            "SELECT story_id, content_item_id FROM story_members LIMIT 0",
            "SELECT session_id, principal_id FROM assistant_sessions LIMIT 0",
            "SELECT session_id, request_id, role FROM assistant_messages LIMIT 0",
            "SELECT event_id, event_json, binding_json, delivery_attempts FROM feishu_events LIMIT 0",
            "SELECT delivery_key, chunks_json, next_chunk FROM feishu_deliveries LIMIT 0",
            "SELECT target_key, story_id, first_persisted_at, registered_at, delivery_key, status "
            "FROM lark_story_deliveries LIMIT 0",
            "SELECT delivery_key, target_key, status, owner, lease_until, first_persisted_at, "
            "created_at, updated_at, chunks_json, next_chunk, attempts, last_error "
            "FROM lark_instant_batches LIMIT 0",
        )
        try:
            for query in queries:
                self._connection.execute(query)
        except sqlite3.Error as exc:
            raise RuntimeError("intelligence.db schema is incomplete or corrupt") from exc

    def _initialize_schema(self) -> None:
        current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"intelligence.db schema {current} is newer than supported {SCHEMA_VERSION}"
            )
        if not self.allow_migrate and current != SCHEMA_VERSION:
            raise RuntimeError(
                f"intelligence.db schema {current} requires explicit migration to "
                f"{SCHEMA_VERSION}; run `python -m trendradar.ops database migrate`"
            )
        if current < 1:
            self._apply_migration(BASE_SCHEMA, 1)
            current = 1
        if current < 2:
            self._apply_migration(STORY_SCHEMA, 2)
            current = 2
        if current < 3:
            self._apply_migration(ASSISTANT_SCHEMA, 3)
            current = 3
        if current < 4:
            self._apply_migration(FEISHU_SCHEMA, 4)
            current = 4
        if current < 5:
            self._apply_migration(FEISHU_DELIVERY_SCHEMA, 5)
            current = 5
        if current < 6:
            self._migrate_feishu_event_queue()
            current = 6
        if current < 7:
            self._apply_migration(LARK_INSTANT_SCHEMA, 7)

    def _migrate_feishu_event_queue(self) -> None:
        columns = {
            str(row[1])
            for row in self._connection.execute("PRAGMA table_info(feishu_events)")
        }
        additions = [
            name for name in ("event_json", "binding_json", "delivery_attempts")
            if name not in columns
        ]
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            for name in additions:
                column_type = "INTEGER NOT NULL DEFAULT 0" if name == "delivery_attempts" else "TEXT"
                self._connection.execute(
                    f"ALTER TABLE feishu_events ADD COLUMN {name} {column_type}"
                )
            self._connection.execute(
                """CREATE INDEX IF NOT EXISTS idx_feishu_events_recovery
                   ON feishu_events(status, lease_until, updated_at)"""
            )
            self._connection.execute("PRAGMA user_version = 6")
            self._connection.execute("COMMIT")
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def _apply_migration(self, schema: str, version: int) -> None:
        try:
            self._connection.executescript(
                f"BEGIN IMMEDIATE;\n{schema}\nPRAGMA user_version = {version};\nCOMMIT;"
            )
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        if self._owns_connection:
            self._connection.close()

    def __enter__(self) -> IntelligenceStorage:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield self._connection
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")

    def write_batch(
        self,
        items: Iterable[ContentItem],
        observations: Iterable[ContentObservation] | None = None,
    ) -> tuple[int, int]:
        item_list = list(items)
        observation_list = (
            list(observations)
            if observations is not None
            else [ContentObservation.from_item(item) for item in item_list]
        )
        with self.transaction() as connection:
            item_count = sum(self._upsert_item(connection, item) for item in item_list)
            observation_count = sum(
                self._upsert_observation(connection, observation) for observation in observation_list
            )
        return item_count, observation_count

    @staticmethod
    def _upsert_item(connection: sqlite3.Connection, item: ContentItem) -> int:
        now = datetime.now(tz=timezone.utc).isoformat()
        existing = connection.execute(
            "SELECT 1 FROM content_items WHERE id = ?", (item.id,)
        ).fetchone()
        connection.execute(
            """
            INSERT INTO content_items (
                id, title, content, url, source, domain, published_time, collected_at,
                tags_json, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                content = CASE WHEN excluded.content != '' THEN excluded.content ELSE content END,
                published_time = COALESCE(content_items.published_time, excluded.published_time),
                tags_json = excluded.tags_json,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                item.id,
                item.title,
                item.content,
                item.url,
                item.source,
                item.domain,
                item.published_time.isoformat() if item.published_time else None,
                item.collected_at.isoformat(),
                json.dumps(item.tags, ensure_ascii=False),
                json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        return int(existing is None)

    @staticmethod
    def _upsert_observation(
        connection: sqlite3.Connection,
        observation: ContentObservation,
    ) -> int:
        existing = connection.execute(
            """
            SELECT metadata_json, last_observed_at
            FROM content_observations
            WHERE source = ? AND source_content_id = ?
            """,
            (observation.source, observation.source_content_id),
        ).fetchone()
        observed_at = observation.observed_at.isoformat()
        metadata = dict(observation.metadata)
        if existing is None:
            observation_sightings = 1
        else:
            try:
                prior_metadata = json.loads(existing["metadata_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                prior_metadata = {}
            if isinstance(prior_metadata, dict):
                try:
                    observation_sightings = max(
                        1,
                        int(prior_metadata.get("_observation_count", 1)),
                    )
                except (TypeError, ValueError):
                    observation_sightings = 1
                metadata = {**prior_metadata, **metadata}
            else:
                observation_sightings = 1
            # Replaying one poll at the same timestamp is idempotent; a new
            # timestamp represents another sighting of this source record.
            if str(existing["last_observed_at"]) != observed_at:
                observation_sightings += 1
        metadata["_observation_count"] = observation_sightings
        connection.execute(
            """
            INSERT INTO content_observations (
                content_item_id, source, source_content_id, title, content, url,
                metadata_json, first_observed_at, last_observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_content_id) DO UPDATE SET
                title = excluded.title,
                content = excluded.content,
                url = excluded.url,
                metadata_json = excluded.metadata_json,
                first_observed_at = MIN(first_observed_at, excluded.first_observed_at),
                last_observed_at = MAX(last_observed_at, excluded.last_observed_at)
            """,
            (
                observation.content_item_id,
                observation.source,
                observation.source_content_id,
                observation.title,
                observation.content,
                observation.url,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str),
                observed_at,
                observed_at,
            ),
        )
        return int(existing is None)

    def record_source_run(self, record: SourceRunRecord) -> int:
        started_at = _utc(record.started_at, "started_at")
        finished_at = _utc(record.finished_at, "finished_at")
        cursor = self._connection.execute(
            """
            INSERT INTO source_runs (
                adapter_id, status, started_at, finished_at, duration_ms,
                fetched_count, normalized_count, error_count, error_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.adapter_id,
                record.status,
                started_at.isoformat(),
                finished_at.isoformat(),
                record.duration_ms,
                record.fetched_count,
                record.normalized_count,
                record.error_count,
                record.error_summary,
            ),
        )
        return int(cursor.lastrowid)

    def list_source_runs(
        self,
        adapter_id: str,
        *,
        successful_only: bool = False,
        limit: int | None = None,
    ) -> list[SourceRunRecord]:
        clauses = ["adapter_id = ?"]
        parameters: list[Any] = [adapter_id]
        if successful_only:
            clauses.append("status IN ('healthy', 'degraded')")
        sql = (
            "SELECT * FROM source_runs WHERE "
            + " AND ".join(clauses)
            + " ORDER BY finished_at DESC, id DESC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(max(0, int(limit)))
        rows = self._connection.execute(sql, parameters).fetchall()
        return [self._row_to_source_run(row) for row in rows]

    def latest_source_run(
        self,
        adapter_id: str,
        *,
        successful_only: bool = False,
    ) -> SourceRunRecord | None:
        runs = self.list_source_runs(
            adapter_id,
            successful_only=successful_only,
            limit=1,
        )
        return runs[0] if runs else None

    def get_item(self, item_id: str) -> ContentItem | None:
        row = self._connection.execute(
            "SELECT * FROM content_items WHERE id = ?", (item_id,)
        ).fetchone()
        return self._row_to_item(row) if row else None

    def get_security_item_view(self, item_id: str) -> ContentItem | None:
        """Project security observations over a canonical item without changing its identity."""
        canonical = self.get_item(item_id)
        if canonical is None:
            return None
        rows = self._connection.execute(
            """
            SELECT * FROM content_observations
            WHERE content_item_id = ? AND source LIKE 'security:%'
            ORDER BY source, source_content_id, id
            """,
            (item_id,),
        ).fetchall()
        if not rows:
            return canonical if canonical.domain == "security" else None
        representative = rows[0]
        merged: dict[str, Any] = dict(canonical.metadata) if canonical.domain == "security" else {}
        cve_ids: set[str] = set()
        entities: set[str] = set()
        references: set[str] = set()
        observation_sources: set[str] = set()
        published_times: list[datetime] = []
        latest_observed = canonical.collected_at

        for row in rows:
            metadata = _json_mapping(row["metadata_json"])
            observation_sources.add(str(row["source"]))
            cve_ids.update(_metadata_cves(metadata))
            entities.update(str(value) for value in _metadata_values(metadata.get("entities")))
            references.update(
                str(value) for value in _metadata_values(metadata.get("references")) if str(value)
            )
            published = _stored_datetime(metadata.get("published_time"))
            if published is not None:
                published_times.append(published)
            observed = _stored_datetime(row["last_observed_at"])
            if observed is not None:
                latest_observed = max(latest_observed, observed)
            for key, value in metadata.items():
                if key in {"cve_ids", "entities", "references"}:
                    continue
                if key in {"known_exploited", "action_required"}:
                    merged[key] = bool(merged.get(key)) or bool(value)
                elif value not in (None, "", [], {}):
                    merged[key] = value

        cve_ids.update(_metadata_cves(merged))
        entities.update(cve_ids)
        merged.update(
            {
                "cve_ids": sorted(cve_ids),
                "entities": sorted({value for value in entities if value}, key=str.casefold),
                "references": sorted(references),
                "source_name": _json_mapping(representative["metadata_json"]).get(
                    "source_name", representative["source"]
                ),
                "raw_url": str(representative["url"] or canonical.url),
                "security_observation_sources": sorted(observation_sources),
            }
        )
        severity = str(merged.get("severity") or "")
        tags = normalize_tags([*canonical.tags, *cve_ids, severity])
        return ContentItem(
            id=canonical.id,
            title=str(representative["title"] or canonical.title),
            content=str(representative["content"] or canonical.content),
            url=canonical.url,
            source=str(representative["source"]),
            domain="security",
            published_time=min(published_times) if published_times else canonical.published_time,
            collected_at=latest_observed,
            tags=tags,
            metadata=merged,
        )

    def find_observation_item_id(self, source: str, source_content_id: str) -> str | None:
        row = self._connection.execute(
            """
            SELECT content_item_id FROM content_observations
            WHERE source = ? AND source_content_id = ?
            """,
            (source, source_content_id),
        ).fetchone()
        return str(row[0]) if row else None

    def find_by_url(self, url: str) -> ContentItem | None:
        if not url:
            return None
        row = self._connection.execute(
            "SELECT * FROM content_items WHERE url = ?", (url,)
        ).fetchone()
        return self._row_to_item(row) if row else None

    def find_source_items_in_window(
        self,
        source: str,
        event_time: datetime,
        *,
        hours: int = 24,
    ) -> list[ContentItem]:
        event_time = _utc(event_time, "event_time")
        start = (event_time - timedelta(hours=hours)).isoformat()
        end = (event_time + timedelta(hours=hours)).isoformat()
        rows = self._connection.execute(
            """
            SELECT * FROM content_items
            WHERE source = ?
              AND COALESCE(published_time, collected_at) BETWEEN ? AND ?
            ORDER BY COALESCE(published_time, collected_at), id
            """,
            (source, start, end),
        ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def list_observations(self, content_item_id: str | None = None) -> list[sqlite3.Row]:
        if content_item_id is None:
            return self._connection.execute(
                "SELECT * FROM content_observations ORDER BY id"
            ).fetchall()
        return self._connection.execute(
            "SELECT * FROM content_observations WHERE content_item_id = ? ORDER BY id",
            (content_item_id,),
        ).fetchall()

    def list_items(self) -> list[ContentItem]:
        rows = self._connection.execute(
            "SELECT * FROM content_items ORDER BY collected_at, id"
        ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def list_items_in_window(
        self,
        domain: str,
        start: datetime,
        end: datetime,
    ) -> list[ContentItem]:
        start = _utc(start, "start")
        end = _utc(end, "end")
        rows = self._connection.execute(
            """
            SELECT * FROM content_items
            WHERE domain = ?
              AND COALESCE(published_time, collected_at) BETWEEN ? AND ?
            ORDER BY COALESCE(published_time, collected_at), id
            """,
            (domain, start.isoformat(), end.isoformat()),
        ).fetchall()
        items = {str(row["id"]): self._row_to_item(row) for row in rows}
        if domain == "security":
            observation_rows = self._connection.execute(
                """
                SELECT DISTINCT content_item_id
                FROM content_observations
                WHERE source LIKE 'security:%'
                  AND last_observed_at BETWEEN ? AND ?
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
            for row in observation_rows:
                view = self.get_security_item_view(str(row["content_item_id"]))
                if view is not None and start <= (view.published_time or view.collected_at) <= end:
                    items[view.id] = view
        return sorted(
            items.values(),
            key=lambda item: (item.published_time or item.collected_at, item.id),
        )

    def list_security_items_by_cves(self, cve_ids: Iterable[str]) -> list[ContentItem]:
        """Return canonical IDs with matching security evidence, regardless of age/domain."""
        targets = {
            normalized
            for normalized in (str(value).strip().upper() for value in cve_ids)
            if _CVE_RE.fullmatch(normalized)
        }
        if not targets:
            return []
        item_rows = self._connection.execute(
            """
            SELECT id, metadata_json FROM content_items
            WHERE domain = 'security'
            """
        ).fetchall()
        observation_rows = self._connection.execute(
            """
            SELECT content_item_id, metadata_json
            FROM content_observations
            WHERE source LIKE 'security:%'
            """
        ).fetchall()
        matching_ids = {
            str(row["id"])
            for row in item_rows
            if targets & _metadata_cves(_json_mapping(row["metadata_json"]))
        }
        matching_ids.update(
            str(row["content_item_id"])
            for row in observation_rows
            if targets & _metadata_cves(_json_mapping(row["metadata_json"]))
        )
        matches = [
            view
            for item_id in matching_ids
            if (view := self.get_security_item_view(item_id)) is not None
        ]
        return sorted(matches, key=lambda item: (item.published_time or item.collected_at, item.id))

    def upsert_story_batch(
        self,
        clusters: Iterable[Cluster],
        stories: Iterable[Story],
    ) -> tuple[int, int, int]:
        """Atomically upsert derived clusters, Stories, and stable memberships."""
        cluster_list = list(clusters)
        story_list = list(stories)
        with self.transaction() as connection:
            for story in story_list:
                row = connection.execute(
                    "SELECT member_ids_json FROM stories WHERE id = ?", (story.id,)
                ).fetchone()
                if row is not None:
                    story.member_ids = sorted(
                        set(story.member_ids) | set(json.loads(row["member_ids_json"] or "[]"))
                    )
            cluster_count = sum(
                self._upsert_cluster(connection, cluster) for cluster in cluster_list
            )
            story_count = sum(self._upsert_story(connection, story) for story in story_list)
            member_count = sum(
                self._upsert_story_members(connection, story) for story in story_list
            )
        return cluster_count, story_count, member_count

    @staticmethod
    def _upsert_cluster(connection: sqlite3.Connection, cluster: Cluster) -> int:
        now = datetime.now(tz=timezone.utc).isoformat()
        existing = connection.execute(
            """
            SELECT member_ids_json, tags_json, entities_json
            FROM clusters
            WHERE id = ?
            """,
            (cluster.id,),
        ).fetchone()
        if existing is not None:
            try:
                prior_members = json.loads(existing["member_ids_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                prior_members = []
            cluster.member_ids = sorted(set(cluster.member_ids) | set(prior_members))
            try:
                prior_tags = json.loads(existing["tags_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                prior_tags = []
            try:
                prior_entities = json.loads(existing["entities_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                prior_entities = []
            cluster.tags = sorted(set(cluster.tags) | set(prior_tags), key=str.casefold)
            cluster.entities = sorted(set(cluster.entities) | set(prior_entities), key=str.casefold)
        connection.execute(
            """
            INSERT INTO clusters (
                id, signature, domain, event_time, last_activity_at, member_ids_json,
                tags_json, entities_json, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                signature = excluded.signature,
                event_time = MIN(clusters.event_time, excluded.event_time),
                last_activity_at = MAX(clusters.last_activity_at, excluded.last_activity_at),
                member_ids_json = excluded.member_ids_json,
                tags_json = excluded.tags_json,
                entities_json = excluded.entities_json,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                cluster.id,
                cluster.signature,
                cluster.domain,
                cluster.event_time.isoformat(),
                cluster.last_activity_at.isoformat(),
                json.dumps(cluster.member_ids, ensure_ascii=False),
                json.dumps(cluster.tags, ensure_ascii=False),
                json.dumps(cluster.entities, ensure_ascii=False),
                json.dumps(cluster.metadata, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        return int(existing is None)

    @staticmethod
    def _upsert_story(connection: sqlite3.Connection, story: Story) -> int:
        now = datetime.now(tz=timezone.utc).isoformat()
        existing = connection.execute(
            "SELECT 1 FROM stories WHERE id = ?", (story.id,)
        ).fetchone()
        cluster_id = str(story.metadata.get("cluster_id") or "") or None
        connection.execute(
            """
            INSERT INTO stories (
                id, identity_key, cluster_id, title, summary, domain, event_time,
                last_activity_at, member_ids_json, tags_json, entities_json,
                importance_score, importance_json, generator_version, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                cluster_id = excluded.cluster_id,
                title = excluded.title,
                summary = excluded.summary,
                event_time = MIN(stories.event_time, excluded.event_time),
                last_activity_at = MAX(stories.last_activity_at, excluded.last_activity_at),
                member_ids_json = excluded.member_ids_json,
                tags_json = excluded.tags_json,
                entities_json = excluded.entities_json,
                importance_score = excluded.importance_score,
                importance_json = excluded.importance_json,
                generator_version = excluded.generator_version,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                story.id,
                story.identity_key,
                cluster_id,
                story.title,
                story.summary,
                story.domain,
                story.event_time.isoformat(),
                story.last_activity_at.isoformat(),
                json.dumps(story.member_ids, ensure_ascii=False),
                json.dumps(story.tags, ensure_ascii=False),
                json.dumps(story.entities, ensure_ascii=False),
                story.importance.score,
                json.dumps(story.importance.to_dict(), ensure_ascii=False, sort_keys=True),
                story.generator_version,
                json.dumps(story.metadata, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        return int(existing is None)

    @staticmethod
    def _upsert_story_members(connection: sqlite3.Connection, story: Story) -> int:
        now = datetime.now(tz=timezone.utc).isoformat()
        created = 0
        for ordinal, content_item_id in enumerate(story.member_ids):
            existing = connection.execute(
                """
                SELECT 1 FROM story_members
                WHERE story_id = ? AND content_item_id = ?
                """,
                (story.id, content_item_id),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO story_members (
                    story_id, content_item_id, ordinal, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(story_id, content_item_id) DO UPDATE SET
                    ordinal = excluded.ordinal,
                    first_seen_at = MIN(story_members.first_seen_at, excluded.first_seen_at),
                    last_seen_at = MAX(story_members.last_seen_at, excluded.last_seen_at)
                """,
                (story.id, content_item_id, ordinal, now, now),
            )
            created += int(existing is None)
        return created

    def get_story(self, story_id: str) -> Story | None:
        row = self._connection.execute(
            "SELECT * FROM stories WHERE id = ?", (story_id,)
        ).fetchone()
        return self._row_to_story(row) if row else None

    def get_story_by_identity_key(self, identity_key: str) -> Story | None:
        row = self._connection.execute(
            "SELECT * FROM stories WHERE identity_key = ?", (identity_key,)
        ).fetchone()
        return self._row_to_story(row) if row else None

    def list_stories(
        self,
        *,
        domain: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> list[Story]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if domain:
            clauses.append("domain = ?")
            parameters.append(domain)
        if start is not None:
            clauses.append("last_activity_at >= ?")
            parameters.append(_utc(start, "start").isoformat())
        if end is not None:
            clauses.append("event_time < ?")
            parameters.append(_utc(end, "end").isoformat())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT * FROM stories"
            f"{where} ORDER BY importance_score DESC, event_time DESC, id"
        )
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(max(0, int(limit)))
        rows = self._connection.execute(sql, parameters).fetchall()
        return [self._row_to_story(row) for row in rows]

    def search_stories(
        self,
        query: str = "",
        *,
        start: datetime,
        end: datetime,
        domain: str | None = None,
        limit: int = 20,
    ) -> list[Story]:
        """Search Story fields in an explicit UTC half-open interval."""
        start = _utc(start, "start")
        end = _utc(end, "end")
        if end <= start:
            raise ValueError("end must be after start")
        bounded_limit = max(0, min(1000, int(limit)))
        clauses = ["event_time >= ?", "event_time < ?"]
        parameters: list[Any] = [start.isoformat(), end.isoformat()]
        if domain:
            clauses.append("domain = ?")
            parameters.append(str(domain).casefold())
        terms = str(query or "").strip().casefold().split()
        for term in terms:
            pattern = f"%{_escape_like(term)}%"
            clauses.append(
                "(" + " OR ".join(
                    f"lower({field}) LIKE ? ESCAPE '\\'"
                    for field in ("title", "summary", "tags_json", "entities_json")
                ) + ")"
            )
            parameters.extend(pattern for _ in range(4))
        parameters.append(bounded_limit)
        rows = self._connection.execute(
            "SELECT * FROM stories WHERE "
            + " AND ".join(clauses)
            + " ORDER BY importance_score DESC, event_time DESC, id LIMIT ?",
            parameters,
        ).fetchall()
        return [self._row_to_story(row) for row in rows]

    def search_content_items(
        self,
        query: str = "",
        *,
        start: datetime,
        end: datetime,
        domain: str | None = None,
        limit: int = 20,
    ) -> list[ContentItem]:
        """Search canonical items in an explicit UTC half-open interval."""
        start = _utc(start, "start")
        end = _utc(end, "end")
        if end <= start:
            raise ValueError("end must be after start")
        bounded_limit = max(0, min(1000, int(limit)))
        clauses = [
            "COALESCE(published_time, collected_at) >= ?",
            "COALESCE(published_time, collected_at) < ?",
        ]
        parameters: list[Any] = [start.isoformat(), end.isoformat()]
        if domain:
            clauses.append("domain = ?")
            parameters.append(str(domain).casefold())
        terms = str(query or "").strip().casefold().split()
        for term in terms:
            pattern = f"%{_escape_like(term)}%"
            clauses.append(
                "(" + " OR ".join(
                    f"lower({field}) LIKE ? ESCAPE '\\'"
                    for field in ("title", "content", "tags_json")
                ) + ")"
            )
            parameters.extend(pattern for _ in range(3))
        parameters.append(bounded_limit)
        rows = self._connection.execute(
            "SELECT * FROM content_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY COALESCE(published_time, collected_at) DESC, id LIMIT ?",
            parameters,
        ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def story_ids_for_members(
        self,
        member_ids: Iterable[str],
        *,
        domain: str | None = None,
    ) -> set[str]:
        values = sorted(set(member_ids))
        if not values:
            return set()
        placeholders = ",".join("?" for _ in values)
        domain_clause = " AND stories.domain = ?" if domain else ""
        parameters = [*values, domain] if domain else values
        rows = self._connection.execute(
            "SELECT DISTINCT story_members.story_id FROM story_members "
            "JOIN stories ON stories.id = story_members.story_id "
            f"WHERE story_members.content_item_id IN ({placeholders}){domain_clause}",
            parameters,
        ).fetchall()
        return {str(row[0]) for row in rows}

    def list_story_items(self, story_id: str, *, limit: int | None = None) -> list[ContentItem]:
        story_row = self._connection.execute(
            "SELECT domain FROM stories WHERE id = ?", (story_id,)
        ).fetchone()
        sql = """
            SELECT content_items.*
            FROM story_members
            JOIN content_items ON content_items.id = story_members.content_item_id
            WHERE story_members.story_id = ?
            ORDER BY story_members.ordinal, content_items.id
        """
        parameters: list[Any] = [story_id]
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(max(0, int(limit)))
        rows = self._connection.execute(sql, parameters).fetchall()
        if story_row is not None and str(story_row["domain"]) == "security":
            return [
                view or self._row_to_item(row)
                for row in rows
                if (view := self.get_security_item_view(str(row["id"]))) is not None
                or str(row["domain"]) == "security"
            ]
        return [self._row_to_item(row) for row in rows]

    def list_story_evidence(self, story_id: str, *, limit: int | None = None) -> list[sqlite3.Row]:
        sql = """
            SELECT content_observations.*
            FROM story_members
            JOIN content_observations
              ON content_observations.content_item_id = story_members.content_item_id
            WHERE story_members.story_id = ?
            ORDER BY story_members.ordinal, content_observations.id
        """
        parameters: list[Any] = [story_id]
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(max(0, int(limit)))
        return self._connection.execute(sql, parameters).fetchall()

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

    @staticmethod
    def _row_to_source_run(row: sqlite3.Row) -> SourceRunRecord:
        return SourceRunRecord(
            adapter_id=str(row["adapter_id"]),
            status=str(row["status"]),
            started_at=_utc(datetime.fromisoformat(str(row["started_at"])), "started_at"),
            finished_at=_utc(datetime.fromisoformat(str(row["finished_at"])), "finished_at"),
            duration_ms=int(row["duration_ms"]),
            fetched_count=int(row["fetched_count"]),
            normalized_count=int(row["normalized_count"]),
            error_count=int(row["error_count"]),
            error_summary=str(row["error_summary"]),
        )

    def count(self, table: str = "content_items") -> int:
        if table not in {
            "assistant_messages",
            "assistant_sessions",
            "clusters",
            "content_items",
            "content_observations",
            "source_runs",
            "stories",
            "story_members",
        }:
            raise ValueError(f"unsupported table: {table}")
        row = self._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0])


__all__ = [
    "BASE_SCHEMA",
    "ASSISTANT_SCHEMA",
    "SCHEMA_VERSION",
    "STORY_SCHEMA",
    "ContentObservation",
    "IntelligenceStorage",
    "SourceRunRecord",
]
