"""VFX generator with a simulated clip. No GPU."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from services.game_generators.base import GenContext
from services.game_generators.vfx import VfxGenerator


def _frame(on: bool) -> np.ndarray:
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    if on:
        image[12:20, 12:20] = (240, 240, 240)
    return image


def _lossless(folder: Path) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is missing")
    raw = folder / "src"
    raw.mkdir()
    frames = [_frame(False), _frame(True), _frame(True), _frame(True), _frame(False)]
    for index, frame in enumerate(frames):
        Image.fromarray(frame).save(raw / f"{index:04d}.png")
    video = folder / "burst.mkv"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", "8", "-start_number", "0",
         "-i", str(raw / "%04d.png"), "-c:v", "ffv1", str(video)],
        check=True,
    )
    return video


class _Video:
    def __init__(self, video: Path):
        self.video = video
        self.calls = []

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        if tool == "generation.video":
            return {"receipt": {"result": {"job_id": "job-vfx"}}}
        if tool == "jobs.wait":
            return {"status": "completed", "output_files": [str(self.video)]}
        raise AssertionError(tool)


def test_vfx_sheet_border_is_clear_and_blend_is_add(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    video = _lossless(workspace)
    game = {"id": "bosque", "style": {"screen": "magenta", "pixel": {"enabled": False}}, "assets": []}
    asset = {
        "id": "explosion", "kind": "vfx", "description": "burst",
        "spec": {"effect": "a small white burst", "frames": 3, "fps": 12, "sizePx": 16, "blend": "add"},
        "attempts": [],
    }
    fake = _Video(video)
    ctx = GenContext(
        workspace="bosque", game=game, asset=asset, attempt_id="a1", call=fake,
        loopback=lambda _tool, _args: {}, workspace_dir=lambda _name: str(workspace),
        cancelled=lambda: False, log=lambda _message: None,
    )
    result = VfxGenerator().run(ctx)
    params = fake.calls[0][1]["input"]["params"]
    assert params["image_start"] == params["image_end"]
    assert "pure black background" in params["prompt"]
    assert "a small white burst" in params["prompt"]
    assert result.metrics["blend"] == "add"
    assert result.metrics["frames"] == 3
    atlas = json.loads((workspace / result.files["atlas"]).read_text(encoding="utf-8"))
    assert atlas["meta"]["blend"] == "add"
    sheet = np.asarray(Image.open(workspace / result.files["sheet"]).convert("RGBA"))
    assert int(sheet[0, :, 3].max()) == 0
    assert int(sheet[-1, :, 3].max()) == 0
    assert int(sheet[:, 0, 3].max()) == 0
    assert int(sheet[:, -1, 3].max()) == 0
    assert (workspace / result.files["preview"]).is_file()
