"""Series library and the cheap Series plan reads: list, create, get, update, delete, and error answers.

Success paths that start an LLM or a render are not recorded here.
"""
from __future__ import annotations

WORKSPACE = "golden-series"


def test_series_project_lifecycle(server, golden) -> None:
    server.client.post("/api/v1/workspaces", json={"name": WORKSPACE})
    server.check(golden, "list empty", "GET", "/api/v1/series", params={"workspace": WORKSPACE})
    created = server.check(golden, "create", "POST", "/api/v1/series",
                           json={"workspace": WORKSPACE, "title": "Golden series", "logline": "A test."})
    series_id = created.json()["id"]
    server.check(golden, "get", "GET", f"/api/v1/series/{series_id}", params={"workspace": WORKSPACE})
    server.check(golden, "update", "PUT", f"/api/v1/series/{series_id}",
                 json={"workspace": WORKSPACE, "baseRevision": 1, "series": {"title": "Golden series, revised"}})
    server.check(golden, "update stale revision", "PUT", f"/api/v1/series/{series_id}",
                 json={"workspace": WORKSPACE, "baseRevision": 1, "series": {"title": "Lost write"}})
    server.check(golden, "update other id", "PUT", f"/api/v1/series/{series_id}",
                 json={"workspace": WORKSPACE, "series": {"id": "someone-else"}})
    server.check(golden, "episode before canon approval", "POST", f"/api/v1/series/{series_id}/episodes",
                 json={"workspace": WORKSPACE, "title": "Pilot"})
    server.check(golden, "list one", "GET", "/api/v1/series", params={"workspace": WORKSPACE})
    server.check(golden, "library", "GET", "/api/v1/series/library", params={"workspace": WORKSPACE})
    server.check(golden, "delete", "DELETE", f"/api/v1/series/{series_id}", params={"workspace": WORKSPACE})
    server.check(golden, "get deleted", "GET", f"/api/v1/series/{series_id}", params={"workspace": WORKSPACE})
    server.check(golden, "list after delete", "GET", "/api/v1/series", params={"workspace": WORKSPACE})


def test_series_job_lists_start_empty(server, golden) -> None:
    for case, path in (
        ("plan recovery", "/api/v1/series/plan/recovery"),
        ("render recovery", "/api/v1/series/render/recovery"),
        ("assembly recovery", "/api/v1/series/assembly/recovery"),
        ("native render recovery", "/api/v1/series/native-render/recovery"),
        ("produce jobs", "/api/v1/series/produce/jobs"),
    ):
        server.check(golden, case, "GET", path, params={"workspace": "default"})


def test_series_library_routes_answer_the_recorded_errors(server, golden) -> None:
    """Validation and missing-project answers for the routes step 0.12 moves."""
    missing = "missing-series"
    workspace = {"workspace": "default"}
    server.check(golden, "put series without a project", "PUT", f"/api/v1/series/{missing}", json=workspace)
    server.check(golden, "delete missing series", "DELETE", f"/api/v1/series/{missing}", params=workspace)
    server.check(golden, "duplicate missing series", "POST", f"/api/v1/series/{missing}/duplicate", json=workspace)
    server.check(golden, "import story without a source", "POST", "/api/v1/series/import-story", json=workspace)
    server.check(golden, "list episodes of a missing series", "GET", f"/api/v1/series/{missing}/episodes", params=workspace)
    server.check(
        golden, "get missing episode", "GET",
        f"/api/v1/series/{missing}/episodes/missing-episode", params=workspace,
    )
    server.check(
        golden, "delete missing episode", "DELETE",
        f"/api/v1/series/{missing}/episodes/missing-episode", params=workspace,
    )
    server.check(
        golden, "put missing episode", "PUT",
        f"/api/v1/series/{missing}/episodes/missing-episode", json=workspace,
    )
    server.check(
        golden, "import asset outside uploads", "POST",
        f"/api/v1/series/{missing}/assets/import",
        json={**workspace, "uploadPath": "/tmp/not-an-upload.png"},
    )
    server.check(
        golden, "canon commit without a revision", "POST",
        f"/api/v1/series/{missing}/episodes/missing-episode/canon/commit", json=workspace,
    )
    server.check(
        golden, "refresh references of a missing series", "POST",
        f"/api/v1/series/{missing}/episodes/missing-episode/references/refresh", json=workspace,
    )
    server.check(golden, "approve canon without a revision", "POST", f"/api/v1/series/{missing}/canon/approve", json=workspace)
    server.check(
        golden, "route references of a missing series", "POST",
        f"/api/v1/series/{missing}/episodes/missing-episode/references/route", json=workspace,
    )
    server.check(
        golden, "approve a missing attempt", "POST",
        f"/api/v1/series/{missing}/episodes/missing-episode/shots/missing-shot/attempts/missing-attempt/approve",
        json=workspace,
    )
    server.check(
        golden, "approve bulk of a missing episode", "POST",
        f"/api/v1/series/{missing}/episodes/missing-episode/attempts/approve-bulk", json=workspace,
    )
    server.check(
        golden, "reject a missing attempt", "POST",
        f"/api/v1/series/{missing}/episodes/missing-episode/shots/missing-shot/attempts/missing-attempt/reject",
        json=workspace,
    )


def test_series_duplicate_and_empty_episode_list(server, golden) -> None:
    server.client.post("/api/v1/workspaces", json={"name": WORKSPACE})
    created = server.client.post("/api/v1/series", json={"workspace": WORKSPACE, "title": "Golden series"})
    series_id = created.json()["id"]
    server.check(golden, "duplicate", "POST", f"/api/v1/series/{series_id}/duplicate", json={"workspace": WORKSPACE})
    server.check(golden, "episodes empty", "GET", f"/api/v1/series/{series_id}/episodes", params={"workspace": WORKSPACE})
    server.check(
        golden, "approve canon before it is complete", "POST",
        f"/api/v1/series/{series_id}/canon/approve",
        json={"workspace": WORKSPACE, "baseRevision": 1},
    )


def test_series_render_routes_answer_the_recorded_errors(server, golden, monkeypatch) -> None:
    """Validation and missing-job answers for the Series render routes. No model runs."""
    missing = "missing-series"
    workspace = {"workspace": "default"}
    server.check(
        golden, "render start of a missing series", "POST",
        f"/api/v1/series/{missing}/episodes/missing-episode/render/start", json=workspace,
    )
    job = "/api/v1/series/render/jobs/missing-job"
    server.check(golden, "get missing render job", "GET", job)
    server.check(golden, "cancel missing render job", "POST", f"{job}/cancel")
    server.check(golden, "resume missing render job", "POST", f"{job}/resume")
    server.check(golden, "discard missing render job", "DELETE", job)

    created = server.client.post("/api/v1/series", json={"workspace": "default", "title": "Golden series"})
    assert created.status_code == 200, created.text
    series_id = created.json()["id"]
    server.check(
        golden, "render start of a missing episode", "POST",
        f"/api/v1/series/{series_id}/episodes/missing-episode/render/start", json=workspace,
    )
    saved = server.client.put(
        f"/api/v1/series/{series_id}",
        json={
            "workspace": "default",
            "baseRevision": created.json().get("revision", 1),
            "series": {
                "canon": {"worldSummary": "A harbour that keeps its own time."},
                "characters": [{"id": "mara", "name": "Mara"}],
                "locations": [{"id": "harbour", "name": "Harbour"}],
            },
        },
    )
    assert saved.status_code == 200, saved.text
    project = saved.json()
    approved = server.client.post(
        f"/api/v1/series/{series_id}/canon/approve",
        json={"workspace": "default", "baseRevision": project["canon"]["revision"]},
    )
    assert approved.status_code == 200, approved.text
    episode = server.client.post(
        f"/api/v1/series/{series_id}/episodes",
        json={"workspace": "default", "title": "Pilot"},
    )
    assert episode.status_code == 200, episode.text
    start = f"/api/v1/series/{series_id}/episodes/{episode.json()['id']}/render/start"
    server.check(
        golden, "render start with an unknown mode", "POST", start,
        json={**workspace, "mode": "not-a-mode"},
    )
    server.check(
        golden, "render start with no generated shots", "POST", start, json=workspace,
    )
    import sys
    from services.series_render_jobs import series_render_task_adapter
    launch = sys.modules["_launch_runtime"]
    assert launch.ctx.tasks.adapter_for("series-render") is series_render_task_adapter
    _assert_series_render_is_bound_to_the_server(launch, monkeypatch)


def _assert_series_render_is_bound_to_the_server(launch, monkeypatch) -> None:
    """The render state has one instance, and every injected name is the server's own."""
    import routers.series_render as render_router
    import services.series_render_jobs as render_jobs

    for name in ("_series_render_jobs", "_series_render_jobs_lock", "_series_render_active_jobs"):
        assert getattr(launch, name) is getattr(render_jobs, name) is getattr(render_router, name), name
    assert render_jobs._jobs is launch._jobs is launch.ctx.jobs.registry
    assert render_router._jobs is launch._jobs
    assert render_jobs._series_library_lock is launch._series_library_lock
    assert render_router._series_library_lock is launch._series_library_lock
    assert render_jobs._run_generation is launch._run_generation
    assert render_jobs._cancel_series_render_job is render_router.cancel_series_render_job
    # The publish hook is read with globals().get, so a name the bind forgot would stop the
    # Activity row without an error. Both are forwarders that look the launch name up at call time.
    assert callable(render_jobs._publish_series_task) and callable(render_router._publish_series_task)
    monkeypatch.setattr(launch, "_publish_series_task", lambda job, adapter: ("published", adapter))
    assert render_jobs._publish_series_task({}, "series-render") == ("published", "series-render")
    assert render_router._publish_series_task({}, "series-render") == ("published", "series-render")
    monkeypatch.setattr(launch, "_reset_canonical_task_for_resume", lambda workspace, task_id: (workspace, task_id))
    assert render_router._reset_canonical_task_for_resume("film", "task-1") == ("film", "task-1")


def test_series_plan_routes_answer_the_recorded_errors(server, golden) -> None:
    """Validation and missing-job answers for the routes step 0.13 moves. No LLM call."""
    missing = "missing-series"
    workspace = {"workspace": "default"}
    server.check(
        golden, "prepare canon of a missing series", "POST",
        f"/api/v1/series/{missing}/canon/prepare/start", json=workspace,
    )
    server.check(
        golden, "plan start with an unknown scope", "POST",
        f"/api/v1/series/{missing}/episodes/missing-episode/plan/start",
        json={**workspace, "scope": "not-a-scope"},
    )
    job = "/api/v1/series/plan/jobs/missing-job"
    server.check(golden, "get missing plan job", "GET", job)
    server.check(golden, "cancel missing plan job", "POST", f"{job}/cancel")
    server.check(golden, "resume missing plan job", "POST", f"{job}/resume", json=workspace)
    server.check(golden, "apply missing plan job", "POST", f"{job}/apply", json=workspace)
    server.check(golden, "apply canon of a missing plan job", "POST", f"{job}/apply-canon")
    server.check(golden, "discard missing plan job", "DELETE", job)
    server.check(
        golden, "duration preview without a shot", "POST",
        f"/api/v1/series/{missing}/shots/duration/preview", json=workspace,
    )
