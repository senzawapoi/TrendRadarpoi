"""Consistent SQLite snapshots and isolated restore helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trendradar.core.locking import runtime_locks
from trendradar.ops.maintenance import (
    _controller_alive,
    control_directory,
    pending_restore_transactions,
    read_deployment,
    read_guard,
    read_recovery_cutover,
    set_guard,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sync_directory(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _publish_directory(staging: Path, destination: Path) -> None:
    """Publish a new directory on Windows and POSIX without replacing a directory."""
    destination.mkdir()
    try:
        for child in staging.iterdir():
            os.replace(child, destination / child.name)
        staging.rmdir()
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _validate(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = [str(row[0]) for row in connection.execute("PRAGMA foreign_key_check")]
        schema = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(f"database validation failed: {path}")
        return {
            "schema": schema,
            "integrity_check": integrity,
            "foreign_key_errors": foreign_keys,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
    finally:
        connection.close()


def snapshot_database(source: str | Path, target: str | Path, *, timeout_seconds: int = 120) -> dict[str, Any]:
    """Copy a live SQLite database through the Online Backup API."""
    source_path, target_path = Path(source).resolve(), Path(target).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if source_path == target_path:
        raise ValueError("backup target must differ from source")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        raise FileExistsError(target_path)
    temporary = target_path.with_name(f".{target_path.name}.{os.getpid()}.tmp")
    started = _now()
    source_connection = sqlite3.connect(
        source_path.as_uri() + "?mode=ro", uri=True, timeout=5
    )
    target_connection = sqlite3.connect(temporary, timeout=5)
    deadline = time.monotonic() + max(1, timeout_seconds)

    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise TimeoutError("SQLite backup exceeded its time budget")

    try:
        source_connection.backup(target_connection, pages=128, progress=progress, sleep=0.1)
        target_connection.commit()
        target_connection.close()
        target_connection = None
        result = _validate(temporary)
        os.replace(temporary, target_path)
        result.update({"source": str(source_path), "target": str(target_path), "started_at": started, "finished_at": _now()})
        return result
    finally:
        source_connection.close()
        if target_connection is not None:
            target_connection.close()
        with suppress(FileNotFoundError):
            temporary.unlink()


def create_snapshot(
    databases: list[str | Path], destination: str | Path, *, release_id: str = "unknown",
    root: str | Path | None = None,
    target_mapping: list[str | Path] | None = None,
    retention_managed: bool = False,
) -> dict[str, Any]:
    """Create an all-or-nothing local snapshot set and manifest."""
    source_paths = list(dict.fromkeys(Path(path).resolve() for path in databases))
    if not source_paths:
        raise ValueError("at least one database is required")
    destination_path = Path(destination).resolve()
    destination_path.mkdir(parents=True, exist_ok=True)
    backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    final_dir = destination_path / backup_id
    if final_dir.exists():
        raise FileExistsError(final_dir)
    staging = Path(tempfile.mkdtemp(prefix=f".{backup_id}-", dir=destination_path))
    manifest: dict[str, Any] = {
        "backup_id": backup_id,
        "created_at": _now(),
        "release_id": release_id[:128],
        "databases": [],
        "complete": False,
        "retention_managed": retention_managed,
    }
    root_path = Path(root).resolve() if root is not None else None
    if root_path is not None:
        manifest["root"] = str(root_path)
    if target_mapping is not None:
        if root_path is None:
            raise ValueError("target_mapping requires root")
        mapping = []
        for target in target_mapping:
            target_path = Path(target).resolve()
            try:
                relative = target_path.relative_to(root_path).as_posix()
            except ValueError as exc:
                raise ValueError("target mapping escapes root") from exc
            mapping.append({
                "relative_path": relative,
                "present": target_path.is_file(),
            })
        manifest["target_mapping"] = mapping
    try:
        for index, source in enumerate(source_paths):
            target = staging / f"database-{index}.db"
            entry = snapshot_database(source, target)
            entry["file"] = target.name
            entry["target"] = str(final_dir / target.name)
            if root_path is not None:
                entry["relative_path"] = source.relative_to(root_path).as_posix()
            manifest["databases"].append(entry)
        manifest["complete"] = True
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(staging, final_dir)
        return manifest | {"path": str(final_dir)}
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def discover_databases(root: str | Path = "output") -> list[Path]:
    """Find the unified, AI Frontier, and date-partitioned legacy databases."""
    output = Path(root).expanduser().resolve()
    unified = output / "intelligence.db"
    if not unified.is_file():
        raise FileNotFoundError(f"required intelligence database is missing: {unified}")
    candidates = [
        unified,
        output / "ai_frontier.db",
    ]
    for directory in (output / "news", output / "rss"):
        if directory.is_dir():
            candidates.extend(sorted(directory.glob("*.db")))
    return list(dict.fromkeys(path for path in candidates if path.is_file()))


def _manifest_created_at(manifest: dict[str, Any]) -> datetime:
    value = manifest.get("created_at")
    if not isinstance(value, str):
        raise ValueError("snapshot manifest has no valid created_at")
    try:
        created = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("snapshot manifest has no valid created_at") from exc
    if created.tzinfo is None or created.utcoffset() is None:
        raise ValueError("snapshot manifest created_at must be timezone-aware")
    return created.astimezone(timezone.utc)


def _write_restore_journal(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    with temporary.open("r+b") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _sync_directory(path.parent)


def restore_snapshot(
    snapshot: str | Path,
    destination: str | Path,
    *,
    max_age_hours: int | None = None,
    guard_database: str | Path | None = None,
) -> dict[str, Any]:
    """Restore a validated snapshot into a new directory only."""
    snapshot_path, destination_path = Path(snapshot).resolve(), Path(destination).resolve()
    if destination_path.exists():
        raise FileExistsError(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = snapshot_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("complete") is not True:
        raise ValueError("snapshot manifest is incomplete")
    created_at = _manifest_created_at(manifest)
    if max_age_hours is not None:
        if isinstance(max_age_hours, bool) or max_age_hours < 0:
            raise ValueError("max_age_hours must be a non-negative integer")
        age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
        if age_seconds > max_age_hours * 3600:
            raise ValueError("snapshot is older than max_age_hours")
    entries = manifest.get("databases")
    if not isinstance(entries, list) or not entries or any(not isinstance(e, dict) for e in entries):
        raise ValueError("snapshot manifest has no databases")
    guard_path_database = (
        Path(guard_database).expanduser().resolve()
        if guard_database
        else destination_path.parent / ".restore-target.db"
    )
    guard = None
    staging = Path(tempfile.mkdtemp(prefix=f".{destination_path.name}-", dir=destination_path.parent))
    try:
        restored = []
        for index, expected in enumerate(entries):
            source = snapshot_path / f"database-{index}.db"
            target = staging / f"database-{index}.db"
            shutil.copyfile(source, target)
            actual = _validate(target)
            if actual["sha256"] != expected.get("sha256"):
                raise RuntimeError(f"snapshot checksum mismatch: {source}")
            restored.append(expected | actual | {"file": target.name})
        guard = set_guard(guard_path_database, reason=f"restore {snapshot_path.name}")
        restored_manifest = {
            "source": str(snapshot_path),
            "created_at": created_at.isoformat(),
            "databases": restored,
            "complete": True,
            "guard_database": str(guard_path_database),
        }
        # Preserve absent targets so deployment rollback can remove databases
        # created after the snapshot was taken.
        for key in ("root", "target_mapping"):
            if key in manifest:
                restored_manifest[key] = manifest[key]
        (staging / "manifest.json").write_text(
            json.dumps(restored_manifest, indent=2) + "\n", encoding="utf-8"
        )
        _publish_directory(staging, destination_path)
        return {"path": str(destination_path), "databases": restored, "guard": guard}
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def activate_restore(
    restored: str | Path,
    database: str | Path,
    *,
    max_age_hours: int | None = None,
    root: str | Path | None = None,
    index: int | None = None,
    deployment_rollback: bool = False,
) -> dict[str, Any]:
    """Switch one restored database into place while a persistent guard is active."""
    restored_path = Path(restored).expanduser().resolve()
    target = Path(database).expanduser().resolve()
    pending = pending_restore_transactions(target)
    if pending:
        raise RuntimeError(
            "restore activation has an incomplete transaction; inspect recovery-status before retrying"
        )
    guard = read_guard(target)
    if not guard or not guard.get("valid"):
        raise RuntimeError("restore activation requires a valid maintenance guard")
    manifest = json.loads((restored_path / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("complete") is not True:
        raise ValueError("restored manifest is incomplete")
    deployment = None
    if deployment_rollback:
        deployment = _authorize_deployment_rollback(target, restored_path, root, index, manifest)
    created_at = _manifest_created_at(manifest)
    if max_age_hours is not None:
        if isinstance(max_age_hours, bool) or max_age_hours < 0:
            raise ValueError("max_age_hours must be a non-negative integer")
        if (datetime.now(timezone.utc) - created_at).total_seconds() > max_age_hours * 3600:
            raise ValueError("restored snapshot is older than max_age_hours")
    entries = manifest.get("databases")
    if not isinstance(entries, list) or not entries or any(not isinstance(e, dict) for e in entries):
        raise ValueError("restored manifest has no databases")
    selected: list[tuple[Path | None, Path, dict[str, Any] | None]] = []
    if root is not None:
        output_root = Path(root).expanduser().resolve()
        mapping = manifest.get("target_mapping")
        if deployment_rollback and not isinstance(mapping, list):
            raise ValueError("deployment rollback requires a complete target mapping")
        if not isinstance(mapping, list):
            mapping = [
                {"relative_path": entry.get("relative_path"), "present": True}
                for entry in entries
            ]
        by_relative: dict[str, tuple[int, dict[str, Any]]] = {}
        for entry_index, entry in enumerate(entries):
            relative = entry.get("relative_path")
            if not isinstance(relative, str) or relative in by_relative:
                raise ValueError("restored manifest has duplicate database paths")
            by_relative[relative] = (entry_index, entry)
        for mapping_item in mapping:
            if (not isinstance(mapping_item, dict)
                    or not isinstance(mapping_item.get("relative_path"), str)
                    or not isinstance(mapping_item.get("present"), bool)):
                raise ValueError("invalid restored target mapping")
            relative = mapping_item["relative_path"]
            destination_db = (output_root / relative).resolve()
            if not relative or destination_db.suffix != ".db" or output_root not in destination_db.parents:
                raise ValueError("invalid restored database relative_path")
            if mapping_item["present"]:
                entry_data = by_relative.get(relative)
                if entry_data is None:
                    raise ValueError("restored target mapping has no database entry")
                entry_index, entry = entry_data
                selected.append((restored_path / f"database-{entry_index}.db", destination_db, entry))
            else:
                if relative in by_relative:
                    raise ValueError("absent restored target has a database entry")
                selected.append((None, destination_db, None))
        if {item["relative_path"] for item in mapping if item["present"]} != set(by_relative):
            raise ValueError("restored target mapping omits a database entry")
    else:
        if index is None:
            matching = [i for i, entry in enumerate(entries)
                        if Path(str(entry.get("source", ""))).name == target.name]
            if len(matching) == 1:
                index = matching[0]
            elif len(entries) == 1:
                index = 0
            else:
                raise ValueError("select a database with --index or activate the complete set with --root")
        if not 0 <= index < len(entries):
            raise ValueError("invalid database index")
        selected.append((restored_path / f"database-{index}.db", target, entries[index]))
    if len({db for _, db, _ in selected}) != len(selected) or target not in {db for _, db, _ in selected}:
        raise ValueError("restore destinations must be unique and include the guarded database")
    for source, destination_db, expected in selected:
        if source is None:
            continue
        if source == destination_db:
            raise ValueError("restore source must differ from destination")
        if expected is None or _validate(source)["sha256"] != expected.get("sha256"):
            raise RuntimeError("restored database checksum mismatch")
    with runtime_locks(target, "bot", "worker", "scheduler", "collector"):
        if deployment_rollback:
            _authorize_deployment_rollback(target, restored_path, root, index, manifest)
        previous = [db for _, db, _ in selected if db.exists()]
        snapshot_root = (
            Path(root).expanduser().resolve() if root is not None else target.parent
        )
        previous_snapshot = (
            create_snapshot(
                previous,
                target.parent / "pre-restore",
                release_id="pre-restore",
                root=snapshot_root,
                target_mapping=[db for _, db, _ in selected],
            )
            if previous else None
        )
        activation_at = datetime.now(timezone.utc).isoformat()
        prior_cutover = read_recovery_cutover(target) if deployment_rollback else None
        cutover_at = (
            prior_cutover.isoformat() if prior_cutover is not None
            else None if deployment_rollback else activation_at
        )
        guard = set_guard(target, reason=f"activate restore {restored_path.name}",
                          recovery_cutover_at=None if deployment_rollback else cutover_at)
        prepared = []
        moved: list[tuple[Path, Path]] = []
        installed: list[Path] = []
        journal_path = control_directory(target) / (
            f"restore-activation-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
        )
        journal: dict[str, Any] = {
            "state": "prepared",
            "created_at": _now(),
            "database": str(target),
            "runtime_root": str(snapshot_root),
            "restored": str(restored_path),
            "recovery_cutover_at": cutover_at,
            "deployment_rollback": deployment_rollback,
            "deployment_transaction_id": deployment.get("transaction_id") if deployment else None,
            "destinations": [str(destination_db) for _, destination_db, _ in selected],
            "sources": [str(source) if source is not None else None
                        for source, _, _ in selected],
            "temporary": [],
            "retained": [],
            "installed": [],
            "operations": [],
            "current_operation": None,
            "previous_snapshot": previous_snapshot,
            "original_targets": [
                {"path": str(db), "present": db.exists(),
                 "metadata": ({"uid": db.stat().st_uid, "gid": db.stat().st_gid,
                               "mode": stat.S_IMODE(db.stat().st_mode)} if db.exists() else None)}
                for _, db, _ in selected
            ],
        }
        _write_restore_journal(journal_path, journal)
        try:
            for source, destination_db, _expected in selected:
                if source is None:
                    continue
                missing_parents = []
                parent = destination_db.parent
                while not parent.exists():
                    missing_parents.append(parent)
                    parent = parent.parent
                destination_db.parent.mkdir(parents=True, exist_ok=True)
                if os.name != "nt":
                    parent_info = target.parent.stat()
                    for parent in missing_parents:
                        os.chown(parent, parent_info.st_uid, parent_info.st_gid)
                        os.chmod(parent, stat.S_IMODE(parent_info.st_mode))
                fd, temporary = tempfile.mkstemp(prefix=".restore-", dir=destination_db.parent)
                os.close(fd)
                temporary_path = Path(temporary)
                prepared.append((temporary_path, destination_db))
                journal["temporary"].append(str(temporary_path))
                shutil.copyfile(source, temporary_path)
                # mkstemp defaults to root:root/0600 when an operator uses sudo.
                # Apply metadata before publication so service access is atomic.
                reference = destination_db if destination_db.exists() else target
                info = reference.stat() if reference.exists() else destination_db.parent.stat()
                if os.name != "nt":
                    os.chown(temporary_path, info.st_uid, info.st_gid)
                    os.chmod(temporary_path, stat.S_IMODE(info.st_mode) if reference.is_file() else 0o600)
                with temporary_path.open("r+b") as stream:
                    os.fsync(stream.fileno())
            journal["state"] = "installing"
            _write_restore_journal(journal_path, journal)
            prepared_by_destination = {
                destination: temporary for temporary, destination in prepared
            }
            for _source, destination_db, _expected in selected:
                temporary_path = prepared_by_destination.get(destination_db)
                retained_plan = []
                for suffix in ("", "-wal", "-shm"):
                    old_file = Path(str(destination_db) + suffix)
                    if old_file.exists():
                        retained = old_file.with_name(
                            f"{old_file.name}.pre-restore-{activation_at.replace(':', '')}"
                        )
                        retained_plan.append({
                            "original": str(old_file),
                            "retained": str(retained),
                            "completed": False,
                        })
                operation = {
                    "source": str(temporary_path) if temporary_path is not None else None,
                    "destination": str(destination_db),
                    "retained_plan": retained_plan,
                    "installed": False,
                    "removed": temporary_path is None,
                }
                journal["operations"].append(operation)
                journal["current_operation"] = operation
                _write_restore_journal(journal_path, journal)
                for suffix in ("", "-wal", "-shm"):
                    old_file = Path(str(destination_db) + suffix)
                    if old_file.exists():
                        retained = old_file.with_name(
                            f"{old_file.name}.pre-restore-{activation_at.replace(':', '')}"
                        )
                        os.replace(old_file, retained)
                        moved.append((retained, old_file))
                        _sync_directory(old_file.parent)
                        journal["retained"].append({
                            "retained": str(retained),
                            "original": str(old_file),
                        })
                        for planned in retained_plan:
                            if planned["original"] == str(old_file):
                                planned["completed"] = True
                        _write_restore_journal(journal_path, journal)
                if temporary_path is not None:
                    os.replace(temporary_path, destination_db)
                    installed.append(destination_db)
                _sync_directory(destination_db.parent)
                if temporary_path is not None:
                    journal["installed"].append(str(destination_db))
                operation["installed"] = temporary_path is not None
                _write_restore_journal(journal_path, journal)
                journal["current_operation"] = None
                _write_restore_journal(journal_path, journal)
            journal["state"] = "complete"
            journal["completed_at"] = _now()
            _write_restore_journal(journal_path, journal)
        except Exception:
            journal["state"] = "rolling_back"
            _write_restore_journal(journal_path, journal)
            for installed_db in installed:
                installed_db.unlink()
                _sync_directory(installed_db.parent)
            for retained, old_file in reversed(moved):
                os.replace(retained, old_file)
                _sync_directory(old_file.parent)
            journal["state"] = "rolled_back"
            journal["rolled_back_at"] = _now()
            _write_restore_journal(journal_path, journal)
            raise
        finally:
            for temporary_path, _ in prepared:
                with suppress(FileNotFoundError):
                    temporary_path.unlink()
        return {
            "database": str(target),
            "restored_databases": [str(db) for _, db, _ in selected],
            "previous_snapshot": previous_snapshot,
            "guard": guard,
            "recovery_cutover_at": cutover_at,
            "transaction": str(journal_path),
        }


def _authorize_deployment_rollback(
    target: Path, restored: Path, root: str | Path | None, index: int | None,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Bind the replay-preserving path to the live installer's own old snapshot."""
    deployment = read_deployment(target)
    if (not deployment or deployment.get("state") not in {
        "quiesce", "snapshot", "migrate", "switch", "pre_resume", "rollback",
    } or deployment.get("business_boundary_crossed") is not False
            or not _controller_alive(deployment)):
        raise RuntimeError("deployment rollback requires a live pre-business-boundary installer")
    if root is None or index is not None or manifest.get("guard_database") != str(target):
        raise RuntimeError("deployment rollback requires the complete guarded snapshot set")
    snapshot_id = deployment.get("snapshot_id")
    if (not isinstance(snapshot_id, str) or not snapshot_id or snapshot_id in {".", ".."}
            or Path(snapshot_id).name != snapshot_id):
        raise RuntimeError("deployment rollback snapshot identity is invalid")
    snapshot = (Path(os.environ.get("TRENDRADAR_BACKUP_DIR", "output/backups")) / snapshot_id).resolve()
    if manifest.get("source") != str(snapshot):
        raise RuntimeError("deployment rollback snapshot source mismatch")
    runtime_root = Path(root).expanduser().resolve()
    if str(runtime_root) != deployment.get("snapshot_root"):
        raise RuntimeError("deployment rollback runtime root mismatch")
    original = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if (not isinstance(original, dict) or original.get("complete") is not True
            or original.get("backup_id") != snapshot_id
            or original.get("root") != str(runtime_root)
            or manifest.get("root") != str(runtime_root)
            or original.get("target_mapping") != manifest.get("target_mapping")
            or original.get("created_at") != manifest.get("created_at")
            or original.get("release_id") != Path(str(deployment.get("old_target", ""))).name):
        raise RuntimeError("deployment rollback snapshot metadata mismatch")
    old_entries, entries = original.get("databases"), manifest.get("databases")
    if not isinstance(old_entries, list) or not isinstance(entries, list) or len(old_entries) != len(entries):
        raise RuntimeError("deployment rollback snapshot database set mismatch")
    for number, (old_entry, entry) in enumerate(zip(old_entries, entries, strict=True)):
        if (not isinstance(old_entry, dict) or not isinstance(entry, dict)
                or any(old_entry.get(key) != entry.get(key)
                       for key in ("sha256", "relative_path", "schema", "source"))
                or _validate(snapshot / f"database-{number}.db")["sha256"] != entry.get("sha256")):
            raise RuntimeError("deployment rollback snapshot content mismatch")
    return deployment


def recover_restore(database: str | Path) -> dict[str, Any]:
    """Roll back an interrupted activation from its durable pre-restore set."""
    target = Path(database).expanduser().resolve()
    with runtime_locks(target, "bot", "worker", "scheduler", "collector"):
        pending = pending_restore_transactions(target)
        if not pending:
            return {"recovered": False, "pending": []}
        if len(pending) != 1:
            raise RuntimeError("restore recovery requires exactly one valid pending transaction")
        journal = pending[0]
        journal_path = Path(journal["path"])
        if journal.get("database") != str(target) or journal.get("state") not in {
            "prepared", "installing", "rolling_back",
        }:
            raise RuntimeError("restore journal identity or state is invalid")
        original_targets = journal.get("original_targets")
        previous = journal.get("previous_snapshot")
        runtime_value = journal.get("runtime_root", str(target.parent))
        if not isinstance(runtime_value, str) or not runtime_value:
            raise RuntimeError("restore journal runtime root is invalid")
        runtime_root = Path(runtime_value)
        if (not runtime_root.is_absolute() or runtime_root.resolve() != runtime_root
                or runtime_root not in target.parents):
            raise RuntimeError("restore journal runtime root is invalid")
        cutover = journal.get("recovery_cutover_at")
        rollback = journal.get("deployment_rollback", False)
        if not isinstance(rollback, bool):
            raise RuntimeError("restore journal rollback mode is invalid")
        if rollback:
            deployment = read_deployment(target)
            if (not deployment or deployment.get("business_boundary_crossed") is not False
                    or deployment.get("transaction_id") != journal.get("deployment_transaction_id")):
                raise RuntimeError("restore journal deployment rollback identity is invalid")
        if not isinstance(cutover, str) and not (rollback and cutover is None):
            raise RuntimeError("restore journal recovery cutover is invalid")
        try:
            cutover_time = datetime.fromisoformat(cutover.replace("Z", "+00:00")) if cutover else None
        except ValueError as exc:
            raise RuntimeError("restore journal recovery cutover is invalid") from exc
        if cutover_time is not None and (cutover_time.tzinfo is None or cutover_time.utcoffset() is None):
            raise RuntimeError("restore journal recovery cutover must be timezone-aware")
        if not isinstance(original_targets, list) or not original_targets:
            raise RuntimeError("restore journal lacks original target mapping; manual recovery required")
        destinations = journal.get("destinations")
        if any(not isinstance(item, dict) for item in original_targets):
            raise RuntimeError("restore journal original target mapping is invalid")
        if [item.get("path") for item in original_targets] != destinations:
            raise RuntimeError("restore journal target mapping mismatch")
        if (not isinstance(destinations, list) or any(not isinstance(path, str) for path in destinations)
                or len(set(destinations)) != len(destinations)):
            raise RuntimeError("restore journal destinations are invalid")
        for item in original_targets:
            destination = Path(str(item.get("path", "")))
            if (not destination.is_absolute() or str(destination.resolve()) != str(destination)
                    or runtime_root not in destination.parents or destination.suffix != ".db"
                    or not isinstance(item.get("present"), bool)):
                raise RuntimeError("restore journal destination escapes runtime or is invalid")
            if item["present"]:
                metadata = item.get("metadata")
                if not isinstance(metadata, dict) or any(
                    isinstance(metadata.get(key), bool) or not isinstance(metadata.get(key), int)
                    or metadata[key] < 0 for key in ("uid", "gid", "mode")
                ) or metadata["mode"] > 0o777:
                    raise RuntimeError("restore journal original metadata is invalid")
        if str(target) not in destinations:
            raise RuntimeError("restore journal does not include the guarded database")
        snapshots = {}
        if previous is not None:
            if not isinstance(previous, dict) or not isinstance(previous.get("path"), str):
                raise RuntimeError("pre-restore snapshot reference is invalid")
            snapshot_path = Path(previous["path"]).resolve()
            if (target.parent / "pre-restore").resolve() != snapshot_path.parent:
                raise RuntimeError("pre-restore snapshot escapes the retained snapshot directory")
            try:
                manifest = json.loads((snapshot_path / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise RuntimeError("pre-restore snapshot manifest is unavailable or invalid") from exc
            if not isinstance(manifest, dict) or manifest.get("complete") is not True:
                raise RuntimeError("pre-restore snapshot is incomplete")
            if manifest.get("root", str(target.parent)) != str(runtime_root):
                raise RuntimeError("pre-restore snapshot runtime root mismatch")
            mapping = [{"relative_path": Path(item["path"]).relative_to(runtime_root).as_posix(),
                        "present": item["present"]} for item in original_targets]
            if manifest.get("target_mapping") != mapping:
                raise RuntimeError("pre-restore snapshot target mapping mismatch")
            entries = manifest.get("databases")
            if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
                raise RuntimeError("pre-restore snapshot database list is invalid")
            for entry in entries:
                if not isinstance(entry.get("file"), str) or not isinstance(entry.get("source"), str):
                    raise RuntimeError("pre-restore snapshot database mapping is invalid")
                source = (snapshot_path / entry["file"]).resolve()
                if source.parent != snapshot_path or source.suffix != ".db":
                    raise RuntimeError("pre-restore snapshot database escapes snapshot")
                if entry.get("source") not in destinations or entry["source"] in snapshots:
                    raise RuntimeError("pre-restore snapshot source mapping is invalid")
                if _validate(source)["sha256"] != entry.get("sha256"):
                    raise RuntimeError("pre-restore snapshot checksum mismatch")
                snapshots[entry["source"]] = source
        expected_sources = {item["path"] for item in original_targets if item["present"]}
        if set(snapshots) != expected_sources:
            raise RuntimeError("pre-restore snapshot does not match the original database set")
        for item in original_targets:
            if item.get("present") and item["path"] not in snapshots:
                raise RuntimeError("pre-restore snapshot is missing an original database")
        set_guard(target, reason="interrupted restore rollback",
                  recovery_cutover_at=None if rollback else journal.get("recovery_cutover_at"))
        journal["state"] = "rolling_back"
        _write_restore_journal(journal_path, journal)
        for item in original_targets:
            destination = Path(item["path"])
            if item["present"]:
                source = snapshots[item["path"]]
                temporary = destination.with_name(f".rollback-{destination.name}-{os.getpid()}")
                shutil.copyfile(source, temporary)
                if os.name != "nt":
                    metadata = item["metadata"]
                    os.chown(temporary, metadata["uid"], metadata["gid"])
                    os.chmod(temporary, metadata["mode"])
                with temporary.open("r+b") as stream:
                    os.fsync(stream.fileno())
                for suffix in ("-wal", "-shm"):
                    with suppress(FileNotFoundError):
                        Path(str(destination) + suffix).unlink()
                os.replace(temporary, destination)
                _sync_directory(destination.parent)
                _validate(destination)
            else:
                for suffix in ("", "-wal", "-shm"):
                    with suppress(FileNotFoundError):
                        Path(str(destination) + suffix).unlink()
                _sync_directory(destination.parent)
        journal["state"] = "rolled_back"
        journal["rolled_back_at"] = _now()
        _write_restore_journal(journal_path, journal)
        return {"recovered": True, "transaction": str(journal_path), "state": "rolled_back"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TrendRadar SQLite backup tools")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--database", action="append")
    create.add_argument("--root", default="output", help="runtime output root for automatic discovery")
    create.add_argument("--destination", required=True)
    create.add_argument("--release-id", default="unknown")
    create.add_argument("--apply-retention", action="store_true",
                        help="manage scheduled snapshots: 24 hourly, 7 daily, 4 weekly")
    restore = subparsers.add_parser("restore")
    restore.add_argument("--snapshot", required=True)
    restore.add_argument("--destination", required=True)
    restore.add_argument("--max-age-hours", type=int)
    restore.add_argument("--guard-database")
    activate = subparsers.add_parser("activate")
    activate.add_argument("--restored", required=True)
    activate.add_argument("--database", required=True)
    activate.add_argument("--max-age-hours", type=int)
    activate.add_argument("--root", help="activate all databases using manifest relative paths")
    activate.add_argument("--index", type=int)
    activate.add_argument(
        "--deployment-rollback", action="store_true",
        help="restore the live installer's own pre-business-boundary snapshot",
    )
    subparsers.add_parser("recovery-status").add_argument("--database", required=True)
    subparsers.add_parser("recover").add_argument("--database", required=True)
    args = parser.parse_args(argv)
    if args.command == "create":
        if args.apply_retention and args.database:
            parser.error("--apply-retention requires automatic --root discovery")
        databases = args.database or discover_databases(args.root)
        result = create_snapshot(databases, args.destination, release_id=args.release_id,
                                 root=args.root if not args.database else None,
                                 retention_managed=args.apply_retention)
        if args.apply_retention:
            from trendradar.ops.backup_retention import prune_snapshots

            result["retention"] = prune_snapshots(args.destination, args.root)
    elif args.command == "restore":
        guard_database = args.guard_database or os.environ.get("INTELLIGENCE_DB_PATH") or str(
            Path(args.destination).expanduser().resolve().parent / ".restore-target.db"
        )
        result = restore_snapshot(
            args.snapshot,
            args.destination,
            max_age_hours=args.max_age_hours,
            guard_database=guard_database,
        )
    elif args.command == "activate":
        result = activate_restore(
            args.restored,
            args.database,
            max_age_hours=args.max_age_hours,
            root=args.root,
            index=args.index,
            deployment_rollback=args.deployment_rollback,
        )
    elif args.command == "recover":
        result = recover_restore(args.database)
    else:
        result = {"pending": pending_restore_transactions(args.database)}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
