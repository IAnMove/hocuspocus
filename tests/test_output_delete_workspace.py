"""Gallery delete must remove the file from the listed workspace, not the active one."""

from __future__ import annotations

import ast
import copy
import os
import sys
import types
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.kernel.paths import PathPolicy


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "app" / "services" / "output_ops.py"


def load_functions(names: list[str], namespace: dict) -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    selected = []
    for name in names:
        node = copy.deepcopy(next(
            item
            for item in tree.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == name
        ))
        node.decorator_list = []
        selected.append(node)
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(SOURCE), "exec"), namespace)


def delete_namespace(active: Path, film: Path) -> dict:
    namespace = {
        "os": os,
        "HTTPException": HTTPException,
        "_workspace_dir": lambda workspace=None: str(film if workspace == "film" else active),
        "_load_favorites": lambda: set(),
        "_save_favorites": lambda _favorites: None,
        "_safe_join": PathPolicy().safe_join,
    }
    load_functions(["delete_output"], namespace)
    return namespace


def install_delete_stubs(monkeypatch) -> None:
    win = types.ModuleType("services.win_safe_files")
    win.favorites_lock = __import__("threading").RLock()

    def safe_delete(path):
        os.remove(path)
        return {"deleted": True}

    win.safe_delete = safe_delete
    monkeypatch.setitem(sys.modules, "services.win_safe_files", win)
    search = types.ModuleType("services.search_index")
    search.get_search_index = lambda: types.SimpleNamespace(remove_file=lambda _name: None)
    monkeypatch.setitem(sys.modules, "services.search_index", search)


def test_delete_output_uses_the_listed_workspace_not_the_active_one(tmp_path, monkeypatch):
    active = tmp_path / "ads"
    film = tmp_path / "film"
    active.mkdir()
    film.mkdir()
    (active / "hero.png").write_bytes(b"ads-hero")
    (film / "hero.png").write_bytes(b"film-hero")
    (film / "hero.meta.json").write_text("{}", encoding="utf-8")
    install_delete_stubs(monkeypatch)
    namespace = delete_namespace(active, film)

    result = namespace["delete_output"]("hero.png", workspace="film")

    assert result == {"deleted": "hero.png"}
    assert not (film / "hero.png").exists()
    assert (active / "hero.png").read_bytes() == b"ads-hero"


def test_delete_output_without_workspace_still_uses_the_active_folder(tmp_path, monkeypatch):
    active = tmp_path / "ads"
    film = tmp_path / "film"
    active.mkdir()
    film.mkdir()
    (active / "hero.png").write_bytes(b"ads-hero")
    (film / "hero.png").write_bytes(b"film-hero")
    install_delete_stubs(monkeypatch)
    namespace = delete_namespace(active, film)

    result = namespace["delete_output"]("hero.png")

    assert result == {"deleted": "hero.png"}
    assert not (active / "hero.png").exists()
    assert (film / "hero.png").read_bytes() == b"film-hero"


@pytest.mark.parametrize("name", ["../outside.png", "/tmp/outside.png"])
def test_delete_output_rejects_traversal(tmp_path, monkeypatch, name):
    active = tmp_path / "ads"
    film = tmp_path / "film"
    active.mkdir()
    film.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"keep")
    install_delete_stubs(monkeypatch)
    namespace = delete_namespace(active, film)

    result = namespace["delete_output"](name, workspace="film")

    assert result == {"deleted": name}
    assert outside.read_bytes() == b"keep"


def _workspace_delete_client(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.workspace_outputs import create_workspace_router

    film = tmp_path / "film"
    film.mkdir()
    policy = PathPolicy()
    app = FastAPI()
    app.include_router(create_workspace_router(
        list_workspaces=lambda: ["film"],
        get_active_workspace=lambda: "default",
        persist_active=lambda name, apply_save_paths=True: str(tmp_path / name),
        workspace_dir=lambda name: str(tmp_path / name),
        generation_idle=lambda: True,
        jobs=lambda: [],
        safe_join=policy.safe_join,
        save_path=lambda: str(tmp_path),
    ))
    return TestClient(app), film


def test_delete_workspace_refuses_while_story_plan_is_running(tmp_path):
    """Story Lab planners live in `_story_plan_jobs`, not jobs()
    or `_active_gen_states`. The shared delete route must still treat them as busy."""
    from services.story_lab_jobs import (
        _story_plan_jobs,
        _story_plan_jobs_lock,
        reset_story_plan_jobs,
    )

    client, film = _workspace_delete_client(tmp_path)
    (film / "story.project.json").write_text("{}", encoding="utf-8")
    reset_story_plan_jobs()
    try:
        with _story_plan_jobs_lock:
            _story_plan_jobs["story-plan-abc123abc123"] = {
                "jobId": "story-plan-abc123abc123",
                "workspace": "film",
                "status": "running",
            }
        refused = client.delete("/api/v1/workspaces/film")
        kept_story = film.is_dir() and (film / "story.project.json").read_text(encoding="utf-8") == "{}"
        reset_story_plan_jobs()
        deleted = client.delete("/api/v1/workspaces/film")
    finally:
        reset_story_plan_jobs()
    assert refused.status_code == 409, refused.text
    assert "generation" in refused.json()["detail"].lower()
    assert kept_story
    assert deleted.status_code == 200, deleted.text
    assert not film.is_dir()


def test_delete_workspace_refuses_while_comic_plan_is_running(tmp_path):
    """Comic planners live in `_comic_plan_jobs`, not jobs()
    or `_active_gen_states`. The shared delete route must still treat them as busy."""
    from services.director_comic_jobs import (
        _comic_plan_jobs,
        _comic_plan_jobs_lock,
        reset_comic_plan_jobs,
    )

    client, film = _workspace_delete_client(tmp_path)
    (film / "page.comic.json").write_text("{}", encoding="utf-8")
    reset_comic_plan_jobs()
    try:
        with _comic_plan_jobs_lock:
            _comic_plan_jobs["comic-plan-job-abc123abc123"] = {
                "jobId": "comic-plan-job-abc123abc123",
                "workspace": "film",
                "status": "planning",
            }
        refused = client.delete("/api/v1/workspaces/film")
        kept_comic = film.is_dir() and (film / "page.comic.json").read_text(encoding="utf-8") == "{}"
        reset_comic_plan_jobs()
        deleted = client.delete("/api/v1/workspaces/film")
    finally:
        reset_comic_plan_jobs()
    assert refused.status_code == 409, refused.text
    assert "generation" in refused.json()["detail"].lower()
    assert kept_comic
    assert deleted.status_code == 200, deleted.text
    assert not film.is_dir()
