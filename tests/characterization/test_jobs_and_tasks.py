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


def test_the_full_server_builds_one_runtime_context_and_launch_names_its_objects(full_server) -> None:
    """Every shared registry, lock and queue launch still names is the object the context holds."""
    import launch

    ctx = full_server.api.state.runtime
    runtime = _launch()
    assert ctx.profile == "full" and ctx.config.wgp is full_server.wgp
    state = {
        "_jobs": ctx.jobs.registry,
        "_active_gen_states": ctx.jobs.active_states,
        "_gen_lock": ctx.jobs.gen_lock,
        "_local_gpu_lane": ctx.jobs.local_gpu_lane,
        "_queue_recovery_lock": ctx.jobs.recovery_lock,
        "_durable_generation_queue": ctx.jobs.durable_queue,
        "_UPLOAD_TRANSCODE_SLOTS": ctx.paths.transcode_slots,
    }
    for name, shared in state.items():
        assert getattr(runtime, name) is shared, name
        assert getattr(launch, name) is shared, f"launch.{name}"
    handles = {
        "_save_server_config": ctx.config.save,
        "_get_active_workspace": ctx.workspaces.active,
        "_workspace_dir": ctx.workspaces.workspace_dir,
        "_list_workspaces": ctx.workspaces.list,
        "_persist_active_workspace": ctx.workspaces.persist_active,
        "_safe_join": ctx.paths.safe_join,
        "_resolve_output_move_path": ctx.paths.resolve_output_move_path,
        "_resolve_request_media_path": ctx.paths.resolve_request_media_path,
        "_story_cover_reference_path": ctx.paths.story_cover_reference_path,
        "_stream_upload": ctx.paths.stream_upload,
        "_transcode_upload": ctx.paths.transcode_upload,
        "_task_registry": ctx.tasks.for_workspace,
        "_coordinated_generation_slot": ctx.jobs.slot,
        "_is_durable_generation_job": ctx.jobs.is_durable_job,
        "_persist_generation_job": ctx.jobs.persist_job,
        "_remove_persisted_generation_job": ctx.jobs.remove_persisted_job,
        "_new_generation_job": ctx.jobs.new_job,
        "_register_manual_generation_job": ctx.jobs.register_manual_job,
        "_generation_job_acceptance": ctx.jobs.job_acceptance,
        "_public_generation_details": ctx.jobs.public_details,
        "_pending_gpu_jobs": ctx.jobs.pending_gpu_jobs,
        "_request_generation_cancel": ctx.jobs.cancel,
    }
    for name, method in handles.items():
        assert getattr(runtime, name) == method, name
    assert ctx.scheduler is runtime.resource_scheduler.coordinator
    assert runtime._gen_lock is runtime.resource_scheduler.coordinator.shared_lock(runtime._local_gpu_lane)


@pytest.mark.usefixtures("empty_generation_queue")
def test_a_job_added_through_the_context_is_seen_by_the_routes(server, monkeypatch) -> None:
    """The status route reads launch's ``_jobs``; the context's registry is that dictionary."""
    ctx = server.client.app.state.runtime
    job = {"id": "ctx-manual", "workspace": "default", "created_at": CREATED, "status": "queued",
           "progress": 0, "message": "Queued", "output_files": [], "error": None, "params": {"prompt": "p"}}
    monkeypatch.setitem(ctx.jobs.registry, "ctx-manual", job)
    answer = server.client.get("/api/v1/status/ctx-manual")
    assert answer.status_code == 200 and answer.json()["job_id"] == "ctx-manual"
    assert server.client.post("/api/v1/cancel/ctx-manual").json()["status"] == "cancelled"
    assert job["status"] == "cancelled"


def test_audio_analysis_jobs_are_registry_entries_that_either_cancel_route_ends(server, monkeypatch) -> None:
    """An analysis job is an ``audio-analysis-*`` entry of the shared job registry.

    The worker is stubbed (no librosa, no model). The generic ``/cancel`` route hands
    these ids to the audio cancel, a job that waits for the audio lane is cancelled
    at once, and a running one is cancelled after the current phase.
    """
    import threading
    import time

    from services import audio_analysis
    from tests.characterization import media

    registry = server.client.app.state.runtime.jobs.registry
    gate = threading.Event()
    reached_beats = threading.Event()

    def analyze(audio_path, transcribe=False, extract_vocals_for_transcription=True, lyrics_hint=None):
        # The progress callback writes the job on this thread before it returns, so the event below says the
        # job already shows the phase. ``running`` alone does not: it is written first, still in ``loading_audio``.
        audio_analysis._set_progress("detecting_beats", "beats")
        reached_beats.set()
        gate.wait(20)
        return {"duration": 1.0}

    monkeypatch.setattr(audio_analysis, "analyze", analyze)
    media.sound(server.outputs / "first.wav", seconds=1.0)
    media.sound(server.outputs / "second.wav", seconds=1.0)
    jobs = "/api/v1/audio/analyze/jobs"
    started: list[str] = []

    def read(job_id: str) -> dict:
        return server.client.get(f"{jobs}/{job_id}").json()

    def wait_for(job_id: str, states: set[str]) -> dict:
        deadline = time.time() + 15
        while time.time() < deadline:
            job = read(job_id)
            if job["status"] in states:
                return job
            time.sleep(0.05)
        return read(job_id)

    try:
        first = server.client.post(jobs, json={"audio_path": "first.wav", "task_id": "task-mine", "root_task_id": "task-root"})
        assert first.status_code == 200
        first_id = first.json()["job_id"]
        started.append(first_id)
        assert first_id.startswith("audio-analysis-")
        assert first.json() == {
            "job_id": first_id, "task_id": "task-mine", "root_task_id": "task-root",
            "parent_task_id": None, "status": "queued",
        }
        assert registry[first_id]["id"] == first_id and registry[first_id]["task_id"] == "task-mine"

        assert reached_beats.wait(15), "the first analysis never reached its beat detection"
        running = read(first_id)
        assert (running["status"], running["phase"], running["step"], running["progress"]) == ("running", "detecting_beats", 2, 20)

        second = server.client.post(jobs, json={"audio_path": "second.wav"})
        second_id = second.json()["job_id"]
        started.append(second_id)
        waiting = wait_for(second_id, {"waiting_resource"})
        assert waiting["status"] == "waiting_resource" and waiting["message"] == "Waiting for audio CPU worker"
        cancelled = server.client.post(f"{jobs}/{second_id}/cancel")
        assert cancelled.json()["status"] == "cancelled"
        assert read(second_id)["message"] == "Cancelled before analysis started"
        assert registry[second_id]["_cancel_requested"] is True

        generic = server.client.post(f"/api/v1/cancel/{first_id}")
        assert (generic.status_code, generic.json()["status"]) == (200, "cancelling")
        after = read(first_id)
        assert (after["status"], after["phase"]) == ("cancelling", "cancelling")
        assert after["message"] == "Cancelling after the current analysis phase…"
        assert registry[first_id]["_cancel_requested"] is True

        gate.set()
        final = wait_for(first_id, {"cancelled", "completed", "failed"})
        assert (final["status"], final["message"], final["result"]) == ("cancelled", "Cancelled", None)
        again = server.client.post(f"{jobs}/{first_id}/cancel")
        assert again.json() == {"job_id": first_id, "status": "cancelled"}
        assert server.client.get(f"{jobs}/{first_id}", params={"workspace": "elsewhere"}).status_code == 404
        assert server.client.post(f"{jobs}/{first_id}/cancel", params={"workspace": "elsewhere"}).status_code == 404
    finally:
        gate.set()
        time.sleep(0.2)
        for job_id in started:
            registry.pop(job_id, None)
        assert not [key for key in registry if key.startswith("audio-analysis-")]


def test_the_audio_and_scene_modules_hold_the_objects_launch_names(full_server) -> None:
    """Late binding: what launch assigns to the moved modules is the object launch itself holds.

    The audio routes read ``_jobs`` and the lock; the worker publishes through the task
    publisher launch defines late; the recording route reads the gallery scan cache, which
    launch creates after the scene routes are included; the scene helpers read the kit
    library launch imports last. A name still ``None`` here would fail on the first request.
    """
    import routers.audio as audio
    import routers.scenes_favorites as scenes
    import services.audio_jobs as audio_jobs
    import services.output_listing as listing
    import services.scene_favorites as favorites

    runtime = _launch()
    registry = full_server.api.state.runtime.jobs.registry
    assert audio._jobs is registry and audio_jobs._jobs is registry and runtime._jobs is registry
    assert audio._audio_analysis_jobs_lock is audio_jobs._audio_analysis_jobs_lock
    assert not hasattr(runtime, "_audio_analysis_jobs_lock")
    assert audio_jobs._publish_generic_legacy_task is runtime._publish_generic_legacy_task
    assert runtime.cancel_audio_analysis_job is audio.cancel_audio_analysis_job
    assert audio._stream_upload is runtime._stream_upload and audio._transcode_upload is runtime._transcode_upload
    assert audio._get_active_workspace == runtime._get_active_workspace
    assert audio._resolve_request_media_path == runtime._resolve_request_media_path
    assert audio._safe_join == runtime._safe_join and audio._workspace_dir == runtime._workspace_dir
    assert audio.wgp is runtime.wgp
    assert scenes._workspace_dir == runtime._workspace_dir and scenes._safe_join == runtime._safe_join
    assert scenes._stream_upload is runtime._stream_upload
    assert scenes._UPLOAD_TRANSCODE_SLOTS is runtime._UPLOAD_TRANSCODE_SLOTS
    assert scenes._output_scan_cache is listing._output_scan_cache and scenes._output_scan_cache is runtime._output_scan_cache
    assert scenes._output_scan_cache_lock is listing._output_scan_cache_lock
    assert favorites._workspace_dir == runtime._workspace_dir
    assert favorites._get_active_workspace == runtime._get_active_workspace
    assert favorites._read_kit_library is runtime._read_kit_library
    assert runtime._load_favorites is favorites._load_favorites and listing._load_favorites is favorites._load_favorites


def _plain_job(job_id: str, **fields: object) -> dict:
    """One idle registry record. No worker, no process, fixed clock."""
    job = {
        "id": job_id,
        "jobId": job_id,
        "workspace": "default",
        "status": "queued",
        "phase": "queued",
        "stage": "queued",
        "message": "Waiting",
        "created_at": CREATED,
        "createdAt": CREATED,
        "current": 0,
        "total": 0,
        "progress": 0,
    }
    job.update(fields)
    return job


@pytest.mark.usefixtures("empty_generation_queue")
def test_canonical_sync_lists_every_kind_and_control_answers(server, golden, tmp_path, monkeypatch) -> None:
    """One Activity sync walks every registry the canonical cluster still reads.

    Recorded on the unchanged server. Every seeded job is idle: cancel settles in
    this thread. Resume is asked only where the adapter returns before it starts a
    worker (a completed Series plan, a comic plan with no saved request, a
    generation task). A disk-only Director pipeline is not a live pipeline, and
    the assembly controller was registered for the server's original outputs
    folder, so those cancels are the current 404s. The reset is read from the
    registry before another sync can publish over it.
    """
    import json

    from services import model3d_service, rig_service
    from services.series_jobs import SeriesJobStore
    import routers.comics as comics
    import routers.video_editor as video_editor

    launch = _launch()
    # ``test_manual_generation_job_is_published_with_its_details`` inserts this
    # job into the shared registry before monkeypatch owns the key, then
    # cancels it and leaves the cancelled record behind. Drop it so this sync
    # lists only the jobs seeded below, in either test order.
    launch._jobs.pop("golden-manual", None)
    monkeypatch.setattr(launch._durable_generation_queue, "path", str(tmp_path / "queue.json"))
    generation = launch._new_generation_job(
        dict(PARAMS), "default", job_id="golden-gen", created_at=CREATED, publish_task=False,
    )
    monkeypatch.setitem(launch._jobs, "golden-gen", generation)
    audio = _plain_job(
        "audio-analysis-golden",
        jobId="audio-analysis-golden",
        task_id="task-audio-analysis-golden",
        message="Waiting for audio CPU worker",
    )
    monkeypatch.setitem(launch._jobs, audio["id"], audio)
    plan = _plain_job("golden-plan", message="Waiting to plan an episode", seriesId="series-golden", episodeId="episode-golden")
    done = _plain_job(
        "golden-plan-done", status="completed", phase="completed", stage="completed",
        message="Episode planning finished", seriesId="series-golden", episodeId="episode-done",
        finishedAt=CREATED,
    )
    render = _plain_job(
        "golden-render", message="Waiting to render", seriesId="series-golden",
        episodeId="episode-golden", items=[],
    )
    monkeypatch.setitem(launch._series_plan_jobs, plan["jobId"], plan)
    monkeypatch.setitem(launch._series_plan_jobs, done["jobId"], done)
    monkeypatch.setitem(launch._series_render_jobs, render["jobId"], render)
    story = _plain_job("golden-story", message="Waiting to plan a story")
    comic = _plain_job("golden-comic", message="Waiting to plan a comic")
    monkeypatch.setitem(launch._story_plan_jobs, story["jobId"], story)
    monkeypatch.setitem(launch._comic_plan_jobs, comic["jobId"], comic)
    editor = _plain_job("golden-editor", message="Waiting for FFmpeg")
    image = _plain_job("golden-image", message="Waiting for MiniMax Image")
    monkeypatch.setitem(video_editor._video_editor_jobs, editor["id"], editor)
    monkeypatch.setitem(comics._minimax_image_jobs, image["jobId"], image)
    music = _plain_job(
        "minimax-music-aabbccddeeff",
        message="Waiting for MiniMax Music",
        children=[_plain_job("golden-candidate", message="Waiting for a candidate", parentTaskId="task-minimax-music-minimax-music-aabbccddeeff")],
    )
    monkeypatch.setitem(launch._minimax_music_jobs, music["jobId"], music)
    monkeypatch.setitem(model3d_service._jobs, "golden-model3d", _plain_job("golden-model3d", message="Waiting for Hunyuan"))
    monkeypatch.setitem(rig_service._jobs, "golden-rig", _plain_job("golden-rig", engine="procedural", message="Waiting to rig"))
    SeriesJobStore(launch._workspace_dir("default"), "assembly").save(_plain_job(
        "golden-assembly", message="Waiting to join clips", seriesId="series-golden", episodeId="episode-golden",
    ))
    (server.outputs / "_director_pipeline_golden-director.json").write_text(json.dumps({
        "pipeline_id": "golden-director",
        "status": "completed",
        "phase": "completed",
        "pipeline_type": "music_video",
        "generation_mode": "image_guided",
        "created_at": CREATED,
        "updated_at": CREATED,
        "completed_at": CREATED,
        "progress": {"current": 1, "total": 1, "message": "Director finished"},
        "scene_description": "a golden scene",
        "output_files": [],
    }), encoding="utf-8")

    server.check(golden, "canonical sync every kind", "GET", "/api/v1/tasks", params={"workspace": "default", "status": "all"})
    productions = server.check(golden, "productions of the seeded pipeline", "GET", "/api/v1/productions", params={"workspace": "default"})
    production_id = productions.json()["productions"][0]["id"]
    run_id = productions.json()["productions"][0]["run_ids"][0]
    server.check(golden, "one production", "GET", f"/api/v1/productions/{production_id}")
    server.check(golden, "runs of the seeded pipeline", "GET", "/api/v1/runs", params={"workspace": "default"})
    server.check(golden, "one run", "GET", f"/api/v1/runs/{run_id}")
    server.check(golden, "production missing", "GET", "/api/v1/productions/production-does-not-exist")
    server.check(golden, "productions unknown workspace", "GET", "/api/v1/productions", params={"workspace": "missing-workspace"})

    workspace = {"workspace": "default"}
    for case, task_id in (
        ("cancel generation", "task-generation-golden-gen"),
        ("cancel audio analysis", "task-audio-analysis-golden"),
        ("cancel series plan", "task-series-plan-golden-plan"),
        ("cancel series render", "task-series-render-golden-render"),
        ("cancel story plan", "task-story-plan-golden-story"),
        ("cancel video editor", "task-video-editor-golden-editor"),
        ("cancel minimax image", "task-minimax-image-golden-image"),
        ("cancel minimax music", "task-minimax-music-minimax-music-aabbccddeeff"),
        ("cancel model3d", "task-model3d-golden-model3d"),
        ("cancel rig", "task-rig-golden-rig"),
        ("cancel series assembly", "task-series-assembly-golden-assembly"),
        ("cancel director pipeline", "task-director-golden-director"),
        ("cancel comic plan", "task-comic-plan-golden-comic"),
    ):
        server.check(golden, case, "POST", f"/api/v1/tasks/{task_id}/cancel", params=workspace)
    server.check(golden, "retry generation", "POST", "/api/v1/tasks/task-generation-golden-gen/retry", params=workspace)
    server.check(golden, "resume generation", "POST", "/api/v1/tasks/task-generation-golden-gen/resume", params=workspace)
    server.check(golden, "retry completed series plan", "POST", "/api/v1/tasks/task-series-plan-golden-plan-done/retry", params=workspace)
    server.check(golden, "resume completed series plan", "POST", "/api/v1/tasks/task-series-plan-golden-plan-done/resume", params=workspace)
    server.check(golden, "retry comic plan without a request", "POST", "/api/v1/tasks/task-comic-plan-golden-comic/retry", params=workspace)

    launch._upsert_canonical_task(
        "default", "task-golden-reset",
        root_id="task-golden-reset", kind="foreground", workflow="frontend",
        title="Golden reset", status="failed", phase="failed", message="Failed",
        created_at=CREATED, cancelable=False, error={"message": "boom", "retryable": True},
    )
    launch._reset_canonical_task_for_resume("default", "task-golden-reset")
    reopened = launch._task_registry("default").get("task-golden-reset")
    golden.check("reset reopens a failed task before the next sync", 200, server.normalise(reopened))
    server.check(golden, "reset task after a later sync", "GET", "/api/v1/tasks/task-golden-reset", params=workspace)


# The canonical task cluster (C10a review): a workspace of its own, so that jobs other tests leave in the shared
# registries (they use "default") never reach these listings, and a fresh task registry, so event ids are fixed.
ACTIVITY_WORKSPACE = "activity-golden"
ISO_CREATED = "2023-11-14T22:13:20Z"  # the same instant as CREATED, written as text


def _registry_rows(launch, workspace: str) -> dict:
    """Every row of the workspace's task registry file: what a restart would read back."""
    import json
    import sqlite3

    path = launch._task_registry(workspace).path
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        tasks = [
            {**dict(row), "snapshot": json.loads(row["snapshot"])}
            for row in connection.execute("SELECT * FROM tasks ORDER BY id")
        ]
        events = [
            {**dict(row), "changes": json.loads(row["changes"]), "context": json.loads(row["context"])}
            for row in connection.execute("SELECT * FROM task_events ORDER BY event_id")
        ]
    finally:
        connection.close()
    return {"tasks": tasks, "events": events}


def _seed_activity_kinds(launch, server, monkeypatch) -> None:
    """One idle record per field branch of every publisher, all in ``ACTIVITY_WORKSPACE``."""
    from services import director_pipeline, model3d_service, rig_service
    from services.series_jobs import SeriesJobStore
    import routers.comics as comics
    import routers.video_editor as video_editor

    workspace = ACTIVITY_WORKSPACE

    def generation(job_id: str, params: dict, **fields: object) -> None:
        job = {
            "id": job_id, "workspace": workspace, "status": "queued", "step": 0, "total_steps": 0,
            "params": {"model_type": "golden_model", "prompt": f"prompt of {job_id}", "generation_mode": "video", **params},
            "created_at": CREATED, "output_files": [],
        }
        job.update(fields)
        monkeypatch.setitem(launch._jobs, job_id, job)

    # Generation: a Series child running without the acquired_resources field (the compatibility lane), with a text
    # creation time; a Director child on MiniMax; a cancelling remote job; a failed tool job; a job of another
    # workspace that the sync must skip.
    generation(
        "act-gen-series", {"_director_pipeline_id": "series:act-render"}, status="running", step=3, total_steps=12,
        created_at=ISO_CREATED, started_at=CREATED + 5, phase="denoising", message="Step 3 of 12",
        provenance={"actor": "agent", "tool": "tools", "capability": "remove_background",
                    "command": {"command_id": "cmd-1", "workflow_id": "wf-1", "run_id": "run-1"}},
    )
    generation(
        "act-gen-director", {"_director_pipeline_id": "act-director-run", "model_type": "minimax:image-01",
                             "generation_mode": "image"},
        provenance={"actor": "user", "capability": "upscale"}, progress=40,
    )
    generation(
        "act-gen-cancelling", {"model_type": "minimax:video-01"}, status="cancelling",
        provenance={"capability": "revoice"}, progress="n/a",
    )
    generation(
        "act-gen-failed", {"generation_mode": "music"}, status="failed", error="engine stopped",
        finished_at=CREATED + 60, output_files=["act_failed_partial.wav"], acquired_resources=["local_gpu:0"],
        provenance={"capability": "tools.upscale"},
    )
    generation("act-gen-elsewhere", {}, workspace="default-elsewhere")

    # Series: a known-series bible, a canon job and a running render, each with its own lane inputs.
    known = _plain_job(
        "act-plan-known", workspace=workspace, status="waiting", stage="bible", bootstrapKnownSeries=True,
        request={"writingProvider": "openai", "writingBaseUrl": "https://llm.example", "writingDevice": "gpu",
                 "writingModel": "gpt-golden"},
        validationError="needs a title", retryCount=2, seriesId="series-act", episodeId="episode-act",
        outputAssetIds=["asset-1"], settings={"tone": "dry"},
    )
    canon = _plain_job(
        "act-plan-canon", workspace=workspace, status="failed", jobType="canon", error="canon broke",
        validationAttempt=1, model="canon-model", createdAt=ISO_CREATED, finishedAt="not a time",
    )
    render = _plain_job(
        "act-render", workspace=workspace, status="running", seriesId="series-act", episodeId="episode-act",
        provider={"videoModel": "golden-video"}, current=2, total=5,
    )
    other = _plain_job("act-plan-other", workspace="default-elsewhere")
    for job in (known, canon, other):
        monkeypatch.setitem(launch._series_plan_jobs, job["jobId"], job)
    monkeypatch.setitem(launch._series_render_jobs, render["jobId"], render)

    # Series assembly checkpoints: cancelling counts as running; a failed one is resumable; a custom task id.
    store = SeriesJobStore(launch._workspace_dir(workspace), "assembly")
    store.save(_plain_job(
        "act-asm-cancelling", workspace=workspace, status="cancelling", stage="joining", assetId="asset-joined",
        startedAt=ISO_CREATED, updatedAt=CREATED + 3, seriesId="series-act", episodeId="episode-act",
    ))
    store.save(_plain_job(
        "act-asm-failed", workspace=workspace, status="failed", error="ffmpeg exited 1", finishedAt=CREATED + 9,
        updatedAt=CREATED + 2, taskId="task-act-assembly-custom",
    ))

    # Story and comic plans with explicit task identities, lane inputs and command fields.
    story = _plain_job(
        "act-story", workspace=workspace, status="failed", error="model refused",
        request={"writingProvider": "ollama", "writingBaseUrl": "http://127.0.0.1:11434", "writingDevice": "gpu"},
        taskId="task-act-story", rootTaskId="task-act-story-root", parentTaskId="task-act-story-parent",
        detailCurrent=2, detailTotal=7, current=1, total=3, provider="ollama", model_id="llama-golden",
        provenance={"actor": "wizard", "tool": "story", "capability": "plan", "command": {"workflow_id": "wf-s"}},
        commandId="cmd-story", generationId="gen-1", candidateId="cand-1", idempotencyKey="idem-1",
        createdAt=ISO_CREATED, startedAt=CREATED + 1, finishedAt=CREATED + 2,
    )
    story_done = _plain_job("act-story-done", workspace=workspace, status="completed", message="Story ready")
    comic = _plain_job(
        "act-comic", workspace=workspace, status="running", writingBaseUrl="http://127.0.0.1:8080",
        writingDevice="cpu", progress=55, server_origin="http://127.0.0.1:8080",
    )
    monkeypatch.setitem(launch._story_plan_jobs, story["jobId"], story)
    monkeypatch.setitem(launch._story_plan_jobs, story_done["jobId"], story_done)
    monkeypatch.setitem(launch._comic_plan_jobs, comic["jobId"], comic)

    # The other legacy kinds: a cancelling export with an output, a finished image with a file name, an explicit
    # lane, a UniRig rig on the GPU and a procedural one on the CPU.
    editor = _plain_job("act-editor", workspace=workspace, status="cancelling", output="act_export.mp4",
                        cancel_mode="cooperative", safe_boundary="segment")
    image = _plain_job("act-image", workspace=workspace, status="completed", filename="act_image.png",
                       provider="minimax", model="image-01", finished_at=CREATED + 4)
    monkeypatch.setitem(video_editor._video_editor_jobs, editor["id"], editor)
    monkeypatch.setitem(comics._minimax_image_jobs, image["jobId"], image)
    monkeypatch.setitem(model3d_service._jobs, "act-model3d", _plain_job(
        "act-model3d", workspace=workspace, resource_lane="remote:https://3d.example", status="paused",
        step=1, total_steps=4,
    ))
    monkeypatch.setitem(rig_service._jobs, "act-rig-gpu", _plain_job(
        "act-rig-gpu", workspace=workspace, request={"engine": "UniRig"}, output_files=["rigged.glb"],
    ))
    monkeypatch.setitem(rig_service._jobs, "act-rig-cpu", _plain_job("act-rig-cpu", workspace=workspace, engine="procedural"))

    # MiniMax Music: a candidate whose root is its parent job (cancel reaches the parent through the root id).
    music = _plain_job(
        "minimax-music-112233445566", workspace=workspace, message="Waiting for MiniMax Music",
        children=[_plain_job("act-candidate", workspace=workspace, parentTaskId="task-minimax-music-minimax-music-112233445566",
                             rootTaskId="task-minimax-music-minimax-music-112233445566")],
    )
    monkeypatch.setitem(launch._minimax_music_jobs, music["jobId"], music)

    # Director pipelines held in memory: a running music video with a resource schedule and provenance, a crashed
    # run, a PRE preview, a failed run that only has updated_at, and a completed run the test dismisses.
    def pipeline(pipeline_id: str, status: str, **fields: object) -> None:
        record = {"id": pipeline_id, "workspace": workspace, "status": status, "phase": status,
                  "created_at": CREATED, "progress": {"current": 0, "total": 0}, "clip_plans": [], "output_files": []}
        record.update(fields)
        monkeypatch.setitem(director_pipeline._pipelines, pipeline_id, record)

    pipeline(
        "act-director-run", "running", pipeline_type="music_video", phase="rendering", phase_started_at=CREATED + 7,
        progress={"step": 2, "total_steps": 6, "detail_current": 1, "detail_total": 3, "message": "Rendering clip 2"},
        params={"pipeline_type": "music_video", "writing_provider": "ollama", "writing_model": "llama-golden",
                "video_model": "golden_video"},
        resource_schedule={"lanes": {"video": {"key": "local_gpu:0"}, "text": {"key": "remote:https://llm.example"},
                                     "again": {"key": "local_gpu:0"}, "empty": {"key": ""}, "bad": "lane"}},
        provenance={"actor": "agent", "tool": "mcp", "capability": "director.run",
                    "command": {"command_id": "cmd-d", "workflow_id": "wf-d", "run_id": "run-d"}},
    )
    pipeline("act-director-crashed", "crashed", error="backend restarted", updated_at=CREATED + 11)
    pipeline("act-director-pre", "preview_ready", completed_at=CREATED + 12)
    pipeline("act-director-failed", "failed", updated_at=CREATED + 13, error="no clips")
    pipeline("act-director-done", "completed", _completed_at=CREATED + 14)


@pytest.mark.usefixtures("empty_generation_queue")
def test_canonical_activity_maps_every_publisher_branch_and_keeps_its_registry_rows(server, golden, monkeypatch) -> None:
    """Activity over one record per publisher branch, its idempotent resync, task details, events and the registry file.

    Recorded on development cda915466, where the canonical task cluster was still in ``_launch_runtime.py``.
    """
    launch = _launch()
    _seed_activity_kinds(launch, server, monkeypatch)
    params = {"workspace": ACTIVITY_WORKSPACE, "status": "all"}
    server.check(golden, "activity every branch", "GET", "/api/v1/tasks", params=params)
    # A second sync of unchanged records writes no event.
    server.check(golden, "activity resync", "GET", "/api/v1/tasks", params=params)
    workspace = {"workspace": ACTIVITY_WORKSPACE}
    server.check(golden, "series render parent and its generation child", "GET",
                 "/api/v1/tasks/task-series-render-act-render", params=workspace)
    server.check(golden, "director run parent and its generation child", "GET",
                 "/api/v1/tasks/task-director-act-director-run", params=workspace)
    server.check(golden, "story task events", "GET", "/api/v1/tasks/task-act-story/events", params=workspace)
    # A terminal Director card the user dismissed is not rebuilt from its checkpoint by later syncs.
    server.check(golden, "dismiss completed director", "DELETE", "/api/v1/tasks/task-director-act-director-done",
                 params=workspace)
    server.check(golden, "activity after the dismissal", "GET", "/api/v1/tasks", params=params)
    golden.check("activity registry rows", 200, server.normalise(_registry_rows(launch, ACTIVITY_WORKSPACE)))


@pytest.mark.usefixtures("empty_generation_queue")
def test_canonical_control_reaches_each_adapter_and_resume_reopens_only_terminal_tasks(server, golden, monkeypatch, capsys) -> None:
    """Cancel, retry, resume and dismiss for the adapters the first control golden does not reach, and the reset edges.

    Recorded on development cda915466, where the canonical task cluster was still in ``_launch_runtime.py``. The
    Assembly and Quick Video controllers are the routers' own registries, filled with a recorder for this workspace,
    so each answer names the action the control function asked for.
    """
    import os

    import routers.quick_video_batches as quick_video_batches
    import routers.series_assembly as series_assembly

    launch = _launch()
    _seed_activity_kinds(launch, server, monkeypatch)
    workspace = {"workspace": ACTIVITY_WORKSPACE}
    server.check(golden, "control seed", "GET", "/api/v1/tasks", params={**workspace, "status": "all"})

    calls: list = []
    directory = os.path.realpath(os.path.abspath(launch._workspace_dir(ACTIVITY_WORKSPACE)))
    monkeypatch.setitem(series_assembly._ASSEMBLY_CONTROLLERS, directory,
                        lambda job_id, action: calls.append(["assembly", job_id, action]) or {"assembly": job_id, "action": action})
    monkeypatch.setitem(quick_video_batches._CONTROLLERS, directory,
                        lambda job_id, action, item_index=None: calls.append(["quick", job_id, action, item_index])
                        or {"quick": job_id, "action": action})
    for task_id, status in (("task-quick-video-batch-act-q1", "running"), ("task-quick-video-batch-act-q2", "failed")):
        launch._upsert_canonical_task(
            ACTIVITY_WORKSPACE, task_id, root_id=task_id, kind="video", workflow="quick-video-batch",
            title="Quick Video batch", status=status, phase=status, message=status, created_at=CREATED,
            backend_job_id=task_id.rsplit("-", 1)[-1], cancelable=status == "running",
            metadata={"adapter": "quick-video-batch"},
        )
    launch._upsert_canonical_task(
        ACTIVITY_WORKSPACE, "task-act-frontend", root_id="task-act-frontend", kind="foreground", workflow="frontend",
        title="Frontend", status="failed", phase="failed", message="Failed", created_at=CREATED, cancelable=False,
        metadata={"adapter": "frontend"},
    )

    for case, method, task_id, action in (
        ("cancel music candidate through its root", "POST", "task-minimax-music-candidate-act-candidate", "cancel"),
        ("cancel quick video batch", "POST", "task-quick-video-batch-act-q1", "cancel"),
        ("retry quick video batch", "POST", "task-quick-video-batch-act-q2", "retry"),
        ("cancel running assembly", "POST", "task-series-assembly-act-asm-cancelling", "cancel"),
        ("resume failed assembly", "POST", "task-act-assembly-custom", "resume"),
        ("retry failed assembly", "POST", "task-act-assembly-custom", "retry"),
        ("dismiss assembly discards it", "DELETE", "task-act-assembly-custom", ""),
        ("resume completed story", "POST", "task-story-plan-act-story-done", "resume"),
        ("retry series render without its project", "POST", "task-series-render-act-render", "retry"),
        ("resume missing director run", "POST", "task-director-act-director-crashed", "resume"),
        ("cancel frontend task", "POST", "task-act-frontend", "cancel"),
        ("retry video editor", "POST", "task-video-editor-act-editor", "retry"),
        ("retry rig", "POST", "task-rig-act-rig-cpu", "retry"),
        ("dismiss failed frontend task", "DELETE", "task-act-frontend", ""),
    ):
        path = f"/api/v1/tasks/{task_id}" + (f"/{action}" if action else "")
        server.check(golden, case, method, path, params=workspace)
    golden.check("controller calls", 200, calls)

    registry = launch._task_registry(ACTIVITY_WORKSPACE)
    before = registry.get("task-generation-act-gen-series")
    launch._reset_canonical_task_for_resume(ACTIVITY_WORKSPACE, "")
    launch._reset_canonical_task_for_resume(ACTIVITY_WORKSPACE, "task-generation-act-gen-series")
    launch._reset_canonical_task_for_resume(ACTIVITY_WORKSPACE, "task-does-not-exist")
    launch._reset_canonical_task_for_resume("../outside", "task-generation-act-gen-series")
    golden.check("reset leaves a running task alone", 200, registry.get("task-generation-act-gen-series") == before)
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("[Task registry]")]
    golden.check("reset of a bad workspace is printed", 200, server.normalise(printed))
    launch._reset_canonical_task_for_resume(ACTIVITY_WORKSPACE, "task-generation-act-gen-failed")
    golden.check("reset reopens a failed generation", 200, server.normalise(registry.get("task-generation-act-gen-failed")))
    golden.check("control registry rows", 200, server.normalise(_registry_rows(launch, ACTIVITY_WORKSPACE)))


@pytest.mark.usefixtures("empty_generation_queue")
def test_canonical_activity_skips_a_registry_it_cannot_read_and_lists_the_rest(server, golden, monkeypatch) -> None:
    """A Director listing, an Assembly folder, a 3D or a rig registry that raises drops that kind only.

    Recorded on development cda915466, where the canonical task cluster was still in ``_launch_runtime.py``.
    """
    import threading

    from services import director_pipeline, model3d_service, rig_service
    from services.series_jobs import SeriesJobStore

    launch = _launch()
    workspace = ACTIVITY_WORKSPACE
    monkeypatch.setitem(launch._story_plan_jobs, "act-story-ok", _plain_job("act-story-ok", workspace=workspace))
    # The Director listing measures clip_plans with len(); a number there makes the listing raise.
    monkeypatch.setitem(director_pipeline._pipelines, "act-director-broken", {
        "id": "act-director-broken", "workspace": workspace, "status": "running", "params": {}, "clip_plans": 5,
    })
    # The Assembly store sorts by float(updatedAt or createdAt); a text creation time makes the listing raise.
    SeriesJobStore(launch._workspace_dir(workspace), "assembly").save(
        _plain_job("act-asm-text-time", workspace=workspace, createdAt=ISO_CREATED),
    )
    # A lock cannot be deep-copied: the 3D and rig snapshots raise.
    monkeypatch.setitem(model3d_service._jobs, "act-model3d-lock", _plain_job("act-model3d-lock", workspace=workspace, lock=threading.Lock()))
    monkeypatch.setitem(rig_service._jobs, "act-rig-lock", _plain_job("act-rig-lock", workspace=workspace, lock=threading.Lock()))
    server.check(golden, "activity without the unreadable registries", "GET", "/api/v1/tasks",
                 params={"workspace": workspace, "status": "all"})


@pytest.mark.usefixtures("empty_generation_queue")
def test_canonical_task_edges_the_mutations_found_open(server, golden, tmp_path, monkeypatch) -> None:
    """Edges no other golden pinned (C10a review mutations), recorded before the move.

    A text time that does not parse falls back to the next key; an Assembly checkpoint without a workspace is read
    from the folder it is in; cancelling a Director-owned generation reaches the generation job, not the pipeline;
    the lifecycle observer publishes a transition without a sync and ignores a job with no model; a volatile
    client detail stays out of the event log; the productions list reads the workspace it is asked for. Recorded
    on development cda915466, where the canonical task cluster was still in _launch_runtime.py.
    """

    import json

    from services.series_jobs import SeriesJobStore

    launch = _launch()
    workspace = ACTIVITY_WORKSPACE
    params = {"workspace": workspace, "status": "all"}
    monkeypatch.setattr(launch._durable_generation_queue, "path", str(tmp_path / "queue.json"))
    monkeypatch.setitem(launch._story_plan_jobs, "act-edge-story", _plain_job(
        "act-edge-story", workspace=workspace, status="completed",
        createdAt="not a time", created_at=CREATED + 20,
        startedAt="", started_at=CREATED + 21, finishedAt="still not a time", finished_at=CREATED + 22,
    ))
    checkpoint = _plain_job("act-edge-assembly", message="Joining without a workspace field")
    checkpoint.pop("workspace")
    SeriesJobStore(launch._workspace_dir(workspace), "assembly").save(checkpoint)
    owned = launch._new_generation_job(
        {**PARAMS, "_director_pipeline_id": "act-edge-run"}, workspace,
        job_id="act-edge-owned", created_at=CREATED, publish_task=False,
    )
    monkeypatch.setitem(launch._jobs, "act-edge-owned", owned)
    server.check(golden, "edges listed", "GET", "/api/v1/tasks", params=params)
    # The checkpoint is read from this workspace's folder, and its task is published under "default", the
    # publisher's own fallback for a record without a workspace.
    golden.check("assembly without a workspace field", 200, server.normalise(
        launch._task_registry("default").get("task-series-assembly-act-edge-assembly")))
    server.check(golden, "cancel a director-owned generation", "POST", "/api/v1/tasks/task-generation-act-edge-owned/cancel",
                 params={"workspace": workspace})

    registry = launch._task_registry(workspace)
    # The lifecycle observer publishes a transition by itself, before any Activity sync reads the job.
    from services import job_lifecycle

    started = {"id": "act-edge-started", "workspace": workspace, "status": "queued", "created_at": CREATED,
               "params": {"model_type": "golden_model", "prompt": "started"}, "output_files": []}
    job_lifecycle.try_start(started, phase="loading", message="Loading the model")
    golden.check("a lifecycle start publishes without a sync", 200,
                 server.normalise(registry.get("task-generation-act-edge-started")))
    launch._observe_generation_job_state({"id": "act-edge-no-model", "workspace": workspace, "status": "running",
                                          "params": {"prompt": "no model"}, "created_at": CREATED})
    launch._observe_generation_job_state({"id": "act-edge-model", "workspace": workspace, "status": "running",
                                          "params": {"model_type": "golden_model"}, "created_at": CREATED})
    golden.check("observer skips a job with no model", 200, {
        "no model": registry.get("task-generation-act-edge-no-model"),
        "model": server.normalise(registry.get("task-generation-act-edge-model")),
    })

    for detail in ("first volatile detail", "second volatile detail"):
        server.check(golden, f"client upsert {detail}", "POST", "/api/v1/tasks/upsert", json={
            "id": "act-edge-client", "workspace": workspace, "status": "running", "title": "Client work",
            "detailMessage": detail, "detailVolatile": True, "message": f"working on {detail}",
        })
    client = [task for task in registry.list(limit=500) if task.get("metadata", {}).get("client_activity_id") == "act-edge-client"]
    server.check(golden, "client task events", "GET", f"/api/v1/tasks/{client[0]['id']}/events", params={"workspace": workspace})

    for folder, pipeline_id in ((server.outputs / workspace, "act-edge-production"), (server.outputs, "act-edge-default")):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"_director_pipeline_{pipeline_id}.json").write_text(json.dumps({
            "pipeline_id": pipeline_id, "status": "completed", "phase": "completed", "pipeline_type": "music_video",
            "generation_mode": "image_guided", "created_at": CREATED, "updated_at": CREATED, "completed_at": CREATED,
            "progress": {"current": 1, "total": 1, "message": "Director finished"},
            "scene_description": f"scene of {pipeline_id}", "output_files": [],
        }), encoding="utf-8")
    server.check(golden, "productions of a named workspace", "GET", "/api/v1/productions", params={"workspace": workspace})
