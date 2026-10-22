"""Build a deterministic source release without runtime state or secrets."""

from __future__ import annotations

import argparse
import gzip
import re
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "output", "dist", "build", "__pycache__",
    ".pytest_cache", ".ruff_cache", "runtime",
}
EXCLUDED_SUFFIXES = {".pyc", ".db", ".db-wal", ".db-shm", ".log"}


def _excluded(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return True
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
        return True
    return any(path.name.endswith(suffix) for suffix in EXCLUDED_SUFFIXES)


def _release_paths() -> list[Path]:
    paths: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"release contains an unsupported symlink: {path.relative_to(ROOT)}")
        if path.is_dir() or _excluded(path):
            continue
        relative = path.relative_to(ROOT)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"release path escapes repository: {relative}")
        paths.append(path)
    return paths


def _release_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return normalized[:120] or "release"


def build_release(output_dir: Path, release_id: str | None = None) -> Path:
    release_id = _release_id(release_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / f"trendradar-{release_id}.tar.gz"
    with artifact.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed, tarfile.open(
        fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT
    ) as archive:
        for path in _release_paths():
            info = archive.gettarinfo(
                str(path), arcname=f"trendradar-{release_id}/{path.relative_to(ROOT)}"
            )
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            if info.isreg():
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
            else:
                archive.addfile(info)
    return artifact


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build a TrendRadar source release")
    parser.add_argument("--output-dir", default="dist")
    parser.add_argument("--release-id")
    args = parser.parse_args(argv)
    output = Path(args.output_dir)
    if not output.is_absolute():
        output = ROOT / output
    print(build_release(output, args.release_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
