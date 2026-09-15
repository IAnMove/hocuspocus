"""Canonical Activity adapters for the Apple Silicon core/remote profile.

NVIDIA launch injects GPU workers into ``create_canonical_tasks_router``.
Core only has MiniMax jobs plus frontend Activity rows in TaskRegistry.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from services import core_generation_commands, core_remote_image
from services.task_manager import ACTIVE_STATUSES, TERMINAL_STATUSES


def task_status(value: object) -> str:
    raw = str(value or "queued").lower()
    if raw in {"completed", "failed", "cancelled", "interrupted", "created", "queued"}:
        return raw
    if raw in {"paused", "waiting", "waiting_resource"}:
        return "waiting_resource"
    return "running"


def upsert_task(
    workspace: str,
    task_id: str,
    *,
    event_exclude_fields: set[str] | frozenset[str] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    registry = core_generation_commands.registry_for(workspace)
    existing = registry.get(task_id)
    if existing is None:
        return registry.create(
            id=task_id,
            workspace=workspace,
            event_exclude_fields=event_exclude_fields,
            **fields,
        )
    existing_status = str(existing.get("status") or "")
    incoming_status = str(fields.get("status") or existing_status)
    if existing_status in TERMINAL_STATUSES and incoming_status in ACTIVE_STATUSES:
        return existing
    mutable = {
        key: value for key, value in fields.items()
        if key not in {"id", "created_at"} and existing.get(key) != value
    }
    if not mutable:
        return existing
    return registry.update(
        task_id,
        event_exclude_fields=event_exclude_fields,
        **mutable,
    )


def sync_tasks(workspace: str) -> None:
    registry = core_generation_commands.registry_for(workspace)
    tasks, _latest = registry.snapshot(limit=500)
    for task in tasks:
        core_generation_commands.get_task(workspace, str(task.get("id") or ""))


def control_task(task: dict, action: str):
    workspace = str(task.get("workspace") or "default")
    task_id = str(task.get("id") or "")
    job_id = str(task.get("backend_job_id") or "")
    if action != "cancel":
        raise HTTPException(status_code=409, detail=f"Task does not support {action}")
    if job_id:
        cancelled = core_remote_image.cancel_job(job_id)
        if cancelled is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return cancelled
    if not task_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return core_generation_commands.registry_for(workspace).update(
        task_id,
        status="cancelled",
        phase="cancelled",
        force=True,
        event_type="task.cancelled",
    )
