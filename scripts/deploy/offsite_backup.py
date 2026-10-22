"""Upload a completed local snapshot with restic, never an active database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import tempfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_KILL_GRACE_SECONDS = 10


def _latest_snapshot(root: Path) -> Path:
    candidates = []
    for manifest_path in root.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest, dict) and manifest.get("complete") is True:
                created = datetime.fromisoformat(str(manifest["created_at"]).replace("Z", "+00:00"))
                candidates.append((created, manifest_path.parent))
        except (OSError, TypeError, ValueError, json.JSONDecodeError, KeyError):
            continue
    if not candidates:
        raise FileNotFoundError(f"no complete snapshot found under {root}")
    return max(candidates, key=lambda item: item[0])[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_id(repository: str) -> str:
    """Return a stable, non-reversible identifier for a restic repository."""
    return hashlib.sha256(repository.encode("utf-8")).hexdigest()[:16]


def _terminate_process(process: subprocess.Popen[str], grace_seconds: float) -> None:
    if os.name == "nt":  # pragma: no cover - exercised on Windows hosts.
        if process.poll() is None:
            with suppress(OSError):
                process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=max(0.1, grace_seconds))
    if os.name == "nt":  # pragma: no cover - exercised on Windows hosts.
        if process.poll() is None:
            process.kill()
    else:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=max(0.1, grace_seconds))


def _remote_snapshot_id(stdout: str) -> str | None:
    """Extract only restic's remote snapshot id from JSON-lines output."""
    for line in reversed(stdout.splitlines()):
        try:
            payload = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("snapshot_id"), str):
            return payload["snapshot_id"][:128]
    return None


def upload_snapshot(
    snapshot: str | Path,
    *,
    restic_bin: str | list[str] = "restic",
    repository: str | None = None,
    password_file: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    kill_grace_seconds: int = DEFAULT_KILL_GRACE_SECONDS,
) -> dict[str, object]:
    path = Path(snapshot).expanduser().resolve()
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("complete") is not True:
        raise ValueError("snapshot manifest is incomplete")
    repository = repository or os.environ.get("RESTIC_REPOSITORY", "").strip()
    password_file = password_file or os.environ.get("RESTIC_PASSWORD_FILE", "").strip()
    if not repository or not password_file:
        raise ValueError("RESTIC_REPOSITORY and RESTIC_PASSWORD_FILE are required")
    if isinstance(timeout_seconds, bool) or timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")
    if isinstance(kill_grace_seconds, bool) or kill_grace_seconds < 0:
        raise ValueError("kill_grace_seconds must be non-negative")
    manifest_digest = _sha256(path / "manifest.json")
    command = [
        *(restic_bin if isinstance(restic_bin, list) else [restic_bin]),
        "backup",
        str(path),
        "--repo",
        repository,
        "--password-file",
        password_file,
        "--json",
    ]
    command.extend(("--tag", "trendradar", "--tag", f"release:{manifest.get('release_id', 'unknown')}"))
    job = None
    if os.name == "nt":
        if __package__:
            from .process_tree import WindowsJob
        else:
            from process_tree import WindowsJob
        job = WindowsJob()
    process = None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=os.name != "nt",
            creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | 0x4) if job else 0,
        )
        if job:
            job.attach_and_resume(process)
        stdout, _stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        raise TimeoutError("restic backup exceeded its time budget") from None
    finally:
        if job:
            job.close()
        if process is not None:
            # Reap descendants even if the leader has exited or job assignment failed.
            _terminate_process(process, kill_grace_seconds)
    if process.returncode != 0:
        raise RuntimeError(f"restic backup failed with exit code {process.returncode}")
    remote_snapshot_id = _remote_snapshot_id(stdout)
    if not remote_snapshot_id:
        raise ValueError("restic returned no remote snapshot id")
    finished_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "success": True,
        "backup_id": manifest.get("backup_id"),
        "snapshot_created_at": manifest.get("created_at"),
        "manifest_sha256": manifest_digest,
        "finished_at": finished_at,
        "offsite_finished_at": finished_at,
        "repository_id": _repository_id(repository),
        "remote_snapshot_id": remote_snapshot_id,
        "release_id": manifest.get("release_id", "unknown"),
        "validation": "restic_backup_completed",
    }
    marker = path / "offsite-manifest.json"
    fd, temporary = tempfile.mkstemp(prefix=".offsite-", dir=path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, marker)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Upload one completed TrendRadar snapshot")
    parser.add_argument("--snapshot")
    parser.add_argument("--snapshot-root", default="/var/backups/trendradar/local")
    parser.add_argument("--restic-bin", default="restic")
    parser.add_argument("--repository")
    parser.add_argument("--password-file")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--kill-grace-seconds", type=int, default=DEFAULT_KILL_GRACE_SECONDS)
    args = parser.parse_args(argv)
    if os.environ.get("TRENDRADAR_OFFSITE_ENABLED", "false").strip().lower() not in {
        "1", "true", "yes", "on"
    }:
        print(json.dumps({"success": True, "skipped": "disabled"}))
        return 0
    try:
        snapshot = Path(args.snapshot).expanduser() if args.snapshot else _latest_snapshot(Path(args.snapshot_root))
        result = upload_snapshot(
            snapshot,
            restic_bin=args.restic_bin,
            repository=args.repository,
            password_file=args.password_file,
            timeout_seconds=args.timeout_seconds,
            kill_grace_seconds=args.kill_grace_seconds,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        # Command arguments and provider output may contain secrets.
        print(json.dumps({"success": False, "error": type(exc).__name__}))
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
