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
from services.production_project_link import LinkError, bind_producer, read_link_store
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


def test_works_resolve_does_not_reset_a_finished_episode_to_pending(tmp_path):
    """Series bind writes no music stub. MCP resolve defaults to create_stub=True.

    The pending stub's status is copied onto the link the next time the catalog
    lists works, so a completed episode looks unfinished and an agent may start
    another GPU render — or production.run, which then hides series shots.
    """
    from services.production_project_link import note_production_status, resolve_production_project
    from services.production_work_commands import run_command
    series = create_series_project("film", title="Series")
    episode = create_series_episode(series)
    series["episodesById"][episode["id"]] = episode
    write_series_library(str(tmp_path), {"workspaceId": "film", "seriesById": {series["id"]: series},
                                      "seriesOrder": [series["id"]]}, "film")
    bound = attach_episode(str(tmp_path), "film", episode, {})
    production_id = f"series-{episode['id']}"
    note_production_status(str(tmp_path), production_id, "completed")
    assert read_link_store(str(tmp_path))["links"][bound["intent_id"]]["status"] == "completed"

    resolved = resolve_production_project(str(tmp_path), {
        "workspace": "film", "origin": "ui", "format": "full_story",
        "production_id": production_id, "intent_id": f"generation-{production_id}",
        "title": episode["title"], "project": {"kind": "episode", "id": episode["id"]},
    })
    catalog = run_command(str(tmp_path), {
        "operation": "production.works.resolve", "version": 1,
        "input": {
            "workspace": "film", "origin": "ui", "format": "full_story",
            "production_id": production_id, "intent_id": "generation-catalog",
            "title": episode["title"], "project": {"kind": "episode", "id": episode["id"]},
        },
    })
    listed = run_command(str(tmp_path), {
        "operation": "production.works.list", "version": 1, "input": {"workspace": "film"},
    })
    work = next(item for item in listed["works"] if item["production_id"] == production_id)
    assert resolved["production_id"] == catalog["production_id"] == production_id
    assert work["status"] == "completed"
    assert read_link_store(str(tmp_path))["links"][bound["intent_id"]]["status"] == "completed"
    assert not list(tmp_path.glob("*.production.json"))
    assert not read_story_library(str(tmp_path))["projects"]


def test_leftover_pending_stub_does_not_downgrade_a_finished_episode(tmp_path):
    """A pre-fix resolve wrote a pending music stub next to the episode id.

    Listing works used to copy that file status onto the completed link, so the
    catalog looked unfinished and an agent started another GPU render.
    """
    from services.production_project_link import note_production_status
    from services.production_work_commands import run_command
    series = create_series_project("film", title="Series")
    episode = create_series_episode(series)
    series["episodesById"][episode["id"]] = episode
    write_series_library(str(tmp_path), {"workspaceId": "film", "seriesById": {series["id"]: series},
                                      "seriesOrder": [series["id"]]}, "film")
    bound = attach_episode(str(tmp_path), "film", episode, {})
    production_id = f"series-{episode['id']}"
    note_production_status(str(tmp_path), production_id, "completed")
    (tmp_path / f"{production_id}.production.json").write_text(json.dumps({
        "status": "pending",
        "project": {"kind": "episode", "id": episode["id"]},
        "intent_id": bound["intent_id"],
        "origin": "ui",
        "spec": {"title": episode["title"]},
        "format": "full_story",
    }), encoding="utf-8")

    listed = run_command(str(tmp_path), {
        "operation": "production.works.list", "version": 1, "input": {"workspace": "film"},
    })
    work = next(item for item in listed["works"] if item["production_id"] == production_id)
    assert work["status"] == "completed"
    assert read_link_store(str(tmp_path))["links"][bound["intent_id"]]["status"] == "completed"


def test_episode_bind_does_not_write_a_music_stub_or_accept_a_song_run(tmp_path):
    """write_stub still defaults on for a music producer. An episode id is not one."""
    series = create_series_project("film", title="Series")
    episode = create_series_episode(series)
    series["episodesById"][episode["id"]] = episode
    write_series_library(str(tmp_path), {"workspaceId": "film", "seriesById": {series["id"]: series},
                                      "seriesOrder": [series["id"]]}, "film")
    bound = attach_episode(str(tmp_path), "film", episode, {})
    production_id = f"series-{episode['id']}"
    again = bind_producer(str(tmp_path), {
        "workspace": "film", "production_id": production_id, "origin": "mcp",
        "format": "full_story", "title": episode["title"], "write_stub": True,
        "project": {"kind": "episode", "id": episode["id"]},
    })
    assert again["reused"] is True
    assert again["project"] == bound["project"]
    assert not list(tmp_path.glob("*.production.json"))
    with pytest.raises(LinkError) as error:
        bind_producer(str(tmp_path), {
            "workspace": "film", "production_id": production_id, "origin": "mcp",
            "format": "music_video", "title": "Night bus", "write_stub": True,
        })
    assert error.value.code == "invalid_project"
    assert not list(tmp_path.glob("*.production.json"))
    assert not read_story_library(str(tmp_path))["projects"]


def test_first_song_bind_cannot_claim_a_series_episode_id(tmp_path):
    """production.run used series-{episode} before GPU bind and invented a Story.

    attach_episode then failed with invalid_project, so the episode could not
    render until the link file was repaired by hand.
    """
    series = create_series_project("film", title="Series")
    episode = create_series_episode(series)
    series["episodesById"][episode["id"]] = episode
    write_series_library(str(tmp_path), {"workspaceId": "film", "seriesById": {series["id"]: series},
                                      "seriesOrder": [series["id"]]}, "film")
    production_id = f"series-{episode['id']}"
    with pytest.raises(LinkError) as error:
        bind_producer(str(tmp_path), {
            "workspace": "film", "production_id": production_id, "origin": "mcp",
            "format": "music_video", "title": "Night bus", "write_stub": True,
        })
    assert error.value.code == "invalid_project"
    with pytest.raises(LinkError) as error:
        bind_producer(str(tmp_path), {
            "workspace": "film", "production_id": production_id, "origin": "mcp",
            "format": "music_video", "title": "Night bus", "write_stub": True,
            "project": {"kind": "episode", "id": episode["id"]},
        })
    assert error.value.code == "invalid_project"
    assert not read_link_store(str(tmp_path))["links"]
    assert not read_story_library(str(tmp_path))["projects"]
    assert not list(tmp_path.glob("*.production.json"))
    bound = attach_episode(str(tmp_path), "film", episode, {})
    assert bound["production_id"] == production_id
    assert bound["project"] == {"kind": "episode", "id": episode["id"]}


def test_first_resolve_cannot_claim_a_series_episode_id_as_a_story(tmp_path):
    from services.production_project_link import resolve_production_project
    series = create_series_project("film", title="Series")
    episode = create_series_episode(series)
    series["episodesById"][episode["id"]] = episode
    write_series_library(str(tmp_path), {"workspaceId": "film", "seriesById": {series["id"]: series},
                                      "seriesOrder": [series["id"]]}, "film")
    production_id = f"series-{episode['id']}"
    with pytest.raises(LinkError) as error:
        resolve_production_project(str(tmp_path), {
            "workspace": "film", "origin": "mcp", "intent_id": "agent-1",
            "format": "music_video", "title": "Night bus", "production_id": production_id,
        })
    assert error.value.code == "invalid_project"
    resolved = resolve_production_project(str(tmp_path), {
        "workspace": "film", "origin": "mcp", "intent_id": "agent-1",
        "format": "full_story", "title": episode["title"], "production_id": production_id,
    })
    assert resolved["project"] == {"kind": "episode", "id": episode["id"]}
    assert not read_story_library(str(tmp_path))["projects"]
    assert not list(tmp_path.glob("*.production.json"))
    again = attach_episode(str(tmp_path), "film", episode, {})
    assert again["production_id"] == production_id
    assert again["project"] == resolved["project"]


def test_leftover_running_stub_with_newer_timestamp_stays_completed(tmp_path):
    """A crashed production.run left series-{episode}.production.json running.

    Listing used the newer file timestamp and hid the completed link, so an
    agent started another GPU render of a finished episode.
    """
    from services.production_project_link import note_production_status
    from services.production_work_commands import run_command
    series = create_series_project("film", title="Series")
    episode = create_series_episode(series)
    series["episodesById"][episode["id"]] = episode
    write_series_library(str(tmp_path), {"workspaceId": "film", "seriesById": {series["id"]: series},
                                      "seriesOrder": [series["id"]]}, "film")
    bound = attach_episode(str(tmp_path), "film", episode, {})
    production_id = f"series-{episode['id']}"
    note_production_status(str(tmp_path), production_id, "completed")
    (tmp_path / f"{production_id}.production.json").write_text(json.dumps({
        "status": "running",
        "project": {"kind": "episode", "id": episode["id"]},
        "intent_id": bound["intent_id"],
        "origin": "mcp",
        "spec": {"title": "Night bus"},
        "format": "music_video",
        "updated_at": "2099-01-01T00:00:00+00:00",
    }), encoding="utf-8")
    listed = run_command(str(tmp_path), {
        "operation": "production.works.list", "version": 1, "input": {"workspace": "film"},
    })
    work = next(item for item in listed["works"] if item["production_id"] == production_id)
    assert work["status"] == "completed"
    assert work["format"] == "full_story"
    assert read_link_store(str(tmp_path))["links"][bound["intent_id"]]["status"] == "completed"


def test_leftover_pending_stub_with_newer_timestamp_stays_completed(tmp_path):
    from services.production_project_link import note_production_status
    from services.production_work_commands import run_command
    series = create_series_project("film", title="Series")
    episode = create_series_episode(series)
    series["episodesById"][episode["id"]] = episode
    write_series_library(str(tmp_path), {"workspaceId": "film", "seriesById": {series["id"]: series},
                                      "seriesOrder": [series["id"]]}, "film")
    bound = attach_episode(str(tmp_path), "film", episode, {})
    production_id = f"series-{episode['id']}"
    note_production_status(str(tmp_path), production_id, "completed")
    (tmp_path / f"{production_id}.production.json").write_text(json.dumps({
        "status": "pending",
        "project": {"kind": "episode", "id": episode["id"]},
        "intent_id": bound["intent_id"],
        "origin": "ui",
        "spec": {"title": episode["title"]},
        "format": "full_story",
        "updated_at": "2099-01-01T00:00:00+00:00",
    }), encoding="utf-8")
    listed = run_command(str(tmp_path), {
        "operation": "production.works.list", "version": 1, "input": {"workspace": "film"},
    })
    work = next(item for item in listed["works"] if item["production_id"] == production_id)
    assert work["status"] == "completed"
    assert read_link_store(str(tmp_path))["links"][bound["intent_id"]]["status"] == "completed"


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
