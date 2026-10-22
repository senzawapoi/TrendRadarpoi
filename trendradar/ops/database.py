"""Explicit database preparation commands for production deployments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trendradar.ai_frontier.storage import (
    SCHEMA_VERSION as AI_FRONTIER_SCHEMA_VERSION,
)
from trendradar.ai_frontier.storage import (
    AIFrontierStorage,
)
from trendradar.core.locking import runtime_locks
from trendradar.intelligence.storage import SCHEMA_VERSION, IntelligenceStorage


def migrate_database(
    database: str | Path,
    *,
    synchronous: str = "FULL",
    kind: str = "intelligence",
) -> dict[str, object]:
    """Create or migrate one supported database, and report its final schema."""
    if kind not in {"intelligence", "ai_frontier"}:
        raise ValueError(f"unsupported database kind: {kind}")
    path = Path(database).expanduser().resolve()
    storage_type = AIFrontierStorage if kind == "ai_frontier" else IntelligenceStorage
    schema_version = AI_FRONTIER_SCHEMA_VERSION if kind == "ai_frontier" else SCHEMA_VERSION
    lock_names = ("collector",) if kind == "ai_frontier" else (
        "bot", "worker", "collector", "scheduler"
    )
    with runtime_locks(path, *lock_names), storage_type.migrate(
        path, synchronous=synchronous
    ) as storage:
        version = int(storage.connection.execute("PRAGMA user_version").fetchone()[0])
        actual_sync = str(storage.connection_policy["sqlite_synchronous"])
        journal = str(storage.connection.execute("PRAGMA journal_mode").fetchone()[0])
    return {
        "database": str(path),
        "kind": kind,
        "schema": version,
        "expected_schema": schema_version,
        "synchronous": actual_sync,
        "journal_mode": journal,
    }


def check_database(
    database: str | Path,
    *,
    synchronous: str = "FULL",
    kind: str = "intelligence",
) -> dict[str, object]:
    if kind not in {"intelligence", "ai_frontier"}:
        raise ValueError(f"unsupported database kind: {kind}")
    storage_type = AIFrontierStorage if kind == "ai_frontier" else IntelligenceStorage
    with storage_type.open_existing(database, synchronous=synchronous) as storage:
        return storage.connection_policy


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TrendRadar database maintenance")
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate = subparsers.add_parser(
        "migrate", help="create or explicitly migrate a supported database"
    )
    migrate.add_argument("--database", required=True)
    migrate.add_argument("--synchronous", default="FULL")
    migrate.add_argument(
        "--kind", choices=("intelligence", "ai_frontier"), default="intelligence"
    )
    check = subparsers.add_parser("check", help="refuse a missing or incompatible database")
    check.add_argument("--database", required=True)
    check.add_argument("--synchronous", default="FULL")
    check.add_argument(
        "--kind", choices=("intelligence", "ai_frontier"), default="intelligence"
    )
    args = parser.parse_args(argv)
    if args.command == "migrate":
        result = migrate_database(args.database, synchronous=args.synchronous, kind=args.kind)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    if args.command == "check":
        print(json.dumps(check_database(
            args.database, synchronous=args.synchronous, kind=args.kind
        )))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
