import time

from routers.quick_video_batches import (
    _EXECUTION_LOCK,
    QuickVideoBatchActionRequest,
    QuickVideoBatchStartRequest,
    create_quick_video_batch_router,
)
from services.task_manager import get_task_registry


def _payload(ideas, *, continue_on_error=True):
    return {
        "workspace": "default",
        "title": "Night batch",
        "ideas": ideas,
        "continueOnError": continue_on_error,
        "settings": {
            "durationSeconds": 12,
            "generationMode": "direct_video",
            "videoModel": "minimax_h3_legacy",
            "imageModel": "flux2_klein_9b",
            "resolution": "480p",
            "aspectRatio": "9:16",
            "spokenLanguage": "Español de España",
            "visualStyle": "Animación 2D limpia",
            "characterVisualStyle": "",
            "directVideoMasterPrompt": "Animación 2D limpia",
            "allowClipText": False,
            "writingProvider": "maestro",
            "writingModel": "",
            "writingBaseUrl": "",
            "characters": [],
            "references": [],
        },
    }


def _endpoint(router, path, method):
    return next(
        route.endpoint for route in router.routes
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set())
    )


def _app(tmp_path, terminal_statuses):
    started = []
    statuses = terminal_statuses

    def start_pipeline(params):
        pipeline_id = f"pipeline-{len(started) + 1}"
        started.append((pipeline_id, params))
        return pipeline_id

    def get_status(pipeline_id, _out_dir):
        status = statuses.get(pipeline_id, "completed")
        return {
            "id": pipeline_id,
            "status": status,
            "phase": status,
            "progress": {"current": 1, "total": 1, "message": status},
            "output_files": [f"{pipeline_id}.mp4"] if status == "completed" else [],
            "error": "synthetic failure" if status == "failed" else None,
        }

    router = create_quick_video_batch_router(
        resolve_workspace=lambda value: str(value or "default"),
        workspace_dir=lambda _workspace: str(tmp_path),
        list_workspaces=lambda: [{"name": "default"}],
        ensure_pipeline_ready=lambda: None,
        start_pipeline=start_pipeline,
        get_pipeline_status=get_status,
        stop_pipeline=lambda _pipeline_id: True,
        resume_pipeline=lambda _pipeline_id, _out_dir: (True, "resumed"),
        get_model_def=lambda _model: {"fps": 24, "frames_steps": 17, "frames_minimum": 124},
        get_model_defaults=lambda _model: {},
        resolve_reference=lambda _source, _workspace: None,
    )
    return router, started


def _wait_for_terminal(app, job_id, timeout=3):
    get_batch = _endpoint(
        app, "/api/v1/stories/quick-video-batches/{job_id}", "GET",
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = get_batch(job_id, "default")
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    raise AssertionError("Quick Video batch did not settle")


def test_quick_video_batch_runs_ideas_strictly_in_order(tmp_path):
    app, started = _app(tmp_path, {})
    start = _endpoint(app, "/api/v1/stories/quick-video-batches/start", "POST")
    response = start(QuickVideoBatchStartRequest.model_validate(
        _payload(["Idea uno", "Idea dos", "Idea tres"]),
    ))
    job = _wait_for_terminal(app, response["jobId"])

    assert job["status"] == "completed"
    assert [item["status"] for item in job["items"]] == ["completed"] * 3
    assert [item["finalOutput"] for item in job["items"]] == [
        "pipeline-1.mp4", "pipeline-2.mp4", "pipeline-3.mp4",
    ]
    assert [params["scene_description"].split("IDEA: ", 1)[1] for _, params in started] == [
        "Idea uno", "Idea dos", "Idea tres",
    ]
    assert all(params["music_video_treatment"]["generation_mode"] == "direct_video" for _, params in started)


def test_quick_video_batch_continues_after_one_failure(tmp_path):
    app, started = _app(tmp_path, {"pipeline-2": "failed"})
    start = _endpoint(app, "/api/v1/stories/quick-video-batches/start", "POST")
    response = start(QuickVideoBatchStartRequest.model_validate(
        _payload(["Primera", "Segunda", "Tercera"], continue_on_error=True),
    ))
    job = _wait_for_terminal(app, response["jobId"])

    assert len(started) == 3
    assert [item["status"] for item in job["items"]] == [
        "completed", "failed", "completed",
    ]
    assert job["status"] == "completed"
    assert job["error"] == "1 item(s) failed"


def test_quick_video_batch_rejects_duplicate_and_blank_ideas(tmp_path):
    app, started = _app(tmp_path, {})
    start = _endpoint(app, "/api/v1/stories/quick-video-batches/start", "POST")
    response = start(QuickVideoBatchStartRequest.model_validate(
        _payload(["Idea", "", "  idea  ", "# comentario"]),
    ))
    job = _wait_for_terminal(app, response["jobId"])
    assert job["total"] == 1
    assert len(started) == 1


def test_cancelled_batch_does_not_start_after_waiting_for_queue(tmp_path):
    router, started = _app(tmp_path, {})
    start = _endpoint(router, "/api/v1/stories/quick-video-batches/start", "POST")
    cancel = _endpoint(
        router, "/api/v1/stories/quick-video-batches/{job_id}/{action}", "POST",
    )

    _EXECUTION_LOCK.acquire()
    try:
        response = start(QuickVideoBatchStartRequest.model_validate(_payload(["No ejecutar"])))
        cancelling = cancel(
            response["jobId"],
            "cancel",
            QuickVideoBatchActionRequest(workspace="default"),
        )
        task = get_task_registry(str(tmp_path)).get(response["taskId"])
        assert cancelling["status"] == "cancelling"
        assert task and task["status"] == "running" and task["phase"] == "cancelling"
    finally:
        _EXECUTION_LOCK.release()

    job = _wait_for_terminal(router, response["jobId"])
    assert job["status"] == "cancelled"
    assert started == []


def test_listing_batches_does_not_interrupt_a_live_worker(tmp_path):
    statuses = {"pipeline-1": "running"}
    router, started = _app(tmp_path, statuses)
    start = _endpoint(router, "/api/v1/stories/quick-video-batches/start", "POST")
    list_batches = _endpoint(router, "/api/v1/stories/quick-video-batches", "GET")
    cancel = _endpoint(
        router, "/api/v1/stories/quick-video-batches/{job_id}/{action}", "POST",
    )
    response = start(QuickVideoBatchStartRequest.model_validate(_payload(["En curso"])))

    deadline = time.time() + 2
    while time.time() < deadline and not started:
        time.sleep(0.01)
    assert started
    listed = list_batches("default")["jobs"][0]
    assert listed["status"] == "running"
    assert listed["items"][0]["status"] in {"planning", "running"}

    cancel(response["jobId"], "cancel", QuickVideoBatchActionRequest(workspace="default"))
    statuses["pipeline-1"] = "cancelled"
    assert _wait_for_terminal(router, response["jobId"])["status"] == "cancelled"
