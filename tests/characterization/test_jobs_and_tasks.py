"""Generation jobs, canonical tasks, resource lanes, Director pipelines and favorites, as listings."""
from __future__ import annotations


def test_job_and_task_listings_start_empty(server, golden) -> None:
    server.check(golden, "jobs", "GET", "/api/v1/jobs")
    server.check(golden, "jobs recovery", "GET", "/api/v1/jobs/recovery")
    server.check(golden, "tasks", "GET", "/api/v1/tasks", params={"workspace": "default"})
    server.check(golden, "tasks all", "GET", "/api/v1/tasks", params={"workspace": "default", "status": "all"})
    server.check(golden, "task missing", "GET", "/api/v1/tasks/task-does-not-exist")
    server.check(golden, "resources", "GET", "/api/v1/resources")
    server.check(golden, "director pipelines", "GET", "/api/v1/director/pipelines")
    server.check(golden, "director pipelines active", "GET", "/api/v1/director/pipelines/active")
    server.check(golden, "director v2 plan jobs", "GET", "/api/v1/director/v2/plan/jobs")
    server.check(golden, "job status missing", "GET", "/api/v1/status/job-does-not-exist")


def test_favorites_toggle(server, golden) -> None:
    (server.outputs / "golden_clip.mp4").write_bytes(b"not really a video")
    server.check(golden, "favorites empty", "GET", "/api/v1/favorites")
    server.check(golden, "favorite on", "POST", "/api/v1/favorites/golden_clip.mp4")
    server.check(golden, "favorites one", "GET", "/api/v1/favorites")
    server.check(golden, "favorite off", "POST", "/api/v1/favorites/golden_clip.mp4")
    server.check(golden, "favorites empty again", "GET", "/api/v1/favorites")


def test_unknown_route(server, golden) -> None:
    server.check(golden, "unknown api route", "GET", "/api/v1/does-not-exist")


def test_director_plan_and_pipeline_reads_reject_a_missing_target(server, golden) -> None:
    """The plan and pipeline-read answers this step moves, before the move."""
    server.check(golden, "director plan prompts need clips", "POST", "/api/v1/director/plan-prompts", json={})
    server.check(
        golden,
        "director plan prompts need a style",
        "POST",
        "/api/v1/director/plan-prompts",
        json={"clips": [{"start": 0, "end": 1}]},
    )
    server.check(
        golden,
        "director plan angle prompts need a style",
        "POST",
        "/api/v1/director/plan-angle-prompts",
        json={},
    )
    server.check(golden, "director saved pipeline missing", "GET", "/api/v1/director/pipelines/missing-pipeline")
    server.check(golden, "director pipeline status missing", "GET", "/api/v1/director/pipeline/missing-pipeline")


def test_task_upsert_keeps_a_terminal_task_terminal(server, golden) -> None:
    """A queued task may jump to completed, and a later active snapshot does not reopen it."""
    body = {
        "id": "core-sync",
        "workspace": "default",
        "status": "queued",
        "title": "Story song",
        "phase": "queued",
        "message": "Waiting",
    }
    server.check(golden, "task upsert queued", "POST", "/api/v1/tasks/upsert", json=body)
    server.check(
        golden,
        "task upsert completed",
        "POST",
        "/api/v1/tasks/upsert",
        json={**body, "status": "completed", "phase": "completed", "message": "Ready"},
    )
    server.check(
        golden,
        "task upsert stays completed",
        "POST",
        "/api/v1/tasks/upsert",
        json={**body, "status": "queued", "phase": "queued", "message": "Waiting again"},
    )
