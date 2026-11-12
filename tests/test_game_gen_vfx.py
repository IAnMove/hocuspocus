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
from services.game_tools import GameToolError


def _frame(on: bool) -> np.ndarray:
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    if on:
        image[12:20, 12:20] = (240, 240, 240)
    return image


def _burst() -> list[np.ndarray]:
    return [_frame(False), _frame(True), _frame(True), _frame(True), _frame(False)]


def _lossless(folder: Path, frames: list[np.ndarray], name: str = "burst") -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is missing")
    raw = folder / f"{name}-src"
    raw.mkdir()
    for index, frame in enumerate(frames):
        Image.fromarray(frame).save(raw / f"{index:04d}.png")
    video = folder / f"{name}.mkv"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", "8", "-start_number", "0",
         "-i", str(raw / "%04d.png"), "-c:v", "ffv1", str(video)],
        check=True,
    )
    return video


class _Video:
    """Answers each ``generation.video`` with the next clip, as an absolute path or a bare file name."""

    def __init__(self, *videos: Path, bare: bool = False):
        self.videos = list(videos)
        self.bare = bare
        self.calls = []

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        if tool == "generation.video":
            return {"receipt": {"result": {"job_id": f"job-{len(self.renders) - 1}"}}}
        if tool == "jobs.wait":
            video = self.videos[min(int(args["input"]["job_id"].split("-")[1]), len(self.videos) - 1)]
            return {"status": "completed", "output_files": [video.name if self.bare else str(video)]}
        raise AssertionError(tool)

    @property
    def renders(self):
        return [args for tool, args in self.calls if tool == "generation.video"]


def _asset(**spec) -> dict:
    return {
        "id": "explosion", "kind": "vfx", "description": "burst",
        "spec": {"effect": "a small white burst", "frames": 3, "fps": 12, "sizePx": 16, "blend": "add", **spec},
        "attempts": [],
    }


def _run(tmp_path, frames, asset=None, *, bare=False):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fake = _Video(_lossless(workspace, frames), bare=bare)
    game = {"id": "bosque", "style": {"screen": "magenta", "pixel": {"enabled": False}}, "assets": []}
    ctx = GenContext(
        workspace="bosque", game=game, asset=asset or _asset(), attempt_id="a1", call=fake,
        loopback=lambda _tool, _args: {}, workspace_dir=lambda _name: str(workspace),
        cancelled=lambda: False, log=lambda _message: None,
    )
    return workspace, fake, VfxGenerator().run(ctx)


def _sheet(workspace: Path, result) -> np.ndarray:
    return np.asarray(Image.open(workspace / result.files["sheet"]).convert("RGBA"))


def _box(alpha: np.ndarray) -> tuple[int, int]:
    """Width and height of the opaque part."""
    ys, xs = np.nonzero(alpha >= 128)
    return int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def test_vfx_sheet_border_is_clear_and_blend_is_add(tmp_path):
    workspace, fake, result = _run(tmp_path, _burst())
    params = fake.renders[0]["input"]["params"]
    assert params["image_start"] == params["image_end"]
    assert "pure black background" in params["prompt"]
    assert "a small white burst" in params["prompt"]
    assert result.metrics["blend"] == "add"
    assert result.metrics["frames"] == 3
    atlas = json.loads((workspace / result.files["atlas"]).read_text(encoding="utf-8"))
    assert atlas["meta"]["blend"] == "add"
    assert atlas["meta"]["frameTags"][0]["name"] == "explosion"
    sheet = _sheet(workspace, result)
    assert int(sheet[0, :, 3].max()) == 0
    assert int(sheet[-1, :, 3].max()) == 0
    assert int(sheet[:, 0, 3].max()) == 0
    assert int(sheet[:, -1, 3].max()) == 0
    assert (workspace / result.files["preview"]).is_file()
    assert not (workspace / "game" / "bosque" / "explosion" / "a1" / "black.png").exists()


def test_vfx_clip_named_by_the_tool_is_read_from_the_workspace(tmp_path):
    workspace, _fake, result = _run(tmp_path, _burst(), bare=True)
    assert (workspace / result.files["sheet"]).is_file()


def test_wide_effect_keeps_its_proportions(tmp_path):
    bar = np.zeros((32, 32, 3), dtype=np.uint8)
    bar[13:19, 4:28] = 240
    workspace, _fake, result = _run(tmp_path, [bar, bar, bar], _asset(frames=1))
    assert _box(_sheet(workspace, result)[..., 3]) == (16, 4)


def test_thin_sparks_survive_the_downscale(tmp_path):
    ring = np.zeros((40, 40, 3), dtype=np.uint8)
    ring[4:36, 4:36] = 240
    ring[5:35, 5:35] = 0
    workspace, _fake, result = _run(tmp_path, [ring, ring, ring], _asset(frames=1, sizePx=4))
    assert int(_sheet(workspace, result)[..., 3].max()) > 0


def test_compression_noise_does_not_shrink_the_effect(tmp_path):
    noisy = _frame(True)
    noisy[0, 0] = (3, 3, 3)
    workspace, _fake, result = _run(tmp_path, [noisy, noisy, noisy], _asset(frames=1))
    assert _box(_sheet(workspace, result)[..., 3]) == (16, 16)


def test_a_clip_with_only_noise_fails_instead_of_storing_an_empty_sheet(tmp_path):
    haze = np.full((32, 32, 3), 3, dtype=np.uint8)
    with pytest.raises(GameToolError) as caught:
        _run(tmp_path, [haze, haze, haze])
    assert caught.value.code == "empty_vfx"


def test_vfx_candidates_are_separate_clips(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    clips = [_lossless(workspace, _burst(), name=f"burst{index}") for index in (1, 2)]
    asset = {**_asset(), "candidates": 2}
    assert VfxGenerator().estimate({}, asset) == {"h3": 2}
    fake = _Video(*clips)
    game = {"id": "bosque", "style": {}, "assets": []}
    ctx = GenContext(
        workspace="bosque", game=game, asset=asset, attempt_id="a1", call=fake,
        loopback=lambda _tool, _args: {}, workspace_dir=lambda _name: str(workspace),
        cancelled=lambda: False, log=lambda _message: None,
    )
    result = VfxGenerator().run(ctx)
    assert [render["intent_id"].rsplit("-", 2)[-2:] for render in fake.renders] == [["vfx", "a1"], ["vfx", "a2"]]
    listed = result.metrics["candidates"]
    assert [item["id"] for item in listed] == ["a1-a1", "a1-a2"]
    stored = [path for item in listed for path in item["files"].values()]
    assert all((workspace / path).is_file() and "\\" not in path for path in stored)
