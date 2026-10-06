"""Tile, tileset and separate-background generators with simulated images."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

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
    assert {args["input"]["params"]["seed"] for tool, args in fake.calls if tool == "generation.image"} == {3}


def test_tileset_writes_nine_named_cells(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _grid(workspace / "grid.png")
    _periodic(workspace / "periodic.png")
    asset = {"id": "suelo", "kind": "tileset", "description": "ground", "spec": {"sizePx": 16, "seed": 5}, "attempts": []}
    game = {"id": "bosque", "style": _style(), "assets": [asset]}
    fake = Fake([str(workspace / "grid.png"), str(workspace / "periodic.png")])
    result = REGISTRY["tileset"].run(_ctx(workspace, game, asset, fake))
    guided = [args for tool, args in fake.calls if tool == "generation.image" and "image_guide" in args["input"]["params"]]
    assert guided[0]["input"]["params"]["resolution"] == "1024x1024"
    assert {args["input"]["params"]["seed"] for tool, args in fake.calls if tool == "generation.image"} == {5}
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


def _images(fake):
    return [args for tool, args in fake.calls if tool == "generation.image"]


def test_tile_variants_paint_each_with_its_own_seed(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _periodic(workspace / "periodic.png")
    asset = {"id": "hierba", "kind": "tile", "description": "grass", "spec": {"sizePx": 16, "seed": 3, "variants": 3}, "attempts": []}
    game = {"id": "bosque", "style": _style(), "assets": [asset]}
    fake = Fake([str(workspace / "periodic.png")] * 6)
    result = REGISTRY["tile"].run(_ctx(workspace, game, asset, fake))
    painted = [args for args in _images(fake) if "image_guide" not in args["input"]["params"]]
    assert [args["input"]["params"]["seed"] for args in painted] == [3, 4, 5]
    assert len({args["intent_id"] for args in _images(fake)}) == 6
    assert sorted(result.files) == ["main", "variant-2", "variant-3"]
    assert all((workspace / path).is_file() for path in result.files.values())
    assert [item["file"] for item in result.metrics["variants"]] == ["main.png", "variant-2.png", "variant-3.png"]
    assert REGISTRY["tile"].estimate(game, asset) == {"image": 6}


def _tile_colors(tmp_path, mode):
    workspace = tmp_path / mode
    workspace.mkdir()
    _periodic(workspace / "periodic.png")
    style = _style()
    style.update({"palette": ["#ff0000"], "paletteMode": mode})
    style["pixel"]["enabled"] = True
    asset = {"id": "hierba", "kind": "tile", "description": "grass", "spec": {"sizePx": 16}, "attempts": []}
    game = {"id": "bosque", "style": style, "assets": [asset]}
    result = REGISTRY["tile"].run(_ctx(workspace, game, asset, Fake([str(workspace / "periodic.png")] * 2)))
    with Image.open(workspace / result.files["main"]) as opened:
        pixels = np.asarray(opened.convert("RGBA"))
    return {tuple(int(value) for value in color) for color in pixels[pixels[..., 3] > 0][:, :3]}


def test_a_free_palette_is_not_snapped_to_the_style_palette(tmp_path):
    assert _tile_colors(tmp_path, "locked") == {(255, 0, 0)}
    free = _tile_colors(tmp_path, "free")
    assert (255, 0, 0) not in free
    assert len(free) > 1


def _band(path):
    image = np.zeros((32, 64, 4), dtype=np.uint8)
    image[...] = (255, 0, 255, 255)
    image[14:22] = (30, 90, 40, 255)
    Image.fromarray(image).save(path)


class Scene:
    """Sky and band paintings. The inpaint returns its guide, and the key clears magenta."""

    def __init__(self, workspace):
        self.workspace = workspace
        self.calls = []
        self.pending = None
        _flat(workspace / "sky.png")
        _band(workspace / "band.png")

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        if tool == "generation.image":
            params = args["input"]["params"]
            if "image_guide" in params:
                self.pending = unquote(urlsplit(params["image_guide"]).path[len("/api/v1/file/"):])
            else:
                self.pending = "sky.png" if args["intent_id"].endswith("layer-0") else "band.png"
            return {"receipt": {"result": {"job_id": f"job-{len(self.calls)}"}}}
        if tool == "jobs.wait":
            return {"status": "completed", "output_files": [self.pending]}
        if tool == "studio.key":
            return {"result": {"file": self._key(args["input"]["source"])}}
        raise AssertionError(tool)

    def _key(self, source):
        with Image.open(self.workspace / source) as opened:
            pixels = np.asarray(opened.convert("RGBA")).copy()
        screen = (pixels[..., 0] > 200) & (pixels[..., 1] < 60) & (pixels[..., 2] > 200)
        pixels[screen, 3] = 0
        name = f"{Path(source).stem}-key.png"
        Image.fromarray(pixels).save(self.workspace / name)
        return name


def _background(spec):
    asset = {"id": "fondo", "kind": "background", "description": "forest", "spec": {"widthPx": 64, "heightPx": 32, "method": "separate", **spec}, "attempts": []}
    return asset, {"id": "bosque", "style": _style(), "assets": [asset]}


def _alpha(workspace, name):
    with Image.open(workspace / "game" / "bosque" / "fondo" / "a1" / name) as opened:
        assert opened.size == (64, 32)
        return np.asarray(opened.convert("RGBA"))[..., 3]


def test_background_heals_the_full_frame_before_keying(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    asset, game = _background({"layers": 2, "seed": 2})
    scene = Scene(workspace)
    REGISTRY["background"].run(_ctx(workspace, game, asset, scene))
    order = [args.get("intent_id", "").rsplit("-a1-", 1)[-1] for _tool, args in scene.calls if "intent_id" in args]
    assert order.index("seam-1") < order.index("key-1")
    heal = next(args for tool, args in scene.calls if tool == "generation.image" and args["intent_id"].endswith("seam-1"))
    assert heal["input"]["params"]["resolution"] == "1024x1024"
    guide = unquote(urlsplit(heal["input"]["params"]["image_guide"]).path[len("/api/v1/file/"):])
    with Image.open(workspace / guide) as opened:
        assert opened.size == (1024, 1024)
    keyed = next(args for tool, args in scene.calls if tool == "studio.key")
    assert keyed["input"]["source"].endswith("layer-1-healed.png")
    assert _alpha(workspace, "layer-0.png").min() == 255
    band = _alpha(workspace, "layer-1.png")
    assert band[0].max() == 0
    assert band[-1].min() == 255
    assert int((band > 0).any(axis=1).sum()) == 8


def test_background_layers_get_a_depth_phrase_and_their_own_seed(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    asset, game = _background({"layers": 3, "seed": 2})
    scene = Scene(workspace)
    REGISTRY["background"].run(_ctx(workspace, game, asset, scene))
    painted = [args["input"]["params"] for args in _images(scene) if "image_guide" not in args["input"]["params"]]
    assert [params["seed"] for params in painted] == [2, 3, 4]
    prompts = [params["prompt"] for params in painted]
    assert len(set(prompts)) == 3
    assert "far distance" in prompts[1]
    assert "near foreground" in prompts[2]
    heals = {args["intent_id"].rsplit("-", 1)[-1]: args["input"]["params"]["seed"] for args in _images(scene) if "image_guide" in args["input"]["params"]}
    assert heals == {"0": 2, "1": 3, "2": 4}


def test_background_without_loop_skips_the_heal(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    asset, game = _background({"layers": 2, "loopX": False})
    scene = Scene(workspace)
    REGISTRY["background"].run(_ctx(workspace, game, asset, scene))
    assert all("image_guide" not in args["input"]["params"] for args in _images(scene))
    parallax = json.loads((workspace / "game" / "bosque" / "fondo" / "a1" / "parallax.json").read_text(encoding="utf-8"))
    assert [item["seamError"] for item in parallax["layers"]] == [None, None]
    keyed = next(args for tool, args in scene.calls if tool == "studio.key")
    assert keyed["input"]["source"] == "band.png"
    assert _alpha(workspace, "layer-1.png")[-1].min() == 255
    assert REGISTRY["background"].estimate(game, asset) == {"image": 2}
