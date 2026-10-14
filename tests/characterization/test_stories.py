"""Story Lab cheap reads: an empty library, and the validation and missing-job answers.

Success paths that call an LLM, analyze a real image, or translate lyrics are not recorded here.
"""
from __future__ import annotations

import sys


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
    # The storyboard check calls the comic page check that the full server assigns onto the schema module.
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
