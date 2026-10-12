"""Still generator with a simulated image tool. No GPU."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from services.game_generators import REGISTRY
from services.game_generators.base import GenContext


def _figure(path):
    image = np.zeros((80, 64, 4), dtype=np.uint8)
    image[10:50, 16:48] = (180, 40, 40, 255)
    Image.fromarray(image).save(path)


class Fake:
    def __init__(self, files):
        self.files = list(files)
        self.calls = []

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        if tool == "generation.image":
            return {"receipt": {"result": {"job_id": "job-still"}}}
        if tool == "jobs.wait":
            return {"status": "completed", "output_files": self.files}
        if tool == "studio.key":
            return {"result": {"file": args["input"]["source"]}}
        raise AssertionError(tool)


def _game(pixel=True, palette_mode="free"):
    return {
        "id": "bosque",
        "style": {
            "preset": "pixel-16",
            "traits": "16-bit pixel art",
            "negative": "blur",
            "palette": [],
            "paletteMode": palette_mode,
            "pixel": {"enabled": pixel, "spriteHeight": 48, "tile": 16, "colors": 4, "outline": "none", "dither": "none"},
            "screen": "magenta",
            "references": [],
        },
        "assets": [],
    }


def _ctx(workspace, game, asset, fake, attempt_id="att1"):
    return GenContext(
        workspace="bosque", game=game, asset=asset, attempt_id=attempt_id, call=fake,
        loopback=lambda tool, args: {}, workspace_dir=lambda name: str(workspace),
        cancelled=lambda: False, log=lambda message: None,
    )


def _knight(candidates=3, seed=4):
    return {
        "id": "heroe",
        "kind": "character",
        "description": "short bronze knight",
        "candidates": candidates,
        "spec": {"heightPx": 48, "seed": seed},
        "attempts": [],
    }


def _seeds(fake):
    return [args["input"]["params"]["seed"] for tool, args in fake.calls if tool == "generation.image"]


def test_character_writes_three_cells_with_palette_and_scale(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _figure(workspace / "knight.png")
    fake = Fake([str(workspace / "knight.png")] * 3)
    result = REGISTRY["character"].run(_ctx(workspace, _game(), _knight(), fake))
    ids = ["att1-a1", "att1-a2", "att1-a3"]
    assert result.metrics["attemptIds"] == ids
    assert _seeds(fake) == [4]
    assert result.metrics["palette"]
    assert all(str(color).startswith("#") for color in result.metrics["palette"])
    assert result.metrics["scale"] > 0
    for index in (1, 2, 3):
        main = workspace / "game" / "bosque" / "heroe" / "att1" / f"a{index}" / "main.png"
        raw = main.with_name("raw-key.png")
        preview = main.with_name("preview.png")
        assert main.is_file() and raw.is_file() and preview.is_file()
        with Image.open(main) as opened:
            assert opened.size == (48, 48)
        with Image.open(preview) as opened:
            assert opened.size == (192, 192)


def test_every_candidate_carries_its_own_files_and_metrics(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _figure(workspace / "knight.png")
    fake = Fake([str(workspace / "knight.png")] * 3)
    result = REGISTRY["character"].run(_ctx(workspace, _game(), _knight(), fake))
    candidates = result.metrics["candidates"]
    assert [item["id"] for item in candidates] == result.metrics["attemptIds"]
    for index, item in enumerate(candidates, start=1):
        assert item["files"]["main"] == f"game/bosque/heroe/att1/a{index}/main.png"
        assert {"main", "preview", "rawKey"} <= set(item["files"])
        assert item["metrics"]["palette"]
        assert (workspace / item["files"]["main"]).is_file()
    assert result.files == candidates[0]["files"]


def test_a_second_production_does_not_overwrite_the_first(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _figure(workspace / "knight.png")
    first = REGISTRY["character"].run(_ctx(workspace, _game(), _knight(), Fake([str(workspace / "knight.png")] * 3), "att1"))
    second = REGISTRY["character"].run(_ctx(workspace, _game(), _knight(), Fake([str(workspace / "knight.png")] * 3), "att2"))
    assert set(first.metrics["attemptIds"]).isdisjoint(second.metrics["attemptIds"])
    first_files = {item["files"]["main"] for item in first.metrics["candidates"]}
    second_files = {item["files"]["main"] for item in second.metrics["candidates"]}
    assert first_files.isdisjoint(second_files)
    assert all((workspace / path).is_file() for path in first_files | second_files)


def test_a_single_candidate_keeps_the_attempt_id_and_seed_zero(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _figure(workspace / "knight.png")
    fake = Fake([str(workspace / "knight.png")])
    result = REGISTRY["character"].run(_ctx(workspace, _game(), _knight(candidates=1, seed=0), fake, "att9"))
    assert result.metrics["attemptIds"] == ["att9"]
    assert "candidates" not in result.metrics
    assert result.files["main"] == "game/bosque/heroe/att9/main.png"
    assert _seeds(fake) == [0]


def _sword(path):
    image = np.zeros((300, 700, 4), dtype=np.uint8)
    image[100:220, 50:650] = (200, 200, 210, 255)
    Image.fromarray(image).save(path)


@pytest.mark.parametrize("pixel", [False, True])
def test_a_wide_item_fits_the_cell_instead_of_being_clipped(tmp_path, pixel):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _sword(workspace / "sword.png")
    asset = {"id": "espada", "kind": "item", "description": "long sword", "candidates": 1, "spec": {"sizePx": 32}, "attempts": []}
    result = REGISTRY["item"].run(_ctx(workspace, _game(pixel=pixel), asset, Fake([str(workspace / "sword.png")])))
    with Image.open(workspace / result.files["main"]) as opened:
        alpha = np.asarray(opened.convert("RGBA"))[..., 3]
    ys, xs = np.nonzero(alpha > 128)
    assert xs.min() > 0 and xs.max() < 31
    assert xs.max() - xs.min() + 1 >= 24
    assert ys.max() - ys.min() + 1 <= 8
