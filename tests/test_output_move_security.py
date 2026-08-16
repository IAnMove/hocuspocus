import ast
import asyncio
import copy
import os
import sys
import types
from pathlib import Path

import pytest
from fastapi import HTTPException, Request as FastAPIRequest


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "app" / "launch.py"


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


class JsonRequest:
    def __init__(self, body: dict):
        self._body = body

    async def json(self):
        return self._body


def move_namespace(source: Path, destination: Path) -> dict:
    namespace = {
        "os": os,
        "Request": FastAPIRequest,
        "HTTPException": HTTPException,
        "traceback": __import__("traceback"),
        "threading": __import__("threading"),
        "time": __import__("time"),
        "_workspace_dir": lambda workspace=None: str(
            destination if workspace == "target" else source
        ),
        "_load_favorites": lambda: set(),
        "_save_favorites": lambda _favorites: None,
    }
    load_functions(
        ["_safe_join", "_resolve_output_move_path", "move_output"],
        namespace,
    )
    return namespace


def install_win_safe_files_stub(monkeypatch) -> None:
    module = types.ModuleType("services.win_safe_files")
    module.favorites_lock = __import__("threading").RLock()
    monkeypatch.setitem(sys.modules, "services.win_safe_files", module)


def test_move_output_accepts_a_contained_file_and_sidecars(tmp_path, monkeypatch):
    source = tmp_path / "source"
    destination = tmp_path / "target"
    source.mkdir()
    destination.mkdir()
    (source / "clip.mp4").write_bytes(b"video")
    (source / "clip.meta.json").write_text("{}", encoding="utf-8")
    (source / "clip.preview.png").write_bytes(b"preview")
    install_win_safe_files_stub(monkeypatch)
    namespace = move_namespace(source, destination)

    result = asyncio.run(namespace["move_output"](
        "clip.mp4",
        JsonRequest({"workspace": "target"}),
    ))

    assert result == {"moved": "clip.mp4", "to": "target"}
    assert not (source / "clip.mp4").exists()
    assert (destination / "clip.mp4").read_bytes() == b"video"
    assert (destination / "clip.meta.json").is_file()
    assert (destination / "clip.preview.png").is_file()


@pytest.mark.parametrize("name", ["../outside.mp4", "/tmp/outside.mp4", "..\\outside.mp4"])
def test_move_output_rejects_traversal_and_absolute_paths(tmp_path, monkeypatch, name):
    source = tmp_path / "source"
    destination = tmp_path / "target"
    source.mkdir()
    destination.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    install_win_safe_files_stub(monkeypatch)
    namespace = move_namespace(source, destination)

    with pytest.raises(HTTPException) as error:
        asyncio.run(namespace["move_output"](
            name,
            JsonRequest({"workspace": "target"}),
        ))

    assert error.value.status_code == 400
    assert outside.read_bytes() == b"outside"
    assert not (destination / "outside.mp4").exists()


def test_move_output_rejects_a_symlink_that_escapes_the_workspace(tmp_path, monkeypatch):
    source = tmp_path / "source"
    destination = tmp_path / "target"
    source.mkdir()
    destination.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    link = source / "escape.mp4"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")
    install_win_safe_files_stub(monkeypatch)
    namespace = move_namespace(source, destination)

    with pytest.raises(HTTPException) as error:
        asyncio.run(namespace["move_output"](
            "escape.mp4",
            JsonRequest({"workspace": "target"}),
        ))

    assert error.value.status_code == 400
    assert outside.read_bytes() == b"outside"
    assert link.is_symlink()


def test_move_output_rejects_a_destination_directory_symlink_escape(tmp_path, monkeypatch):
    source = tmp_path / "source"
    destination = tmp_path / "target"
    outside = tmp_path / "outside"
    (source / "nested").mkdir(parents=True)
    destination.mkdir()
    outside.mkdir()
    media = source / "nested" / "clip.mp4"
    media.write_bytes(b"video")
    try:
        (destination / "nested").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")
    install_win_safe_files_stub(monkeypatch)
    namespace = move_namespace(source, destination)

    with pytest.raises(HTTPException) as error:
        asyncio.run(namespace["move_output"](
            "nested/clip.mp4",
            JsonRequest({"workspace": "target"}),
        ))

    assert error.value.status_code == 400
    assert media.read_bytes() == b"video"
    assert not (outside / "clip.mp4").exists()
