"""Story Lab: an empty library, the validation and missing-job answers, and the job life cycle.

The life cycle runs with a fake writing provider. A real LLM, real images and a real lyrics
translation are not exercised here.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path


def test_story_lab_routes_answer_the_recorded_errors(server, golden, monkeypatch) -> None:
    """Validation and missing-job answers for the Story Lab routes this slice moves. No model runs."""
    server.check(golden, "library empty", "GET", "/api/v1/stories/library", params={"workspace": "default"})
    server.check(golden, "analyze without images", "POST", "/api/v1/stories/assets/analyze", json={})
    server.check(
        golden, "analyze a path outside uploads", "POST", "/api/v1/stories/assets/analyze",
        json={"assets": [{"path": "/tmp/not-an-upload.png", "name": "outside.png"}]},
    )
    server.check(
        golden, "analyze too many images", "POST", "/api/v1/stories/assets/analyze",
        json={"assets": [{"path": "x.png"} for _ in range(25)]},
    )
    server.check(golden, "generate the whole story at once", "POST", "/api/v1/stories/generate", json={"scope": "all"})
    server.check(golden, "generate an unknown scope", "POST", "/api/v1/stories/generate", json={"scope": "not-a-scope"})
    server.check(
        golden, "generate one stage without a premise", "POST", "/api/v1/stories/generate",
        json={"scope": "overview"},
    )
    server.check(golden, "translate without lyrics", "POST", "/api/v1/stories/translate-lyrics", json={})
    server.check(
        golden, "translate without a language", "POST", "/api/v1/stories/translate-lyrics",
        json={"lyrics": "Line one"},
    )
    server.check(
        golden, "start an unknown scope", "POST", "/api/v1/stories/generate/start",
        json={"scope": "not-a-scope", "premise": "A harbour."},
    )
    server.check(golden, "start without a premise", "POST", "/api/v1/stories/generate/start", json={"scope": "all"})
    job = "/api/v1/stories/generate"
    server.check(golden, "status of a missing job", "GET", f"{job}/status/missing-job")
    server.check(golden, "resume a missing job", "POST", f"{job}/resume/missing-job", json={})
    server.check(golden, "cancel a missing job", "POST", f"{job}/cancel/missing-job")
    _assert_story_lab_is_bound_to_the_server(sys.modules["_launch_runtime"], monkeypatch)


def _assert_story_lab_is_bound_to_the_server(launch, monkeypatch) -> None:
    """The Story Lab job state has one instance, and every injected name is the server's own."""
    import routers.story_lab as lab_router
    import services.story_lab_jobs as lab_jobs
    import services.story_lab_schema as lab_schema

    for name in ("_story_plan_jobs", "_story_plan_jobs_lock"):
        assert getattr(launch, name) is getattr(lab_jobs, name) is getattr(lab_router, name), name
    assert lab_router._story_plan_active_jobs is lab_jobs._story_plan_active_jobs
    for name in ("_comic_writing_llm", "_ensure_llm_loaded"):
        assert getattr(launch, name) is getattr(lab_jobs, name) is getattr(lab_router, name), name
    assert lab_jobs._workspace_dir is launch._workspace_dir
    assert lab_jobs._list_workspaces is launch._list_workspaces
    assert lab_router._get_active_workspace is launch._get_active_workspace
    assert lab_router._story_import_upload_path is launch._story_import_upload_path
    # The Activity controller calls these two through the launch names.
    assert launch.cancel_story_lab_generation is lab_router.cancel_story_lab_generation
    assert launch.resume_story_lab_generation is lab_router.resume_story_lab_generation
    # The storyboard check calls the comic page check that the schema module imports from the comic helpers.
    assert lab_schema._comic_page_problem is launch._comic_page_problem
    assert lab_schema._storyboard_page_problem({}, 1) == launch._comic_page_problem({}, 1) is not None
    # The publish and resume hooks are read at call time (the first with globals().get, so a name
    # the bind forgot would stop the Activity row without an error). Both are forwarders that look
    # the launch name up when called, because the real functions are defined later in launch.
    assert callable(lab_jobs._publish_generic_legacy_task) and callable(lab_router._publish_generic_legacy_task)
    monkeypatch.setattr(launch, "_publish_generic_legacy_task", lambda record, adapter: ("published", adapter))
    assert lab_jobs._publish_generic_legacy_task({}, "story-plan") == ("published", "story-plan")
    assert lab_router._publish_generic_legacy_task({}, "story-plan") == ("published", "story-plan")
    monkeypatch.setattr(launch, "_reset_canonical_task_for_resume", lambda workspace, task_id: (workspace, task_id))
    assert lab_router._reset_canonical_task_for_resume("film", "task-1") == ("film", "task-1")


STORY_JOB = r"story-plan-[0-9a-f]{12}"
WRITER = {"writingProvider": "ollama", "writingModel": "golden-writer", "writingBaseUrl": "http://127.0.0.1:11434"}
OVERVIEW = {"overview": {
    "title": "Harbour", "language": "English", "genre": "Adventure", "tone": "warm", "audience": "General",
    "visualStyle": "ink", "characterVisualStyle": "ink", "enforceVisualStyle": True, "allowClipText": False,
    "musicVideoGenerationMode": "", "premise": "A harbour.", "logline": "A keeper waits.",
    "synopsis": "A keeper waits for a ship.", "theme": "patience", "ending": "The ship comes.",
    "creativeBrief": {
        "generalIdea": "A keeper waits.", "context": "A harbour.", "performer": "", "musicStyle": "",
        "songStory": "", "subjects": "keeper", "setting": "harbour", "action": "waiting", "quickFormat": "",
        "durationSeconds": 30,
    },
}}


def test_story_lab_job_lifecycle_with_a_fake_writer(server, golden, monkeypatch) -> None:
    """Start, poll, cancel, fail, resume and reload Story Lab jobs; the writing provider is a fake. No model runs."""
    from services import llm_service

    launch = sys.modules["_launch_runtime"]
    mode = {"now": "good"}
    entered, gate = threading.Event(), threading.Event()
    started: list[str] = []
    replace = ((STORY_JOB, "story-plan-<JOB>"),)
    base = "/api/v1/stories/generate"
    body = {"scope": "overview", "premise": "A harbour.", "project": {"projectType": "full_story"}, **WRITER}

    def fake_writer(**_request):
        if mode["now"] == "block":
            entered.set()
            assert gate.wait(30), "the test never released the writer"
        if mode["now"] == "bad":
            return "[]"
        return json.dumps(OVERVIEW)

    def no_local_model(**_request):
        raise AssertionError("the local model must not run")

    def start() -> str:
        response = server.check(
            golden, f"lifecycle start {len(started) + 1}", "POST", f"{base}/start", replace=replace, json=body,
        )
        started.append(response.json()["jobId"])
        return started[-1]

    def settle(job: str, *states: str) -> None:
        deadline = time.time() + 30
        while time.time() < deadline:
            if server.client.get(f"{base}/status/{job}").json().get("status") in states:
                return
            time.sleep(0.02)
        raise AssertionError(f"{job} never reached {states}")

    def status(case: str, job: str) -> None:
        server.check(golden, case, "GET", f"{base}/status/{job}", replace=replace)

    def activity(case: str) -> None:
        tasks = server.client.get("/api/v1/tasks", params={"workspace": "default", "status": "all"}).json()["tasks"]
        story = sorted(
            (
                {key: task.get(key) for key in ("kind", "title", "status", "phase", "message", "error", "resumable")}
                for task in tasks if (task.get("metadata") or {}).get("adapter") == "story-plan"
            ),
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
        golden.check(case, 200, server.normalise(story, replace=replace))

    monkeypatch.setattr(llm_service, "generate_openai_compatible", fake_writer)
    monkeypatch.setattr(llm_service, "generate_streaming", no_local_model)
    try:
        job = start()
        settle(job, "completed", "failed")
        status("lifecycle completed job", job)
        activity("lifecycle activity after a completed job")
        assert (Path(launch._workspace_dir("default")) / ".story-plan-jobs" / f"{job}.json").is_file()
        server.check(golden, "lifecycle cancel a completed job", "POST", f"{base}/cancel/{job}", replace=replace)
        server.check(golden, "lifecycle resume a completed job", "POST", f"{base}/resume/{job}", replace=replace, json={})
        # A job the process forgot comes back from its checkpoint.
        launch._story_plan_jobs.clear()
        status("lifecycle completed job reloaded from its checkpoint", job)

        mode["now"] = "block"
        job = start()
        assert entered.wait(30)
        status("lifecycle running job", job)
        server.check(golden, "lifecycle cancel a running job", "POST", f"{base}/cancel/{job}", replace=replace)
        server.check(
            golden, "lifecycle resume while the worker is still active", "POST", f"{base}/resume/{job}",
            replace=replace, json={},
        )
        gate.set()
        settle(job, "cancelled", "completed", "failed")
        status("lifecycle cancelled job", job)
        activity("lifecycle activity after a cancelled job")

        mode["now"] = "bad"
        job = start()
        settle(job, "failed", "completed")
        status("lifecycle failed job", job)
        activity("lifecycle activity after a failed job")
        mode["now"] = "good"
        server.check(golden, "lifecycle resume a failed job", "POST", f"{base}/resume/{job}", replace=replace, json={})
        settle(job, "completed", "failed")
        status("lifecycle resumed job", job)
        activity("lifecycle activity after a resumed job")
    finally:
        gate.set()
        deadline = time.time() + 30
        while time.time() < deadline and any(
            thread.name.startswith("story-plan-") and thread.is_alive() for thread in threading.enumerate()
        ):
            time.sleep(0.02)
        launch._story_plan_jobs.clear()
