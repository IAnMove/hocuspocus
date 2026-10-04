"""jobs.wait blocks on the existing status payload and does not spin."""
from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import Future

import pytest
from fastapi import HTTPException

from services.job_lifecycle import finish_job
from services.jobs_wait import (
    command_catalog,
    command_handlers,
    normalize_timeout,
    wait_for_job,
)


def _status_of(job: dict) -> dict:
    return {
        "job_id": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "message": job["message"],
        "output_files": list(job.get("output_files") or []),
        "error": job.get("error"),
    }


def _not_found(_job_id: str) -> dict:
    raise HTTPException(status_code=404, detail="Job not found")


def test_wait_returns_when_a_job_completes_without_spinning():
    job = {
        "id": "job-complete",
        "status": "running",
        "progress": 25,
        "message": "Running",
        "output_files": [],
        "error": None,
    }
    calls = []

    def read_status(job_id: str) -> dict:
        calls.append(time.monotonic())
        assert job_id == job["id"]
        return _status_of(job)

    def complete() -> None:
        time.sleep(0.2)
        finish_job(job, "completed", progress=100, message="Done")

    threading.Thread(target=complete, daemon=True).start()
    started = time.monotonic()
    result = wait_for_job(job["id"], 2, read_status=read_status, lookup_job=lambda _job_id: job)
    elapsed = time.monotonic() - started
    assert result["status"] == "completed"
    assert result["progress"] == 100
    assert result["message"] == "Done"
    assert len(calls) <= 4
    assert 0.1 <= elapsed < 1.5


def test_wait_wakes_on_a_job_event_without_spinning():
    event = threading.Event()
    job = {
        "id": "job-event",
        "status": "running",
        "progress": 10,
        "message": "Running",
        "completion": event,
    }
    calls = []

    def read_status(_job_id: str) -> dict:
        calls.append(1)
        return _status_of(job)

    def complete() -> None:
        time.sleep(0.2)
        job["status"] = "completed"
        job["progress"] = 80
        job["message"] = "Done"
        event.set()

    threading.Thread(target=complete, daemon=True).start()
    result = wait_for_job(job["id"], 2, read_status=read_status, lookup_job=lambda _job_id: job)
    assert result == _status_of(job)
    assert result["progress"] == 80
    assert len(calls) <= 4


def test_wait_wakes_on_a_job_future_without_spinning():
    future: Future[None] = Future()
    job = {
        "id": "job-future",
        "status": "running",
        "progress": 3,
        "message": "Running",
        "done": future,
    }
    calls = []

    def read_status(_job_id: str) -> dict:
        calls.append(1)
        return _status_of(job)

    def complete() -> None:
        time.sleep(0.2)
        job["status"] = "completed"
        job["progress"] = 100
        job["message"] = "Done"
        future.set_result(None)

    threading.Thread(target=complete, daemon=True).start()
    result = wait_for_job(job["id"], 2, read_status=read_status, lookup_job=lambda _job_id: job)
    assert result["status"] == "completed"
    assert result["progress"] == 100
    assert len(calls) <= 4


def test_wait_timeout_returns_the_live_status_not_an_error():
    job = {"id": "job-timeout", "status": "running", "progress": 40, "message": "Still running"}
    calls = []

    def read_status(_job_id: str) -> dict:
        calls.append(1)
        return _status_of(job)

    started = time.monotonic()
    result = wait_for_job(job["id"], 0.25, read_status=read_status, lookup_job=lambda _job_id: job)
    elapsed = time.monotonic() - started
    assert result["timed_out"] is True
    assert result["code"] == "timeout"
    assert result["status"] == "running"
    assert result["progress"] == 40
    assert result["retryable"] is True
    assert len(calls) <= 4
    assert 0.2 <= elapsed < 1.5
    # An MCP client must not read a healthy long job as a failure.
    from routers.wangp_mcp import _tool_result_is_error
    assert _tool_result_is_error(result) is False


def test_unknown_job_uses_the_status_not_found_error():
    started = time.monotonic()
    with pytest.raises(HTTPException) as caught:
        wait_for_job("missing", 30, read_status=_not_found, lookup_job=lambda _job_id: None)
    assert time.monotonic() - started < 0.5
    assert caught.value.status_code == 404
    assert caught.value.detail == "Job not found"

    handler = command_handlers(_not_found, lambda _job_id: None)["jobs.wait"]
    with pytest.raises(HTTPException) as handled:
        asyncio.run(handler({"version": 1, "input": {"job_id": "missing"}}))
    assert handled.value.status_code == 404
    assert handled.value.detail == "Job not found"


def test_interrupted_is_not_terminal():
    job = {
        "id": "job-interrupted",
        "status": "interrupted",
        "progress": 15,
        "message": "Generation was interrupted",
    }
    result = wait_for_job(job["id"], 0.2, read_status=lambda _job_id: _status_of(job), lookup_job=lambda _job_id: job)
    assert result["timed_out"] is True
    assert result["status"] == "interrupted"
    assert result["progress"] == 15


def test_discarded_returns_the_status_payload():
    payload = {"job_id": "gone", "status": "discarded", "progress": 0, "message": "Discarded"}
    result = wait_for_job("gone", 30, read_status=lambda _job_id: payload, lookup_job=lambda _job_id: None)
    assert result == payload


def test_timeout_defaults_to_30_and_caps_at_120():
    assert normalize_timeout(None) == 30
    assert normalize_timeout(120) == 120
    assert normalize_timeout(121) == 120
    with pytest.raises(HTTPException) as caught:
        normalize_timeout(0)
    assert caught.value.detail["code"] == "invalid_command"
    with pytest.raises(HTTPException) as caught:
        normalize_timeout(True)
    assert caught.value.detail["code"] == "invalid_command"


def test_catalog_is_versioned_jobs_wait():
    operation = command_catalog()[0]
    assert operation["name"] == "jobs.wait"
    assert operation["version"] == 1
    assert operation["mutation"] is False
    schema = operation["inputSchema"]
    assert schema["properties"]["version"]["const"] == 1
    assert schema["required"] == ["version", "input"]
    assert schema["properties"]["input"]["required"] == ["job_id"]
    assert "timeout_s" in schema["properties"]["input"]["properties"]
