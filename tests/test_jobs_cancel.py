"""jobs.cancel stops a queued or running job and leaves a finished one alone."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.job_leftovers import command_catalog as leftovers_catalog
from services.jobs_cancel import command_catalog, command_handlers
from services.mcp_profiles import GAME_TOOLS, SERIES_TOOLS


class _Registry:
    def __init__(self, tasks):
        self.tasks = {task["id"]: task for task in tasks}
        self.admissions = {}

    def get(self, task_id):
        return self.tasks.get(task_id)

    def list(self, limit=200):
        return list(self.tasks.values())[:limit]

    def command_admission(self, intent_id):
        return self.admissions.get(intent_id)


def _handlers(job=None, registry=None, workspaces=(), control=None, calls=None):
    def control_task(task, action):
        if calls is not None:
            calls.append((task, action))
        if control is not None:
            return control(task, action)
        return {"status": "cancelled"}

    def job_record(job_id):
        if isinstance(job, dict) and job.get("id") == job_id:
            return job
        return None

    registries = registry or _Registry([])
    return command_handlers(
        control_task,
        lambda _workspace: registries,
        lambda: list(workspaces),
        job_record,
    )["jobs.cancel"]


def test_catalog_is_a_version_1_mutation():
    operation = command_catalog()[0]
    assert operation["name"] == "jobs.cancel"
    assert operation["version"] == 1
    assert operation["mutation"] is True
    assert operation["inputSchema"]["required"] == ["version", "input"]
    assert "jobs.cancel" in SERIES_TOOLS
    assert "jobs.cancel" in GAME_TOOLS


def test_discard_points_at_jobs_cancel():
    discard = next(item for item in leftovers_catalog() if item["name"] == "jobs.discard")
    assert "to cancel a queued or running job use jobs.cancel" in discard["description"].lower()


def test_a_queued_job_becomes_cancelled():
    calls = []
    cancel = _handlers({"id": "job-1", "workspace": "lab", "status": "queued"}, calls=calls)
    result = cancel({"version": 1, "input": {"job_id": "job-1"}})
    assert result == {"status": "cancelled", "previous_status": "queued", "job_id": "job-1"}
    assert calls[0][1] == "cancel"
    assert calls[0][0]["backend_job_id"] == "job-1"
    assert calls[0][0]["metadata"]["adapter"] == "generation"


def test_an_intent_resolves_the_running_task():
    registry = _Registry([{"id": "task-9", "workspace": "lab", "backend_job_id": "job-9", "status": "running"}])
    registry.admissions["intent-9"] = {"task_id": "task-9"}
    cancel = _handlers(registry=registry, workspaces=["lab"])
    result = cancel({"version": 1, "input": {"workspace": "lab", "intent_id": "intent-9"}})
    assert result["status"] == "cancelled"
    assert result["previous_status"] == "running"
    assert result["job_id"] == "job-9"


def test_a_finished_job_is_409_and_control_is_not_called():
    calls = []
    cancel = _handlers({"id": "job-done", "workspace": "lab", "status": "completed"}, calls=calls)
    with pytest.raises(HTTPException) as caught:
        cancel({"version": 1, "input": {"job_id": "job-done"}})
    assert calls == []
    assert caught.value.status_code == 409
    detail = caught.value.detail
    assert detail["code"] == "already_finished"
    assert detail["status"] == "completed"
    assert detail["job_id"] == "job-done"


def test_a_missing_job_is_404():
    cancel = _handlers(workspaces=["lab"], registry=_Registry([]))
    with pytest.raises(HTTPException) as caught:
        cancel({"version": 1, "input": {"job_id": "missing"}})
    assert caught.value.status_code == 404
    assert caught.value.detail["code"] == "job_not_found"


def test_job_id_and_intent_together_are_rejected():
    cancel = _handlers()
    with pytest.raises(HTTPException) as caught:
        cancel({"version": 1, "input": {"job_id": "job-1", "workspace": "lab", "intent_id": "intent-1"}})
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "invalid_command"


def test_an_interrupted_job_stays_open_and_can_be_cancelled():
    calls = []
    cancel = _handlers({"id": "job-3", "workspace": "lab", "status": "interrupted"}, calls=calls)
    result = cancel({"version": 1, "input": {"job_id": "job-3"}})
    assert result["previous_status"] == "interrupted"
    assert result["status"] == "cancelled"
    assert len(calls) == 1
