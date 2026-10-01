"""The shared catalog lists MCP and Wizard works and points at the shot view."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.production_projects import create_production_projects_router
from services.production_project_link import REVIEW_EVENT, resolve_production_project
from services.production_work_commands import WorkCommandError, run_command
from services.series_library import create_series_episode, create_series_project, write_series_library
from services.story_library import read_story_library, write_story_library


def _list(root: Path, **extra):
    data = {"workspace": "film", "format": "", "status": ""}
    data.update(extra)
    return run_command(str(root), {"operation": "production.works.list", "version": 1, "input": data})


def _resolve(root: Path, **extra):
    body = {
        "workspace": "film",
        "origin": "mcp",
        "intent_id": "clip1",
        "format": "music_video",
        "title": "Night bus",
    }
    body.update(extra)
    return resolve_production_project(str(root), body)


def test_mcp_and_wizard_stay_distinct_after_reload(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    mcp = _resolve(root, origin="mcp", intent_id="clip-mcp", title="Same title")
    wizard = _resolve(root, origin="wizard", intent_id="clip-wiz", title="Same title")

    assert mcp["production_id"] != wizard["production_id"]
    assert mcp["review"]["event"] == REVIEW_EVENT
    assert mcp["review"]["workspace"] == "film"
    assert mcp["project"]["kind"] == "story"
    first = _list(root)
    second = _list(root)
    assert first["applied"] is False
    assert {item["production_id"] for item in second["works"]} == {mcp["production_id"], wizard["production_id"]}
    assert first["total"] == second["total"] == 2
    assert {item["origin"] for item in second["works"]} == {"mcp", "wizard"}
    assert all(item["review"]["event"] == REVIEW_EVENT for item in second["works"])
    assert all(item["review"]["workspace"] == "film" for item in second["works"])
    assert len(read_story_library(str(root))["projects"]) == 2


def test_episode_list_does_not_create_a_story(tmp_path: Path):
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
    listed = _list(root)

    assert len(read_story_library(str(root))["projects"]) == 0
    assert listed["total"] == 1
    work = listed["works"][0]
    assert work["production_id"] == linked["production_id"]
    assert work["project"] == {"kind": "episode", "id": episode["id"]}
    assert work["series_id"] == series["id"]
    assert work["review"]["series_id"] == series["id"]
    again = _resolve(root, project={"kind": "episode", "id": episode["id"]})
    assert again["production_id"] == linked["production_id"]
    assert len(read_story_library(str(root))["projects"]) == 0


def test_status_filter_keeps_failures_and_a_retry_reuses_the_work(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    command = {
        "operation": "production.works.resolve",
        "version": 1,
        "input": {
            "workspace": "film",
            "origin": "ui",
            "intent_id": "light1",
            "format": "trailer",
            "title": "Teaser",
        },
    }
    created = run_command(str(root), command)
    repeated = run_command(str(root), command)
    assert created["applied"] is True
    assert created["reused"] is False
    assert repeated["reused"] is True
    assert repeated["production_id"] == created["production_id"]
    assert created["review"]["event"] == REVIEW_EVENT
    path = root / f"{created['production_id']}.production.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["status"] = "failed"
    path.write_text(json.dumps(stored), encoding="utf-8")
    _resolve(root, origin="wizard", intent_id="other", format="quick_video", title="Pending")
    failed = _list(root, status="failed")
    assert [item["production_id"] for item in failed["works"]] == [created["production_id"]]
    assert failed["works"][0]["status"] == "failed"
    assert _list(root)["total"] == 2


def test_open_reports_workspace_and_unknown_ids_fail(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    linked = _resolve(root)
    opened = run_command(str(root), {
        "operation": "production.works.open",
        "version": 1,
        "input": {"workspace": "film", "production_id": linked["production_id"]},
    })
    assert opened["applied"] is False
    assert opened["work"]["review"]["workspace"] == "film"
    assert opened["work"]["review"]["production_id"] == linked["production_id"]
    assert opened["work"]["project"]["id"] == linked["project"]["id"]
    try:
        run_command(str(root), {
            "operation": "production.works.open",
            "version": 1,
            "input": {"workspace": "film", "production_id": "missing"},
        })
    except WorkCommandError as error:
        assert error.code == "not_found"
    else:
        raise AssertionError("missing production was opened")


def test_http_command_stays_inside_the_workspace(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    (tmp_path / "other").mkdir()
    app = FastAPI()
    app.include_router(create_production_projects_router(
        workspace_dir=lambda name: str(tmp_path / name),
    ))
    client = TestClient(app)
    created = client.post("/api/v1/production-projects/commands", json={
        "operation": "production.works.resolve",
        "version": 1,
        "input": {
            "workspace": "film",
            "origin": "wizard",
            "intent_id": "wiz1",
            "format": "music_video",
            "title": "Night bus",
        },
    })
    assert created.status_code == 200
    production_id = created.json()["production_id"]
    listed = client.post("/api/v1/production-projects/commands", json={
        "operation": "production.works.list",
        "version": 1,
        "input": {"workspace": "film"},
    })
    assert listed.status_code == 200
    assert listed.json()["works"][0]["production_id"] == production_id
    other = client.post("/api/v1/production-projects/commands", json={
        "operation": "production.works.list",
        "version": 1,
        "input": {"workspace": "other"},
    })
    assert other.status_code == 200
    assert other.json()["works"] == []
    missing = client.post("/api/v1/production-projects/commands", json={
        "operation": "production.works.open",
        "version": 1,
        "input": {"workspace": "film", "production_id": "nope"},
    })
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "not_found"
    assert client.get("/api/v1/production-projects", params={"workspace": "other"}).json()["total"] == 0


def _story(root: Path, project_id: str, title: str) -> None:
    library = read_story_library(str(root))
    projects = dict(library["projects"])
    projects[project_id] = {"id": project_id, "title": title, "productions": []}
    write_story_library(str(root), {
        "version": 2,
        "revision": library["revision"],
        "activeId": project_id,
        "projects": projects,
    }, base_revision=library["revision"])


def _link(root: Path, production_id: str, project_id: str, *, kind: str = "story"):
    return run_command(str(root), {
        "operation": "production.works.link",
        "version": 1,
        "input": {
            "workspace": "film",
            "production_id": production_id,
            "project": {"kind": kind, "id": project_id},
        },
    })


def test_an_old_file_links_by_id_and_a_repeat_does_not_duplicate(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    original = {"status": "completed", "spec": {"title": "Night bus"}, "origin": "file", "takes": ["take-a.mp4"]}
    (root / "old-a.production.json").write_text(json.dumps(original), encoding="utf-8")
    (root / "old-b.production.json").write_text(json.dumps(original), encoding="utf-8")
    (root / "take-a.mp4").write_bytes(b"take-a")
    before = (root / "old-a.production.json").read_bytes()
    media = (root / "take-a.mp4").read_bytes()
    listed = _list(root)
    assert {item["production_id"] for item in listed["works"]} == {"old-a", "old-b"}
    assert all(item["linked"] is False and item["project"] is None for item in listed["works"])
    _story(root, "nara", "Night bus")
    _story(root, "kael", "Night bus")

    first = _link(root, "old-a", "nara")
    second = _link(root, "old-a", "nara")
    library = read_story_library(str(root))
    nara_ids = [item["id"] for item in library["projects"]["nara"]["productions"]]

    assert first["applied"] is True and first["reused"] is False
    assert second["reused"] is True and second["production_id"] == "old-a"
    assert nara_ids == ["old-a"]
    assert library["projects"]["kael"]["productions"] == []
    assert _list(root)["works"]
    again = {item["production_id"]: item for item in _list(root)["works"]}
    assert again["old-a"]["project"] == {"kind": "story", "id": "nara"}
    assert again["old-b"]["project"] is None
    assert (root / "old-a.production.json").read_bytes() == before
    assert (root / "take-a.mp4").read_bytes() == media
    try:
        _link(root, "old-a", "kael")
    except Exception as error:
        from services.production_project_link import LinkError
        assert isinstance(error, LinkError) and error.code == "invalid_project"
    else:
        raise AssertionError("expected invalid_project")
    assert [item["id"] for item in read_story_library(str(root))["projects"]["nara"]["productions"]] == ["old-a"]


def test_missing_sidecar_stays_readable_and_a_missing_file_does_not_link(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    (root / "old-a.production.json").write_text('{"status":"completed","spec":{"title":"Night bus"}}', encoding="utf-8")
    (root / "bad.production.json").write_text("not-json", encoding="utf-8")
    listed = _list(root)
    assert (root / ".production-project-links-v1.json").exists() is False
    assert listed["works"][0]["production_id"] == "old-a"
    assert listed["works"][0]["linked"] is False
    assert listed["warnings"] == [{"source": "bad.production.json", "error": "unreadable"}]
    _story(root, "nara", "Other title")
    try:
        _link(root, "bad", "nara")
    except Exception as error:
        from services.production_project_link import LinkError
        assert isinstance(error, LinkError) and error.code == "not_found"
    else:
        raise AssertionError("expected not_found")
    assert (root / "bad.production.json").read_text(encoding="utf-8") == "not-json"
    assert (root / ".production-project-links-v1.json").exists() is False
    linked = _link(root, "old-a", "nara")
    assert linked["project"] == {"kind": "story", "id": "nara"}
    assert (root / ".production-project-links-v1.json").is_file()


def test_episode_link_does_not_create_a_story_or_rewrite_the_series(tmp_path: Path):
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
    series_bytes = (root / ".series-library-v1.json").read_bytes()
    (root / "old-ep.production.json").write_text('{"status":"completed","spec":{"title":"Chapter"}}', encoding="utf-8")
    linked = _link(root, "old-ep", episode["id"], kind="episode")
    assert linked["project"] == {"kind": "episode", "id": episode["id"]}
    assert len(read_story_library(str(root))["projects"]) == 0
    assert (root / ".series-library-v1.json").read_bytes() == series_bytes
    assert _link(root, "old-ep", episode["id"], kind="episode")["reused"] is True
