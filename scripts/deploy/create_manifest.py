"""Create a secret-free release manifest for the current source tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"^version\s*=\s*['\"]([^'\"]+)", text, re.MULTILINE)
    return match.group(1) if match else "unknown"


def create_manifest(artifact: Path | None = None, release_id: str | None = None) -> dict:
    changed = _git("status", "--short")
    manifest = {
        "release_id": (release_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))[:128],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repository": str(ROOT),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(changed),
        "changed_file_count": len(changed.splitlines()) if changed else 0,
        "package_version": _version(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "sqlite": sqlite3.sqlite_version,
        "schema_supported": 7,
        "dependency_files": {
            name: _sha256(ROOT / name)
            for name in ("pyproject.toml", "requirements.txt", "requirements.lock", "build-requirements.lock")
            if (ROOT / name).is_file()
        },
        "dependency_lock": {
            "strategy": "exact-resolved-requirements-lock",
            "file": "requirements.lock",
            "sha256": _sha256(ROOT / "requirements.lock")
            if (ROOT / "requirements.lock").is_file()
            else None,
        },
        "package": {
            "install": "pip install --no-build-isolation --no-deps .",
            "build_lock": "build-requirements.lock",
            "root": "trendradar",
            "entrypoints": ["trendradar", "trendradar-mcp"],
        },
        "database_contract": {
            "intelligence_schema": 7,
            "ai_frontier_schema": 1,
            "minimum_readable_intelligence_schema": 7,
            "minimum_readable_ai_frontier_schema": 1,
            "synchronous": "FULL",
            "rollback": "schema-aware-maintenance-guard",
        },
        "artifact": None,
        "deployment_scope": {
            "research_enabled_by_default": False,
            "lark_enabled_by_default": False,
            "database_paths_are_runtime_state": True,
        },
    }
    if artifact is not None and artifact.is_file():
        manifest["artifact"] = {
            "name": artifact.name,
            "sha256": _sha256(artifact),
            "bytes": artifact.stat().st_size,
        }
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create a TrendRadar release manifest")
    parser.add_argument("--output", default="dist/RELEASE-MANIFEST.json")
    parser.add_argument("--artifact")
    parser.add_argument("--release-id")
    args = parser.parse_args(argv)
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    artifact = Path(args.artifact) if args.artifact else None
    if artifact is not None and not artifact.is_absolute():
        artifact = ROOT / artifact
    manifest = create_manifest(artifact, args.release_id)
    output.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
