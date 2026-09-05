import hashlib
import json
import sqlite3

import pytest

from services.task_maintenance import (
    TaskMaintenanceSafetyError,
    apply_task_maintenance,
    preview_task_maintenance,
    restore_task_database_backup,
    task_database_path,
)
from services.task_manager import TASK_SCHEMA_VERSION, TaskRegistry


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _set_updated_at(registry, task, value):
    snapshot = {**task, "updated_at": float(value)}
    with sqlite3.connect(registry.path) as connection:
        connection.execute(
            "UPDATE tasks SET updated_at = ?, snapshot = ? WHERE id = ?",
            (float(value), json.dumps(snapshot), task["id"]),
        )


def test_dry_run_uses_a_copy_and_does_not_mutate_the_source(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    old = registry.create(id="task-old", kind="video", status="completed")
    registry.create(id="task-latest", kind="video", status="completed")
    _set_updated_at(registry, old, 1)
    database = task_database_path(tmp_path)
    before_hash = _sha256(database)

    result = preview_task_maintenance(
        tmp_path, max_age_seconds=0, keep=1, max_events=1,
    )

    assert result["mode"] == "dry-run"
    assert result["source_unchanged"] is True
    assert result["plan"]["tasks"] == 1
    assert _sha256(database) == before_hash
    assert registry.get(old["id"]) is not None


def test_apply_backup_can_restore_every_terminal_snapshot(tmp_path):
    workspace = tmp_path / "workspace"
    registry = TaskRegistry(str(workspace), interrupt_stale=False)
    tasks = [
        registry.create(id=f"task-{index}", kind="video", status="completed")
        for index in range(3)
    ]
    for index, task in enumerate(tasks, start=1):
        _set_updated_at(registry, task, index)

    result = apply_task_maintenance(
        workspace,
        max_age_seconds=0,
        keep=1,
        max_events=100,
    )

    backup = result["backup"]
    assert result["removed_tasks"] == 2
    assert task_database_path(workspace).is_file()
    assert TaskRegistry(str(workspace), interrupt_stale=False).list() == [
        TaskRegistry(str(workspace), interrupt_stale=False).get(tasks[2]["id"])
    ]

    restored_workspace = tmp_path / "restored"
    restored = restore_task_database_backup(
        backup,
        restored_workspace,
        backend_stopped=True,
    )
    restored_registry = TaskRegistry(str(restored_workspace), interrupt_stale=False)
    assert restored["schema_version"] == TASK_SCHEMA_VERSION
    assert {task["id"] for task in restored_registry.list(limit=10)} == {
        task["id"] for task in tasks
    }
    assert all(restored_registry.get(task["id"])["status"] == "completed" for task in tasks)


def test_compaction_is_rejected_before_backup_or_mutation_when_backend_is_live(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    registry.create(id="task-safe", kind="video", status="completed")
    before_hash = _sha256(task_database_path(tmp_path))

    with pytest.raises(TaskMaintenanceSafetyError, match="backend_stopped"):
        apply_task_maintenance(tmp_path, compact=True, backend_stopped=False)

    assert _sha256(task_database_path(tmp_path)) == before_hash
    assert not (tmp_path / ".task-db-backups").exists()
