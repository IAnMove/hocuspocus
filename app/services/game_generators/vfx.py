"""Visual effects: a MiniMax clip on black, keyed by the brightest channel.

The sheet is one row. ``blend: add`` keeps the color on black and records
``blend`` on the atlas. A pad around the effect leaves the cell border clear.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from services.game_frames import extract_frames, sample_frames, vfx_alpha
from services.game_generators.animation import GAME_ANIMATION_DEFAULTS
from services.game_generators.base import AttemptResult, GenContext, attempt_dir
from services.game_sheet import pack_rows, uniform_cell, write_gif_preview
from services.game_tools import GameToolError, file_ref, video_fl2va


def _canvas(resolution: str) -> tuple[int, int]:
    width, height = str(resolution).lower().split("x", 1)
    return int(width), int(height)


def _relative(ctx: GenContext, path: Path) -> str:
    root = Path(ctx.workspace_dir(ctx.workspace))
    return str(path.relative_to(root))


def _remove_frames(folder: Path) -> None:
    if not folder.is_dir():
        return
    for path in folder.glob("[0-9][0-9][0-9][0-9].png"):
        path.unlink()
    try:
        folder.rmdir()
    except OSError:
        return


def _spec(asset: dict) -> dict:
    spec = asset.get("spec")
    return spec if isinstance(spec, dict) else {}


def _effect(asset: dict) -> str:
    spec = _spec(asset)
    text = str(spec.get("effect") or asset.get("description") or "effect").strip()
    return text or "effect"


def _count(asset: dict) -> int:
    try:
        return max(1, int(_spec(asset).get("frames") or 12))
    except (TypeError, ValueError):
        return 12


def _fps(asset: dict) -> int:
    try:
        return max(1, int(_spec(asset).get("fps") or 18))
    except (TypeError, ValueError):
        return 18


def _size(asset: dict) -> int:
    try:
        return max(1, int(_spec(asset).get("sizePx") or 64))
    except (TypeError, ValueError):
        return 64


def _blend(asset: dict) -> str:
    value = str(_spec(asset).get("blend") or "add")
    return value if value in ("add", "alpha") else "add"


def _prompt(asset: dict) -> str:
    return f"{_effect(asset)}, centered, pure black background, locked camera, no other objects"


def _black_ref(ctx: GenContext) -> str:
    width, height = _canvas(str(GAME_ANIMATION_DEFAULTS["resolution"]))
    folder = attempt_dir(ctx)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "black.png"
    Image.fromarray(np.zeros((height, width, 3), dtype=np.uint8)).save(path)
    return file_ref(ctx, _relative(ctx, path))


def _content_box(frames) -> tuple[int, int, int, int] | None:
    x0 = y0 = None
    x1 = y1 = 0
    for frame in frames:
        ys, xs = np.nonzero(np.asarray(frame)[..., 3] > 0)
        if len(xs) == 0:
            continue
        left, top, right, bottom = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        x0 = left if x0 is None else min(x0, left)
        y0 = top if y0 is None else min(y0, top)
        x1, y1 = max(x1, right), max(y1, bottom)
    if x0 is None or y0 is None:
        return None
    return (x0, y0, x1, y1)


def _crop_all(frames, box):
    x0, y0, x1, y1 = box
    return [np.asarray(frame)[y0:y1, x0:x1] for frame in frames]


def _square(frame, size: int) -> np.ndarray:
    image = Image.fromarray(np.asarray(frame, dtype=np.uint8))
    return np.asarray(image.resize((size, size), Image.Resampling.NEAREST))


def _store(ctx: GenContext, sheet, atlas: dict, frames, metrics: dict) -> AttemptResult:
    folder = attempt_dir(ctx)
    folder.mkdir(parents=True, exist_ok=True)
    sheet_path = folder / "sheet.png"
    atlas_path = folder / "sheet.json"
    gif_path = folder / "preview.gif"
    sheet.save(sheet_path)
    atlas_path.write_text(json.dumps(atlas), encoding="utf-8")
    write_gif_preview(frames, _fps(ctx.asset), 1, gif_path)
    root = folder.parents[3]
    files = {
        "main": str(sheet_path.relative_to(root)),
        "sheet": str(sheet_path.relative_to(root)),
        "atlas": str(atlas_path.relative_to(root)),
        "preview": str(gif_path.relative_to(root)),
    }
    _remove_frames(folder / "frames")
    return AttemptResult(files=files, metrics=metrics, warnings=[], provenance={"steps": list(ctx.steps)})


def _run(ctx: GenContext) -> AttemptResult:
    black = _black_ref(ctx)
    video = video_fl2va(
        ctx, "vfx", prompt=_prompt(ctx.asset), start=black, end=black,
        frames=int(GAME_ANIMATION_DEFAULTS["frames"]),
        model=str(GAME_ANIMATION_DEFAULTS["model"]),
        resolution=str(GAME_ANIMATION_DEFAULTS["resolution"]),
        steps=int(GAME_ANIMATION_DEFAULTS["steps"]),
    )
    black_path = attempt_dir(ctx) / "black.png"
    if black_path.is_file():
        black_path.unlink()
    extracted = extract_frames(video, 0, 60, attempt_dir(ctx) / "frames")
    if not extracted:
        raise GameToolError("empty_clip", "the effect clip has no frames")
    rgb = []
    for path in extracted:
        with Image.open(path) as opened:
            rgb.append(np.asarray(opened.convert("RGB")))
    keyed = vfx_alpha(rgb)
    if not keyed:
        raise GameToolError("empty_vfx", "the effect clip is empty")
    box = _content_box(keyed)
    cropped = _crop_all(keyed, box) if box else keyed
    size = _size(ctx.asset)
    fitted = [_square(frame, size) for frame in cropped]
    chosen = sample_frames(fitted, 0, len(fitted), _count(ctx.asset))
    if not chosen:
        raise GameToolError("empty_vfx", "no effect frames were sampled")
    cell = uniform_cell(chosen, 1, 2)
    sheet, atlas = pack_rows([{
        "name": _effect(ctx.asset),
        "frames": chosen,
        "fps": _fps(ctx.asset),
        "loop": True,
    }], cell)
    atlas["meta"]["image"] = "sheet.png"
    atlas["meta"]["blend"] = _blend(ctx.asset)
    return _store(ctx, sheet, atlas, chosen, {
        "frames": len(chosen),
        "blend": _blend(ctx.asset),
        "sizePx": size,
    })


class VfxGenerator:
    """One effect clip on black, packed as an additive or alpha sheet."""

    kind = "vfx"

    def estimate(self, _game: dict, _asset: dict) -> dict[str, int]:
        return {"h3": 1}

    def run(self, ctx: GenContext) -> AttemptResult:
        return _run(ctx)
