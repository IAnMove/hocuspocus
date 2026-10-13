"""Canonical Activity adapters for the Apple Silicon core/remote profile.

NVIDIA launch injects GPU workers into ``create_canonical_tasks_router``.
Core only has MiniMax jobs plus frontend Activity rows in TaskRegistry.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from services import core_generation_commands, core_remote_image
from services.canonical_task_helpers import task_status, upsert_canonical_task


def upsert_task(
    workspace: str,
    task_id: str,
    *,
    event_exclude_fields: set[str] | frozenset[str] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    registry = core_generation_commands.registry_for(workspace)
    return upsert_canonical_task(
        registry,
        workspace,
        task_id,
        event_exclude_fields=event_exclude_fields,
        **fields,
    )


def _editor_text(value: object, fallback: str) -> str:
    raw = str(value).strip() if value is not None else ""
    return raw if raw else fallback


def _editor_int(value: object) -> int:
    try:
        return int(value if value is not None else 0)
    except (TypeError, ValueError):
        return 0


def _editor_list(value: object) -> list:
    return list(value) if isinstance(value, list) else []


def _editor_progress(current: int, total: int, percent: object) -> float:
    if total > 0:
        return max(0.0, min(1.0, current / total))
    try:
        value = float(percent if percent is not None else 0) / 100.0
    except (TypeError, ValueError):
        value = 0.0
    return max(0.0, min(1.0, value))


def _editor_output_files(snapshot: dict) -> list[str]:
    found = []
    for name in _editor_list(snapshot.get("output_files")):
        text = str(name).strip()
        if text:
            found.append(text)
    if found:
        return found
    filename = snapshot.get("filename")
    if filename:
        return [str(filename)]
    return []


def _editor_task_fields(snapshot: dict, adapter: str, status: str, task_id: str) -> dict[str, Any]:
    parent = snapshot.get("parent_task_id")
    workflow = _editor_text(adapter, "video-editor")
    current = _editor_int(snapshot.get("current"))
    total = _editor_int(snapshot.get("total"))
    return {
        "root_id": _editor_text(snapshot.get("root_task_id"), task_id),
        "parent_id": str(parent) if parent else None,
        "kind": "ffmpeg",
        "workflow": workflow,
        "title": "Video editor",
        "status": status,
        "phase": _editor_text(snapshot.get("phase"), status)[:160],
        "message": _editor_text(snapshot.get("message"), status),
        "current": current,
        "total": total,
        "progress": _editor_progress(current, total, snapshot.get("progress")),
        "provider": _editor_text(snapshot.get("provider"), "local"),
        "model": _editor_text(snapshot.get("model"), "FFmpeg"),
        "server_origin": _editor_text(snapshot.get("server_origin"), "local"),
        "resource_requirements": _editor_list(snapshot.get("resource_requirements")),
        "acquired_resources": _editor_list(snapshot.get("acquired_resources")),
        "backend_job_id": _editor_text(snapshot.get("job_id"), ""),
        "cancelable": status in {"created", "queued", "waiting_resource", "running"},
        "result_refs": _editor_output_files(snapshot),
        "metadata": {"adapter": workflow},
    }


def publish_music_activity(job: dict, adapter: str) -> dict | None:
    """Publish one MiniMax Music snapshot into the core Activity registry."""
    if not isinstance(job, dict):
        return None
    task_id = _editor_text(job.get("taskId"), "")
    if not task_id:
        return None
    status = task_status(job.get("status"))
    parent = _editor_text(job.get("parentTaskId"), "") or None
    root = _editor_text(job.get("rootTaskId"), "") or task_id
    title = "MiniMax Music candidate" if adapter == "minimax-music-candidate" else "MiniMax Music"
    return upsert_task(
        _editor_text(job.get("workspace"), "default"),
        task_id,
        root_id=root,
        parent_id=parent,
        kind="music",
        workflow=adapter or "minimax-music",
        title=title,
        status=status,
        phase=_editor_text(job.get("phase"), status)[:160],
        message=_editor_text(job.get("message"), status),
        provider=_editor_text(job.get("provider"), "minimax"),
        model=_editor_text(job.get("model"), ""),
        server_origin=_editor_text(job.get("server_origin"), "https://api.minimax.io"),
        acquired_resources=_editor_list(job.get("acquired_resources")),
        result_refs=_editor_list(job.get("output_files")),
        backend_job_id=_editor_text(job.get("jobId"), ""),
        metadata={"adapter": adapter},
    )


def publish_studio_activity(record: dict, adapter: str) -> dict | None:
    """Publish one Model3D or rig snapshot into the core Activity registry."""
    if not isinstance(record, dict):
        return None
    task_id = _editor_text(record.get("task_id") or record.get("taskId"), "")
    if not task_id:
        return None
    status = task_status(record.get("status"))
    provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    filename = record.get("filename")
    title = "3D model" if adapter == "model3d" else "Rig"
    return upsert_task(
        _editor_text(record.get("workspace"), "default"),
        task_id,
        root_id=_editor_text(record.get("root_task_id") or record.get("rootTaskId"), task_id),
        kind=adapter or "model3d",
        workflow=adapter or "model3d",
        title=title,
        status=status,
        phase=_editor_text(record.get("phase"), status)[:160],
        message=_editor_text(record.get("message"), status),
        provider=_editor_text(record.get("provider"), "local"),
        model=_editor_text(record.get("model_id") or record.get("model") or record.get("engine"), ""),
        backend_job_id=_editor_text(record.get("job_id") or record.get("jobId"), ""),
        result_refs=[str(filename)] if filename else [],
        metadata={
            "adapter": adapter,
            "actor": provenance.get("actor") or "unknown",
            "tool": provenance.get("tool") or adapter,
        },
    )


def publish_video_editor_activity(snapshot: dict, adapter: str) -> dict | None:
    """Publish one video-editor job snapshot into the core Activity registry."""
    task_id = _editor_text(snapshot.get("task_id"), "")
    if not task_id:
        return None
    status = task_status(snapshot.get("status"))
    fields = _editor_task_fields(snapshot, adapter, status, task_id)
    if snapshot.get("created_at"):
        fields["created_at"] = snapshot.get("created_at")
    if snapshot.get("started_at"):
        fields["started_at"] = snapshot.get("started_at")
    if snapshot.get("finished_at"):
        fields["completed_at"] = snapshot.get("finished_at")
    workspace = _editor_text(snapshot.get("workspace"), "default")
    return upsert_task(workspace, task_id, **fields)


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
