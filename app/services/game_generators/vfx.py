"""Visual effects: a MiniMax clip on black, keyed by the brightest channel.

The sheet is one row named after the asset id. ``blend: add`` keeps the color
on black and records ``blend`` on the atlas. Every frame is cut from one square
around the effect, so it keeps its proportions, and box-filtered down to
``sizePx``. A pad around the effect leaves the cell border clear.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from services.game_frames import sample_frames, vfx_alpha
from services.game_generators.animation import (
    candidate_count, candidate_step, clip_frames, clip_size, fold_candidates, render_clip, write_sheet,
)
from services.game_generators.base import AttemptResult, GenContext, attempt_dir, candidate_dirs, relative
from services.game_sheet import pack_rows, uniform_cell
from services.game_tools import GameToolError, file_ref

# Alpha below this is compression noise on the black backdrop, not the effect.
_VISIBLE = 8


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
    width, height = clip_size()
    folder = attempt_dir(ctx)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "black.png"
    Image.fromarray(np.zeros((height, width, 3), dtype=np.uint8)).save(path)
    return file_ref(ctx, relative(ctx, path))


def _open_rgb(path) -> np.ndarray:
    with Image.open(path) as opened:
        return np.asarray(opened.convert("RGB"))


def _content_box(frames) -> tuple[int, int, int, int] | None:
    """Union box of the visible effect over ``frames``; ``None`` when nothing is visible."""
    visible = np.zeros(np.asarray(frames[0]).shape[:2], dtype=bool)
    for frame in frames:
        visible |= np.asarray(frame)[..., 3] >= _VISIBLE
    ys, xs = np.nonzero(visible)
    if len(xs) == 0:
        return None
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def _square(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """``box`` grown to a square around its center."""
    x0, y0, x1, y1 = box
    side = max(x1 - x0, y1 - y0)
    left = x0 - (side - (x1 - x0)) // 2
    top = y0 - (side - (y1 - y0)) // 2
    return (left, top, left + side, top + side)


def _fit(frame, square: tuple[int, int, int, int], size: int) -> np.ndarray:
    """Cut ``square`` (transparent outside the frame) and box-filter it to ``size``."""
    cut = Image.fromarray(np.asarray(frame, dtype=np.uint8)).crop(square)
    return np.asarray(cut.resize((size, size), Image.Resampling.BOX))


def _candidate(ctx: GenContext, black: str, slot: tuple[str, Path], step: str) -> dict:
    attempt_id, folder = slot
    video = render_clip(ctx, step, prompt=_prompt(ctx.asset), start=black, end=black)
    keyed = vfx_alpha([_open_rgb(path) for path in clip_frames(video, folder)])
    if not keyed:
        raise GameToolError("empty_vfx", "the effect clip is empty")
    chosen = sample_frames(keyed, 0, len(keyed), _count(ctx.asset))
    box = _content_box(chosen)
    if box is None:
        raise GameToolError("empty_vfx", "the effect clip is empty")
    size = _size(ctx.asset)
    fitted = [_fit(frame, _square(box), size) for frame in chosen]
    sheet, atlas = pack_rows([{
        "name": str(ctx.asset.get("id") or "effect"),
        "frames": fitted,
        "fps": _fps(ctx.asset),
        "loop": True,
    }], uniform_cell(fitted, 1, 2), anchor="center")
    atlas["meta"]["blend"] = _blend(ctx.asset)
    files = write_sheet(ctx, folder, sheet, atlas, fitted, _fps(ctx.asset))
    metrics = {"frames": len(fitted), "blend": _blend(ctx.asset), "sizePx": size}
    return {"id": attempt_id, "files": files, "metrics": metrics, "warnings": []}


def _run(ctx: GenContext) -> AttemptResult:
    slots = candidate_dirs(ctx, candidate_count(ctx.asset))
    black = _black_ref(ctx)
    try:
        written = [
            _candidate(ctx, black, slot, candidate_step("vfx", index, len(slots)))
            for index, slot in enumerate(slots, start=1)
        ]
    finally:
        (attempt_dir(ctx) / "black.png").unlink(missing_ok=True)
    return fold_candidates(ctx, written)


class VfxGenerator:
    """One effect clip on black per candidate, packed as an additive or alpha sheet."""

    kind = "vfx"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        return {"h3": candidate_count(asset)}

    def run(self, ctx: GenContext) -> AttemptResult:
        return _run(ctx)
