"""Still generator with a simulated image tool. No GPU."""
from __future__ import annotations

import numpy as np
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


def test_character_writes_three_cells_with_palette_and_scale(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _figure(workspace / "knight.png")
    game = {
        "id": "bosque",
        "style": {
            "preset": "pixel-16",
            "traits": "16-bit pixel art",
            "negative": "blur",
            "palette": [],
            "paletteMode": "free",
            "pixel": {"enabled": True, "spriteHeight": 48, "tile": 16, "colors": 4, "outline": "none", "dither": "none"},
            "screen": "magenta",
            "references": [],
        },
        "assets": [],
    }
    asset = {
        "id": "heroe",
        "kind": "character",
        "description": "short bronze knight",
        "candidates": 3,
        "spec": {"heightPx": 48, "seed": 4},
        "attempts": [],
    }
    fake = Fake([str(workspace / "knight.png")] * 3)
    ctx = GenContext(
        workspace="bosque", game=game, asset=asset, attempt_id="a1", call=fake,
        loopback=lambda tool, args: {}, workspace_dir=lambda name: str(workspace),
        cancelled=lambda: False, log=lambda message: None,
    )
    result = REGISTRY["character"].run(ctx)
    assert result.metrics["attemptIds"] == ["a1", "a2", "a3"]
    assert result.metrics["palette"]
    assert all(str(color).startswith("#") for color in result.metrics["palette"])
    assert result.metrics["scale"] > 0
    for attempt_id in ("a1", "a2", "a3"):
        main = workspace / "game" / "bosque" / "heroe" / attempt_id / "main.png"
        raw = main.with_name("raw-key.png")
        preview = main.with_name("preview.png")
        assert main.is_file() and raw.is_file() and preview.is_file()
        with Image.open(main) as opened:
            assert opened.size == (48, 48)
        with Image.open(preview) as opened:
            assert opened.size == (192, 192)
