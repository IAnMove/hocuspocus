"""Producers bind a project before a worker starts. No GPU and no model."""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.music_production import command_handlers
from services.production_project_link import LINK_FILENAME, LinkError, bind_producer
from services.production_producer_link import link_director_start, link_series_render
from services.series_library import create_series_episode, create_series_project, series_library_path, write_series_library
from services.story_library import read_story_library


def test_a_run_creates_one_story_and_a_repeat_reuses_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    started: list[object] = []

    class _Thread:
        def __init__(self, *, target, args, name, daemon):
            self.target = target
            self.args = args

        def start(self) -> None:
            started.append(self.target)

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr("services.music_production.threading.Thread", _Thread)
    monkeypatch.setattr("services.music_production.validate_spec", lambda spec: spec)
    root = tmp_path / "film"
    root.mkdir()
    handlers = command_handlers(lambda _name: str(root), lambda: str(root), lambda: "http://127.0.0.1:9", lambda: "token")
    body = {"version": 1, "input": {"workspace": "film", "production_id": "clip1", "spec": {"title": "Night bus"}}}
    first = asyncio.run(handlers["production.run"](body))
    second = asyncio.run(handlers["production.run"](body))
    assert first["result"]["running"] is True
    assert second["result"]["running"] is True
    assert len(started) == 2
    projects = read_story_library(str(root))["projects"]
    assert len(projects) == 1
    project = next(iter(projects.values()))
    assert [item["id"] for item in project["productions"]] == ["clip1"]
    state = json.loads((root / "clip1.production.json").read_text(encoding="utf-8"))
    assert state["project"]["kind"] == "story"
    assert state["project"]["id"] == project["id"]
    dry = asyncio.run(handlers["production.run"]({"version": 1, "input": {**body["input"], "dry_run": True, "production_id": "other"}}))
    assert dry["result"]["running"] is False
    assert len(read_story_library(str(root))["projects"]) == 1


def test_an_unknown_project_refuses_the_run_before_the_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("services.music_production.validate_spec", lambda spec: spec)

    class _Thread:
        def __init__(self, **_kwargs):
            raise AssertionError("thread started")

        def start(self) -> None:
            raise AssertionError("thread started")

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr("services.music_production.threading.Thread", _Thread)
    root = tmp_path / "film"
    root.mkdir()
    handlers = command_handlers(lambda _name: str(root), lambda: str(root), lambda: "http://127.0.0.1:9", lambda: "token")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers["production.run"]({
            "version": 1,
            "input": {
                "workspace": "film",
                "production_id": "clip1",
                "spec": {"title": "Night bus"},
                "project": {"kind": "story", "id": "missing"},
            },
        }))
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "invalid_project"
    assert (root / LINK_FILENAME).exists() is False
    assert read_story_library(str(root))["projects"] == {}


def test_director_start_reuses_one_story_for_the_same_pipeline(tmp_path: Path):
    first = link_director_start(str(tmp_path), "film", "pipe1111", {"title": "Dawn"})
    second = link_director_start(str(tmp_path), "film", "pipe1111", {"title": "Dawn"})
    other = link_director_start(str(tmp_path), "film", "pipe2222", {"title": "Dusk"})
    assert first["reused"] is False
    assert second["reused"] is True
    assert second["production_id"] == "pipe1111"
    assert second["project"] == first["project"]
    assert other["project"] != first["project"]
    assert len(read_story_library(str(tmp_path))["projects"]) == 2
    assert list(tmp_path.glob("*.production.json")) == []
    source = inspect.getsource(__import__("services.director_pipeline", fromlist=["start_pipeline"]).start_pipeline)
    assert source.index("attach_director") < source.index("_start_pipeline_worker")


def test_series_render_keeps_the_episode_and_does_not_rewrite_the_library(tmp_path: Path):
    series = create_series_project("film", title="Show")
    episode = create_series_episode(series)
    series["episodesById"] = {episode["id"]: episode}
    write_series_library(str(tmp_path), {
        "workspaceId": "film",
        "seriesById": {series["id"]: series},
        "seriesOrder": [series["id"]],
    }, "film")
    before = Path(series_library_path(str(tmp_path))).read_bytes()
    linked = link_series_render(str(tmp_path), "film", episode["id"])
    again = link_series_render(str(tmp_path), "film", episode["id"])
    assert linked["reused"] is False
    assert again["reused"] is True
    assert linked["project"] == {"kind": "episode", "id": episode["id"]}
    assert read_story_library(str(tmp_path))["projects"] == {}
    assert Path(series_library_path(str(tmp_path))).read_bytes() == before
    assert list(tmp_path.glob("*.production.json")) == []
    text = (Path(__file__).resolve().parents[1] / "app/_launch_runtime.py").read_text(encoding="utf-8")
    body = text.split("def start_series_episode_render", 1)[1].split("\ndef ", 1)[0]
    assert body.index("attach_episode") < body.index("_run_series_render_job")


def test_bind_refuses_a_second_project_for_the_same_id(tmp_path: Path):
    from services.story_library import write_story_library

    write_story_library(str(tmp_path), {
        "version": 2, "revision": 0, "activeId": "",
        "projects": {
            "nara": {"id": "nara", "title": "Nara", "productions": []},
            "kael": {"id": "kael", "title": "Kael", "productions": []},
        },
    }, base_revision=0)
    first = bind_producer(str(tmp_path), {
        "workspace": "film", "production_id": "clip1", "origin": "ui",
        "project": {"kind": "story", "id": "nara"}, "write_stub": False,
    })
    assert first["reused"] is False
    with pytest.raises(LinkError) as caught:
        bind_producer(str(tmp_path), {
            "workspace": "film", "production_id": "clip1", "origin": "ui",
            "project": {"kind": "story", "id": "kael"}, "write_stub": False,
        })
    assert caught.value.code == "invalid_project"
    ids = [item["id"] for item in read_story_library(str(tmp_path))["projects"]["nara"]["productions"]]
    assert ids == ["clip1"]
