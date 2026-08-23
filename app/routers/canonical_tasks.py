"""HTTP boundary for the canonical Activity task registry.

The registry, legacy synchronization and worker controls are deliberately
injected.  This keeps the router importable without importing the application
launcher (and, transitively, GPU/model code).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from services.task_identity import canonical_client_task_identity
from services.task_manager import ACTIVE_STATUSES, ALL_STATUSES, bounded_task_preview


TaskRegistryResolver = Callable[[str], Any]


def task_event_cursor(after: object, last_event_id: object) -> int:
    """Resolve the newest valid SSE cursor from query and reconnect state."""

    values: list[int] = []
    for value in (after, last_event_id):
        try:
            values.append(max(0, int(value or 0)))
        except (TypeError, ValueError, OverflowError):
            continue
    return max(values, default=0)


def create_canonical_tasks_router(
    *,
    get_active_workspace: Callable[[], str],
    validate_workspace: Callable[[str], Any],
    registry_for_workspace: TaskRegistryResolver,
    sync_tasks: Callable[[str], None],
    task_status: Callable[[object], str],
    upsert_task: Callable[..., dict],
    control_task: Callable[[dict, str], Any],
) -> APIRouter:
    """Build the canonical task router with explicit application adapters."""

    router = APIRouter()

    def workspace_or_active(workspace: str | None) -> str:
        return get_active_workspace() if workspace is None else workspace

    @router.get("/api/v1/tasks")
    def list_canonical_tasks(
        workspace: str | None = None,
        status: str = "active",
        root_id: str = "",
        limit: int = 200,
    ):
        target = workspace_or_active(workspace)
        sync_tasks(target)
        statuses = set(ACTIVE_STATUSES) if status == "active" else (
            set(ALL_STATUSES)
            if status in {"", "all"}
            else {item.strip() for item in status.split(",")}
        )
        tasks, latest_event_id = registry_for_workspace(target).snapshot(
            statuses=statuses,
            root_id=root_id,
            limit=limit,
        )
        return {
            "workspace": target,
            "tasks": tasks,
            "latest_event_id": latest_event_id,
        }

    @router.post("/api/v1/tasks/upsert")
    def upsert_client_task(body: dict):
        raw = body.get("task") if isinstance(body.get("task"), dict) else body
        workspace = raw.get("workspace") if "workspace" in raw else get_active_workspace()
        validate_workspace(workspace)
        task_id, root_id = canonical_client_task_identity(raw)
        status = task_status(raw.get("status"))
        volatile_detail = raw.get("detailVolatile") is True
        raw_detail = raw.get("detailMessage") or ""
        detail = (
            bounded_task_preview(raw_detail)
            if volatile_detail
            else str(raw_detail)[:8000]
        )
        return upsert_task(
            workspace,
            task_id,
            root_id=root_id,
            event_exclude_fields={"detail"} if volatile_detail else None,
            kind=str(raw.get("kind") or "foreground"),
            workflow="frontend",
            title=str(raw.get("title") or "Maestro activity"),
            status=status,
            phase=str(raw.get("phase") or status),
            message=str(raw.get("error") or raw.get("message") or "Working…"),
            detail=detail,
            current=int(raw.get("current") or 0),
            total=int(raw.get("total") or 0),
            detail_current=int(raw.get("detailCurrent") or 0),
            detail_total=int(raw.get("detailTotal") or 0),
            created_at=(
                float(raw.get("startedAt")) / 1000
                if float(raw.get("startedAt") or 0) > 1e12
                else float(raw.get("startedAt") or time.time())
            ),
            cancelable=False,
            error=(
                {"message": str(raw.get("error")), "retryable": False}
                if raw.get("error")
                else None
            ),
            metadata={
                "adapter": "frontend",
                "client_activity_id": str(raw.get("id") or ""),
                "generation_details": raw.get("generationDetails") or {},
                "token_usage": raw.get("tokenUsage") or {},
            },
        )

    @router.get("/api/v1/tasks/events")
    async def stream_canonical_task_events(
        request: Request,
        workspace: str | None = None,
        after: int = 0,
    ):
        target = workspace_or_active(workspace)
        registry = registry_for_workspace(target)

        async def event_stream():
            cursor = task_event_cursor(after, request.headers.get("last-event-id"))
            yield "retry: 2000\n\n"
            while True:
                if registry.cursor_requires_resync(cursor):
                    marker = await asyncio.to_thread(registry.resync_required_event, cursor)
                    cursor = max(cursor, int(marker["event_id"]))
                    yield (
                        f"id: {cursor}\nevent: task\n"
                        f"data: {json.dumps(marker, ensure_ascii=False)}\n\n"
                    )
                    continue
                events = await asyncio.to_thread(registry.wait_for_events, cursor, 15.0)
                if not events:
                    yield ": keepalive\n\n"
                    continue
                for event in events:
                    cursor = max(cursor, int(event["event_id"]))
                    yield (
                        f"id: {cursor}\nevent: task\n"
                        f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/api/v1/tasks/{task_id}/events")
    def get_canonical_task_events(
        task_id: str,
        workspace: str | None = None,
        after: int = 0,
    ):
        target = workspace_or_active(workspace)
        registry = registry_for_workspace(target)
        if registry.cursor_requires_resync(after):
            marker = registry.resync_required_event(after)
            return {"events": [marker], "resync_required": True}
        return {
            "events": registry.events(task_id, after=after),
            "resync_required": False,
        }

    @router.get("/api/v1/tasks/{task_id}")
    def get_canonical_task(task_id: str, workspace: str | None = None):
        target = workspace_or_active(workspace)
        sync_tasks(target)
        registry = registry_for_workspace(target)
        task = registry.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        children = [
            item
            for item in registry.list(root_id=task["root_id"], limit=500)
            if item.get("parent_id") == task_id
        ]
        return {"task": task, "children": children}

    def require_task(task_id: str, workspace: str | None) -> tuple[str, Any, dict]:
        target = workspace_or_active(workspace)
        registry = registry_for_workspace(target)
        task = registry.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return target, registry, task

    def retry_or_resume(task_id: str, workspace: str | None):
        target, registry, task = require_task(task_id, workspace)
        result = control_task(task, "retry")
        if str(task.get("status") or "") in {"failed", "interrupted", "cancelled"}:
            registry.update(
                task_id,
                status="queued",
                phase="queued",
                message="Resume requested",
                error=None,
                completed_at=None,
                event_type="task.resume_requested",
            )
        sync_tasks(target)
        return {"task": registry.get(task_id), "result": result}

    @router.post("/api/v1/tasks/{task_id}/cancel")
    def cancel_canonical_task(task_id: str, workspace: str | None = None):
        target, registry, task = require_task(task_id, workspace)
        result = control_task(task, "cancel")
        sync_tasks(target)
        return {"task": registry.get(task_id), "result": result}

    @router.post("/api/v1/tasks/{task_id}/retry")
    def retry_canonical_task(task_id: str, workspace: str | None = None):
        return retry_or_resume(task_id, workspace)

    @router.post("/api/v1/tasks/{task_id}/resume")
    def resume_canonical_task(task_id: str, workspace: str | None = None):
        return retry_or_resume(task_id, workspace)

    @router.delete("/api/v1/tasks/{task_id}")
    def dismiss_canonical_task(task_id: str, workspace: str | None = None):
        _target, registry, existing = require_task(task_id, workspace)
        if str((existing.get("metadata") or {}).get("adapter") or "") == "series-assembly":
            return control_task(existing, "discard")
        try:
            deleted = registry.delete(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"deleted": True, "task_id": task_id}

    return router
