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
    identity_distance,
    method_for,
    pose_change,
    split_figures,
)
from services.game_generators.base import GenContext
from services.game_image_ops import feet_point
from services.game_library import normalize_game
from services.game_produce import GameProduce, ProduceDeps
from services.game_tools import GameToolError
from tests.game_warnings import warning_codes


NOW = "2026-10-07T00:00:00Z"
MAGENTA = (255, 0, 255)
INK = (0x14, 0x28, 0x3C)


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


def _codes(warnings) -> list[str]:
    return warning_codes(warnings)


def test_warnings_use_the_trial_thresholds_not_a_half_error():
    assert _codes(animation_warnings(0.05, 0.20, 0.20, 2.0)) == []
    assert "loop_not_closed" in _codes(animation_warnings(0.06, 0, 0, None))
    assert "identity_drift" in _codes(animation_warnings(None, 0.21, 0, None))
    assert "foot_drift" in _codes(animation_warnings(None, 0, 0.21, None))
    assert "foot_drift" not in _codes(animation_warnings(None, 0, None, None))
    assert "halo" in _codes(animation_warnings(None, 0, 0, 2.01))
    assert "halo" not in _codes(animation_warnings(None, 0, 0, None))
    for item in animation_warnings(0.06, 0.21, 0.21, 2.01):
        assert isinstance(item["code"], str) and isinstance(item["message"], str) and item["message"]


def _solid(color, box) -> np.ndarray:
    image = np.zeros((32, 48, 4), dtype=np.uint8)
    y0, y1, x0, x1 = box
    image[y0:y1, x0:x1, :3] = color
    image[y0:y1, x0:x1, 3] = 255
    return image


def test_identity_ignores_a_pose_change_and_warns_on_a_new_palette():
    red = _solid((220, 30, 30), (4, 28, 6, 20))
    shifted = _solid((220, 30, 30), (4, 28, 24, 40))
    blue = _solid((30, 40, 220), (4, 28, 6, 20))
    same = identity_distance(red, shifted)
    other = identity_distance(red, blue)
    assert same <= 0.20
    assert pose_change(red, shifted) > 0
    assert "identity_drift" not in _codes(animation_warnings(None, same, 0, None))
    assert other > 0.20
    assert "identity_drift" in _codes(animation_warnings(None, other, 0, None))


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


def _illustration():
    style = _style()
    style["pixel"] = {"enabled": False, "spriteHeight": 48, "tile": 1, "colors": 16, "outline": "none", "dither": "none"}
    return style


def _character_files(workspace: Path):
    raw = np.zeros((40, 32, 4), dtype=np.uint8)
    raw[6:34, 10:18] = INK + (255,)
    raw_path = workspace / "knight-raw.png"
    Image.fromarray(raw).save(raw_path)
    return "knight-raw.png"


def _pose(top: int = 6, height: int = 28, width: int = 8, size=(40, 32), color=INK) -> np.ndarray:
    """A figure on magenta, centered at x=16, its rows ``top`` to ``top + height``."""
    image = np.zeros(size + (3,), dtype=np.uint8)
    image[...] = MAGENTA
    left = 16 - width // 2
    image[top:top + height, left:left + width] = color
    return image


def _lossless(folder: Path, frames: list[np.ndarray], name: str = "clip", rate: int = 8) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is missing")
    raw = folder / f"{name}-src"
    raw.mkdir()
    for index, frame in enumerate(frames):
        Image.fromarray(frame).save(raw / f"{index:04d}.png")
    video = folder / f"{name}.mkv"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(rate), "-start_number", "0",
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


def _ctx(workspace: Path, game, asset, call):
    return GenContext(
        workspace="bosque", game=game, asset=asset, attempt_id="a1", call=call,
        loopback=lambda _tool, _args: {}, workspace_dir=lambda _name: str(workspace),
        cancelled=lambda: False, log=lambda _message: None,
    )


def _knight(workspace: Path, *, height: int = 48, metrics=None, description: str = "") -> dict:
    return {
        "id": "heroe", "kind": "character", "status": "approved", "approvedAttemptId": "base",
        "description": description, "spec": {"heightPx": height},
        "attempts": [{
            "id": "base", "status": "ok",
            "files": {"rawKey": _character_files(workspace)},
            "metrics": metrics if metrics is not None else {"palette": ["#14283c", "#e8d8a0"]},
        }],
    }


def _action(action: str, description: str = "", **spec) -> dict:
    return {
        "id": f"heroe-{action}", "kind": "animation", "description": description,
        "spec": {"character": "heroe", "action": action, "method": "h3", **spec},
        "attempts": [],
    }


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return workspace


def _cells(workspace: Path, result) -> list[np.ndarray]:
    sheet = np.asarray(Image.open(workspace / result.files["sheet"]).convert("RGBA"))
    atlas = json.loads((workspace / result.files["atlas"]).read_text(encoding="utf-8"))
    boxes = [item["frame"] for item in atlas["frames"].values()]
    return [sheet[box["y"]:box["y"] + box["h"], box["x"]:box["x"] + box["w"]] for box in boxes]


def _rows(cell: np.ndarray) -> tuple[int, int]:
    """First and last opaque row."""
    rows = np.nonzero((cell[..., 3] > 128).any(axis=1))[0]
    return int(rows[0]), int(rows[-1])


def _width(cell: np.ndarray) -> int:
    cols = np.nonzero((cell[..., 3] > 128).any(axis=0))[0]
    return int(cols[-1] - cols[0] + 1)


def _h3(tmp_path, frames, asset, *, style=None, height=48, metrics=None, rate=8, bare=False):
    workspace = _workspace(tmp_path)
    video = _lossless(workspace, frames, rate=rate)
    game = {"id": "bosque", "style": style or _style(), "assets": [_knight(workspace, height=height, metrics=metrics)]}
    fake = _Video(video, bare=bare)
    return workspace, fake, AnimationGenerator().run(_ctx(workspace, game, asset, fake))


def test_h3_sheet_has_equal_cells_a_stable_pivot_and_the_character_palette(tmp_path):
    asset = _action("idle", "breathing", frames=4, fps=8, loop=True)
    workspace, fake, result = _h3(tmp_path, [_pose() for _index in range(8)], asset)
    params = fake.renders[0]["input"]["params"]
    assert params["model_type"] == "minimax_h3"
    assert params["resolution"] == "544x960"
    assert params["video_length"] == 124
    assert params["num_inference_steps"] == 30
    assert params["image_end"] == params["image_start"]
    assert params["image_start"].startswith("/api/v1/file/")
    assert "[ACTION]" in params["prompt"] and "Silence" in params["prompt"]
    assert result.metrics["frames"] == 4
    assert result.metrics["palette"] == ["#14283c", "#e8d8a0"]
    assert result.metrics["scale"] == pytest.approx(48 / 28)
    assert "loop_not_closed" in warning_codes(result.warnings)
    assert "halo" not in warning_codes(result.warnings)
    cells = _cells(workspace, result)
    assert len(cells) == 4
    assert len({cell.shape for cell in cells}) == 1
    colors = {tuple(int(channel) for channel in pixel) for cell in cells for pixel in cell[cell[..., 3] > 0][:, :3]}
    assert colors and colors <= {INK, (0xE8, 0xD8, 0xA0)}
    feet = [feet_point(cell)[0] for cell in cells]
    assert max(feet) - min(feet) <= 1
    assert (workspace / result.files["preview"]).is_file()


def test_h3_clip_named_by_the_tool_is_read_from_the_workspace(tmp_path):
    # The server answers output_files with a bare workspace file name, not a path ffmpeg can open from its cwd.
    asset = _action("idle", frames=2, fps=8, loop=True)
    workspace, _fake, result = _h3(tmp_path, [_pose() for _index in range(4)], asset, bare=True)
    assert (workspace / result.files["sheet"]).is_file()


def test_recorded_character_scale_does_not_resize_the_clip(tmp_path):
    # The character's scale was measured on its own raw key; the clip draws the figure at another size.
    asset = _action("idle", frames=2, fps=8, loop=True)
    metrics = {"palette": ["#14283c", "#e8d8a0"], "scale": 0.25}
    workspace, _fake, result = _h3(tmp_path, [_pose() for _index in range(4)], asset, metrics=metrics)
    top, bottom = _rows(_cells(workspace, result)[0])
    assert bottom - top + 1 == pytest.approx(48, abs=1)


def test_illustration_frames_share_one_scale(tmp_path):
    stand, crouch = _pose(top=6, height=28), _pose(top=20, height=14)
    asset = _action("crouch", frames=2, fps=8, loop=False)
    workspace, _fake, result = _h3(tmp_path, [stand, crouch], asset, style=_illustration(), metrics={})
    heights = [bottom - top + 1 for top, bottom in map(_rows, _cells(workspace, result))]
    assert heights[0] == pytest.approx(48, abs=1)
    assert heights[1] == pytest.approx(24, abs=1)


def test_jump_keeps_its_height(tmp_path):
    frames = [_pose(top=30, size=(64, 32)), _pose(top=18, size=(64, 32)), _pose(top=30, size=(64, 32))]
    asset = _action("jump", frames=3, fps=12, loop=False)
    workspace, _fake, result = _h3(tmp_path, frames, asset, height=28)
    bottoms = [_rows(cell)[1] for cell in _cells(workspace, result)]
    assert bottoms[0] == bottoms[2]
    assert bottoms[0] - bottoms[1] == 12


def test_one_shot_ends_on_the_last_clip_frame(tmp_path):
    frames = [_pose(width=4 + 2 * index) for index in range(7)]
    asset = _action("attack", frames=3, fps=14, loop=False)
    workspace, _fake, result = _h3(tmp_path, frames, asset, height=28)
    assert [_width(cell) for cell in _cells(workspace, result)] == [4, 10, 16]


def test_loop_period_is_searched_in_clip_frames(tmp_path):
    # A 24 fps clip with a shallow dip at frame 4 and the real return to frame 0 at frame 16.
    levels = [0, 6, 12, 18, 6, 30, 60, 90, 120, 150, 180, 150, 120, 90, 60, 30] * 2 + [0]
    frames = [_pose(color=(20 + level,) * 3) for level in levels]
    asset = _action("idle", frames=4, fps=8, loop=True)
    _workspace_dir, _fake, result = _h3(tmp_path, frames, asset, style=_illustration(), metrics={}, rate=24)
    assert result.metrics["cycleFrames"] == 16
    assert "loop_not_closed" not in warning_codes(result.warnings)


def test_h3_candidates_are_separate_clips(tmp_path):
    workspace = _workspace(tmp_path)
    clips = [_lossless(workspace, [_pose() for _index in range(4)], name=f"clip{index}") for index in (1, 2)]
    game = {"id": "bosque", "style": _style(), "assets": [_knight(workspace)]}
    asset = {**_action("idle", frames=2, fps=8, loop=True), "candidates": 2}
    fake = _Video(*clips)
    assert AnimationGenerator().estimate(game, asset) == {"h3": 2}
    result = AnimationGenerator().run(_ctx(workspace, game, asset, fake))
    assert [render["intent_id"].rsplit("-", 2)[-2:] for render in fake.renders] == [["clip", "a1"], ["clip", "a2"]]
    listed = result.metrics["candidates"]
    assert [item["id"] for item in listed] == ["a1-a1", "a1-a2"]
    assert all((workspace / item["files"]["sheet"]).is_file() for item in listed)
    assert listed[1]["files"]["sheet"].endswith("a1/a2/sheet.png")
    assert not (workspace / "game" / "bosque" / "heroe-idle" / "a1" / "start.png").exists()


class _Abort:
    """Records the first video request and fails it, so the prompt is checked without a clip."""

    def __init__(self):
        self.params = None

    def __call__(self, tool, args):
        self.params = args["input"]["params"]
        return {"_is_error": True, "error": "stop"}


def _h3_prompt(tmp_path, asset, *, character_description="", style=None) -> str:
    workspace = _workspace(tmp_path)
    game = {"id": "bosque", "style": style or _style(), "assets": [_knight(workspace, description=character_description)]}
    fake = _Abort()
    with pytest.raises(GameToolError):
        AnimationGenerator().run(_ctx(workspace, game, asset, fake))
    return fake.params["prompt"]


def test_green_character_gets_a_magenta_backdrop(tmp_path):
    style = {**_style(), "screen": "auto"}
    prompt = _h3_prompt(tmp_path, _action("idle", "idle"), character_description="green goblin", style=style)
    assert "Solid flat magenta backdrop" in prompt


def test_h3_prompt_keeps_the_users_own_words(tmp_path):
    prompt = _h3_prompt(tmp_path, _action("attack", "swings a huge axe overhead"))
    assert "swings a huge axe overhead" in prompt
    assert "[ACTION] one quick attack" in prompt


def _blobs(tops=(4, 4, 4, 4, 4, 4)) -> np.ndarray:
    colors = (
        (220, 20, 20, 255), (20, 200, 20, 255), (20, 20, 220, 255),
        (220, 220, 20, 255), (20, 200, 220, 255), (220, 20, 220, 255),
    )
    image = np.zeros((32, 140, 4), dtype=np.uint8)
    for index, (color, top) in enumerate(zip(colors, tops)):
        left = 4 + index * 22
        image[top:top + 16, left:left + 12] = color
    return image


class _Image:
    def __init__(self, *paths: Path):
        self.paths = paths
        self.calls = []

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        if tool == "generation.image":
            return {"receipt": {"result": {"job_id": "job-strip"}}}
        if tool == "jobs.wait":
            return {"status": "completed", "output_files": [str(path) for path in self.paths]}
        if tool == "studio.key":
            return {"result": {"file": args["input"]["source"]}}
        raise AssertionError(tool)

    def params(self) -> dict:
        return next(args for tool, args in self.calls if tool == "generation.image")["input"]["params"]


def _strip(tmp_path, pixels: np.ndarray, asset: dict, *, style=None, assets=()):
    workspace = _workspace(tmp_path)
    path = workspace / "strip.png"
    Image.fromarray(pixels).save(path)
    game = {"id": "bosque", "style": style or _illustration(), "assets": list(assets)}
    fake = _Image(path)
    generator = ItemGenerator() if asset["kind"] == "item" else AnimationGenerator()
    return workspace, fake, generator.run(_ctx(workspace, game, asset, fake))


def _walk(**spec) -> dict:
    return {
        "id": "heroe-walk", "kind": "animation", "description": "walk cycle",
        "spec": {"character": "heroe", "action": "walk", "method": "strip", "frames": 8, "fps": 12, "loop": True, **spec},
        "attempts": [],
    }


def _means(workspace: Path, result) -> list[np.ndarray]:
    return [cell[cell[..., 3] > 128][:, :3].mean(axis=0) for cell in _cells(workspace, result)]


def test_strip_keeps_six_figures_in_left_to_right_order(tmp_path):
    workspace, fake, result = _strip(tmp_path, _blobs(), _walk())
    params = fake.params()
    assert params["resolution"] == "1536x512"
    assert "8 frames" in params["prompt"] and "single row" in params["prompt"]
    assert "strip_count_mismatch" in warning_codes(result.warnings)
    assert result.metrics["frames"] == 6
    atlas = json.loads((workspace / result.files["atlas"]).read_text(encoding="utf-8"))
    frames = [atlas["frames"][f"walk_{index}"]["frame"] for index in range(6)]
    assert frames[0]["x"] < frames[-1]["x"]
    means = _means(workspace, result)
    assert means[0][0] > means[2][0]
    assert means[2][2] > means[0][2]
    assert means[1][1] > means[1][0]


def test_extra_strip_figures_warn_and_spread_over_the_cycle(tmp_path):
    workspace, _fake, result = _strip(tmp_path, _blobs(), _walk(frames=3))
    assert "strip_count_mismatch" in warning_codes(result.warnings)
    red, blue, cyan = _means(workspace, result)
    assert red[0] > 150 and blue[2] > 150 and cyan[1] > 150 and cyan[2] > 150


def test_strip_seed_zero_reaches_qwen_and_mirror_reaches_the_atlas(tmp_path):
    workspace, fake, result = _strip(tmp_path, _blobs(), _walk(seed=0, mirror=False))
    assert fake.params()["seed"] == 0
    atlas = json.loads((workspace / result.files["atlas"]).read_text(encoding="utf-8"))
    assert atlas["meta"]["mirror"] is False


def test_strip_prompt_names_the_character_and_its_facing(tmp_path):
    knight = {"id": "heroe", "kind": "character", "description": "knight in blue armor", "status": "pending"}
    _workspace_dir, fake, _result = _strip(tmp_path, _blobs(), _walk(), assets=[knight])
    prompt = fake.params()["prompt"]
    assert "flat shapes" in prompt
    assert "knight in blue armor" in prompt
    assert "facing right" in prompt


def test_strip_candidates_follow_the_contract(tmp_path):
    workspace = _workspace(tmp_path)
    paths = []
    for index in (1, 2):
        paths.append(workspace / f"strip{index}.png")
        Image.fromarray(_blobs()).save(paths[-1])
    game = {"id": "bosque", "style": _illustration(), "assets": []}
    asset = {**_walk(frames=6), "candidates": 2}
    fake = _Image(*paths)
    assert AnimationGenerator().estimate(game, asset) == {"image": 2}
    result = AnimationGenerator().run(_ctx(workspace, game, asset, fake))
    assert fake.params()["batch_size"] == 2
    listed = result.metrics["candidates"]
    assert [item["id"] for item in listed] == ["a1-a1", "a1-a2"]
    assert [item["files"]["sheet"] for item in listed] == [
        "game/bosque/heroe-walk/a1/a1/sheet.png", "game/bosque/heroe-walk/a1/a2/sheet.png",
    ]
    assert result.files == listed[0]["files"]
    stored = [path for item in listed for path in item["files"].values()]
    assert all("\\" not in path and not Path(path).is_absolute() for path in stored)


def _strides() -> np.ndarray:
    """Four figures 28 tall; the second and fourth put a foot forward, so their crops are wider."""
    image = np.zeros((40, 140, 4), dtype=np.uint8)
    for index in range(4):
        left = 6 + index * 32
        image[6:34, left:left + 8] = INK + (255,)
        if index % 2:
            image[31:34, left + 8:left + 18] = INK + (255,)
    return image


def test_strip_figures_keep_their_width(tmp_path):
    style = _style()
    style["pixel"] = {**style["pixel"], "spriteHeight": 28}
    workspace, _fake, result = _strip(tmp_path, _strides(), _walk(frames=4), style=style)
    assert [_width(cell) for cell in _cells(workspace, result)] == [8, 18, 8, 18]


def test_strip_strides_are_not_foot_drift(tmp_path):
    _workspace_dir, _fake, result = _strip(tmp_path, _strides(), _walk(frames=4))
    assert "foot_drift" not in warning_codes(result.warnings)
    assert result.metrics["footDrift"] is None


def test_split_figures_keeps_a_detached_head_with_its_body():
    strip = np.zeros((40, 60, 4), dtype=np.uint8)
    for left in (8, 38):
        strip[2:8, left + 2:left + 8] = 255
        strip[10:38, left:left + 10] = 255
    figures = split_figures(strip)
    assert len(figures) == 2
    assert all(figure.shape[:2] == (36, 10) for figure in figures)


def _coins() -> np.ndarray:
    image = np.zeros((40, 80, 4), dtype=np.uint8)
    for index, top in enumerate((14, 8, 14)):
        left = 6 + index * 26
        image[top:top + 16, left:left + 16] = INK + (255,)
    return image


def _coin(**anim) -> dict:
    return {
        "id": "moneda", "kind": "item", "description": "gold coin", "candidates": 1,
        "spec": {"sizePx": 16, "anim": {"action": "bob", "frames": 3, **anim}},
        "attempts": [],
    }


def test_bob_strip_keeps_its_vertical_motion(tmp_path):
    workspace, _fake, result = _strip(tmp_path, _coins(), _coin(), style=_style())
    bottoms = [_rows(cell)[1] for cell in _cells(workspace, result)]
    assert bottoms[0] == bottoms[2]
    assert bottoms[0] - bottoms[1] == 6


def test_animated_item_uses_the_strip_and_not_video(tmp_path):
    asset = {**_coin(action="spin", frames=6), "candidates": 3}
    assert ItemGenerator().estimate({}, asset) == {"image": 3}
    workspace = _workspace(tmp_path)
    strip = workspace / "coin.png"
    Image.fromarray(_blobs()[:, :26]).save(strip)
    game = {"id": "bosque", "style": _illustration(), "assets": []}
    fake = _Image(strip)
    result = ItemGenerator().run(_ctx(workspace, game, asset, fake))
    tools = [tool for tool, _args in fake.calls]
    assert "generation.image" in tools
    assert "generation.video" not in tools
    assert result.metrics["method"] == "strip"
    assert result.files["sheet"]
    prompt = fake.params()["prompt"]
    assert "gold coin" in prompt and "flat shapes" in prompt
    assert "facing right" not in prompt


def test_pixel_frames_are_box_filtered_not_point_sampled(tmp_path):
    # A fine black-and-white texture shrinks to its average, as the still generator does, not to one sample.
    texture = np.zeros((40, 40, 4), dtype=np.uint8)
    checker = (np.indices((32, 32)).sum(axis=0) % 2 == 1)
    texture[4:36, 4:36, 3] = 255
    texture[4:36, 4:36, :3] = np.where(checker[..., None], 255, 0)
    style = _style()
    style["palette"] = ["#000000", "#808080", "#ffffff"]
    style["pixel"] = {**style["pixel"], "spriteHeight": 8, "colors": 3}
    workspace, _fake, result = _strip(tmp_path, texture, _walk(frames=1), style=style)
    cell = _cells(workspace, result)[0]
    assert {tuple(int(value) for value in pixel) for pixel in cell[cell[..., 3] > 0][:, :3]} == {(128, 128, 128)}
