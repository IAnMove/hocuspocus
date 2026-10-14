import copy
import threading

import pytest
from pathlib import Path

from services.series_jobs import SeriesJobStore


_ROOT = Path(__file__).parents[1]


def test_render_queue_survives_store_recreation(tmp_path):
    first = SeriesJobStore(str(tmp_path), "render")
    first.save({
        "jobId": "series-render-1", "status": "running", "createdAt": 1,
        "updatedAt": 2, "outputAssetIds": [], "providerTaskId": "remote-1",
    })
    second = SeriesJobStore(str(tmp_path), "render")
    loaded = second.load("series-render-1")
    assert loaded["providerTaskId"] == "remote-1"
    assert second.recoverable()[0]["jobId"] == "series-render-1"


def test_render_endpoint_and_resumption_cannot_bypass_series_production_permissions(monkeypatch):
    from fastapi import HTTPException

    import routers.series_render as routes
    import services.series_render_jobs as render_jobs

    shot = {'id':'shot-1', 'productionMethod':'generated_video', 'attempts':[]}
    episode = {'id':'episode-1', 'shots':[shot]}
    series = {'id':'series-1', 'allowedProductionMethods':['animation_2d'], 'episodesById':{'episode-1':episode}}
    library = {'seriesById':{'series-1':series}}
    monkeypatch.setattr(routes, "_series_library_lock", threading.RLock())
    monkeypatch.setattr(routes, "_series_library_workspace", lambda value: 'default')
    monkeypatch.setattr(routes, "_read_series_workspace", lambda workspace: library)
    monkeypatch.setattr(routes, "_series_project_or_404", lambda current, key: current['seriesById'][key])
    monkeypatch.setattr(routes, "_active_series_render_for_episode", lambda *args: None)
    monkeypatch.setattr(routes, "_series_render_candidates", lambda episode, body: episode['shots'])
    monkeypatch.setattr(render_jobs, "_series_library_lock", threading.RLock())
    monkeypatch.setattr(render_jobs, "_read_series_workspace", lambda workspace: library)
    monkeypatch.setattr(render_jobs, "_series_project_or_404", lambda current, key: current['seriesById'][key])
    with pytest.raises(HTTPException, match='No permitted') as denied:
        routes.start_series_episode_render('series-1', 'episode-1', {})
    assert denied.value.status_code == 400
    with pytest.raises(ValueError, match='not permitted'):
        render_jobs._series_render_context({'workspace':'default','seriesId':'series-1','episodeId':'episode-1'}, {'shotId':'shot-1'})
    leftover = {'id':'shot-leftover', 'productionMethod':'imported_video', 'attempts':[]}
    episode['shots'] = [leftover, shot]
    with pytest.raises(HTTPException, match='No permitted'):
        routes.start_series_episode_render('series-1', 'episode-1', {})
    shot['productionMethod'] = 'animation_2d'
    with pytest.raises(HTTPException, match='No permitted'):
        routes.start_series_episode_render('series-1', 'episode-1', {})


def test_discard_removes_checkpoint_not_output(tmp_path):
    output = Path(tmp_path) / "approved.mp4"
    output.write_bytes(b"approved")
    store = SeriesJobStore(str(tmp_path), "render")
    store.save({
        "jobId": "series-render-2", "status": "queued", "createdAt": 1,
        "updatedAt": 1, "outputAssetIds": ["approved.mp4"],
    })
    assert store.discard("series-render-2") is True
    assert store.load("series-render-2") is None
    assert output.read_bytes() == b"approved"


def test_series_render_settlement_marks_fully_rendered_episode_completed(monkeypatch):
    library = {
        "seriesById": {
            "series-1": {
                "id": "series-1",
                "revision": 4,
                "episodesById": {
                    "episode-1": {
                        "id": "episode-1",
                        "status": "rendering",
                        "shots": [
                            {"attempts": [{"status": "completed", "outputAssetIds": ["asset-1"]}]},
                            {"attempts": [
                                {"status": "cancelled", "outputAssetIds": []},
                                {"status": "completed", "outputAssetIds": ["asset-2"]},
                            ]},
                        ],
                    },
                },
            },
        },
    }
    import services.series_render_jobs as render_jobs

    writes = []
    monkeypatch.setattr(render_jobs, "_series_library_lock", threading.RLock())
    monkeypatch.setattr(render_jobs, "_read_series_workspace", lambda _workspace: copy.deepcopy(library))
    monkeypatch.setattr(render_jobs, "_series_project_or_404", lambda current, series_id: current["seriesById"][series_id])
    monkeypatch.setattr(render_jobs, "_write_series_workspace", lambda _workspace, current: writes.append(copy.deepcopy(current)) or current)
    monkeypatch.setattr(render_jobs, "_series_iso_now", lambda: "2026-08-11T00:00:00Z")

    status = render_jobs._series_settle_episode_render_status({
        "workspace": "default", "seriesId": "series-1", "episodeId": "episode-1",
    })

    assert status == "completed"
    assert writes[0]["seriesById"]["series-1"]["revision"] == 5
    episode = writes[0]["seriesById"]["series-1"]["episodesById"]["episode-1"]
    assert episode["status"] == "completed"
    assert episode["updatedAt"] == "2026-08-11T00:00:00Z"


def test_series_render_settlement_returns_partial_episode_to_shot_plan(monkeypatch):
    library = {
        "seriesById": {
            "series-1": {
                "id": "series-1",
                "revision": 8,
                "episodesById": {
                    "episode-1": {
                        "id": "episode-1",
                        "status": "rendering",
                        "shots": [
                            {"attempts": [{"status": "completed", "outputAssetIds": ["asset-1"]}]},
                            {"attempts": [{"status": "failed", "outputAssetIds": []}]},
                        ],
                    },
                },
            },
        },
    }
    import services.series_render_jobs as render_jobs

    writes = []
    monkeypatch.setattr(render_jobs, "_series_library_lock", threading.RLock())
    monkeypatch.setattr(render_jobs, "_read_series_workspace", lambda _workspace: copy.deepcopy(library))
    monkeypatch.setattr(render_jobs, "_series_project_or_404", lambda current, series_id: current["seriesById"][series_id])
    monkeypatch.setattr(render_jobs, "_write_series_workspace", lambda _workspace, current: writes.append(copy.deepcopy(current)) or current)
    monkeypatch.setattr(render_jobs, "_series_iso_now", lambda: "2026-08-11T00:00:00Z")

    status = render_jobs._series_settle_episode_render_status({
        "workspace": "default", "seriesId": "series-1", "episodeId": "episode-1",
    })

    assert status == "shot_plan"
    episode = writes[0]["seriesById"]["series-1"]["episodesById"]["episode-1"]
    assert episode["status"] == "shot_plan"


def test_planning_and_render_namespaces_are_isolated(tmp_path):
    planning = SeriesJobStore(str(tmp_path), "planning")
    render = SeriesJobStore(str(tmp_path), "render")
    planning.save({"jobId": "same", "status": "completed", "createdAt": 1, "updatedAt": 1})
    render.save({"jobId": "same", "status": "failed", "createdAt": 1, "updatedAt": 2})
    assert planning.load("same")["status"] == "completed"
    assert render.load("same")["status"] == "failed"


def test_active_render_guard_is_scoped_to_workspace_series_and_episode(monkeypatch):
    persisted = [{
        "jobId": "persisted-active", "workspace": "default",
        "seriesId": "series-1", "episodeId": "episode-1", "status": "running",
    }, {
        "jobId": "finished", "workspace": "default",
        "seriesId": "series-1", "episodeId": "episode-2", "status": "completed",
    }]

    class Store:
        def list(self):
            return copy.deepcopy(persisted)

    import services.series_render_jobs as render_jobs

    monkeypatch.setattr(render_jobs, "_series_render_jobs_lock", threading.RLock())
    monkeypatch.setattr(render_jobs, "_series_render_jobs", {
        "cached-other-series": {
            "jobId": "cached-other-series", "workspace": "default",
            "seriesId": "series-2", "episodeId": "episode-1", "status": "queued",
        },
    })
    monkeypatch.setattr(render_jobs, "_series_render_store", lambda _workspace: Store())
    # The persisted running job has a worker in this process; one without it is a restart's leftover (below).
    monkeypatch.setattr(render_jobs, "_series_render_active_jobs", {"persisted-active"})

    active = render_jobs._active_series_render_for_episode("default", "series-1", "episode-1")

    assert active["jobId"] == "persisted-active"
    assert render_jobs._active_series_render_for_episode("default", "series-1", "episode-2") is None
    assert render_jobs._active_series_render_for_episode("default", "series-2", "episode-1")["jobId"] == "cached-other-series"
    assert render_jobs._active_series_render_for_episode("other", "series-1", "episode-1") is None


def test_explicit_slot_regeneration_preserves_approved_attempt_while_bulk_skips_it():
    from services.series_render_jobs import _series_render_candidates

    episode = {"shots": [{
        "id": "shot-approved", "approvedAttemptId": "attempt-old", "attempts": [],
    }, {
        "id": "shot-missing", "attempts": [],
    }]}

    selected = _series_render_candidates(episode, {
        "mode": "selected", "shotIds": ["shot-approved"],
    })
    missing = _series_render_candidates(episode, {"mode": "missing"})

    assert [shot["id"] for shot in selected] == ["shot-approved"]
    assert [shot["id"] for shot in missing] == ["shot-missing"]


def test_running_series_cancel_waits_for_child_and_runtime_release(monkeypatch):
    job_id = "series-render-safe-cancel"
    child_id = "series-child-running"
    jobs = {
        job_id: {
            "jobId": job_id,
            "workspace": "default",
            "seriesId": "series-1",
            "episodeId": "episode-1",
            "status": "running",
            "stage": "rendering",
            "activeShotId": "shot-1",
            "model": "minimax_h3_legacy",
            "items": [{
                "shotId": "shot-1",
                "attemptId": "attempt-1",
                "status": "running",
                "childJobId": child_id,
            }],
        },
    }
    active = {job_id}
    child_cancels = []
    releases = []

    def load(render_job_id):
        return copy.deepcopy(jobs.get(render_job_id))

    def update(render_job_id, **patch):
        jobs[render_job_id].update(copy.deepcopy(patch))
        return copy.deepcopy(jobs[render_job_id])

    import routers.series_render as routes
    import services.series_render_jobs as render_jobs

    lock = threading.RLock()
    project = {
        "id": "series-1",
        "revision": 1,
        "episodesById": {"episode-1": {"id": "episode-1", "shots": []}},
    }
    monkeypatch.setattr(routes, "_series_render_jobs_lock", lock)
    monkeypatch.setattr(routes, "_series_render_active_jobs", active)
    monkeypatch.setattr(routes, "_load_series_render_job", load)
    monkeypatch.setattr(routes, "_series_render_update", update)
    monkeypatch.setattr(routes, "_series_iso_now", lambda: "2026-08-10T00:00:00Z")
    monkeypatch.setattr(routes, "_series_library_lock", threading.RLock())
    monkeypatch.setattr(routes, "_read_series_workspace", lambda _workspace: {})
    monkeypatch.setattr(routes, "_series_project_or_404", lambda _library, _series_id: project)
    monkeypatch.setattr(routes, "_write_series_workspace", lambda _workspace, library: library)
    monkeypatch.setattr(routes, "_jobs", {child_id: {}})
    monkeypatch.setattr(routes, "_request_generation_cancel", lambda target: child_cancels.append(target))
    monkeypatch.setattr(render_jobs, "_series_render_jobs_lock", lock)
    monkeypatch.setattr(render_jobs, "_series_render_active_jobs", active)
    monkeypatch.setattr(render_jobs, "_load_series_render_job", load)
    monkeypatch.setattr(render_jobs, "_series_render_update", update)
    monkeypatch.setattr(render_jobs, "_series_iso_now", lambda: "2026-08-10T00:00:00Z")
    monkeypatch.setattr(render_jobs, "_run_series_render_job_inner", lambda _job_id: None)
    monkeypatch.setattr(render_jobs, "_is_legacy_h3_model", lambda model: model == "minimax_h3_legacy")
    monkeypatch.setattr(render_jobs, "_is_minimax_h3_model", lambda _model: False)
    monkeypatch.setattr(render_jobs, "_release_legacy_h3_when_queue_allows", lambda target: releases.append(target))
    monkeypatch.setattr(render_jobs, "_release_h3_when_queue_allows", lambda _target: None)

    response = routes.cancel_series_render_job(job_id)

    assert response["status"] == "cancelling"
    assert jobs[job_id]["status"] == "cancelling"
    assert jobs[job_id]["finishedAt"] is None
    assert jobs[job_id]["items"][0]["status"] == "cancelling"
    assert child_cancels == [child_id]

    # The worker owns the safe boundary. Only its finalizer may publish the
    # terminal state and schedule release of the shared H3 runtime.
    active.clear()
    render_jobs._run_series_render_job(job_id)
    assert jobs[job_id]["status"] == "cancelled"
    assert jobs[job_id]["finishedAt"] is not None
    assert jobs[job_id]["items"][0]["status"] == "cancelled"
    assert releases == [job_id]


def test_series_render_task_adapter_lists_snapshots_and_cancels(monkeypatch):
    import services.series_render_jobs as render_jobs

    job = {
        "jobId": "series-render-1",
        "workspace": "film",
        "taskId": "task-series-render-series-render-1",
        "status": "running",
    }
    other = {
        "jobId": "series-render-2",
        "workspace": "other",
        "taskId": "task-series-render-series-render-2",
    }
    published = []
    cancelled = []

    def publish(item, adapter):
        published.append((item["jobId"], adapter))
        return {"id": item["taskId"], "adapter": adapter}

    monkeypatch.setattr(render_jobs, "_series_render_jobs_lock", threading.RLock())
    monkeypatch.setattr(render_jobs, "_series_render_jobs", {
        job["jobId"]: job,
        other["jobId"]: other,
    })
    monkeypatch.setattr(render_jobs, "_publish_series_task", publish)
    monkeypatch.setattr(
        render_jobs, "_cancel_series_render_job",
        lambda job_id: cancelled.append(job_id) or {"jobId": job_id, "status": "cancelling"},
    )

    adapter = render_jobs.series_render_task_adapter
    assert adapter.list("film") == [{"id": "task-series-render-series-render-1", "adapter": "series-render"}]
    assert published == [("series-render-1", "series-render")]
    assert adapter.snapshot("film", "task-series-render-series-render-1")["id"] == "task-series-render-series-render-1"
    assert adapter.snapshot("film", "missing") is None
    assert adapter.snapshot("other", "task-series-render-series-render-1") is None
    assert adapter.cancel("film", "task-series-render-series-render-1") == {
        "jobId": "series-render-1", "status": "cancelling",
    }
    assert cancelled == ["series-render-1"]
    assert adapter.cancel("film", "missing") is None
    monkeypatch.setattr(render_jobs, "_publish_series_task", None)
    assert adapter.list("film") == []
    assert adapter.snapshot("film", "task-series-render-series-render-1") is None


def test_running_series_plan_cancel_waits_for_llm_worker_boundary():
    from unittest.mock import patch

    import routers.series_plan as routes
    import services.series_plan_jobs as plan_jobs

    job_id = "series-plan-safe-cancel"
    stored = {
        job_id: {
            "jobId": job_id,
            "workspace": "default",
            "status": "running",
            "stage": "script",
            "message": "Generating script",
        },
    }
    active = {job_id}

    def load(plan_job_id):
        return copy.deepcopy(stored.get(plan_job_id))

    def update(plan_job_id, **fields):
        current = stored[plan_job_id]
        if (
            current.get("status") == "cancelling"
            and fields.get("status") not in {"cancelling", "cancelled"}
        ):
            return copy.deepcopy(current)
        current.update(copy.deepcopy(fields))
        return copy.deepcopy(current)

    with (
        patch.object(routes, "_load_series_plan_job", load),
        patch.object(routes, "_series_plan_update", update),
        patch.object(routes, "_series_plan_active_jobs", active),
        patch.object(plan_jobs, "_load_series_plan_job", load),
        patch.object(plan_jobs, "_series_plan_update", update),
        patch.object(plan_jobs, "_series_plan_active_jobs", active),
        patch.object(plan_jobs, "_run_series_plan_job_inner", lambda _job_id: None),
        patch.object(plan_jobs, "_run_series_canon_plan_job_inner", lambda _job_id: None),
        patch.object(plan_jobs, "_publish_series_task", lambda _job, _adapter: None),
        patch.object(plan_jobs, "_workspace_dir", lambda _workspace=None: "/unused"),
    ):
        response = routes.cancel_series_episode_plan(job_id)
        assert response["status"] == "cancelling"
        assert stored[job_id].get("finishedAt") is None

        active.clear()
        plan_jobs._run_series_plan_job(job_id)
    assert stored[job_id]["status"] == "cancelled"
    assert stored[job_id]["finishedAt"] is not None
    assert "Completed stages remain recoverable" in stored[job_id]["message"]


def _editable_episode_fixture():
    return {
        "id": "episode-1",
        "outline": {"beats": ["Original beat"]},
        "script": [{
            "id": "scene-1", "order": 1, "locationId": "location-1", "time": "day",
            "participatingCharacterIds": ["character-1"], "purpose": "Original purpose",
            "entryState": "Before", "exitState": "After",
            "beats": [{"id": "scene-beat-1", "kind": "action", "summary": "Original action"}],
            "dialogue": [{
                "id": "dialogue-1", "characterId": "character-1", "text": "Original line",
                "emotion": "neutral", "delivery": "plain",
            }],
        }],
        "shots": [{
            "id": "shot-1", "sceneId": "scene-1", "order": 1, "durationSeconds": 10,
            "framing": "medium", "camera": "static", "action": "Original shot",
            "dialogueBeats": [{
                "id": "shot-dialogue-1", "characterId": "character-1", "text": "Original line",
                "emotion": "neutral", "delivery": "plain",
            }],
            "visibleCharacterIds": ["character-1"], "speakingCharacterIds": ["character-1"],
            "primarySpeakerId": "character-1", "locationId": "location-1",
            "continuityFromShotId": "", "prompt": "Original prompt", "negativePrompt": "",
        }],
        "continuityIssues": [],
        "proposedCanonDelta": {
            "baseRevision": 1, "sourceEpisodeId": "episode-1",
            "add": [{
                "id": "fact-1", "description": "Original fact", "status": "proposed",
                "decision": "pending",
            }],
            "change": [], "retire": [],
        },
    }


def test_manual_episode_proposal_edits_preserve_protected_ids():
    from services.series_plan_jobs import _prepare_edited_series_episode_proposal

    stored = _editable_episode_fixture()
    edited = copy.deepcopy(stored)
    edited["outline"]["beats"][0] = "Edited beat"
    edited["script"][0]["purpose"] = "Edited purpose"
    edited["shots"][0]["prompt"] = "Edited prompt"
    edited["proposedCanonDelta"]["add"][0]["description"] = "Edited fact"
    series = {
        "characters": [{"id": "character-1"}],
        "locations": [{"id": "location-1"}],
    }

    result = _prepare_edited_series_episode_proposal(stored, edited, series)

    assert result["outline"]["beats"] == ["Edited beat"]
    assert result["script"][0]["id"] == "scene-1"
    assert result["script"][0]["purpose"] == "Edited purpose"
    assert result["shots"][0]["id"] == "shot-1"
    assert result["shots"][0]["prompt"] == "Edited prompt"
    assert result["proposedCanonDelta"]["add"][0]["id"] == "fact-1"
    assert result["proposedCanonDelta"]["add"][0]["description"] == "Edited fact"


def test_manual_episode_proposal_rejects_replaced_internal_ids():
    from services.series_plan_jobs import _prepare_edited_series_episode_proposal

    stored = _editable_episode_fixture()
    edited = copy.deepcopy(stored)
    edited["shots"][0]["id"] = "replacement-shot"

    try:
        _prepare_edited_series_episode_proposal(
            stored, edited, {"characters": [{"id": "character-1"}], "locations": [{"id": "location-1"}]},
        )
    except ValueError as exc:
        assert "cannot add, remove, duplicate, or replace internal IDs" in str(exc)
    else:
        raise AssertionError("Replacing a generated shot ID must be rejected")


def _drive_series_render(monkeypatch, tmp_path, child_files):
    """Run one render job over one generated shot with a fake generation queue and the real Series library
    (so the asset path is validated when the output is registered). ``child_files(params)`` names the clip the
    fake queue writes. Returns the job, the generation params sent and the stored series."""
    import services.series_render as series_render
    import services.series_render_jobs as render_jobs
    from services.series_library import (
        append_shot_render_attempt, normalize_series_project, read_series_library, write_series_library,
    )

    root = str(tmp_path)
    series = normalize_series_project({
        "id": "series-1", "title": "T", "allowedProductionMethods": ["generated_video"],
        "episodesById": {"episode-1": {"id": "episode-1", "number": 1, "script": [{"id": "scene_1"}], "shots": [
            {"id": "e1s00", "sceneId": "scene_1", "order": 1, "productionMethod": "generated_video", "durationSeconds": 5}]}},
    }, "series-1", "default")
    episode = series["episodesById"]["episode-1"]
    episode["shots"][0], attempt = append_shot_render_attempt(
        episode["shots"][0], manifest={}, model="minimax_h3", settings={}, seed=1, prompt="a stone lighthouse at night")
    write_series_library(root, {"seriesById": {"series-1": series}, "seriesOrder": ["series-1"]}, "default")
    job = {"jobId": "series-render-1", "kind": "render", "workspace": "default", "seriesId": "series-1",
           "episodeId": "episode-1", "status": "queued", "model": "minimax_h3", "createdAt": 1, "updatedAt": 1,
           "items": [{"shotId": "e1s00", "attemptId": attempt["id"], "status": "queued", "childJobId": None}]}
    jobs, sent = {}, []

    def new_job(params, workspace, *, job_id):
        sent.append(copy.deepcopy(params))
        jobs[job_id] = {"id": job_id, "params": copy.deepcopy(params), "status": "queued"}
        return jobs[job_id]

    def run_generation(child_id):
        child = jobs[child_id]
        child.update(status="completed", output_files=[child_files(child["params"])])

    monkeypatch.setattr(series_render, "build_h3_generation_params", lambda *_args: {
        "model_type": "minimax_h3", "seed": 7, "prompt": "integrated description [Shot 1] A stone lighthouse on a rocky island"})
    for name, value in {
        "_workspace_dir": lambda _workspace=None: root, "_list_workspaces": lambda: [{"name": "default"}],
        "_series_library_lock": threading.RLock(), "_series_iso_now": lambda: "2026-10-14T00:00:00Z",
        "_read_series_workspace": lambda workspace: read_series_library(root, workspace),
        "_write_series_workspace": lambda workspace, library: write_series_library(root, library, workspace),
        "_series_project_or_404": lambda library, series_id: library["seriesById"][series_id],
        "_publish_series_task": None, "_new_generation_job": new_job, "_jobs": jobs, "_run_generation": run_generation,
        "_request_generation_cancel": lambda _child: None, "_series_render_jobs": {"series-render-1": job},
        "_series_render_jobs_lock": threading.RLock(), "_series_render_active_jobs": set(),
    }.items():
        monkeypatch.setattr(render_jobs, name, value)
    render_jobs._series_render_store("default").save(job)
    render_jobs._run_series_render_job_inner("series-render-1")
    return render_jobs._load_series_render_job("series-render-1"), sent, read_series_library(root, "default")["seriesById"]["series-1"]


def _wangp_name(params):
    """What WanGP does: the requested name, else a stamp and the prompt with its spaces and brackets kept."""
    requested = params.get("output_filename")
    return f"{requested}.mp4" if requested else f"2026-10-14-20h05m00s_seed7_{params['prompt']}.mp4"


def test_a_series_render_names_its_clip_so_the_asset_path_accepts_it(monkeypatch, tmp_path):
    """WanGP names an unnamed clip after the prompt (spaces and brackets stay) and adds "(2)" when a name is taken;
    validate_series_asset_uri accepts neither, so every real H3 shot was marked failed after its GPU time."""
    from services.series_library import validate_series_asset_uri

    job, sent, series = _drive_series_render(monkeypatch, tmp_path, _wangp_name)
    assert job["items"][0]["status"] == "completed", job["items"][0].get("error")
    name = sent[0]["output_filename"]
    assert name == f"series-e1s00-{job['items'][0]['childJobId']}"
    uri = next(iter(series["assets"].values()))["uri"]
    assert validate_series_asset_uri(uri) == uri == f"outputs/{name}.mp4"


def test_two_runs_of_the_same_shot_never_share_a_clip_name(monkeypatch, tmp_path):
    first = _drive_series_render(monkeypatch, tmp_path, _wangp_name)[1][0]["output_filename"]
    second = _drive_series_render(monkeypatch, tmp_path, _wangp_name)[1][0]["output_filename"]
    assert first != second, "WanGP would call the second one name(2).mp4, which the asset path refuses"


def _stale_render_checkpoint(monkeypatch, tmp_path, *, claimed=False, cached=False):
    """A render checkpoint on disk that says running, as a server restart leaves it: no worker, an empty cache."""
    import services.series_render_jobs as render_jobs

    job = {"jobId": "series-render-stale", "kind": "render", "workspace": "default", "seriesId": "series-1",
           "episodeId": "episode-1", "status": "running", "stage": "rendering", "activeShotId": "s1", "createdAt": 1,
           "updatedAt": 2, "items": [
               {"shotId": "s1", "attemptId": "attempt_1", "status": "running", "childJobId": "sr-dead"},
               {"shotId": "s2", "attemptId": "attempt_2", "status": "queued", "childJobId": None}]}
    store = SeriesJobStore(str(tmp_path), "render")
    store.save(job)
    monkeypatch.setattr(render_jobs, "_workspace_dir", lambda _workspace=None: str(tmp_path))
    monkeypatch.setattr(render_jobs, "_list_workspaces", lambda: [{"name": "default"}])
    monkeypatch.setattr(render_jobs, "_series_render_jobs_lock", threading.RLock())
    monkeypatch.setattr(render_jobs, "_series_render_jobs", {"series-render-stale": copy.deepcopy(job)} if cached else {})
    monkeypatch.setattr(render_jobs, "_series_render_active_jobs", {"series-render-stale"} if claimed else set())
    return render_jobs, store


def test_a_render_checkpoint_left_running_by_a_restart_is_loaded_as_interrupted(monkeypatch, tmp_path):
    render_jobs, store = _stale_render_checkpoint(monkeypatch, tmp_path)
    loaded = render_jobs._load_series_render_job("series-render-stale")
    assert loaded["status"] == "interrupted" and "restarted" in loaded["message"] and loaded["finishedAt"]
    assert [item["status"] for item in loaded["items"]] == ["running", "queued"], "the items stay for cancel and resume to settle"
    assert store.load("series-render-stale")["status"] == "interrupted", "once: the checkpoint itself is settled"
    assert [item["jobId"] for item in store.recoverable()] == ["series-render-stale"], "and recovery still lists it"


def test_a_render_a_worker_of_this_process_owns_is_left_running(monkeypatch, tmp_path):
    render_jobs, store = _stale_render_checkpoint(monkeypatch, tmp_path, claimed=True)
    assert render_jobs._load_series_render_job("series-render-stale")["status"] == "running"
    assert store.load("series-render-stale")["status"] == "running"
    render_jobs, store = _stale_render_checkpoint(monkeypatch, tmp_path, cached=True)
    assert render_jobs._load_series_render_job("series-render-stale")["status"] == "running", "this process started it"


def test_an_interrupted_render_still_owns_its_episode_whether_or_not_it_was_read_first(monkeypatch, tmp_path):
    """The render/start guard is the design: an interrupted queue keeps the episode (409, resume or cancel it) so a second
    render cannot append duplicate attempts. Settling the checkpoint must not make that depend on who looked first."""
    render_jobs, store = _stale_render_checkpoint(monkeypatch, tmp_path)
    owner = render_jobs._active_series_render_for_episode("default", "series-1", "episode-1")
    assert owner["jobId"] == "series-render-stale" and owner["status"] == "interrupted"
    assert store.load("series-render-stale")["status"] == "interrupted"
    assert render_jobs._load_series_render_job("series-render-stale")["status"] == "interrupted"
    assert render_jobs._active_series_render_for_episode("default", "series-1", "episode-1")["jobId"] == "series-render-stale"
    store.save({**store.load("series-render-stale"), "status": "cancelled"})
    monkeypatch.setattr(render_jobs, "_series_render_jobs", {})
    assert render_jobs._active_series_render_for_episode("default", "series-1", "episode-1") is None, "cancelled releases it"


def test_a_series_delete_is_no_longer_blocked_by_a_checkpoint_a_restart_interrupted(monkeypatch, tmp_path):
    """series_lifecycle reads the durable store: a checkpoint left running blocked the series and episode deletes (409)."""
    from services.series_lifecycle import list_active_series_jobs

    render_jobs, _store = _stale_render_checkpoint(monkeypatch, tmp_path)
    assert [job["jobId"] for job in list_active_series_jobs(str(tmp_path), "default", "series-1")] == ["series-render-stale"]
    render_jobs._load_series_render_job("series-render-stale")
    assert list_active_series_jobs(str(tmp_path), "default", "series-1") == []


def test_the_recovery_list_reports_a_stale_render_as_interrupted(monkeypatch, tmp_path):
    import routers.series_render as routes

    render_jobs, _store = _stale_render_checkpoint(monkeypatch, tmp_path)
    monkeypatch.setattr(routes, "_series_library_workspace", lambda workspace: workspace or "default")
    monkeypatch.setattr(routes, "_series_render_store", render_jobs._series_render_store)
    jobs = routes.list_series_render_recovery("default")["jobs"]
    assert [(job["jobId"], job["status"]) for job in jobs] == [("series-render-stale", "interrupted")]


def _known_series_job(monkeypatch, tmp_path, *, apply=None):
    """A queued known-series bootstrap with auto-apply, over a real library in ``tmp_path`` and a fake writer."""
    import services.series_plan_jobs as plan_jobs
    from services.series_library import create_series_project, read_series_library, write_series_library
    from tests.test_series_planning import _colliding_bootstrap

    root = str(tmp_path)
    series = create_series_project("default")
    write_series_library(root, {"seriesById": {series["id"]: series}, "seriesOrder": [series["id"]]}, "default")
    job = {"jobId": "series-plan-known", "workspace": "default", "seriesId": series["id"], "status": "queued",
           "jobType": "canon", "bootstrapKnownSeries": True, "autoApply": True,
           "sourceSeriesRevision": series["revision"], "request": {"seriesSnapshot": series, "instruction": "A known show"}}
    jobs = {job["jobId"]: job}

    def update(job_id, **patch):
        jobs[job_id].update(copy.deepcopy(patch))
        return copy.deepcopy(jobs[job_id])

    for name, value in {
        "_series_plan_jobs": jobs, "_series_plan_update": update, "_workspace_dir": lambda _workspace=None: root,
        "_list_workspaces": lambda: [{"name": "default"}], "_series_library_lock": threading.RLock(),
        "_read_series_workspace": lambda workspace: read_series_library(root, workspace),
        "_write_series_workspace": lambda workspace, library: write_series_library(root, library, workspace),
        "_series_project_or_404": lambda library, series_id: library["seriesById"][series_id],
        "_comic_writing_llm": lambda _request: None, "_ensure_llm_loaded": lambda: None,
        "_generate_comic_director_json": lambda **_kw: _colliding_bootstrap(),
    }.items():
        monkeypatch.setattr(plan_jobs, name, value)
    if apply is not None:
        monkeypatch.setattr(plan_jobs, "_apply_series_canon_proposal", apply)
    plan_jobs._run_series_canon_plan_job_inner("series-plan-known")
    return jobs["series-plan-known"]


def test_a_known_series_bootstrap_with_colliding_ids_is_applied_as_a_draft(monkeypatch, tmp_path):
    job = _known_series_job(monkeypatch, tmp_path)
    assert job["status"] == "completed" and job["autoApplied"] is True, job.get("error")


def test_a_draft_the_library_refuses_completes_with_its_proposal_and_an_apply_error(monkeypatch, tmp_path):
    """The ValueError of validate_series_ids is not an HTTPException: it failed a ten-minute job whose proposal was fine."""
    def refuse(_job, _proposal):
        raise ValueError("Series Lab contains duplicate id L_OOF at characters[2] and locations[0]")

    job = _known_series_job(monkeypatch, tmp_path, apply=refuse)
    assert job["status"] == "completed" and job["autoApplied"] is False, job.get("error")
    assert "duplicate id L_OOF" in job["applyError"] and job["error"] is None
    assert job["seriesResult"]["characters"], "the proposal stays reviewable"
    assert "could not be applied" in job["message"]

