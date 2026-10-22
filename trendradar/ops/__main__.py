"""Operational command dispatcher."""

from __future__ import annotations

import argparse

from . import backup, database, health, maintenance


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TrendRadar operational commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    health_parser = subparsers.add_parser("health", help="read-only local health inspection")
    health_parser.add_argument("--config")
    health_parser.add_argument("--json", action="store_true")
    health_parser.add_argument("--readiness", action="store_true")
    health_parser.add_argument("--allow-maintenance", action="store_true")
    backup_parser = subparsers.add_parser("backup", help="consistent SQLite snapshots")
    backup_parser.add_argument("backup_args", nargs=argparse.REMAINDER)
    maintenance_parser = subparsers.add_parser("maintenance", help="persistent restore guard")
    maintenance_parser.add_argument("maintenance_args", nargs=argparse.REMAINDER)
    database_parser = subparsers.add_parser("database", help="explicit database preparation")
    database_parser.add_argument("database_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "health":
        health_args = ["--json"] if args.json else []
        if args.readiness:
            health_args.append("--readiness")
        if args.allow_maintenance:
            health_args.append("--allow-maintenance")
        if args.config:
            health_args.extend(["--config", args.config])
        return health.main(health_args)
    if args.command == "backup":
        return backup.main(args.backup_args)
    if args.command == "maintenance":
        return maintenance.main(args.maintenance_args)
    if args.command == "database":
        return database.main(args.database_args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
