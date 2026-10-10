"""Cancel one queued or running job. ``jobs.discard`` does not do this."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from fastapi import HTTPException


_FINISHED = frozenset({"completed", "failed", "cancelled", "discarded"})
_MAX_INTENT = 160


def command_catalog() -> list[dict]:
    return [{
        "name": "jobs.cancel",
        "version": 1,
        "domain": "jobs",
        "mutation": True,
        "description": (
            "Cancel a queued or running job by input.job_id, or by input.workspace and input.intent_id. "
            "A finished job returns 409 already_finished and is left unchanged. "
            "jobs.discard does not cancel; use jobs.cancel for a queued or running job."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "const": 1},
                "input": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "job_id": {"type": "string", "minLength": 1},
                        "workspace": {"type": "string", "minLength": 1},
                        "intent_id": {"type": "string", "minLength": 1, "maxLength": _MAX_INTENT},
                    },
                },
            },
            "required": ["version", "input"],
        },
    }]


def _error(status_code: int, code: str, message: str, **extra: Any) -> HTTPException:
    detail = {"code": code, "message": message, "retryable": status_code >= 500, **extra}
    return HTTPException(status_code, detail)


def _require_input(arguments: Any) -> dict:
    if not isinstance(arguments, dict) or type(arguments.get("version")) is not int or arguments.get("version") != 1:
        raise _error(422, "invalid_command", "jobs.cancel requires version 1")
    if set(arguments) - {"version", "input"}:
        raise _error(422, "invalid_command", "jobs.cancel accepts version and input")
    payload = arguments.get("input")
    if not isinstance(payload, dict):
        raise _error(422, "invalid_command", "jobs.cancel requires input")
    return payload


def _spec(payload: dict) -> dict:
    extra = set(payload) - {"job_id", "workspace", "intent_id"}
    if extra:
        raise _error(422, "invalid_command", "jobs.cancel accepts job_id, or workspace and intent_id")
    job_id = payload.get("job_id")
    workspace = payload.get("workspace")
    intent_id = payload.get("intent_id")
    by_job = job_id is not None
    by_intent = workspace is not None or intent_id is not None
    if by_job == by_intent:
        raise _error(422, "invalid_command", "jobs.cancel takes job_id, or workspace and intent_id, not both")
    if by_job:
        if not isinstance(job_id, str) or not job_id.strip():
            raise _error(422, "invalid_command", "job_id must be a non-empty string")
        return {"job_id": job_id.strip()}
    if not isinstance(workspace, str) or not workspace.strip():
        raise _error(422, "invalid_command", "workspace must be a non-empty string")
    if not isinstance(intent_id, str) or not intent_id.strip() or len(intent_id.strip()) > _MAX_INTENT:
        raise _error(422, "invalid_command", "intent_id must be a non-empty string")
    return {"workspace": workspace.strip(), "intent_id": intent_id.strip()}


def _sync(sync_tasks: Callable[[str], None] | None, workspace: str) -> None:
    if sync_tasks is not None:
        sync_tasks(workspace)


def _task_for_job(job: dict, registry_for: Callable[[str], Any], sync_tasks: Callable[[str], None] | None) -> dict:
    workspace = str(job.get("workspace") or "default")
    _sync(sync_tasks, workspace)
    task_id = str(job.get("task_id") or "")
    if task_id:
        task = registry_for(workspace).get(task_id)
        if isinstance(task, dict):
            return task
    return {
        "id": task_id,
        "workspace": workspace,
        "backend_job_id": str(job.get("id") or job.get("job_id") or ""),
        "status": str(job.get("status") or ""),
        "metadata": {"adapter": "generation"},
    }


def _task_for_intent(spec: dict, registry_for: Callable[[str], Any], sync_tasks: Callable[[str], None] | None) -> dict:
    workspace = spec["workspace"]
    _sync(sync_tasks, workspace)
    registry = registry_for(workspace)
    entry = registry.command_admission(spec["intent_id"])
    if not isinstance(entry, dict):
        raise _error(404, "job_not_found", "No job exists for this intent_id")
    task = registry.get(entry.get("task_id"))
    if not isinstance(task, dict):
        raise _error(404, "job_not_found", "No task exists for this intent_id")
    return task


def _workspace_name(item: object) -> str:
    """``_list_workspaces`` yields ``{"name": ..., "path": ...}``; a plain name also works."""
    if isinstance(item, dict):
        item = item.get("name")
    return str(item or "").strip()


def _scan_job(
    job_id: str,
    registry_for: Callable[[str], Any],
    workspaces: Callable[[], Iterable[dict | str]],
    sync_tasks: Callable[[str], None] | None,
) -> dict | None:
    try:
        names = list(workspaces() or [])
    except Exception:
        return None
    for workspace in names:
        text = _workspace_name(workspace)
        if not text:
            continue
        try:
            _sync(sync_tasks, text)
            tasks = registry_for(text).list(limit=1000)
        except Exception:
            continue
        for task in tasks or []:
            if isinstance(task, dict) and str(task.get("backend_job_id") or "") == job_id:
                return task
    return None


def _find_task(spec, registry_for, workspaces, job_record, sync_tasks) -> tuple[dict, str]:
    if "job_id" in spec:
        job_id = spec["job_id"]
        job = job_record(job_id) if job_record is not None else None
        if isinstance(job, dict):
            return _task_for_job(job, registry_for, sync_tasks), job_id
        found = _scan_job(job_id, registry_for, workspaces, sync_tasks)
        if found is None:
            raise _error(404, "job_not_found", "No job exists with this job_id")
        return found, job_id
    task = _task_for_intent(spec, registry_for, sync_tasks)
    return task, str(task.get("backend_job_id") or "")


def _status_after(result: object, task: dict, registry_for: Callable[[str], Any]) -> str:
    if isinstance(result, dict) and result.get("status"):
        return str(result["status"])
    task_id = str(task.get("id") or "")
    workspace = str(task.get("workspace") or "default")
    if task_id:
        try:
            fresh = registry_for(workspace).get(task_id)
        except Exception:
            fresh = None
        if isinstance(fresh, dict) and fresh.get("status"):
            return str(fresh["status"])
    return str(task.get("status") or "")


def command_handlers(
    control_task: Callable[[dict, str], Any],
    registry_for: Callable[[str], Any],
    workspaces: Callable[[], Iterable[dict | str]],
    job_record: Callable[[str], Any],
    sync_tasks: Callable[[str], None] | None = None,
) -> dict[str, Callable[[Any], dict]]:
    def jobs_cancel(arguments: Any) -> dict:
        spec = _spec(_require_input(arguments))
        task, job_id = _find_task(spec, registry_for, workspaces, job_record, sync_tasks)
        previous = str(task.get("status") or "")
        if previous in _FINISHED:
            raise _error(
                409, "already_finished", f"Job is already {previous}",
                status=previous, job_id=job_id,
            )
        result = control_task(task, "cancel")
        return {
            "status": _status_after(result, task, registry_for),
            "previous_status": previous,
            "job_id": job_id,
        }

    return {"jobs.cancel": jobs_cancel}
