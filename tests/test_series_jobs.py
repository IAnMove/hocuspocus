import ast
import copy
import json
import sys
import threading
import time
import types
from pathlib import Path

from services.series_jobs import SeriesJobStore


_ROOT = Path(__file__).parents[1]
_LAUNCH = _ROOT / "app" / "launch.py"


def _load_launch_functions(*names: str, namespace: dict) -> None:
    tree = ast.parse(_LAUNCH.read_text(encoding="utf-8"), filename=str(_LAUNCH))
    selected = []
    for name in names:
        function = next(
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        )
        function = copy.deepcopy(function)
        function.decorator_list = []
        selected.append(function)
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(_LAUNCH), "exec"), namespace)


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


def test_series_render_settlement_marks_fully_rendered_episode_completed():
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
    writes = []
    namespace = {
        "copy": copy,
        "_series_library_lock": threading.RLock(),
        "_read_series_workspace": lambda _workspace: copy.deepcopy(library),
        "_series_project_or_404": lambda current, series_id: current["seriesById"][series_id],
        "_write_series_workspace": lambda _workspace, current: writes.append(copy.deepcopy(current)) or current,
        "_series_iso_now": lambda: "2026-08-11T00:00:00Z",
    }
    _load_launch_functions("_series_settle_episode_render_status", namespace=namespace)

    status = namespace["_series_settle_episode_render_status"]({
        "workspace": "default", "seriesId": "series-1", "episodeId": "episode-1",
    })

    assert status == "completed"
    assert writes[0]["seriesById"]["series-1"]["revision"] == 5
    episode = writes[0]["seriesById"]["series-1"]["episodesById"]["episode-1"]
    assert episode["status"] == "completed"
    assert episode["updatedAt"] == "2026-08-11T00:00:00Z"


def test_series_render_settlement_returns_partial_episode_to_shot_plan():
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
    writes = []
    namespace = {
        "copy": copy,
        "_series_library_lock": threading.RLock(),
        "_read_series_workspace": lambda _workspace: copy.deepcopy(library),
        "_series_project_or_404": lambda current, series_id: current["seriesById"][series_id],
        "_write_series_workspace": lambda _workspace, current: writes.append(copy.deepcopy(current)) or current,
        "_series_iso_now": lambda: "2026-08-11T00:00:00Z",
    }
    _load_launch_functions("_series_settle_episode_render_status", namespace=namespace)

    status = namespace["_series_settle_episode_render_status"]({
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


def test_active_render_guard_is_scoped_to_workspace_series_and_episode():
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

    namespace = {
        "copy": copy,
        "json": json,
        "_series_render_jobs_lock": threading.RLock(),
        "_series_render_jobs": {
            "cached-other-series": {
                "jobId": "cached-other-series", "workspace": "default",
                "seriesId": "series-2", "episodeId": "episode-1", "status": "queued",
            },
        },
        "_series_render_store": lambda _workspace: Store(),
    }
    _load_launch_functions("_active_series_render_for_episode", namespace=namespace)

    active = namespace["_active_series_render_for_episode"]("default", "series-1", "episode-1")

    assert active["jobId"] == "persisted-active"
    assert namespace["_active_series_render_for_episode"]("default", "series-1", "episode-2") is None
    assert namespace["_active_series_render_for_episode"]("default", "series-2", "episode-1")["jobId"] == "cached-other-series"
    assert namespace["_active_series_render_for_episode"]("other", "series-1", "episode-1") is None


def test_explicit_slot_regeneration_preserves_approved_attempt_while_bulk_skips_it():
    namespace = {}
    _load_launch_functions("_series_render_candidates", namespace=namespace)
    episode = {"shots": [{
        "id": "shot-approved", "approvedAttemptId": "attempt-old", "attempts": [],
    }, {
        "id": "shot-missing", "attempts": [],
    }]}

    selected = namespace["_series_render_candidates"](episode, {
        "mode": "selected", "shotIds": ["shot-approved"],
    })
    missing = namespace["_series_render_candidates"](episode, {"mode": "missing"})

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

    series_module = types.ModuleType("services.series_library")
    series_module.update_shot_render_attempt = lambda shot, _attempt_id, **_patch: shot
    monkeypatch.setitem(sys.modules, "services.series_library", series_module)

    class HTTPException(Exception):
        def __init__(self, status_code, detail):
            super().__init__(detail)
            self.status_code = status_code

    namespace = {
        "HTTPException": HTTPException,
        "copy": copy,
        "time": time,
        "_jobs": {child_id: {}},
        "_series_render_jobs_lock": threading.RLock(),
        "_series_render_active_jobs": active,
        "_load_series_render_job": load,
        "_series_render_update": update,
        "_series_iso_now": lambda: "2026-08-10T00:00:00Z",
        "_series_library_lock": threading.RLock(),
        "_read_series_workspace": lambda _workspace: {},
        "_series_project_or_404": lambda _library, _series_id: {
            "id": "series-1",
            "revision": 1,
            "episodesById": {"episode-1": {"id": "episode-1", "shots": []}},
        },
        "_write_series_workspace": lambda _workspace, library: library,
        "_request_generation_cancel": lambda target: child_cancels.append(target),
        "_run_series_render_job_inner": lambda _job_id: None,
        "_is_legacy_h3_model": lambda model: model == "minimax_h3_legacy",
        "_is_minimax_h3_model": lambda _model: False,
        "_release_legacy_h3_when_queue_allows": lambda target: releases.append(target),
        "_release_h3_when_queue_allows": lambda _target: None,
    }
    _load_launch_functions(
        "cancel_series_render_job",
        "_run_series_render_job",
        namespace=namespace,
    )

    response = namespace["cancel_series_render_job"](job_id)

    assert response["status"] == "cancelling"
    assert jobs[job_id]["status"] == "cancelling"
    assert jobs[job_id]["finishedAt"] is None
    assert jobs[job_id]["items"][0]["status"] == "cancelling"
    assert child_cancels == [child_id]

    # The worker owns the safe boundary. Only its finalizer may publish the
    # terminal state and schedule release of the shared H3 runtime.
    active.clear()
    namespace["_run_series_render_job"](job_id)
    assert jobs[job_id]["status"] == "cancelled"
    assert jobs[job_id]["finishedAt"] is not None
    assert jobs[job_id]["items"][0]["status"] == "cancelled"
    assert releases == [job_id]


def test_running_series_plan_cancel_waits_for_llm_worker_boundary():
    job_id = "series-plan-safe-cancel"
    jobs = {
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
        return copy.deepcopy(jobs.get(plan_job_id))

    def update(plan_job_id, **patch):
        current = jobs[plan_job_id]
        if (
            current.get("status") == "cancelling"
            and patch.get("status") not in {"cancelling", "cancelled"}
        ):
            return copy.deepcopy(current)
        current.update(copy.deepcopy(patch))
        return copy.deepcopy(current)

    class HTTPException(Exception):
        def __init__(self, status_code, detail):
            super().__init__(detail)
            self.status_code = status_code

    namespace = {
        "HTTPException": HTTPException,
        "copy": copy,
        "time": time,
        "_series_plan_jobs_lock": threading.RLock(),
        "_series_plan_active_jobs": active,
        "_load_series_plan_job": load,
        "_series_plan_update": update,
        "_publish_series_task": lambda _job, _adapter: None,
        "_run_series_plan_job_inner": lambda _job_id: None,
        "_run_series_canon_plan_job_inner": lambda _job_id: None,
        "_workspace_dir": lambda _workspace=None: "/unused",
    }
    _load_launch_functions(
        "_planning_cancel_message",
        "cancel_series_episode_plan",
        "_run_series_plan_job",
        namespace=namespace,
    )

    response = namespace["cancel_series_episode_plan"](job_id)
    assert response["status"] == "cancelling"
    assert jobs[job_id]["finishedAt"] is None

    active.clear()
    namespace["_run_series_plan_job"](job_id)
    assert jobs[job_id]["status"] == "cancelled"
    assert jobs[job_id]["finishedAt"] is not None
    assert "Completed stages remain recoverable" in jobs[job_id]["message"]


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
    namespace = {"copy": copy}
    _load_launch_functions("_prepare_edited_series_episode_proposal", namespace=namespace)
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

    result = namespace["_prepare_edited_series_episode_proposal"](stored, edited, series)

    assert result["outline"]["beats"] == ["Edited beat"]
    assert result["script"][0]["id"] == "scene-1"
    assert result["script"][0]["purpose"] == "Edited purpose"
    assert result["shots"][0]["id"] == "shot-1"
    assert result["shots"][0]["prompt"] == "Edited prompt"
    assert result["proposedCanonDelta"]["add"][0]["id"] == "fact-1"
    assert result["proposedCanonDelta"]["add"][0]["description"] == "Edited fact"


def test_manual_episode_proposal_rejects_replaced_internal_ids():
    namespace = {"copy": copy}
    _load_launch_functions("_prepare_edited_series_episode_proposal", namespace=namespace)
    stored = _editable_episode_fixture()
    edited = copy.deepcopy(stored)
    edited["shots"][0]["id"] = "replacement-shot"

    try:
        namespace["_prepare_edited_series_episode_proposal"](
            stored, edited, {"characters": [{"id": "character-1"}], "locations": [{"id": "location-1"}]},
        )
    except ValueError as exc:
        assert "cannot add, remove, duplicate, or replace internal IDs" in str(exc)
    else:
        raise AssertionError("Replacing a generated shot ID must be rejected")
