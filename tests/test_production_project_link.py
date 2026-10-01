"""A production is linked to one Story or episode before any expensive work."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.production_project_link import (
    LinkError,
    created_story_id,
    note_production_status,
    production_id_for,
    read_link_store,
    resolve_production_project,
)
from services.production_work_catalog import list_works
from services.series_library import create_series_episode, create_series_project, write_series_library
from services.story_library import patch_story_project, read_story_library, write_story_library
from routers.production_projects import create_production_projects_router


def _resolve(root: Path, **extra):
    body = {"workspace": "film", "origin": "mcp", "intent_id": "clip1", "format": "music_video", "title": "Night bus"}
    body.update(extra)
    return resolve_production_project(str(root), body)


def _story_count(root: Path) -> int:
    return len(read_story_library(str(root))["projects"])


def test_retry_reuses_the_story_and_production_and_ignores_the_active_story(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    kept = {"version": 1, "id": "story-open", "title": "Open", "projectType": "full_story", "language": "Español"}
    patch_story_project(str(root), "story-open", kept, base_revision=0, make_active=True)

    first = _resolve(root, idea="a bus at night")
    second = _resolve(root)

    assert first["production_id"] == second["production_id"]
    assert first["project"]["id"] == created_story_id("film", "clip1")
    assert first["project"]["id"] != "story-open"
    assert read_story_library(str(root))["activeId"] == "story-open"
    assert _story_count(root) == 2
    project = read_story_library(str(root))["projects"][first["project"]["id"]]
    assert project["projectType"] == "music_video"
    assert project["productions"][0]["id"] == first["production_id"]
    stub = json.loads((root / f"{first['production_id']}.production.json").read_text(encoding="utf-8"))
    assert stub["status"] == "pending"
    assert stub["project"] == first["project"]
    assert "story_seed" not in first


def test_invalid_project_does_not_create_a_story(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    with pytest.raises(LinkError) as raised:
        _resolve(root, project={"kind": "story", "id": "missing-story"})
    assert raised.value.code == "invalid_project"
    assert _story_count(root) == 0
    assert read_link_store(str(root))["links"] == {}


def test_episode_is_reused_and_a_missing_episode_creates_nothing(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    series = create_series_project("film", title="Show")
    episode = create_series_episode(series)
    series["episodesById"] = {episode["id"]: episode}
    write_series_library(str(root), {
        "workspaceId": "film",
        "seriesById": {series["id"]: series},
        "seriesOrder": [series["id"]],
    }, "film")

    linked = _resolve(root, project={"kind": "episode", "id": episode["id"]})

    assert linked["project"] == {"kind": "episode", "id": episode["id"]}
    assert _story_count(root) == 0
    with pytest.raises(LinkError) as raised:
        _resolve(root, intent_id="other", project={"kind": "episode", "id": "episode-missing"})
    assert raised.value.code == "invalid_project"
    assert _story_count(root) == 0
    assert len(read_link_store(str(root))["links"]) == 1


def test_partial_write_reconciles_on_retry_without_a_second_story(tmp_path: Path, monkeypatch):
    root = tmp_path / "film"
    root.mkdir()
    import services.production_project_link as link_module

    original = link_module._ensure_stub

    def boom(workspace_dir, record):
        boom.calls += 1
        if boom.calls == 1:
            raise OSError("disk")
        return original(workspace_dir, record)

    boom.calls = 0
    monkeypatch.setattr(link_module, "_ensure_stub", boom)
    with pytest.raises(LinkError) as raised:
        _resolve(root)
    assert raised.value.code == "partial_write"
    monkeypatch.setattr(link_module, "_ensure_stub", original)
    again = _resolve(root)
    assert again["project"]["id"] == created_story_id("film", "clip1")
    assert _story_count(root) == 1
    assert (root / f"{again['production_id']}.production.json").is_file()


def test_stale_story_save_is_restored_for_the_same_intent(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    first = _resolve(root)
    library = read_story_library(str(root))
    write_story_library(str(root), {"version": 2, "revision": library["revision"], "activeId": "", "projects": {}}, base_revision=library["revision"])
    assert _story_count(root) == 0
    again = _resolve(root)
    assert again["project"]["id"] == first["project"]["id"]
    assert again["production_id"] == first["production_id"]
    assert _story_count(root) == 1


def test_link_keeps_a_newer_story_save_and_still_attaches(tmp_path: Path, monkeypatch):
    """A Story Lab save during resolve must not be overwritten by the stale snapshot."""
    root = tmp_path / "film"
    root.mkdir()
    project = {
        "version": 1,
        "id": "story-open",
        "title": "Open",
        "projectType": "full_story",
        "language": "Español",
        "beats": [{"id": "beat-1", "title": "Opening"}],
    }
    patch_story_project(str(root), "story-open", project, base_revision=0, make_active=True)

    import services.story_library as story_library

    original = story_library.patch_story_project

    def collide(workspace_dir, project_id, body, *, base_revision, make_active=False):
        collide.calls += 1
        if collide.calls == 1:
            current = read_story_library(workspace_dir)
            newer = dict(current["projects"]["story-open"])
            newer["title"] = "Open — edited"
            newer["beats"] = [
                {"id": "beat-1", "title": "Opening"},
                {"id": "beat-2", "title": "The user just wrote this"},
            ]
            write_story_library(
                workspace_dir,
                {**current, "projects": {**current["projects"], "story-open": newer}},
                base_revision=current["revision"],
            )
            raise story_library.StoryLibraryRevisionConflict(base_revision, current["revision"] + 1)
        return original(
            workspace_dir, project_id, body, base_revision=base_revision, make_active=make_active,
        )

    collide.calls = 0
    monkeypatch.setattr(story_library, "patch_story_project", collide)

    linked = resolve_production_project(str(root), {
        "workspace": "film",
        "origin": "ui",
        "intent_id": "clip1",
        "format": "music_video",
        "title": "Night bus",
        "project": {"kind": "story", "id": "story-open"},
    })
    saved = read_story_library(str(root))["projects"]["story-open"]
    assert saved["title"] == "Open — edited"
    assert {item["id"] for item in saved["beats"]} == {"beat-1", "beat-2"}
    assert linked["production_id"] in {item["id"] for item in saved["productions"]}


def test_new_execution_adds_a_production_on_the_same_project(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    first = _resolve(root)
    second = _resolve(root, new_execution=True)
    assert second["project"] == first["project"]
    assert second["production_id"] == production_id_for("film", "clip1", 2)
    assert second["production_id"] != first["production_id"]
    assert _story_count(root) == 1
    productions = read_story_library(str(root))["projects"][first["project"]["id"]]["productions"]
    assert {item["id"] for item in productions} == {first["production_id"], second["production_id"]}


def test_concurrent_resolve_returns_one_record(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    found = []
    errors = []

    def work():
        try:
            found.append(_resolve(root))
        except Exception as error:  # noqa: BLE001 — the test records the worker failure
            errors.append(error)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len({item["production_id"] for item in found}) == 1
    assert _story_count(root) == 1


def test_status_and_catalog_keep_one_row_for_one_work(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    linked = _resolve(root, title="Shared title")
    (root / "loose.production.json").write_text(json.dumps({
        "status": "failed", "spec": {"title": "Shared title"},
    }), encoding="utf-8")
    (root / "poster.jpg").write_bytes(b"not a project")
    note_production_status(str(root), linked["production_id"], "failed")
    state_path = root / f"{linked['production_id']}.production.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["status"] = "completed"
    state["contact_sheet"] = "sheet.jpg"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    (root / "_director_pipeline_abcd.json").write_text(json.dumps({
        "pipeline_id": "abcd", "production_id": linked["production_id"], "title": "Shared title",
        "pipeline_type": "music_video", "status": "completed", "story_id": linked["project"]["id"],
    }), encoding="utf-8")

    listed = list_works(str(root), "film")
    by_id = {item["production_id"]: item for item in listed["works"]}

    assert linked["production_id"] in by_id
    assert "loose" in by_id
    assert by_id["loose"]["project"] is None
    assert by_id["loose"]["linked"] is False
    assert by_id[linked["production_id"]]["project"]["id"] == linked["project"]["id"]
    assert by_id[linked["production_id"]]["status"] == "completed"
    assert by_id[linked["production_id"]]["preview"] == "sheet.jpg"
    assert listed["total"] == 2
    assert "poster.jpg" not in json.dumps(listed)
    assert "/" not in json.dumps(by_id[linked["production_id"]]["preview"])


def test_resolve_retry_does_not_clobber_a_live_production_file(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    first = _resolve(root)
    path = root / f"{first['production_id']}.production.json"
    live = json.loads(path.read_text(encoding="utf-8"))
    live.update(
        status="running",
        clips={"verse1": {"file": "verse1.mp4", "qa": {"best_r": 0.41}}},
        frames={"verse1": "verse1.png"},
        scenes={"verse1": {"file": "verse1-scene.mp4", "dur": 4.0}},
    )
    path.write_text(json.dumps(live), encoding="utf-8")

    import services.production_project_link as link_module

    original_read = link_module._read_json
    first_read = {"done": False}

    def race(target):
        body = original_read(target)
        if target == str(path) and not first_read["done"] and isinstance(body, dict) and body.get("status") == "running":
            first_read["done"] = True
            newer = dict(body)
            newer["clips"] = {**body["clips"], "chorus": {"file": "chorus.mp4"}}
            path.write_text(json.dumps(newer), encoding="utf-8")
        return body

    link_module._read_json = race
    try:
        again = _resolve(root)
    finally:
        link_module._read_json = original_read

    after = json.loads(path.read_text(encoding="utf-8"))
    assert again["production_id"] == first["production_id"]
    assert after["status"] == "running"
    assert after["clips"]["verse1"]["file"] == "verse1.mp4"
    assert after["clips"]["chorus"]["file"] == "chorus.mp4"
    assert after["scenes"]["verse1"]["file"] == "verse1-scene.mp4"


def test_resolve_copies_project_onto_a_legacy_file_without_dropping_clips(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    first = _resolve(root)
    path = root / f"{first['production_id']}.production.json"
    path.write_text(json.dumps({
        "status": "running",
        "spec": {"title": "Night bus", "song": {"lyrics": "x"}},
        "clips": {"verse1": {"file": "verse1.mp4"}},
    }), encoding="utf-8")
    again = _resolve(root)
    after = json.loads(path.read_text(encoding="utf-8"))
    assert again["production_id"] == first["production_id"]
    assert after["status"] == "running"
    assert after["clips"] == {"verse1": {"file": "verse1.mp4"}}
    assert after["project"] == first["project"]
    assert after["intent_id"] == first["intent_id"]
    assert after["spec"]["song"] == {"lyrics": "x"}


def test_http_resolve_retry_and_unknown_workspace(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    app = FastAPI()
    app.include_router(create_production_projects_router(
        workspace_dir=lambda name: str(root) if name == "film" else str(tmp_path / "missing"),
    ))
    client = TestClient(app)
    body = {"workspace": "film", "origin": "wizard", "intent_id": "wiz1", "format": "quick_video", "title": "Sketch"}
    first = client.post("/api/v1/production-projects/resolve", json=body)
    second = client.post("/api/v1/production-projects/resolve", json=body)
    assert first.status_code == 200
    assert second.json()["production_id"] == first.json()["production_id"]
    assert second.json()["review"]["project"]["kind"] == "story"
    missing = client.post("/api/v1/production-projects/resolve", json={
        **body, "intent_id": "wiz-missing", "project": {"kind": "story", "id": "nope"},
    })
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "invalid_project"
    conflict = client.post("/api/v1/production-projects/resolve", json={
        **body, "project": {"kind": "story", "id": "nope"},
    })
    assert conflict.status_code == 422
    assert _story_count(root) == 1
    assert client.post("/api/v1/production-projects/resolve", json={**body, "workspace": "other"}).status_code == 404
    listing = client.get("/api/v1/production-projects", params={"workspace": "film"})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
