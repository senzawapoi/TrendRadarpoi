"""Create or inspect a small, isolated Phase 5 intelligence database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(__file__).resolve().parent
RUNTIME_ROOT = (TEST_ROOT / "runtime").resolve()
DEFAULT_DB = RUNTIME_ROOT / "intelligence.db"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from trendradar.core.models import (  # noqa: E402
    Cluster,
    ContentItem,
    ImportanceBreakdown,
    Story,
    deterministic_cluster_id,
    deterministic_story_id,
)
from trendradar.intelligence.storage import IntelligenceStorage  # noqa: E402


def _safe_db_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if path.parent != RUNTIME_ROOT or path.name != "intelligence.db":
        raise SystemExit("The Phase 5 test database must be test/runtime/intelligence.db")
    if path.exists() and path.is_symlink():
        raise SystemExit("Refusing a symlink database path")
    return path


def _print_counts(path: Path, *, require_fixture: bool = False) -> None:
    if not path.is_file():
        raise SystemExit("Test database does not exist")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        schema = connection.execute("PRAGMA user_version").fetchone()[0]
        content = connection.execute("SELECT COUNT(*) FROM content_items").fetchone()[0]
        stories = connection.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
    if require_fixture and (schema != 5 or content < 2 or stories < 2):
        raise SystemExit("Existing test database does not contain the Phase 5 fixture")
    print(json.dumps({"schema": schema, "content_items": content, "stories": stories}))


def _seed(path: Path) -> None:
    if path.exists():
        raise SystemExit("Refusing to overwrite an existing test database; use --verify or -Reset")
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    items: list[ContentItem] = []
    clusters: list[Cluster] = []
    stories: list[Story] = []
    for index, score in ((1, 88.0), (2, 42.0)):
        identity = f"phase5-uat-{index}"
        event_time = now - timedelta(minutes=index)
        item = ContentItem.create(
            title=f"UAT Story {index}: synthetic intelligence fixture",
            content=f"UAT fixture {index}. Test fact: budget is {index * 10} units.",
            url=f"https://example.invalid/phase5-uat/{index}",
            source="rss:phase5-uat",
            domain="ai",
            published_time=event_time,
            collected_at=now,
            tags=["UAT", "synthetic"],
            metadata={"source_content_id": identity, "synthetic": True},
        )
        cluster = Cluster(
            id=deterministic_cluster_id([item.id]),
            member_ids=[item.id],
            domain="ai",
            event_time=event_time,
            last_activity_at=now,
            tags=["UAT"],
            metadata={"synthetic": True},
        )
        story = Story(
            id=deterministic_story_id(identity),
            identity_key=identity,
            title=item.title,
            summary=item.content,
            domain="ai",
            event_time=event_time,
            last_activity_at=now,
            member_ids=[item.id],
            tags=["UAT"],
            importance=ImportanceBreakdown(score=score, reasons=["synthetic UAT fixture"]),
            metadata={"cluster_id": cluster.id, "synthetic": True},
        )
        items.append(item)
        clusters.append(cluster)
        stories.append(story)
    with IntelligenceStorage(path) as storage:
        storage.write_batch(items)
        storage.upsert_story_batch(clusters, stories)
    _print_counts(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed or inspect the isolated Phase 5 test DB")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--verify", action="store_true", help="Read counts without writing")
    args = parser.parse_args()
    path = _safe_db_path(args.db)
    if args.verify:
        _print_counts(path, require_fixture=True)
    else:
        _seed(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
