"""Parse a trusted single-line EnvironmentFile without evaluating shell code."""

from __future__ import annotations

import os
import re
import shlex
import stat
import sys
from pathlib import Path

PATH_KEYS = {
    "CONFIG_PATH", "INTELLIGENCE_DB_PATH", "AI_FRONTIER_DB_PATH", "TRENDRADAR_HEALTH_DIR",
    "TRENDRADAR_LOCK_DIR", "TRENDRADAR_CONTROL_DIR", "TRENDRADAR_BACKUP_DIR",
    "TRENDRADAR_RELEASE_ROOT", "TRENDRADAR_CURRENT_LINK", "TRENDRADAR_RELEASE_ENV",
    "TRENDRADAR_DEPLOY_LOCK",
}
REQUIRED = {
    "CONFIG_PATH", "INTELLIGENCE_DB_PATH", "AI_FRONTIER_DB_PATH", "TRENDRADAR_HEALTH_DIR",
    "TRENDRADAR_LOCK_DIR", "TRENDRADAR_CONTROL_DIR", "TRENDRADAR_BACKUP_DIR",
}


def parse_environment(path: Path) -> dict[str, str]:
    values = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if "=" not in line:
            raise ValueError(f"invalid EnvironmentFile assignment at line {number}")
        key, raw = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"invalid EnvironmentFile key at line {number}")
        if raw.strip().startswith(("'", '"')):
            parts = shlex.split(raw.strip(), comments=False, posix=True)
            if len(parts) != 1:
                raise ValueError(f"invalid quoted value at line {number}")
            value = parts[0]
        else:
            value = raw.strip()
            if any(char in value for char in ("'", '"', "\\")):
                raise ValueError(f"unsupported EnvironmentFile escaping at line {number}")
        if key not in PATH_KEYS and not key.startswith((
            "INTELLIGENCE_", "AI_FRONTIER_", "TRENDRADAR_", "LARK_",
        )):
            raise ValueError(f"EnvironmentFile key is not allowed: {key}")
        values[key] = value
    for key in REQUIRED:
        if not values.get(key):
            raise ValueError(f"missing required EnvironmentFile key: {key}")
    for key in PATH_KEYS & values.keys():
        value = values[key]
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", value) or ".." in Path(value).parts:
            raise ValueError(f"invalid absolute path in {key}")
    config_path = Path(values["CONFIG_PATH"])
    if not config_path.is_file():
        raise ValueError("CONFIG_PATH is not a readable file")
    with config_path.open("rb") as config_file:
        config_file.read(1)
    if values.get("INTELLIGENCE_SQLITE_SYNCHRONOUS") != "FULL":
        raise ValueError("production installer requires SQLite FULL")
    return values


def trusted_file(path: Path) -> None:
    for candidate in (path, *path.parents):
        info = candidate.stat()
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
            raise ValueError("controlled installer/configuration must be root-owned and not writable by others")
    if path.is_symlink() or not path.is_file():
        raise ValueError("controlled input must be a regular file")


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        print("environment loader requires configuration and installer", file=sys.stderr)
        return 2
    common, installer = map(Path, args[:2])
    try:
        trusted_file(common)
        trusted_file(installer)
        values = parse_environment(common)
    except (OSError, ValueError):
        # Do not disclose values or parser exceptions containing credentials.
        print("invalid or missing trusted production configuration", file=sys.stderr)
        return 2
    environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", **values}
    os.execve(installer, [str(installer), *args[2:]], environment)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
