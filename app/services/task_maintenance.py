"""Safe inspection, retention, backup and compaction for task registries."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid
from typing import Any

from services.task_manager import TASK_DB_NAME, TaskRegistry


class TaskMaintenanceSafetyError(RuntimeError):
    """Raised before an operation that cannot satisfy the safety contract."""


def task_database_path(workspace_dir: str | os.PathLike[str]) -> Path:
    return Path(workspace_dir).expanduser().resolve() / TASK_DB_NAME


def _readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def _validate_database(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Task database does not exist: {path}")
    with _readonly_connection(path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).lower() != "ok":
            raise TaskMaintenanceSafetyError(f"Task database integrity check failed: {integrity}")
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing = {"tasks", "task_events"} - tables
        if missing:
            raise TaskMaintenanceSafetyError(
                f"Not a task registry database; missing tables: {', '.join(sorted(missing))}"
            )


def _online_backup(source_path: Path, destination_path: Path) -> Path:
    _validate_database(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        raise FileExistsError(f"Backup destination already exists: {destination_path}")
    try:
        with _readonly_connection(source_path) as source:
            with sqlite3.connect(destination_path, timeout=30) as destination:
                source.backup(destination)
        os.chmod(destination_path, 0o600)
        _validate_database(destination_path)
        return destination_path
    except BaseException:
        destination_path.unlink(missing_ok=True)
        raise


def create_task_database_backup(
    workspace_dir: str | os.PathLike[str],
    backup_dir: str | os.PathLike[str] | None = None,
    *,
    label: str = "before-retention",
) -> Path:
    source_path = task_database_path(workspace_dir)
    destination_root = (
        Path(backup_dir).expanduser().resolve()
        if backup_dir is not None
        else source_path.parent / ".task-db-backups"
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = destination_root / (
        f"loreframe-tasks-{label}-{timestamp}-{uuid.uuid4().hex[:8]}.sqlite3"
    )
    return _online_backup(source_path, destination)


def inspect_task_database(workspace_dir: str | os.PathLike[str]) -> dict[str, Any]:
    path = task_database_path(workspace_dir)
    _validate_database(path)
    with _readonly_connection(path) as connection:
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        task_count = int(connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
        event_count = int(connection.execute("SELECT COUNT(*) FROM task_events").fetchone()[0])
        active_count = int(connection.execute(
            "SELECT COUNT(*) FROM tasks WHERE status IN ('created','queued','waiting_resource','running')"
        ).fetchone()[0])
        terminal_count = task_count - active_count
        schema_version = 0
        pruned_through = 0
        if "task_registry_meta" in tables:
            metadata = dict(connection.execute(
                "SELECT key, value FROM task_registry_meta"
            ).fetchall())
            try:
                schema_version = int(metadata.get("schema_version", 0))
            except (TypeError, ValueError, OverflowError):
                schema_version = 0
            try:
                pruned_through = int(metadata.get("events_pruned_through", 0))
            except (TypeError, ValueError, OverflowError):
                pruned_through = 0
    sidecars = [path, Path(f"{path}-wal"), Path(f"{path}-shm")]
    return {
        "database": str(path),
        "schema_version": schema_version,
        "tasks": task_count,
        "active_tasks": active_count,
        "terminal_tasks": terminal_count,
        "events": event_count,
        "events_pruned_through": max(0, pruned_through),
        "bytes": sum(candidate.stat().st_size for candidate in sidecars if candidate.exists()),
    }


def _retention_kwargs(
    *,
    max_age_seconds: float | None,
    keep: int | None,
    max_events: int | None,
) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "max_age_seconds": max_age_seconds,
            "keep": keep,
            "max_events": max_events,
        }.items()
        if value is not None
    }


def preview_task_maintenance(
    workspace_dir: str | os.PathLike[str],
    *,
    max_age_seconds: float | None = None,
    keep: int | None = None,
    max_events: int | None = None,
) -> dict[str, Any]:
    """Plan retention against a temporary consistent snapshot, never the source."""
    workspace = Path(workspace_dir).expanduser().resolve()
    before = inspect_task_database(workspace)
    with tempfile.TemporaryDirectory(prefix="loreframe-task-dry-run-") as temporary:
        preview_workspace = Path(temporary)
        _online_backup(task_database_path(workspace), preview_workspace / TASK_DB_NAME)
        registry = TaskRegistry(str(preview_workspace), interrupt_stale=False)
        plan = registry.prune(
            dry_run=True,
            **_retention_kwargs(
                max_age_seconds=max_age_seconds,
                keep=keep,
                max_events=max_events,
            ),
        )
    after = inspect_task_database(workspace)
    return {
        "mode": "dry-run",
        "source_unchanged": before == after,
        "before": before,
        "plan": plan,
    }


def _checkpoint_database(path: Path, *, truncate: bool) -> tuple[int, int, int]:
    mode = "TRUNCATE" if truncate else "PASSIVE"
    with sqlite3.connect(path, timeout=30, isolation_level=None) as connection:
        connection.execute("PRAGMA busy_timeout=30000")
        row = connection.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
    return tuple(int(value) for value in (row or (0, 0, 0)))


def _compact_database(path: Path) -> tuple[int, int, int]:
    checkpoint = _checkpoint_database(path, truncate=True)
    if checkpoint[0] != 0:
        raise TaskMaintenanceSafetyError(
            "WAL checkpoint is busy; stop the backend completely before compacting"
        )
    with sqlite3.connect(path, timeout=30, isolation_level=None) as connection:
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("VACUUM")
    return checkpoint


def apply_task_maintenance(
    workspace_dir: str | os.PathLike[str],
    *,
    backup_dir: str | os.PathLike[str] | None = None,
    max_age_seconds: float | None = None,
    keep: int | None = None,
    max_events: int | None = None,
    compact: bool = False,
    backend_stopped: bool = False,
) -> dict[str, Any]:
    """Back up, apply retention, checkpoint and optionally compact a registry."""
    if compact and not backend_stopped:
        raise TaskMaintenanceSafetyError(
            "Compaction requires backend_stopped=True after stopping Loreframe Lab"
        )
    workspace = Path(workspace_dir).expanduser().resolve()
    before = inspect_task_database(workspace)
    backup = create_task_database_backup(workspace, backup_dir)
    try:
        registry = TaskRegistry(str(workspace), interrupt_stale=False)
        retention = _retention_kwargs(
            max_age_seconds=max_age_seconds,
            keep=keep,
            max_events=max_events,
        )
        plan = registry.prune(dry_run=True, **retention)
        removed_tasks = registry.prune(dry_run=False, **retention)
        checkpoint = _compact_database(task_database_path(workspace)) if compact else _checkpoint_database(
            task_database_path(workspace), truncate=False,
        )
    except BaseException as error:
        raise TaskMaintenanceSafetyError(
            f"Maintenance failed; the pre-change backup is available at {backup}: {error}"
        ) from error
    after = inspect_task_database(workspace)
    return {
        "mode": "apply",
        "backup": str(backup),
        "plan": plan,
        "removed_tasks": removed_tasks,
        "checkpoint": checkpoint,
        "compacted": compact,
        "before": before,
        "after": after,
    }


def restore_task_database_backup(
    backup_path: str | os.PathLike[str],
    workspace_dir: str | os.PathLike[str],
    *,
    backend_stopped: bool,
    safety_backup_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Atomically restore a validated backup while the backend is stopped."""
    if not backend_stopped:
        raise TaskMaintenanceSafetyError(
            "Restore requires backend_stopped=True after stopping Loreframe Lab"
        )
    source = Path(backup_path).expanduser().resolve()
    _validate_database(source)
    destination = task_database_path(workspace_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    safety_backup = None
    checkpoint = None
    if destination.exists():
        safety_backup = create_task_database_backup(
            destination.parent,
            safety_backup_dir,
            label="before-restore",
        )
        checkpoint = _checkpoint_database(destination, truncate=True)
        if checkpoint[0] != 0:
            raise TaskMaintenanceSafetyError(
                "Restore checkpoint is busy; the backend is still using the task database"
            )
    temporary = destination.with_name(f".{destination.name}.restore-{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        _validate_database(temporary)
        os.replace(temporary, destination)
        for sidecar in (Path(f"{destination}-wal"), Path(f"{destination}-shm")):
            sidecar.unlink(missing_ok=True)
        try:
            directory_fd = os.open(destination.parent, os.O_RDONLY)
        except OSError:
            # Some Windows filesystems do not allow directory handles. The
            # atomic replacement itself remains valid there.
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    restored = TaskRegistry(str(destination.parent), interrupt_stale=False)
    return {
        "mode": "restore",
        "restored_from": str(source),
        "safety_backup": str(safety_backup) if safety_backup else None,
        "checkpoint": checkpoint,
        "schema_version": restored.schema_version(),
        "after": inspect_task_database(destination.parent),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely inspect or maintain Loreframe Lab's canonical task database."
    )
    parser.add_argument("--workspace-dir", required=True, help="Directory containing the task DB")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Plan against a temporary snapshot")
    mode.add_argument("--apply", action="store_true", help="Back up and apply retention")
    mode.add_argument("--restore", metavar="BACKUP", help="Restore a validated backup")
    parser.add_argument("--backup-dir")
    parser.add_argument("--max-age-seconds", type=float)
    parser.add_argument("--keep-terminal", type=int)
    parser.add_argument("--max-events", type=int)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument(
        "--backend-stopped",
        action="store_true",
        help="Explicit confirmation required for compact/restore",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.restore:
        if args.compact:
            parser.error("--compact cannot be combined with --restore")
        result = restore_task_database_backup(
            args.restore,
            args.workspace_dir,
            backend_stopped=args.backend_stopped,
            safety_backup_dir=args.backup_dir,
        )
    elif args.dry_run:
        if args.compact or args.backend_stopped:
            parser.error("--compact/--backend-stopped are only valid with --apply or --restore")
        result = preview_task_maintenance(
            args.workspace_dir,
            max_age_seconds=args.max_age_seconds,
            keep=args.keep_terminal,
            max_events=args.max_events,
        )
    else:
        result = apply_task_maintenance(
            args.workspace_dir,
            backup_dir=args.backup_dir,
            max_age_seconds=args.max_age_seconds,
            keep=args.keep_terminal,
            max_events=args.max_events,
            compact=args.compact,
            backend_stopped=args.backend_stopped,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
