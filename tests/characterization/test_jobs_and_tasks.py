"""Generation jobs, canonical tasks, resource lanes, Director pipelines and favorites, as listings."""
from __future__ import annotations

import sys

import pytest

CREATED = 1_700_000_000.0
PARAMS = {"model_type": "golden_model", "prompt": "a golden prompt", "generation_mode": "video"}


def _launch():
    """The imported full server module (the harness imports it once per process)."""
    return sys.modules["_launch_runtime"]


@pytest.fixture
def empty_generation_queue():
    """A cancelled queued job with no worker keeps its FIFO entry; start and end each test with none."""
    from services import job_lifecycle

    def clear() -> None:
        with job_lifecycle._generation_queue_condition:
            job_lifecycle._generation_queues.pop(id(_launch()._gen_lock), None)

    clear()
    yield
    clear()


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


def test_story_music_job_missing(server, golden) -> None:
    server.check(
        golden,
        "story music job missing",
        "GET",
        "/api/v1/stories/music-candidates/jobs/minimax-music-000000000000",
    )


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


@pytest.mark.usefixtures("empty_generation_queue")
def test_generation_job_queue_status_and_cancel(server, golden, tmp_path, monkeypatch) -> None:
    """A queued job registered through the shared queue, as the status, listing, task and cancel routes see it.

    The job is built by the server's own job factory and held in the server's
    own registry, FIFO lock and durable queue, so a route answers the same only
    while those are one shared set of objects.
    """
    launch = _launch()
    monkeypatch.setattr(launch._durable_generation_queue, "path", str(tmp_path / "queue.json"))
    job = launch._new_generation_job(dict(PARAMS), "default", job_id="golden-queued", created_at=CREATED)
    monkeypatch.setitem(launch._jobs, "golden-queued", job)
    launch._persist_generation_job(job)
    assert [record["id"] for record in launch._durable_generation_queue.list()] == ["golden-queued"]

    server.check(golden, "queued job status", "GET", "/api/v1/status/golden-queued")
    server.check(golden, "queued job listed", "GET", "/api/v1/jobs")
    server.check(
        golden, "queued job is a canonical task", "GET", "/api/v1/tasks/task-generation-golden-queued",
        params={"workspace": "default"},
    )
    server.check(golden, "queued job is not a recovery leftover", "GET", "/api/v1/jobs/recovery")
    server.check(golden, "cancel the queued job", "POST", "/api/v1/cancel/golden-queued")
    server.check(golden, "cancelled job status", "GET", "/api/v1/status/golden-queued")
    server.check(golden, "cancelled job is no longer listed", "GET", "/api/v1/jobs")
    assert launch._durable_generation_queue.list() == []
    server.check(golden, "cancel a job that does not exist", "POST", "/api/v1/cancel/golden-missing")


@pytest.mark.usefixtures("empty_generation_queue")
def test_running_generation_job_is_cancelled_through_its_abort_state(server, golden, monkeypatch) -> None:
    """A running job's abort state lives in the shared ``_active_gen_states`` dictionary."""
    launch = _launch()
    job = launch._new_generation_job(
        dict(PARAMS), "default", job_id="golden-running", created_at=CREATED, reserve_generation=False,
        publish_task=False,
    )
    monkeypatch.setitem(launch._jobs, "golden-running", job)
    assert launch.try_start(job)
    state: dict = {}
    assert launch.register_abort_state(job, "golden-running", launch._active_gen_states, state)
    assert launch._active_gen_states["golden-running"] is state
    server.check(golden, "running job status", "GET", "/api/v1/status/golden-running", mask=("processing_time_sec",))
    server.check(golden, "cancel the running job", "POST", "/api/v1/cancel/golden-running")
    assert state["abort"] is True
    launch.unregister_abort_state("golden-running", launch._active_gen_states, state)
    assert "golden-running" not in launch._active_gen_states
    server.check(golden, "running job cancelled", "GET", "/api/v1/status/golden-running", mask=("processing_time_sec",))


@pytest.mark.usefixtures("empty_generation_queue")
def test_cancel_helper_answers_for_missing_queued_and_running_jobs(server, golden, monkeypatch) -> None:
    """``_request_generation_cancel`` is what Director cancellation calls."""
    launch = _launch()
    body = {}
    body["missing"] = launch._request_generation_cancel("golden-never-registered")
    queued = launch._new_generation_job(
        dict(PARAMS), "default", job_id="golden-helper-queued", created_at=CREATED, publish_task=False,
    )
    monkeypatch.setitem(launch._jobs, "golden-helper-queued", queued)
    body["queued"] = launch._request_generation_cancel("golden-helper-queued")
    running = launch._new_generation_job(
        dict(PARAMS), "default", job_id="golden-helper-running", created_at=CREATED, reserve_generation=False,
        publish_task=False,
    )
    monkeypatch.setitem(launch._jobs, "golden-helper-running", running)
    assert launch.try_start(running)
    state: dict = {}
    assert launch.register_abort_state(running, "golden-helper-running", launch._active_gen_states, state)
    body["running"] = launch._request_generation_cancel("golden-helper-running")
    assert state["abort"] is True
    launch.unregister_abort_state("golden-helper-running", launch._active_gen_states, state)
    golden.check("cancel helper", 200, server.normalise(body))


@pytest.mark.usefixtures("empty_generation_queue")
def test_manual_generation_job_is_published_with_its_details(server, golden, monkeypatch) -> None:
    """Edit and tool jobs register themselves and answer with a public acceptance."""
    launch = _launch()
    job = {"id": "golden-manual", "workspace": "default", "created_at": CREATED, "status": "queued",
           "progress": 0, "message": "Queued", "output_files": [], "error": None,
           "params": {"prompt": "a manual prompt", "activated_loras": ["/private/path/golden.safetensors"]}}
    registered = launch._register_manual_generation_job(job)
    monkeypatch.setitem(launch._jobs, "golden-manual", registered)
    assert registered is job and launch._jobs["golden-manual"] is job
    golden.check("manual job registered", 200, server.normalise({
        "task_id": job["task_id"], "root_task_id": job["root_task_id"], "params": job["params"],
        "acceptance": launch._generation_job_acceptance(job),
    }))
    server.check(
        golden, "manual job is a canonical task", "GET", "/api/v1/tasks/task-generation-golden-manual",
        params={"workspace": "default"},
    )
    server.check(golden, "manual job status", "GET", "/api/v1/status/golden-manual")
    server.check(golden, "cancel the manual job", "POST", "/api/v1/cancel/golden-manual")


def test_recovery_leftovers_are_read_from_the_durable_queue(server, golden, tmp_path, monkeypatch) -> None:
    """A leftover in the durable queue file shows up in the recovery list and can be discarded."""
    launch = _launch()
    queue = launch._durable_generation_queue
    monkeypatch.setattr(queue, "path", str(tmp_path / "queue.json"))
    queue.upsert({"id": "golden-leftover", "status": "running", "created_at": CREATED,
                  "params": dict(PARAMS), "workspace": "default"})
    server.check(golden, "recovery lists the leftover", "GET", "/api/v1/jobs/recovery")
    server.check(golden, "recovery discard", "POST", "/api/v1/jobs/recovery/discard")
    server.check(golden, "recovery is empty again", "GET", "/api/v1/jobs/recovery")
