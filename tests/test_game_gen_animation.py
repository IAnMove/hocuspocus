"""Animation and animated-item generators with a simulated tool. No GPU."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from services.game_generators.animation import (
    GAME_ANIMATION_DEFAULTS,
    AnimationGenerator,
    ItemGenerator,
    animation_warnings,
    method_for,
)
from services.game_generators.base import GenContext
from services.game_image_ops import feet_point
from services.game_library import normalize_game
from services.game_produce import GameProduce, ProduceDeps


NOW = "2026-10-07T00:00:00Z"


def test_method_for_follows_the_trial_table():
    assert method_for("walk") == "strip"
    assert method_for("run") == "strip"
    assert method_for("spin") == "strip"
    assert method_for("idle") == "h3"
    assert method_for("attack") == "h3"
    assert method_for("walk", "h3") == "h3"
    assert GAME_ANIMATION_DEFAULTS["groupActions"] is False
    assert GAME_ANIMATION_DEFAULTS["resolution"] == "544x960"
    assert GAME_ANIMATION_DEFAULTS["frames"] == 124
    assert GAME_ANIMATION_DEFAULTS["steps"] == 30


def test_warnings_use_the_trial_thresholds_not_a_half_error():
    assert animation_warnings(0.05, 0.20, 0.20, 2.0) == []
    assert "loop_not_closed" in animation_warnings(0.06, 0, 0, None)
    assert "identity_drift" in animation_warnings(None, 0.21, 0, None)
    assert "foot_drift" in animation_warnings(None, 0, 0.21, None)
    assert "halo" in animation_warnings(None, 0, 0, 2.01)
    assert "halo" not in animation_warnings(None, 0, 0, None)


def test_explicit_method_overrides_the_table():
    game = normalize_game({
        "id": "bosque", "title": "Bosque",
        "assets": [
            {"id": "heroe", "kind": "character"},
            {"id": "heroe-walk", "kind": "animation", "spec": {"character": "heroe", "action": "walk", "method": "h3"}},
        ],
    }, now=NOW)
    walk = next(asset for asset in game["assets"] if asset["id"] == "heroe-walk")
    assert walk["spec"]["method"] == "h3"


def test_unapproved_character_waits_without_calling_the_generator(tmp_path):
    def refuse(_tool, _args):
        raise AssertionError("the generator ran")

    assets = [
        {"id": "heroe", "kind": "character", "status": "pending", "dependsOn": [], "spec": {}},
        {
            "id": "heroe-idle", "kind": "animation", "status": "pending", "dependsOn": ["heroe"],
            "spec": {"character": "heroe", "action": "idle", "method": "h3", "frames": 4, "fps": 8, "loop": True},
        },
    ]
    service = GameProduce(ProduceDeps(
        call=refuse, loopback=lambda _tool, _args: {}, workspace_dir=lambda _name: str(tmp_path),
        read_game=lambda _workspace, _game: {"id": "bosque", "assets": assets},
        write_attempt=refuse, inline=True,
    ))
    job = service.start("lab", "bosque", asset_ids=["heroe-idle"])
    assert job["steps"][0]["status"] == "skipped"
    assert job["steps"][0]["reason"] == "waiting_dependency"


def _style():
    return {
        "preset": "pixel-16",
        "traits": "flat shapes",
        "palette": ["#14283c", "#e8d8a0"],
        "paletteMode": "locked",
        "pixel": {"enabled": True, "spriteHeight": 48, "tile": 1, "colors": 2, "outline": "none", "dither": "none"},
        "screen": "magenta",
        "references": [],
    }


def _character_files(workspace: Path):
    raw = np.zeros((40, 32, 4), dtype=np.uint8)
    raw[6:34, 10:18] = (0x14, 0x28, 0x3C, 255)
    raw_path = workspace / "knight-raw.png"
    Image.fromarray(raw).save(raw_path)
    return "knight-raw.png"


def _pose() -> np.ndarray:
    image = np.zeros((40, 32, 3), dtype=np.uint8)
    image[..., 0] = 255
    image[..., 2] = 255
    image[6:34, 10:18] = (0x14, 0x28, 0x3C)
    return image


def _lossless(folder: Path, frames: list[np.ndarray]) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is missing")
    raw = folder / "src"
    raw.mkdir()
    for index, frame in enumerate(frames):
        Image.fromarray(frame).save(raw / f"{index:04d}.png")
    video = folder / "clip.mkv"
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
            return {"receipt": {"result": {"job_id": "job-h3"}}}
        if tool == "jobs.wait":
            return {"status": "completed", "output_files": [str(self.video)]}
        raise AssertionError(tool)


def _ctx(workspace: Path, game, asset, call):
    return GenContext(
        workspace="bosque", game=game, asset=asset, attempt_id="a1", call=call,
        loopback=lambda _tool, _args: {}, workspace_dir=lambda _name: str(workspace),
        cancelled=lambda: False, log=lambda _message: None,
    )


def test_h3_sheet_has_equal_cells_a_stable_pivot_and_the_character_palette(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    video = _lossless(workspace, [_pose() for _index in range(8)])
    raw_name = _character_files(workspace)
    game = {"id": "bosque", "style": _style(), "assets": []}
    character = {
        "id": "heroe", "kind": "character", "status": "approved", "approvedAttemptId": "base",
        "spec": {"heightPx": 48},
        "attempts": [{
            "id": "base", "status": "ok",
            "files": {"rawKey": raw_name},
            "metrics": {"palette": ["#14283c", "#e8d8a0"], "scale": 1},
        }],
    }
    game["assets"] = [character]
    asset = {
        "id": "heroe-idle", "kind": "animation", "description": "breathing",
        "spec": {"character": "heroe", "action": "idle", "method": "h3", "frames": 4, "fps": 8, "loop": True},
        "attempts": [],
    }
    fake = _Video(video)
    result = AnimationGenerator().run(_ctx(workspace, game, asset, fake))
    params = fake.calls[0][1]["input"]["params"]
    assert params["model_type"] == "minimax_h3"
    assert params["resolution"] == "544x960"
    assert params["video_length"] == 124
    assert params["num_inference_steps"] == 30
    assert params["image_end"] == params["image_start"]
    assert params["image_start"].startswith("/api/v1/file/")
    assert "[ACTION]" in params["prompt"] and "Silence" in params["prompt"]
    assert result.metrics["frames"] == 4
    assert result.metrics["palette"] == ["#14283c", "#e8d8a0"]
    assert result.metrics["scale"] == 1
    assert "loop_not_closed" in result.warnings
    assert "halo" not in result.warnings
    sheet = Image.open(workspace / result.files["sheet"])
    atlas = json.loads((workspace / result.files["atlas"]).read_text(encoding="utf-8"))
    frames = list(atlas["frames"].values())
    assert len(frames) == 4
    size = (frames[0]["frame"]["w"], frames[0]["frame"]["h"])
    assert all((item["frame"]["w"], item["frame"]["h"]) == size for item in frames)
    pixels = np.asarray(sheet.convert("RGBA"))
    opaque = pixels[..., 3] > 0
    assert opaque.any()
    colors = {tuple(int(channel) for channel in pixel) for pixel in pixels[opaque][:, :3]}
    assert colors <= {(0x14, 0x28, 0x3C), (0xE8, 0xD8, 0xA0)}
    feet = []
    for item in frames:
        box = item["frame"]
        cell = pixels[box["y"]:box["y"] + box["h"], box["x"]:box["x"] + box["w"]]
        feet.append(feet_point(cell)[0])
    assert max(feet) - min(feet) <= 1
    assert (workspace / result.files["preview"]).is_file()


def _blobs() -> np.ndarray:
    colors = (
        (220, 20, 20, 255), (20, 200, 20, 255), (20, 20, 220, 255),
        (220, 220, 20, 255), (20, 200, 220, 255), (220, 20, 220, 255),
    )
    image = np.zeros((24, 140, 4), dtype=np.uint8)
    for index, color in enumerate(colors):
        left = 4 + index * 22
        image[4:20, left:left + 12] = color
    return image


class _Image:
    def __init__(self, path: Path):
        self.path = path
        self.calls = []

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        if tool == "generation.image":
            return {"receipt": {"result": {"job_id": "job-strip"}}}
        if tool == "jobs.wait":
            return {"status": "completed", "output_files": [str(self.path)]}
        if tool == "studio.key":
            return {"result": {"file": args["input"]["source"]}}
        raise AssertionError(tool)


def _illustration():
    style = _style()
    style["pixel"] = {"enabled": False, "spriteHeight": 48, "tile": 1, "colors": 16, "outline": "none", "dither": "none"}
    return style


def test_strip_keeps_six_figures_in_left_to_right_order(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    strip = workspace / "strip.png"
    Image.fromarray(_blobs()).save(strip)
    game = {"id": "bosque", "style": _illustration(), "assets": []}
    asset = {
        "id": "heroe-walk", "kind": "animation", "description": "walk cycle",
        "spec": {"character": "heroe", "action": "walk", "method": "strip", "frames": 8, "fps": 12, "loop": True},
        "attempts": [],
    }
    fake = _Image(strip)
    result = AnimationGenerator().run(_ctx(workspace, game, asset, fake))
    params = fake.calls[0][1]["input"]["params"]
    assert params["resolution"] == "1536x512"
    assert "8 frames" in params["prompt"] and "single row" in params["prompt"]
    assert "strip_count_mismatch" in result.warnings
    assert result.metrics["frames"] == 6
    atlas = json.loads((workspace / result.files["atlas"]).read_text(encoding="utf-8"))
    frames = [atlas["frames"][f"walk_{index}"]["frame"] for index in range(6)]
    assert frames[0]["x"] < frames[-1]["x"]
    sheet = np.asarray(Image.open(workspace / result.files["sheet"]).convert("RGBA"))
    means = []
    for box in frames:
        cell = sheet[box["y"]:box["y"] + box["h"], box["x"]:box["x"] + box["w"]]
        opaque = cell[..., 3] > 128
        means.append(cell[opaque][:, :3].mean(axis=0))
    assert means[0][0] > means[2][0]
    assert means[2][2] > means[0][2]
    assert means[1][1] > means[1][0]


def test_animated_item_uses_the_strip_and_not_video(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    strip = workspace / "coin.png"
    Image.fromarray(_blobs()[:, :26]).save(strip)
    game = {"id": "bosque", "style": _illustration(), "assets": []}
    asset = {
        "id": "moneda", "kind": "item", "description": "gold coin",
        "spec": {"sizePx": 32, "anim": {"action": "spin", "frames": 6}},
        "attempts": [],
    }
    fake = _Image(strip)
    result = ItemGenerator().run(_ctx(workspace, game, asset, fake))
    tools = [tool for tool, _args in fake.calls]
    assert "generation.image" in tools
    assert "generation.video" not in tools
    assert result.metrics["method"] == "strip"
    assert result.files["sheet"]
