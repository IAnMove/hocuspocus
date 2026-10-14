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
