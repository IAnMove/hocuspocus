"""Still generators for characters, sprites, items, icons and UI elements.

Each candidate is its own attempt directory (``a1``, ``a2``, ``a3``). The
full-resolution crop is ``raw-key.png``. ``main.png`` is the cell, and a pixel
style also writes a nearest-neighbor ``preview.png``.
"""
from __future__ import annotations

import json

import numpy as np
from PIL import Image

from services.game_generators.base import AttemptResult, GenContext, candidate_dirs
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


def _opaque_height(rgba: np.ndarray) -> int:
    rows = np.nonzero((rgba[..., 3] > 128).any(axis=1))[0]
    if len(rows) == 0:
        return max(1, int(rgba.shape[0]))
    return max(1, int(rows[-1] - rows[0] + 1))


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


def _render(cropped: np.ndarray, style: dict, screen: str, target_h: int) -> tuple[np.ndarray, list[str], bool]:
    pixel = style.get("pixel") or {}
    palette, free = _palette(style, cropped)
    if not pixel.get("enabled"):
        return to_illustration(cropped, target_h, screen), palette, free
    factor = max(1, int(round(_opaque_height(cropped) / float(max(1, target_h)))))
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


def _metrics(kind: str, style: dict, cropped: np.ndarray, palette: list[str], free: bool, screen: str, height: int) -> dict:
    measured = dict(pixel_metrics(cropped, palette or ["#000000"], screen))
    if kind == "character" and free:
        measured["palette"] = list(palette)
        measured["scale"] = float(height) / float(_opaque_height(cropped))
    if not (style.get("pixel") or {}).get("enabled"):
        measured["colors"] = measured.get("colors", 0)
    return measured


def _write_attempt(ctx, kind, folder, attempt_id, raw, screen, width, height) -> dict:
    style = ctx.game.get("style") or {}
    keyed = key(ctx, f"key-{attempt_id}", raw, screen)
    cropped = crop_figure(_load(ctx, keyed))
    target_h = max(1, height - max(1, height // 16))
    rendered, palette, free = _render(cropped, style, screen, target_h)
    placed = _place(kind, rendered, width, height)
    folder.mkdir(parents=True, exist_ok=True)
    raw_path = folder / "raw-key.png"
    main_path = folder / "main.png"
    preview_path = folder / "preview.png"
    _save(raw_path, cropped)
    _save(main_path, placed)
    preview = preview_nearest(placed, 4) if (style.get("pixel") or {}).get("enabled") else placed
    _save(preview_path, preview)
    root = folder.parents[3]
    files = {
        "main": str(main_path.relative_to(root)),
        "preview": str(preview_path.relative_to(root)),
        "rawKey": str(raw_path.relative_to(root)),
    }
    if kind == "ui":
        margins = nine_slice_margins(placed)
        (folder / "nine.json").write_text(json.dumps(margins), encoding="utf-8")
        files["nine"] = str((folder / "nine.json").relative_to(root))
    metrics = _metrics(kind, style, cropped, palette, free, screen, height)
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
        seed = int((ctx.asset.get("spec") or {}).get("seed") or 1)
        raws = image(
            ctx, "still", prompt=prompt, negative=negative, resolution=resolution,
            refs=refs_for(ctx.game, ctx.asset), seed=seed, batch=count,
        )
        width, height = _frame(self.kind, ctx.game, ctx.asset)
        written = [
            _write_attempt(ctx, self.kind, folder, attempt_id, raw, screen, width, height)
            for (attempt_id, folder), raw in zip(candidate_dirs(ctx, len(raws)), raws)
        ]
        first = written[0]
        metrics = {**first["metrics"], "attemptIds": [item["id"] for item in written]}
        return AttemptResult(
            files=first["files"], metrics=metrics, warnings=[], provenance={"steps": list(ctx.steps)},
        )
