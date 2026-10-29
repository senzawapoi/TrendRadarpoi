"""Persistent maintenance/restore guard for controlled recovery operations."""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import tempfile
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class FinalizeHealthError(RuntimeError):
    """Expose bounded reason codes without leaking configuration or provider values."""

    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__("finalized deployment must pass health confirmation")
        self.diagnostics = {
            "status": report.get("status"),
            "errors": [str(item).split(":", 1)[0][:80]
                       for item in report.get("errors", [])[:20]],
            "warnings": [str(item).split(":", 1)[0][:80]
                         for item in report.get("warnings", [])[:20]],
        }
        clocks = {}
        for role in ("bot", "worker", "scheduler", "collector"):
            heartbeat = (report.get("heartbeats") or {}).get(role, {})
            age = heartbeat.get("age_seconds")
            if isinstance(age, int | float) and not isinstance(age, bool) and math.isfinite(age):
                clocks[role] = {"age_seconds": age}
                for field in ("updated_at", "sampled_at"):
                    try:
                        stamp = datetime.fromisoformat(heartbeat.get(field, ""))
                    except (TypeError, ValueError):
                        continue
                    if stamp.tzinfo and stamp.utcoffset() is not None:
                        clocks[role][field] = stamp.astimezone(timezone.utc).isoformat()
        if clocks:
            self.diagnostics["heartbeat_clocks"] = clocks


def _sync_directory(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _unlink_control_marker(path: Path) -> None:
    original = path.read_bytes()
    path.unlink()
    try:
        _sync_directory(path.parent)
    except OSError:
        # A failed clear must remain protected in the running filesystem too.
        fd, temporary = tempfile.mkstemp(prefix=".control-marker-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            with suppress(OSError):
                _sync_directory(path.parent)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary)
        raise


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("transaction must be an object")
    return value


def pending_restore_transactions(database_path: str | Path) -> list[dict[str, Any]]:
    pending = []
    for path in sorted(control_directory(database_path).glob("restore-activation-*.json")):
        try:
            payload = _read_object(path)
            if payload.get("state") in {"complete", "rolled_back"}:
                continue
        except (OSError, ValueError):
            payload = {"state": "invalid", "reason": "invalid_restore_transaction"}
        pending.append(payload | {"path": str(path)})
    return pending


def _controller_alive(payload: dict[str, Any]) -> bool:
    """Fence PID reuse with Linux boot/start identity and a bounded lease."""
    try:
        pid = payload["controller_pid"]
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
            return False
        proc = Path("/proc") / str(pid)
        fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z" or fields[19] != payload["controller_start_time"]:
            return False
        if Path("/proc/sys/kernel/random/boot_id").read_text().strip() != payload["boot_id"]:
            return False
        updated = datetime.fromisoformat(payload["updated_at"])
        if updated.tzinfo is None or updated.utcoffset() is None:
            return False
        if "controller_lease_boottime_ns" in payload:
            lease = payload["controller_lease_boottime_ns"]
            if isinstance(lease, bool) or not isinstance(lease, int) or lease < 0:
                return False
            # Same-boot elapsed time includes suspend and ignores wall-clock corrections.
            age_ns = time.clock_gettime_ns(time.CLOCK_BOOTTIME) - lease
            return 0 <= age_ns <= 15_000_000_000
        age = (datetime.now(timezone.utc) - updated).total_seconds()
        return 0 <= age <= 15
    except (OSError, KeyError, TypeError, ValueError, IndexError, AttributeError):
        return False


def read_deployment(database_path: str | Path) -> dict[str, Any] | None:
    path = control_directory(database_path) / "deploy-in-progress.json"
    if not path.exists():
        return None
    try:
        return _read_object(path)
    except (OSError, ValueError):
        return {"state": "invalid", "reason": "invalid_deployment_transaction"}


def deployment_authorized(database_path: str | Path) -> bool:
    deployment = read_deployment(database_path)
    return bool(
        deployment
        and deployment.get("state") in {"resume", "verify", "finalize"}
        and deployment.get("business_boundary_crossed") is True
        and deployment.get("new_release_id") == os.environ.get("TRENDRADAR_RELEASE_ID")
        and _controller_alive(deployment)
    )


def control_directory(database_path: str | Path) -> Path:
    configured = os.environ.get("TRENDRADAR_CONTROL_DIR", "").strip()
    if configured:
        return Path(configured)
    database = Path(database_path).expanduser().resolve()
    if database.parent.name == "output":
        return database.parent.parent / "control"
    return database.parent / "control"


def guard_path(database_path: str | Path) -> Path:
    return control_directory(database_path) / "restore-guard.json"


def recovery_cutover_path(database_path: str | Path) -> Path:
    return control_directory(database_path) / "recovery-cutover.json"


def read_guard(database_path: str | Path) -> dict[str, Any] | None:
    if pending_restore_transactions(database_path):
        return {"state": "maintenance", "valid": True, "reason": "incomplete_restore_transaction"}
    deployment = read_deployment(database_path)
    if deployment is not None and not deployment_authorized(database_path):
        return {"state": "maintenance", "valid": True, "reason": "incomplete_deployment_transaction"}
    path = guard_path(database_path)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"state": "maintenance", "valid": False, "reason": "invalid_guard"}
    if not isinstance(value, dict) or value.get("state") != "maintenance":
        return {"state": "maintenance", "valid": False, "reason": "invalid_guard"}
    return value | {"valid": True}


def set_guard(
    database_path: str | Path,
    *,
    reason: str,
    recovery_cutover_at: str | None = None,
) -> dict[str, Any]:
    path = guard_path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": "maintenance",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "reason": reason[:200],
        "accept_new_work": False,
        "process_recovery": False,
        "allow_external_send": False,
        "allow_collection": False,
    }
    if recovery_cutover_at:
        payload["recovery_cutover_at"] = recovery_cutover_at
    fd, temporary = tempfile.mkstemp(prefix=".restore-guard-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)
    return payload | {"path": str(path)}


def read_recovery_cutover(database_path: str | Path) -> datetime | None:
    guard = read_guard(database_path)
    value = guard.get("recovery_cutover_at") if guard else None
    if value is None:
        path = recovery_cutover_path(database_path)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get("recovery_cutover_at")
        except (OSError, TypeError, ValueError, AttributeError) as exc:
            raise RuntimeError("invalid recovery cutover marker") from exc
    if not isinstance(value, str):
        raise RuntimeError("invalid recovery cutover time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("invalid recovery cutover time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError("recovery cutover time must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _persist_recovery_cutover(database_path: str | Path, value: str) -> None:
    path = recovery_cutover_path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump({"recovery_cutover_at": value}, stream, ensure_ascii=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _sync_directory(path.parent)


def clear_guard(database_path: str | Path) -> bool:
    if pending_restore_transactions(database_path):
        raise RuntimeError("incomplete restore transaction requires recovery before clear")
    if read_deployment(database_path) is not None and not deployment_authorized(database_path):
        raise RuntimeError("incomplete deployment transaction requires recovery before clear")
    path = guard_path(database_path)
    guard = read_guard(database_path)
    if guard and guard.get("recovery_cutover_at"):
        _persist_recovery_cutover(database_path, str(guard["recovery_cutover_at"]))
    try:
        _unlink_control_marker(path)
        return True
    except FileNotFoundError:
        return False


def finalize_deployment(database_path: str | Path) -> dict[str, Any]:
    """Confirm a durably finalized deployment before removing its active marker."""
    deployment = read_deployment(database_path)
    if not deployment or deployment.get("state") != "finalize":
        raise RuntimeError("deployment has not durably finalized")
    if pending_restore_transactions(database_path):
        raise RuntimeError("incomplete restore transaction requires recovery")
    release_id = os.environ.get("TRENDRADAR_RELEASE_ID")
    if not release_id or release_id != deployment.get("new_release_id"):
        raise RuntimeError("deployment release identity mismatch")
    current = Path(str(deployment.get("current_link", "")))
    if not current.is_symlink() or str(current.resolve()) != deployment.get("new_target"):
        raise RuntimeError("deployment current target mismatch")
    from trendradar.ops.health import collect_health

    report = collect_health(readiness=True, allow_maintenance=True)
    if report["status"] not in {"healthy", "maintenance"} or report.get("errors"):
        raise FinalizeHealthError(report)
    path = control_directory(database_path) / "deploy-in-progress.json"
    _unlink_control_marker(path)
    return {"finalized": True, "release_id": release_id}


def confirm_deployment_rollback(database_path: str | Path) -> dict[str, Any]:
    """Permit old roles only after the installer persisted an exact rollback."""
    deployment = read_deployment(database_path)
    if not deployment or deployment.get("state") != "rollback_complete":
        raise RuntimeError("deployment rollback has not completed")
    if deployment.get("business_boundary_crossed") is not False:
        raise RuntimeError("business boundary forbids automatic rollback")
    if pending_restore_transactions(database_path):
        raise RuntimeError("restore rollback remains incomplete")
    current = Path(str(deployment.get("current_link", "")))
    if not current.is_symlink() or str(current.resolve()) != deployment.get("old_target"):
        raise RuntimeError("rollback current target mismatch")
    if os.environ.get("TRENDRADAR_RELEASE_ID") != Path(str(deployment["old_target"])).name:
        raise RuntimeError("rollback release identity mismatch")
    # Candidate schema policy cannot validate an older release's snapshot.
    database = Path(database_path).resolve()
    expected: dict[Path, int | None] = {database: None}
    absent: list[Path] = []
    if deployment.get("snapshot_id"):
        snapshot_id = deployment["snapshot_id"]
        if not isinstance(snapshot_id, str) or Path(snapshot_id).name != snapshot_id:
            raise RuntimeError("invalid rollback snapshot identity")
        backup_root = Path(os.environ.get("TRENDRADAR_BACKUP_DIR", "output/backups"))
        manifest = _read_object(backup_root / snapshot_id / "manifest.json")
        root = Path(str(deployment.get("snapshot_root", ""))).resolve()
        if manifest.get("complete") is not True or manifest.get("release_id") != current.resolve().name:
            raise RuntimeError("invalid rollback snapshot")
        if manifest.get("root", str(root)) != str(root):
            raise RuntimeError("rollback snapshot root mismatch")
        entries = manifest.get("databases")
        mapping = manifest.get("target_mapping")
        if not isinstance(entries, list) or not entries or not isinstance(mapping, list):
            raise RuntimeError("rollback snapshot requires complete target mapping")
        expected = {}
        for item in entries:
            if not isinstance(item, dict) or type(item.get("schema")) is not int:
                raise RuntimeError("invalid rollback schema evidence")
            relative = item.get("relative_path")
            if not isinstance(relative, str) or not relative:
                raise RuntimeError("invalid rollback target")
            target = (root / relative).resolve()
            if root not in target.parents or target.suffix != ".db" or target in expected:
                raise RuntimeError("invalid rollback target")
            expected[target] = item["schema"]
        present = set()
        for item in mapping:
            if (not isinstance(item, dict) or not isinstance(item.get("relative_path"), str)
                    or not isinstance(item.get("present"), bool)):
                raise RuntimeError("invalid rollback target mapping")
            target = (root / item["relative_path"]).resolve()
            if root not in target.parents or target.suffix != ".db" or target in present or target in absent:
                raise RuntimeError("invalid rollback target mapping")
            if item["present"]:
                present.add(target)
            else:
                absent.append(target)
        if present != set(expected) or database not in expected:
            raise RuntimeError("rollback snapshot target set mismatch")
    for target, schema in expected.items():
        connection = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            if ((schema is not None and connection.execute("PRAGMA user_version").fetchone()[0] != schema)
                    or connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or connection.execute("PRAGMA foreign_key_check").fetchall()):
                raise RuntimeError("rollback database validation failed")
        finally:
            connection.close()
    if any(Path(str(target) + suffix).exists() for target in absent for suffix in ("", "-wal", "-shm")):
        raise RuntimeError("rollback left an originally absent database")
    marker = control_directory(database_path) / "deploy-in-progress.json"
    original = marker.read_text(encoding="utf-8")
    _unlink_control_marker(marker)
    try:
        clear_guard(database_path)
    except OSError:
        # Restore the transaction fence if guard removal was not durable.
        temporary = marker.with_name(f".{marker.name}.{os.getpid()}.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, marker)
        with suppress(OSError):
            _sync_directory(marker.parent)
        raise
    return {"rolled_back": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TrendRadar persistent maintenance guard")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("enter", "status", "clear", "finalize-deployment", "confirm-deployment-rollback"):
        command = subparsers.add_parser(name)
        command.add_argument("--database", required=True)
        if name == "enter":
            command.add_argument("--reason", required=True)
        if name == "clear":
            command.add_argument("--clear-recovery-cutover", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "enter":
        result = set_guard(args.database, reason=args.reason)
    elif args.command == "status":
        result = read_guard(args.database) or {"state": "accepting_work", "valid": True}
    elif args.command == "finalize-deployment":
        try:
            result = finalize_deployment(args.database)
        except (RuntimeError, ValueError, OSError, sqlite3.Error) as exc:
            print(json.dumps({
                "error": "finalize_confirmation_failed",
                "error_type": type(exc).__name__,
                "errno": getattr(exc, "errno", None),
                "health": getattr(exc, "diagnostics", None),
            }))
            return 2
    elif args.command == "confirm-deployment-rollback":
        try:
            result = confirm_deployment_rollback(args.database)
        except (RuntimeError, ValueError, OSError, sqlite3.Error) as exc:
            print(json.dumps({"error": str(exc)}))
            return 2
    else:
        try:
            result = {"cleared": clear_guard(args.database)}
        except RuntimeError as exc:
            print(json.dumps({"error": str(exc)}))
            return 2
        if args.clear_recovery_cutover:
            path = recovery_cutover_path(args.database)
            with suppress(FileNotFoundError):
                _unlink_control_marker(path)
            result["recovery_cutover_cleared"] = True
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
