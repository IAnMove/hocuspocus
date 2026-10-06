"""Still generators for characters, sprites, items, icons and UI elements.

Several candidates are ``<attemptId>-a1``, ``-a2``... in the folders ``a1``,
``a2``... of the attempt directory. The full-resolution crop is
``raw-key.png``. ``main.png`` is the cell, and a pixel style also writes a
nearest-neighbor ``preview.png``. The figure is scaled so its opaque box fits
the cell in both directions, so a wide item is not clipped.
"""
from __future__ import annotations

import json

import numpy as np
from PIL import Image

from services.game_generators.base import (
    AttemptResult, GenContext, candidate_dirs, candidate_result, relative, spec_seed,
)
from services.game_image_ops import crop_figure, feet_point, place_on_cell, to_illustration
from services.game_pixel import median_cut, pixel_metrics, preview_nearest, to_pixel
from services.game_prompts import build, refs_for, screen_for
from services.game_tiles import nine_slice_margins
from services.game_tools import image, key, resolve_path

_DEFAULT_CANDIDATES = {"character": 3, "sprite": 2, "item": 3, "icon": 3, "ui": 2}


def _count(kind: str, asset: dict) -> int:
    if asset.get("candidates"):
        return max(1, int(asset["candidates"]))
    return _DEFAULT_CANDIDATES.get(kind, 1)


def _frame(kind: str, game: dict, asset: dict) -> tuple[int, int]:
    spec = asset.get("spec") or {}
    pixel = ((game.get("style") or {}).get("pixel") or {})
    if kind in {"character", "sprite"}:
        height = int(spec.get("heightPx") or pixel.get("spriteHeight") or 48)
        return height, height
    if kind == "ui":
        height = int(spec.get("heightPx") or 32)
        return int(spec.get("widthPx") or height), height
    size = int(spec.get("sizePx") or 32)
    return size, size


def _extent(opaque: np.ndarray, axis: int, fallback: int) -> int:
    found = np.nonzero(opaque.any(axis=axis))[0]
    if len(found) == 0:
        return max(1, int(fallback))
    return max(1, int(found[-1] - found[0] + 1))


def _opaque_height(rgba: np.ndarray) -> int:
    return _extent(rgba[..., 3] > 128, 1, rgba.shape[0])


def _fit_ratio(rgba: np.ndarray, target_w: int, target_h: int) -> float:
    """Downscale ratio that fits the opaque box inside ``target_w`` by ``target_h``."""
    opaque = rgba[..., 3] > 128
    height = _extent(opaque, 1, rgba.shape[0])
    width = _extent(opaque, 0, rgba.shape[1])
    return max(height / float(max(1, target_h)), width / float(max(1, target_w)))


def _dither(pixel: dict):
    value = pixel.get("dither")
    if value in (None, "none", False, 0, "0"):
        return False
    if value in (True, "ordered", "bayer"):
        return True
    try:
        return float(value)
    except (TypeError, ValueError):
        return False


def _palette(style: dict, cropped: np.ndarray) -> tuple[list[str], bool]:
    pixel = style.get("pixel") or {}
    colors = int(pixel.get("colors") or 16)
    free = style.get("paletteMode") == "free" or not style.get("palette")
    if free:
        return median_cut(cropped, colors), True
    return [str(item) for item in style.get("palette") or []], False


def _render(cropped: np.ndarray, style: dict, screen: str, target: tuple[int, int]) -> tuple[np.ndarray, list[str], bool]:
    pixel = style.get("pixel") or {}
    palette, free = _palette(style, cropped)
    ratio = _fit_ratio(cropped, target[0], target[1])
    if not pixel.get("enabled"):
        return to_illustration(cropped, max(1, int(round(cropped.shape[0] / ratio))), screen), palette, free
    factor = max(1, int(round(ratio)))
    rendered = to_pixel(
        cropped, factor, palette or None, str(pixel.get("outline") or "none"),
        _dither(pixel), int(pixel.get("colors") or 16),
    )
    return rendered, palette, free


def _load(ctx: GenContext, path) -> np.ndarray:
    file = resolve_path(ctx, path)
    with Image.open(file) as opened:
        return np.asarray(opened.convert("RGBA"))


def _save(path, rgba: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(rgba, dtype=np.uint8)).save(path)


def _place(kind: str, rendered: np.ndarray, width: int, height: int) -> np.ndarray:
    if kind == "ui":
        resampling = Image.Resampling.BOX
        return np.asarray(Image.fromarray(rendered).resize((width, height), resampling))
    if kind in {"character", "sprite"}:
        pad = max(1, height // 16)
        feet_x, feet_y = feet_point(rendered)
        return place_on_cell(rendered, (width, height), (width / 2.0, float(height - pad)), (feet_x, feet_y))
    center = ((rendered.shape[1] - 1) / 2.0, (rendered.shape[0] - 1) / 2.0)
    return place_on_cell(rendered, (width, height), (width / 2.0, height / 2.0), center)


def _metrics(kind: str, cropped: np.ndarray, palette: list[str], free: bool, screen: str, height: int) -> dict:
    measured = dict(pixel_metrics(cropped, palette or ["#000000"], screen))
    if kind == "character" and free:
        measured["palette"] = list(palette)
        measured["scale"] = float(height) / float(_opaque_height(cropped))
    return measured


def _write_attempt(ctx, kind, folder, attempt_id, raw, screen, width, height) -> dict:
    style = ctx.game.get("style") or {}
    keyed = key(ctx, f"key-{attempt_id}", raw, screen)
    cropped = crop_figure(_load(ctx, keyed))
    pad = max(1, height // 16)
    rendered, palette, free = _render(cropped, style, screen, (max(1, width - pad), max(1, height - pad)))
    placed = _place(kind, rendered, width, height)
    folder.mkdir(parents=True, exist_ok=True)
    raw_path = folder / "raw-key.png"
    main_path = folder / "main.png"
    preview_path = folder / "preview.png"
    _save(raw_path, cropped)
    _save(main_path, placed)
    preview = preview_nearest(placed, 4) if (style.get("pixel") or {}).get("enabled") else placed
    _save(preview_path, preview)
    files = {
        "main": relative(ctx, main_path),
        "preview": relative(ctx, preview_path),
        "rawKey": relative(ctx, raw_path),
    }
    if kind == "ui":
        margins = nine_slice_margins(placed)
        (folder / "nine.json").write_text(json.dumps(margins), encoding="utf-8")
        files["nine"] = relative(ctx, folder / "nine.json")
    metrics = _metrics(kind, cropped, palette, free, screen, height)
    (folder / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return {"id": attempt_id, "files": files, "metrics": metrics}


class StillGenerator:
    """Qwen still, keyed and fitted to the cell for one asset kind."""

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def estimate(self, game: dict, asset: dict) -> dict[str, int]:
        return {"image": _count(self.kind, asset)}

    def run(self, ctx: GenContext) -> AttemptResult:
        prompt, negative = build(ctx.game, ctx.asset)
        screen = screen_for(ctx.game, ctx.asset)
        count = _count(self.kind, ctx.asset)
        resolution = "768x1024" if self.kind in {"character", "sprite"} else "1024x1024"
        seed = spec_seed(ctx.asset)
        raws = image(
            ctx, "still", prompt=prompt, negative=negative, resolution=resolution,
            refs=refs_for(ctx.game, ctx.asset), seed=seed, batch=count,
        )
        width, height = _frame(self.kind, ctx.game, ctx.asset)
        written = [
            _write_attempt(ctx, self.kind, folder, attempt_id, raw, screen, width, height)
            for (attempt_id, folder), raw in zip(candidate_dirs(ctx, len(raws)), raws)
        ]
        return candidate_result(written, [], ctx.steps)
