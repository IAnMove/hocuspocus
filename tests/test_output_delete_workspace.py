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


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"


def load_functions(names: list[str], namespace: dict) -> None:
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))
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
    exec(compile(module, str(LAUNCH), "exec"), namespace)


def delete_namespace(active: Path, film: Path) -> dict:
    namespace = {
        "os": os,
        "HTTPException": HTTPException,
        "_workspace_dir": lambda workspace=None: str(film if workspace == "film" else active),
        "_load_favorites": lambda: set(),
        "_save_favorites": lambda _favorites: None,
    }
    load_functions(["_safe_join", "delete_output"], namespace)
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
