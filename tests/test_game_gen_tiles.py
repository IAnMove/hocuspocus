"""Tile, tileset and separate-background generators with simulated images."""
from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from services.game_generators import REGISTRY
from services.game_generators.base import GenContext
from services.game_tools import GameToolError


def _periodic(path):
    row = np.concatenate([np.arange(0, 16), np.arange(15, -1, -1)]).astype(np.uint8)
    tile = np.tile(row, (32, 1))
    image = np.dstack([tile, tile, tile, np.full_like(tile, 255)])
    Image.fromarray(image).save(path)


def _grid(path):
    image = np.zeros((96, 96, 4), dtype=np.uint8)
    image[..., 3] = 255
    for index in range(9):
        row, col = divmod(index, 3)
        color = (40 + index * 20, 80, 50, 255)
        image[row * 32:(row + 1) * 32, col * 32:(col + 1) * 32] = color
    Image.fromarray(image).save(path)


def _flat(path):
    image = np.zeros((32, 64, 4), dtype=np.uint8)
    image[..., 0] = 70
    image[..., 1] = 120
    image[..., 2] = 180
    image[..., 3] = 255
    Image.fromarray(image).save(path)


class Fake:
    def __init__(self, files):
        self.files = list(files)
        self.calls = []
        self.image_calls = 0

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        if tool == "generation.image":
            self.image_calls += 1
            return {"receipt": {"result": {"job_id": f"job-{self.image_calls}"}}}
        if tool == "jobs.wait":
            return {"status": "completed", "output_files": [self.files.pop(0)]}
        if tool == "studio.key":
            return {"result": {"file": args["input"]["source"]}}
        if tool == "media.options":
            return {"models": []}
        raise AssertionError(tool)


def _style():
    return {
        "preset": "pixel-16",
        "traits": "16-bit pixel art",
        "negative": "blur",
        "palette": [],
        "paletteMode": "free",
        "pixel": {"enabled": False, "spriteHeight": 48, "tile": 16, "colors": 8, "outline": "none", "dither": "none"},
        "screen": "magenta",
        "references": [],
    }


def _ctx(workspace, game, asset, fake):
    return GenContext(
        workspace="bosque", game=game, asset=asset, attempt_id="a1", call=fake,
        loopback=lambda tool, args: {}, workspace_dir=lambda name: str(workspace),
        cancelled=lambda: False, log=lambda message: None,
    )


def test_tile_seam_falls_below_the_limit_after_the_simulated_pass(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _periodic(workspace / "periodic.png")
    asset = {"id": "hierba", "kind": "tile", "description": "grass", "spec": {"sizePx": 16, "seed": 3}, "attempts": []}
    game = {"id": "bosque", "style": _style(), "assets": [asset]}
    fake = Fake([str(workspace / "periodic.png"), str(workspace / "periodic.png")])
    result = REGISTRY["tile"].run(_ctx(workspace, game, asset, fake))
    guided = [args for tool, args in fake.calls if tool == "generation.image" and "image_guide" in args["input"]["params"]]
    assert guided
    assert result.metrics["seamError"] < 1.5
    assert result.warnings == []
    assert (workspace / "game" / "bosque" / "hierba" / "a1" / "main.png").is_file()


def test_tileset_writes_nine_named_cells(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _grid(workspace / "grid.png")
    _periodic(workspace / "periodic.png")
    asset = {"id": "suelo", "kind": "tileset", "description": "ground", "spec": {"sizePx": 16, "seed": 5}, "attempts": []}
    game = {"id": "bosque", "style": _style(), "assets": [asset]}
    fake = Fake([str(workspace / "grid.png"), str(workspace / "periodic.png")])
    result = REGISTRY["tileset"].run(_ctx(workspace, game, asset, fake))
    payload = json.loads((workspace / "game" / "bosque" / "suelo" / "a1" / "tiles.json").read_text(encoding="utf-8"))
    assert payload["names"] == ["tl", "t", "tr", "l", "c", "r", "bl", "b", "br"]
    assert len(payload["tiles"]) == 9
    assert result.files["main"].endswith("tileset.png")


def test_separate_background_writes_parallax(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _flat(workspace / "flat.png")
    asset = {
        "id": "fondo", "kind": "background", "description": "forest",
        "spec": {"layers": 2, "widthPx": 64, "heightPx": 32, "method": "separate", "seed": 2},
        "attempts": [],
    }
    game = {"id": "bosque", "style": _style(), "assets": [asset]}
    fake = Fake([str(workspace / "flat.png")] * 8)
    result = REGISTRY["background"].run(_ctx(workspace, game, asset, fake))
    parallax = json.loads((workspace / "game" / "bosque" / "fondo" / "a1" / "parallax.json").read_text(encoding="utf-8"))
    assert [item["factor"] for item in parallax["layers"]] == [0.1, 1.0]
    assert (workspace / "game" / "bosque" / "fondo" / "a1" / "layer-0.png").is_file()
    assert (workspace / "game" / "bosque" / "fondo" / "a1" / "layer-1.png").is_file()
    assert "parallax" in result.files


def test_layered_background_errors_when_the_model_is_missing(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    asset = {"id": "fondo", "kind": "background", "description": "forest", "spec": {"method": "layered"}, "attempts": []}
    game = {"id": "bosque", "style": _style(), "assets": [asset]}
    fake = Fake([])
    with pytest.raises(GameToolError) as caught:
        REGISTRY["background"].run(_ctx(workspace, game, asset, fake))
    assert caught.value.code == "model_not_installed"
    assert [tool for tool, _args in fake.calls] == ["media.options"]
