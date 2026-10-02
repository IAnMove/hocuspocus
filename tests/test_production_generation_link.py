"""Ownership exists before a worker runs; replays keep the producer's identity."""
import asyncio
import ast
import copy
import json
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi import HTTPException

from services import music_production as music
from services.production_generation_link import attach_episode, register_generation
from services.production_project_link import LinkError, read_link_store
from services.production_work_catalog import list_works
from services.series_library import create_series_project, create_series_episode, write_series_library
from services.story_library import read_story_library


SPEC = {"title": "Night bus", "song": {"lyrics": "Night bus", "caption": "pop", "duration": 60, "bpm": 120},
        "style": {}, "shots": [{"key": "s1", "kind": "still", "frame": "A night bus"}]}


def test_music_worker_observes_the_persisted_owner_and_retry_keeps_it(tmp_path, monkeypatch):
    handlers = music.command_handlers(lambda _ws: str(tmp_path), lambda: str(tmp_path), lambda: "http://studio", lambda: "token")
    seen = []

    class Worker:
        def __init__(self, *, target, args, **kwargs):
            self.target, self.args = target, args
        def is_alive(self):
            return False
        def start(self):
            state = json.loads((tmp_path / "clip1.production.json").read_text())
            assert state["project"]["id"] in read_story_library(str(tmp_path))["projects"]
            seen.append(state["project"])

    monkeypatch.setattr(music.threading, "Thread", Worker)
    monkeypatch.setattr(music, "require_free_disk", lambda _root: None)
    monkeypatch.setattr(music, "_threads", {})
    request = {"version": 1, "input": {"workspace": "film", "production_id": "clip1", "spec": copy.deepcopy(SPEC)}}
    first = asyncio.run(handlers[music.RUN](request))
    second = asyncio.run(handlers[music.RUN](request))
    assert first["result"]["production_id"] == second["result"]["production_id"] == "clip1"
    assert seen[0] == seen[1]
    assert len(read_story_library(str(tmp_path))["projects"]) == 1
    assert [row["production_id"] for row in list_works(str(tmp_path), "film")["works"]] == ["clip1"]


def test_invalid_music_owner_and_dry_run_start_no_worker_or_story(tmp_path, monkeypatch):
    handlers = music.command_handlers(lambda _ws: str(tmp_path), lambda: str(tmp_path), lambda: "http://studio", lambda: "token")
    monkeypatch.setattr(music, "require_free_disk", lambda _root: None)
    request = {"version": 1, "input": {"workspace": "film", "production_id": "bad", "spec": copy.deepcopy(SPEC),
                                      "project": {"kind": "story", "id": "missing"}}}
    with pytest.raises(HTTPException) as error:
        asyncio.run(handlers[music.RUN](request))
    assert error.value.detail["code"] == "invalid_project"
    assert not read_story_library(str(tmp_path))["projects"]
    request["input"]["dry_run"] = True
    asyncio.run(handlers[music.RUN](request))
    assert not read_link_store(str(tmp_path))["links"]


def test_pre_resolved_work_is_reused_and_not_duplicated(tmp_path):
    from services.production_project_link import resolve_production_project
    work = resolve_production_project(str(tmp_path), {"workspace": "film", "origin": "wizard", "intent_id": "asked",
                                                    "format": "music_video", "title": "Night bus"})
    started = register_generation(str(tmp_path), "film", work["production_id"], {}, form="music_video", title="Night bus")
    assert started["intent_id"] == "asked"
    assert started["project"] == work["project"]
    assert len(read_link_store(str(tmp_path))["links"]) == 1


def test_episode_registration_keeps_series_owner_and_no_fake_music_state(tmp_path):
    series = create_series_project("film", title="Series")
    episode = create_series_episode(series)
    series["episodesById"][episode["id"]] = episode
    write_series_library(str(tmp_path), {"workspaceId": "film", "seriesById": {series["id"]: series},
                                      "seriesOrder": [series["id"]]}, "film")
    first = attach_episode(str(tmp_path), "film", episode, {})
    second = attach_episode(str(tmp_path), "film", episode, {})
    assert first["production_id"] == second["production_id"]
    assert episode["productionIds"] == [first["production_id"]]
    assert not read_story_library(str(tmp_path))["projects"]
    assert not list(tmp_path.glob("*.production.json"))


@pytest.mark.parametrize("persist_failure", [False, True])
def test_director_owner_is_saved_before_planning(tmp_path, monkeypatch, persist_failure):
    from services import director_pipeline as pipeline
    monkeypatch.setattr(pipeline, "_normalise_master_seed", lambda _p: None)
    monkeypatch.setattr(pipeline, "_validate_director_models", lambda _p: None)
    monkeypatch.setattr(pipeline, "_resolve_fresh_shot_image_policy", lambda _p: "generate")
    monkeypatch.setattr(pipeline, "_create_director_video_execution_profile", lambda _p: {})
    monkeypatch.setattr(pipeline, "_wgp", SimpleNamespace(save_path=str(tmp_path)))
    monkeypatch.setattr(pipeline, "_pipeline_state_observer", None)
    monkeypatch.setattr(pipeline, "_pipelines", {})
    seen = []
    def start(pid):
        state = json.loads((tmp_path / f"_director_pipeline_{pid}.json").read_text())
        rows = list_works(str(tmp_path), "default")["works"]
        assert len(rows) == 1
        assert state["production_id"] == rows[0]["production_id"]
        assert state["project"] == rows[0]["project"]
        assert state["project"]["id"] in read_story_library(str(tmp_path))["projects"]
        seen.append(pid)
    monkeypatch.setattr(pipeline, "_start_pipeline_worker", start)
    if persist_failure:
        monkeypatch.setattr(pipeline, "_save_pipeline_state", lambda _pid: False)
        with pytest.raises(ValueError, match="persist"):
            pipeline.start_pipeline({"pipeline_type": "music_video", "scene_description": "Night bus"})
        assert not seen and not pipeline._pipelines
        return
    pid = pipeline.start_pipeline({"pipeline_type": "music_video", "scene_description": "Night bus"})
    assert seen == [pid]


@pytest.mark.parametrize("identifier", ["../outside", "bad/id", "", 42])
def test_bad_production_identity_has_no_side_effect(tmp_path, identifier):
    with pytest.raises(LinkError):
        register_generation(str(tmp_path), "film", identifier, {}, form="music_video", title="Clip")
    assert not read_story_library(str(tmp_path))["projects"]


def test_production_cannot_get_a_second_owner_by_another_intent(tmp_path):
    from services.production_project_link import resolve_production_project
    request = {"workspace": "film", "origin": "ui", "intent_id": "one", "format": "quick_video", "production_id": "clip1"}
    first = resolve_production_project(str(tmp_path), request)
    second = resolve_production_project(str(tmp_path), {**request, "intent_id": "other"})
    assert second["production_id"] == first["production_id"] == "clip1"
    assert second["project"] == first["project"]
    assert list(read_link_store(str(tmp_path))["links"]) == ["one"]
    assert len(read_story_library(str(tmp_path))["projects"]) == 1


def test_native_batch_resolve_reuses_the_bound_episode_production(tmp_path):
    """Series GPU render binds with b+digest; the native batch resolve uses generation-series-*."""
    from services.production_project_link import resolve_production_project
    series = create_series_project("film", title="Series")
    episode = create_series_episode(series)
    series["episodesById"][episode["id"]] = episode
    write_series_library(str(tmp_path), {"workspaceId": "film", "seriesById": {series["id"]: series},
                                      "seriesOrder": [series["id"]]}, "film")
    bound = attach_episode(str(tmp_path), "film", episode, {})
    production_id = f"series-{episode['id']}"
    resolved = resolve_production_project(str(tmp_path), {
        "workspace": "film", "origin": "ui", "format": "full_story",
        "production_id": production_id, "intent_id": f"generation-{production_id}",
        "title": episode["title"], "project": {"kind": "episode", "id": episode["id"]},
    }, create_stub=False)
    assert resolved["production_id"] == bound["production_id"] == production_id
    assert resolved["project"] == bound["project"] == {"kind": "episode", "id": episode["id"]}
    assert list(read_link_store(str(tmp_path))["links"]) == [bound["intent_id"]]
    other = create_series_episode(series)
    series["episodesById"][other["id"]] = other
    write_series_library(str(tmp_path), {"workspaceId": "film", "seriesById": {series["id"]: series},
                                      "seriesOrder": [series["id"]]}, "film")
    with pytest.raises(LinkError) as error:
        resolve_production_project(str(tmp_path), {
            "workspace": "film", "origin": "ui", "format": "full_story",
            "production_id": production_id, "intent_id": f"generation-{production_id}",
            "project": {"kind": "episode", "id": other["id"]},
        }, create_stub=False)
    assert error.value.code == "invalid_project"
    assert not read_story_library(str(tmp_path))["projects"]
    assert not list(tmp_path.glob("*.production.json"))


def test_series_render_worker_observes_episode_production_ids_on_disk(tmp_path, monkeypatch):
    import threading
    import time
    import uuid
    from datetime import datetime, timezone
    from services.series_library import read_series_library
    import services.series_reference_router as references
    series = create_series_project("film", title="Show")
    episode = create_series_episode(series)
    episode["script"] = [{"id": "scene1", "locationId": ""}]
    episode["shots"] = [{"id": "s1", "sceneId": "scene1", "productionMethod": "generated_video", "order": 1,
                         "durationSeconds": 8, "prompt": "A bus", "attempts": []}]
    series["episodesById"][episode["id"]] = episode
    write_series_library(str(tmp_path), {"workspaceId": "film", "seriesById": {series["id"]: series},
                                      "seriesOrder": [series["id"]]}, "film")
    jobs, seen = {}, []
    class Worker:
        def __init__(self, **kwargs):
            pass
        def start(self):
            saved = read_series_library(str(tmp_path), "film")["seriesById"][series["id"]]["episodesById"][episode["id"]]
            assert saved["productionIds"] == [f"series-{episode['id']}"]
            assert saved["shots"][0]["attempts"][0]["status"] == "queued"
            assert not read_story_library(str(tmp_path))["projects"]
            seen.append(saved)
    monkeypatch.setattr(references, "route_shot_references", lambda *_args: {"errors": [], "strategy": "first_frame", "selected": []})
    namespace = {
        "copy": copy, "time": time, "uuid": uuid, "HTTPException": HTTPException,
        "threading": SimpleNamespace(Thread=Worker),
        "_series_library_lock": threading.RLock(), "_series_render_jobs_lock": threading.RLock(),
        "_series_render_jobs": jobs, "_series_library_workspace": lambda _value: "film",
        "_workspace_dir": lambda _ws: str(tmp_path),
        "_read_series_workspace": lambda _ws: read_series_library(str(tmp_path), "film"),
        "_write_series_workspace": lambda _ws, library: write_series_library(str(tmp_path), library, "film"),
        "_series_project_or_404": lambda library, identifier: library["seriesById"][identifier],
        "_active_series_render_for_episode": lambda *_args: None,
        "_series_iso_now": lambda: datetime.now(timezone.utc).isoformat(),
        "_series_render_store": lambda _ws: SimpleNamespace(save=lambda job: None),
        "_run_series_render_job": lambda _id: None,
    }
    source = Path(__file__).resolve().parents[1] / "app" / "_launch_runtime.py"
    tree = ast.parse(source.read_text())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"_series_render_candidates", "start_series_episode_render"}]
    for function in functions:
        function.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    exec(compile(module, str(source), "exec"), namespace)
    result = namespace["start_series_episode_render"](series["id"], episode["id"], {"workspace": "film"})
    assert seen and jobs[result["jobId"]]["productionId"] == f"series-{episode['id']}"
