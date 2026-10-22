"""Read-only host preflight for the reference Linux deployment layout."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


def _systemd() -> str | None:
    try:
        return subprocess.run(
            ["systemctl", "--version"], check=True, capture_output=True, text=True
        ).stdout.splitlines()[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        return None


def collect_preflight(database: str | Path = "/var/lib/trendradar/output/intelligence.db") -> dict:
    path = Path(database).expanduser()
    usage = shutil.disk_usage(path.parent if path.parent.exists() else Path.cwd())
    return {
        "host": platform.node()[:128],
        "os": platform.platform()[:256],
        "architecture": platform.machine()[:64],
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "systemd": _systemd(),
        "timezone": str(Path("/etc/localtime").resolve()) if Path("/etc/localtime").exists() else "unknown",
        "database_path": str(path),
        "database_exists": path.is_file(),
        "disk": {"total_bytes": usage.total, "free_bytes": usage.free},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only TrendRadar deployment preflight")
    parser.add_argument("--database", default="/var/lib/trendradar/output/intelligence.db")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = collect_preflight(args.database)
    print(json.dumps(report, ensure_ascii=True, indent=2) if args.json else "\n".join(f"{k}: {v}" for k, v in report.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
