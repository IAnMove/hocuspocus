from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.projects import create_projects_router


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, Path]]:
    roots = {"default": tmp_path / "default", "film": tmp_path / "film"}
    for path in roots.values():
        path.mkdir()
    app = FastAPI()
    app.include_router(create_projects_router(
        list_workspaces=lambda: [{"name": "default"}, {"name": "film"}],
        workspace_dir=lambda name: str(roots[name]),
    ))
    return TestClient(app), roots


def test_projects_route_lists_filters_and_never_exposes_paths(tmp_path: Path):
    client, roots = _client(tmp_path)
    (roots["default"] / ".story-library-v1.json").write_text(json.dumps({
        "version": 2, "revision": 1, "activeId": "story-1",
        "projects": {"story-1": {
            "id": "story-1", "title": "Server anthem", "projectType": "music_video",
        }},
    }), encoding="utf-8")
    (roots["film"] / "comic.comic.json").write_text(json.dumps({
        "id": "comic-1", "title": "Other project", "version": 2, "pages": [],
    }), encoding="utf-8")

    response = client.get("/api/v1/projects", params={
        "search": "server", "kind": "story", "workspace": "default",
    })

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["projects"][0]["id"] == "story-1"
    assert str(tmp_path) not in response.text


def test_projects_route_returns_exact_record_and_validates_filters(tmp_path: Path):
    client, roots = _client(tmp_path)
    (roots["film"] / "scene.scene.json").write_text(json.dumps({
        "version": 1, "name": "Server room", "layers": [],
    }), encoding="utf-8")
    listing = client.get("/api/v1/projects").json()
    project_id = listing["projects"][0]["id"]

    detail = client.get(f"/api/v1/projects/{project_id}")

    assert detail.status_code == 200
    assert detail.json()["id"] == project_id
    assert client.get("/api/v1/projects", params={"kind": "magic"}).status_code == 400
    assert client.get("/api/v1/projects", params={"workspace": "missing"}).status_code == 404
    assert client.get("/api/v1/projects/missing").status_code == 404
