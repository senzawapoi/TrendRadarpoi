"""Read-only runtime health inspection.

The command intentionally avoids the path-based IntelligenceStorage
constructor because that constructor creates missing databases and may migrate
schemas. Health must report those conditions instead of fixing them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trendradar.core.heartbeat import heartbeat_directory
from trendradar.core.settings import load_settings
from trendradar.ops.backup import pending_restore_transactions
from trendradar.ops.maintenance import read_guard

EXPECTED_SCHEMA = 6
EXPECTED_AI_FRONTIER_SCHEMA = 1
HEARTBEAT_STALE_SECONDS = 60
ACCEPTING_ROLE_STATES = {
    "bot": {"connected"},
    "worker": {"running"},
    "scheduler": {"running", "completed"},
    "collector": {"running", "completed"},
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo and parsed.utcoffset() is not None else None


def _manifest_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_only(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.is_file():
        return {}, "database_missing"
    connection = None
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        schema = int(connection.execute("PRAGMA user_version").fetchone()[0])
        synchronous = int(connection.execute("PRAGMA synchronous").fetchone()[0])
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if schema != EXPECTED_SCHEMA:
            return {"schema": schema, "tables": sorted(tables)}, "schema_mismatch"
        counts: dict[str, int] = {}
        for table in ("feishu_events", "feishu_deliveries", "source_runs", "stories"):
            if table in tables:
                counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        queue: dict[str, int] = {}
        if "feishu_events" in tables:
            for row in connection.execute(
                "SELECT status, COUNT(*) AS count FROM feishu_events GROUP BY status"
            ):
                queue[str(row["status"])] = int(row["count"])
        deliveries: dict[str, int] = {}
        if "feishu_deliveries" in tables:
            for row in connection.execute(
                "SELECT status, COUNT(*) AS count FROM feishu_deliveries GROUP BY status"
            ):
                deliveries[str(row["status"])] = int(row["count"])
        source_runs: dict[str, dict[str, Any]] = {}
        if "source_runs" in tables:
            for row in connection.execute(
                """SELECT r.adapter_id, r.status, r.finished_at, r.fetched_count,
                          r.normalized_count, r.error_count
                   FROM source_runs AS r
                   JOIN (
                       SELECT adapter_id, MAX(finished_at) AS finished_at
                       FROM source_runs GROUP BY adapter_id
                   ) AS latest
                   ON latest.adapter_id = r.adapter_id AND latest.finished_at = r.finished_at
                   ORDER BY r.adapter_id"""
            ):
                source_runs[str(row["adapter_id"])] = {
                    "status": str(row["status"]),
                    "finished_at": row["finished_at"],
                    "fetched_count": int(row["fetched_count"]),
                    "normalized_count": int(row["normalized_count"]),
                    "error_count": int(row["error_count"]),
                }
        pending_oldest = None
        if "feishu_events" in tables:
            rows = connection.execute(
                """SELECT event_json, updated_at
                   FROM feishu_events
                   WHERE event_json IS NOT NULL
                     AND ((status IN ('processing', 'failed') AND reply_json IS NULL AND attempts < 3)
                       OR (status='failed' AND reply_json IS NOT NULL AND delivery_attempts < 3))"""
            ).fetchall()
            received = []
            for row in rows:
                try:
                    payload = json.loads(row["event_json"])
                    first_received = _parse_time(payload.get("received_at"))
                except (ValueError, TypeError, AttributeError):
                    first_received = None
                stamp = first_received or _parse_time(row["updated_at"])
                if stamp:
                    received.append(stamp)
            # Durable envelope received_at survives claims, leases and retries.
            pending_oldest = min(received).isoformat() if received else None
        return {
            "schema": schema,
            "sqlite_synchronous": ("OFF", "NORMAL", "FULL", "EXTRA")[synchronous],
            "tables": sorted(tables),
            "counts": counts,
            "queue": queue,
            "deliveries": deliveries,
            "source_runs": source_runs,
            "pending_oldest_at": pending_oldest,
        }, None
    except (OSError, sqlite3.Error, ValueError) as exc:
        return {}, f"database_read_failed:{type(exc).__name__}"
    finally:
        if connection is not None:
            connection.close()


def _read_only_ai(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.is_file():
        return {}, "database_missing"
    connection = None
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        schema = int(connection.execute("PRAGMA user_version").fetchone()[0])
        synchronous = int(connection.execute("PRAGMA synchronous").fetchone()[0])
        if schema != EXPECTED_AI_FRONTIER_SCHEMA:
            return {"schema": schema}, "schema_mismatch"
        return {
            "schema": schema,
            "sqlite_synchronous": ("OFF", "NORMAL", "FULL", "EXTRA")[synchronous],
        }, None
    except (OSError, sqlite3.Error, ValueError) as exc:
        return {}, f"database_read_failed:{type(exc).__name__}"
    finally:
        if connection is not None:
            connection.close()


def _heartbeats(
    database_path: Path,
    *,
    expected_roles: list[str] | tuple[str, ...] = (),
    stale_seconds: int = HEARTBEAT_STALE_SECONDS,
    expected_release_id: str | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    directory = heartbeat_directory(database_path)
    result: dict[str, Any] = {}
    warnings: list[str] = []
    errors: list[str] = []
    if not directory.is_dir():
        errors.extend(f"missing_heartbeat:{role}" for role in expected_roles)
        return result, warnings, errors
    now = _utc_now()
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("heartbeat is not an object")
            updated = _parse_time(payload.get("updated_at"))
            age = (now - updated).total_seconds() if updated else None
            item = {
                "state": str(payload.get("state", "unknown")),
                "pid": payload.get("pid"),
                "updated_at": payload.get("updated_at"),
                "age_seconds": round(age, 3) if age is not None else None,
                "sqlite_synchronous": payload.get("sqlite_synchronous"),
                "release_id": str(payload.get("release_id", "unknown"))[:128],
            }
            result[path.stem] = item
            if age is not None and age > stale_seconds and item["state"] not in {
                "stopped",
                "disabled",
            }:
                target = errors if path.stem in expected_roles else warnings
                target.append(f"stale_heartbeat:{path.stem}")
            if path.stem in expected_roles and item["state"] == "stopped":
                errors.append(f"stopped_heartbeat:{path.stem}")
            if path.stem in expected_roles and item["state"] == "disabled":
                errors.append(f"disabled_heartbeat:{path.stem}")
            if path.stem in expected_roles and item["state"] == "disconnected":
                errors.append(f"disconnected_heartbeat:{path.stem}")
            if (
                path.stem in expected_roles
                and item["state"] not in ACCEPTING_ROLE_STATES.get(path.stem, {"running"})
            ):
                errors.append(f"non_accepting_heartbeat:{path.stem}:{item['state']}")
            if path.stem in expected_roles and updated is None:
                errors.append(f"invalid_heartbeat:{path.name}")
            if path.stem in expected_roles and age is not None and age < 0:
                errors.append(f"future_heartbeat:{path.stem}")
            if (
                path.stem in expected_roles
                and expected_release_id
                and expected_release_id not in {"unknown", "replace-with-release-id"}
                and item["release_id"] != expected_release_id
            ):
                errors.append(f"release_mismatch:{path.stem}")
        except (OSError, AttributeError, ValueError, TypeError, json.JSONDecodeError):
            if path.stem in expected_roles:
                errors.append(f"invalid_heartbeat:{path.name}")
            else:
                warnings.append(f"invalid_heartbeat:{path.name}")
    for role in expected_roles:
        if role not in result:
            errors.append(f"missing_heartbeat:{role}")
    return result, warnings, errors


def _latest_backup(backup_dir: Path, *, offsite: bool = False) -> dict[str, Any] | None:
    candidates: list[tuple[datetime, Path, dict[str, Any]]] = []
    now = _utc_now()
    if not backup_dir.is_dir():
        return None
    for manifest_path in backup_dir.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict) or manifest.get("complete") is not True:
                continue
            created = _parse_time(manifest.get("created_at"))
            if created is None or created > now:
                continue
            marker = manifest_path.parent / "offsite-manifest.json"
            manifest_digest = _manifest_digest(manifest_path)
            if offsite:
                if not marker.is_file():
                    continue
                offsite_payload = json.loads(marker.read_text(encoding="utf-8"))
                finished = _parse_time(offsite_payload.get("finished_at"))
                snapshot_created = _parse_time(offsite_payload.get("snapshot_created_at"))
                if (
                    finished is None
                    or snapshot_created is None
                    or offsite_payload.get("success") is not True
                    or offsite_payload.get("backup_id") != manifest.get("backup_id")
                    or offsite_payload.get("manifest_sha256") != manifest_digest
                    or not offsite_payload.get("remote_snapshot_id")
                ):
                    continue
                if snapshot_created != created or finished > now:
                    continue
                manifest = manifest | {
                    "offsite_finished_at": offsite_payload.get("finished_at"),
                    "remote_snapshot_id": offsite_payload.get("remote_snapshot_id"),
                    "manifest_sha256": manifest_digest,
                }
            elif marker.is_file():
                try:
                    marker_payload = json.loads(marker.read_text(encoding="utf-8"))
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    marker_payload = None
                manifest = manifest | {
                    "offsite_available": bool(
                        isinstance(marker_payload, dict)
                        and marker_payload.get("success") is True
                        and marker_payload.get("backup_id") == manifest.get("backup_id")
                        and marker_payload.get("manifest_sha256") == manifest_digest
                        and marker_payload.get("remote_snapshot_id")
                    )
                }
            candidates.append((created, manifest_path.parent, manifest))
        except (OSError, AttributeError, TypeError, ValueError, json.JSONDecodeError):
            continue
    if not candidates:
        return None
    created, path, manifest = max(candidates, key=lambda item: item[0])
    result = {
        "path": str(path),
        "created_at": created.isoformat(),
        "snapshot_created_at": created.isoformat(),
        "data_age_seconds": round(max(0.0, (now - created).total_seconds()), 3),
        "age_seconds": round(max(0.0, (now - created).total_seconds()), 3),
        "backup_id": manifest.get("backup_id"),
        "manifest_sha256": manifest.get("manifest_sha256") or _manifest_digest(path / "manifest.json"),
        "release_id": manifest.get("release_id", "unknown"),
        "offsite_available": bool(manifest.get("offsite_available")),
    }
    if offsite:
        finished = _parse_time(manifest.get("offsite_finished_at"))
        result["offsite_finished_at"] = finished.isoformat() if finished else None
        result["upload_age_seconds"] = round(
            max(0.0, (now - finished).total_seconds()), 3
        ) if finished else None
        result["remote_snapshot_id"] = manifest.get("remote_snapshot_id")
        result["validation"] = "receipt_bound_to_manifest"
    return result


def collect_health(
    config_path: str | Path | None = None,
    *,
    readiness: bool = False,
    allow_maintenance: bool = False,
) -> dict[str, Any]:
    """Collect a secret-free, local-only health snapshot."""
    settings = load_settings(config_path, fallback_to_empty=True)
    database_path = settings.intelligence_database_path.expanduser().resolve()
    enabled = settings.intelligence_enabled
    report: dict[str, Any] = {
        "status": "disabled" if not enabled else "healthy",
        "readiness": readiness,
        "allow_maintenance": allow_maintenance,
        "release_id": os.environ.get("TRENDRADAR_RELEASE_ID", "unknown")[:128],
        "database_path": str(database_path),
        "intelligence_enabled": enabled,
        "schema_expected": EXPECTED_SCHEMA,
        "sqlite_synchronous": settings.intelligence_sqlite_synchronous,
        "config": {
            "lark_enabled": bool(settings.lark_config.get("enabled")),
            "lark_identity_fields": len(settings.lark_config.get("identity_fields") or {}),
            "lark_delivery_enabled": bool(
                settings.lark_config.get("delivery_enabled")
            ),
            "gemini_enabled": settings.gemini_enabled,
            "research_enabled": bool(settings.intelligence_research_config.get("enabled")),
        },
    }
    guard = read_guard(database_path)
    if guard is not None:
        report["maintenance"] = guard
        report["status"] = "maintenance" if guard.get("valid") else "unhealthy"
    if not enabled:
        if readiness:
            report["errors"] = ["intelligence_disabled"]
            report["status"] = "unhealthy"
        return report
    pending_restore = pending_restore_transactions(database_path)
    if pending_restore:
        report["restore_transactions"] = pending_restore
        report.setdefault("errors", []).append("incomplete_restore_transaction")
        report["status"] = "unhealthy"
    database, database_error = _read_only(database_path)
    report["database"] = database
    if database_error:
        report["status"] = "unhealthy"
        report["errors"] = [database_error]
    ai_config = settings.yaml_value("ai_frontier", {})
    ai_enabled = isinstance(ai_config, Mapping) and bool(ai_config.get("enabled"))
    report["config"]["ai_frontier_enabled"] = ai_enabled
    if ai_enabled:
        ai_database, ai_error = _read_only_ai(settings.ai_frontier_database_path.expanduser().resolve())
        report["ai_frontier_database"] = ai_database
        if ai_error:
            report.setdefault("errors", []).append(f"ai_frontier:{ai_error}")
            report["status"] = "unhealthy"
    warnings: list[str] = []
    health_config = settings.intelligence_health_config
    expected_roles = health_config.get("expected_roles") or []
    heartbeats, heartbeat_warnings, heartbeat_errors = _heartbeats(
        database_path,
        expected_roles=expected_roles,
        stale_seconds=int(health_config["heartbeat_max_age_seconds"]),
        expected_release_id=report["release_id"],
    )
    report["heartbeats"] = heartbeats
    warnings.extend(heartbeat_warnings)
    if heartbeat_errors:
        report.setdefault("errors", []).extend(heartbeat_errors)
        report["status"] = "unhealthy"
    if heartbeats:
        strategies = {str(item.get("sqlite_synchronous")) for item in heartbeats.values()}
        report["heartbeat_sqlite_synchronous"] = sorted(strategies)
        for role in expected_roles:
            actual = heartbeats.get(role, {}).get("sqlite_synchronous")
            if actual != settings.intelligence_sqlite_synchronous:
                report.setdefault("errors", []).append(
                    f"sqlite_policy_mismatch:{role}:{actual or 'unknown'}"
                )
                report["status"] = "unhealthy"

    if database:
        now = _utc_now()
        pending_oldest = _parse_time(database.get("pending_oldest_at"))
        if pending_oldest is not None:
            wait = max(0.0, (now - pending_oldest).total_seconds())
            report["queue_wait_seconds"] = round(wait, 3)
            if wait > int(health_config["queue_wait_seconds"]):
                warnings.append("queue_wait_exceeded")
        source_runs = database.get("source_runs") or {}
        expected_sources = health_config.get("expected_sources") or list(source_runs)
        if health_config["require_source_runs"] and not expected_sources:
            report.setdefault("errors", []).append("source_runs_unverified")
            report["status"] = "unhealthy"
        source_age = int(health_config["source_max_age_hours"]) * 3600
        report["source_health"] = source_runs
        for source in expected_sources:
            run = source_runs.get(source)
            if run is None:
                message = f"missing_source_run:{source}"
                (report.setdefault("errors", []) if health_config["require_source_runs"] else warnings).append(message)
                if health_config["require_source_runs"]:
                    report["status"] = "unhealthy"
                continue
            finished = _parse_time(run.get("finished_at"))
            if str(run.get("status")) not in {"healthy", "degraded"}:
                warnings.append(f"source_unhealthy:{source}")
            if finished is None or (now - finished).total_seconds() > source_age:
                warnings.append(f"stale_source:{source}")

    backup_dir = Path(str(health_config["backup_dir"])).expanduser()
    if not backup_dir.is_absolute():
        backup_dir = database_path.parent.parent / backup_dir
    local_backup = _latest_backup(backup_dir)
    offsite_backup = _latest_backup(backup_dir, offsite=True)
    report["backups"] = {"local": local_backup, "offsite": offsite_backup}
    backup_age = int(health_config["backup_max_age_hours"]) * 3600
    if health_config["require_backup"]:
        if local_backup is None or local_backup["age_seconds"] > backup_age:
            warnings.append("backup_overdue:local")
        if offsite_backup is None or offsite_backup["data_age_seconds"] > backup_age:
            warnings.append("backup_overdue:offsite")
    try:
        usage = shutil.disk_usage(database_path.parent)
        report["disk"] = {
            "total_bytes": usage.total,
            "free_bytes": usage.free,
            "used_ratio": round((usage.total - usage.free) / usage.total, 4)
            if usage.total
            else None,
        }
        if usage.total and (usage.total - usage.free) / usage.total >= 0.9:
            warnings.append("disk_usage_high")
    except OSError:
        warnings.append("disk_usage_unavailable")
    report["database_files"] = {
        "database_bytes": database_path.stat().st_size if database_path.is_file() else 0,
        "wal_bytes": database_path.with_name(database_path.name + "-wal").stat().st_size
        if database_path.with_name(database_path.name + "-wal").is_file()
        else 0,
        "shm_bytes": database_path.with_name(database_path.name + "-shm").stat().st_size
        if database_path.with_name(database_path.name + "-shm").is_file()
        else 0,
    }
    if warnings:
        report["warnings"] = warnings
        if report["status"] == "healthy":
            report["status"] = "degraded"
    if readiness:
        if report["status"] == "disabled" or (
            report["status"] == "maintenance" and not allow_maintenance
        ):
            report.setdefault("errors", []).append("runtime_not_accepting_work")
            report["status"] = "unhealthy"
        release_id = report["release_id"]
        if not release_id or release_id in {"unknown", "replace-with-release-id"}:
            report.setdefault("errors", []).append("release_id_unverified")
            report["status"] = "unhealthy"
        if not expected_roles:
            report.setdefault("errors", []).append("expected_roles_not_configured")
            report["status"] = "unhealthy"
        if health_config["require_backup"]:
            for marker in ("backup_overdue:local", "backup_overdue:offsite"):
                if marker in warnings:
                    report.setdefault("errors", []).append(marker)
                    report["status"] = "unhealthy"
        if health_config["require_source_runs"]:
            for warning in warnings:
                if warning.startswith(("missing_source_run:", "stale_source:", "source_unhealthy:")):
                    report.setdefault("errors", []).append(warning)
                    report["status"] = "unhealthy"
        if "queue_wait_exceeded" in warnings:
            report.setdefault("errors", []).append("queue_wait_exceeded")
            report["status"] = "unhealthy"
    return report


def _exit_code(status: str) -> int:
    return {"healthy": 0, "degraded": 1, "disabled": 0, "maintenance": 0, "unhealthy": 2}.get(status, 2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only TrendRadar health check")
    parser.add_argument("--config", help="YAML path; defaults to CONFIG_PATH or config/config.yaml")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--readiness",
        action="store_true",
        help="Apply the production readiness gate; disabled/maintenance is not ready",
    )
    parser.add_argument(
        "--allow-maintenance",
        action="store_true",
        help="Keep the maintenance status while checking deployment prerequisites",
    )
    args = parser.parse_args(argv)
    report = collect_health(
        args.config,
        readiness=args.readiness,
        allow_maintenance=args.allow_maintenance,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    else:
        print(f"TrendRadar health: {report['status']}")
        print(f"Database: {report['database_path']}")
        if report.get("database"):
            print(f"Schema: {report['database'].get('schema')} / expected {EXPECTED_SCHEMA}")
        for warning in report.get("warnings", ()):
            print(f"Warning: {warning}")
        for error in report.get("errors", ()):
            print(f"Error: {error}")
    return _exit_code(str(report["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
