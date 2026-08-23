from __future__ import annotations

import copy

import pytest
from fastapi import FastAPI, HTTPException

from routers.canonical_tasks import create_canonical_tasks_router


class FakeRegistry:
    def __init__(self):
        self.tasks: dict[str, dict] = {}
        self.updated: list[tuple[str, dict]] = []

    def snapshot(self, *, statuses, root_id, limit):
        tasks = [
            copy.deepcopy(task)
            for task in self.tasks.values()
            if task.get("status") in statuses
            and (not root_id or task.get("root_id") == root_id)
        ][:limit]
        return tasks, 17

    def get(self, task_id):
        task = self.tasks.get(task_id)
        return copy.deepcopy(task) if task else None

    def list(self, *, root_id, limit):
        return [
            copy.deepcopy(task)
            for task in self.tasks.values()
            if task.get("root_id") == root_id
        ][:limit]

    def update(self, task_id, **patch):
        self.updated.append((task_id, copy.deepcopy(patch)))
        self.tasks[task_id].update(copy.deepcopy(patch))
        return self.get(task_id)

    def delete(self, task_id):
        task = self.tasks.get(task_id)
        if task and task.get("status") == "running":
            raise ValueError("Active tasks cannot be dismissed")
        return self.tasks.pop(task_id, None) is not None

    def cursor_requires_resync(self, _after):
        return False

    def events(self, task_id, *, after):
        return [{"task_id": task_id, "event_id": after + 1}]


def _app():
    registry = FakeRegistry()
    synced: list[str] = []
    controls: list[tuple[str, str]] = []
    upserts: list[tuple[str, str, dict]] = []

    def upsert(workspace, task_id, **fields):
        upserts.append((workspace, task_id, copy.deepcopy(fields)))
        task = {"id": task_id, "workspace": workspace, **copy.deepcopy(fields)}
        registry.tasks[task_id] = task
        return copy.deepcopy(task)

    def control(task, action):
        controls.append((task["id"], action))
        if not task.get("cancelable") and action == "cancel":
            raise HTTPException(status_code=409, detail="Task does not support cancel")
        return {"accepted": True}

    app = FastAPI()
    app.include_router(create_canonical_tasks_router(
        get_active_workspace=lambda: "default",
        validate_workspace=lambda workspace: workspace,
        registry_for_workspace=lambda _workspace: registry,
        sync_tasks=synced.append,
        task_status=lambda value: str(value or "queued"),
        upsert_task=upsert,
        control_task=control,
    ))
    return app, registry, synced, controls, upserts


def _endpoint(app: FastAPI, path: str, method: str):
    candidates = []
    for route in app.routes:
        candidates.append(route)
        included = getattr(route, "original_router", None)
        if included is not None:
            candidates.extend(included.routes)
    return next(
        route.endpoint
        for route in candidates
        if getattr(route, "path", None) == path
        and method.upper() in getattr(route, "methods", set())
    )


def test_canonical_task_openapi_route_snapshot_is_stable():
    app, *_ = _app()
    paths = app.openapi()["paths"]
    snapshot = {
        path: sorted(method for method in item if method != "parameters")
        for path, item in paths.items()
    }

    assert snapshot == {
        "/api/v1/tasks": ["get"],
        "/api/v1/tasks/events": ["get"],
        "/api/v1/tasks/upsert": ["post"],
        "/api/v1/tasks/{task_id}": ["delete", "get"],
        "/api/v1/tasks/{task_id}/cancel": ["post"],
        "/api/v1/tasks/{task_id}/events": ["get"],
        "/api/v1/tasks/{task_id}/resume": ["post"],
        "/api/v1/tasks/{task_id}/retry": ["post"],
    }
    assert paths["/api/v1/tasks"]["get"]["operationId"].startswith(
        "list_canonical_tasks_"
    )


def test_list_and_upsert_keep_snapshot_and_client_namespace_contracts():
    app, registry, synced, _controls, upserts = _app()
    registry.tasks["task-active"] = {
        "id": "task-active",
        "root_id": "task-active",
        "status": "running",
    }
    listed = _endpoint(app, "/api/v1/tasks", "GET")()
    created = _endpoint(app, "/api/v1/tasks/upsert", "POST")({
        "id": "task-generation-reserved",
        "root_id": "task-director-reserved",
        "status": "running",
        "detailVolatile": True,
        "detailMessage": "token " * 500,
    })

    assert listed == {
        "workspace": "default",
        "tasks": [registry.tasks["task-active"]],
        "latest_event_id": 17,
    }
    assert synced == ["default"]
    assert created["id"] == "task-client-task-generation-reserved"
    assert created["root_id"] == created["id"]
    assert upserts[0][2]["event_exclude_fields"] == {"detail"}
    assert len(created["detail"]) <= 400


def test_task_controls_preserve_404_409_resume_and_delete_behavior():
    app, registry, synced, controls, _upserts = _app()
    registry.tasks.update({
        "task-failed": {
            "id": "task-failed",
            "root_id": "task-failed",
            "status": "failed",
            "cancelable": False,
        },
        "task-running": {
            "id": "task-running",
            "root_id": "task-running",
            "status": "running",
            "cancelable": False,
        },
    })
    get_task = _endpoint(app, "/api/v1/tasks/{task_id}", "GET")
    cancel = _endpoint(app, "/api/v1/tasks/{task_id}/cancel", "POST")
    resume = _endpoint(app, "/api/v1/tasks/{task_id}/resume", "POST")
    dismiss = _endpoint(app, "/api/v1/tasks/{task_id}", "DELETE")

    with pytest.raises(HTTPException) as missing:
        get_task("missing")
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as unsupported:
        cancel("task-running")
    assert unsupported.value.status_code == 409
    resumed = resume("task-failed")
    assert resumed["task"]["status"] == "queued"
    assert registry.tasks["task-failed"]["status"] == "queued"
    assert controls[-1] == ("task-failed", "retry")
    assert synced[-1] == "default"
    with pytest.raises(HTTPException) as active:
        dismiss("task-running")
    assert active.value.status_code == 409
    with pytest.raises(HTTPException) as absent:
        dismiss("missing")
    assert absent.value.status_code == 404
