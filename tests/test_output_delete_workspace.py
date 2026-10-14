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


def test_delete_workspace_refuses_while_a_video_editor_export_is_running(tmp_path):
    """Editor/alternative-song FFmpeg jobs live in `_video_editor_jobs`, not jobs()
    or `_active_gen_states`. The shared delete route must still treat them as busy."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.video_editor import _register_video_editor_job, reset_video_editor_jobs
    from routers.workspace_outputs import create_workspace_router

    film = tmp_path / "film"
    film.mkdir()
    (film / "clip.mp4").write_bytes(b"clip")
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
    client = TestClient(app)
    reset_video_editor_jobs()
    try:
        _register_video_editor_job({
            "job_id": "export-film",
            "workspace": "film",
            "status": "running",
        })
        refused = client.delete("/api/v1/workspaces/film")
        kept_clip = film.is_dir() and (film / "clip.mp4").read_bytes() == b"clip"
        reset_video_editor_jobs()
        deleted = client.delete("/api/v1/workspaces/film")
    finally:
        reset_video_editor_jobs()
    assert refused.status_code == 409, refused.text
    assert "generation" in refused.json()["detail"].lower()
    assert kept_clip
    assert deleted.status_code == 200, deleted.text
    assert not film.is_dir()
