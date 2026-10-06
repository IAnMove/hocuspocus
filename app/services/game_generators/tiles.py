"""Tile and 3×3 platform tileset generators.

A tile is painted, rolled so the seam sits in the middle, inpainted, then
unrolled. One extra pass runs when the seam error stays above 1.5. The
tileset cuts nine named cells and heals the center with the same roll.
"""
from __future__ import annotations

import json

import numpy as np
from PIL import Image

from services.game_generators.base import AttemptResult, GenContext, attempt_dir
from services.game_image_ops import crop_figure
from services.game_pixel import to_pixel
from services.game_prompts import build, screen_for
from services.game_tiles import roll_half, seam_error, seam_mask, slice_grid, unroll
from services.game_tools import file_ref, image, key, resolve_path

_NAMES = ("tl", "t", "tr", "l", "c", "r", "bl", "b", "br")
_PAIRS = (("tl", "t"), ("t", "tr"), ("l", "c"), ("c", "r"), ("bl", "b"), ("b", "br"))
# Qwen-Image-2.1 inpaint at 128x128 mismatches vision slots (latent 128 vs mask 320).
# The 1024x1024 inpaint path is the one that completes.
_HEAL_SIDE = 1024


def _seed(asset: dict) -> int:
    return int((asset.get("spec") or {}).get("seed") or 1)


def _size(game: dict, asset: dict) -> int:
    spec = asset.get("spec") or {}
    pixel = (game.get("style") or {}).get("pixel") or {}
    return int(spec.get("sizePx") or pixel.get("tile") or 16)


def _load(ctx: GenContext, path) -> np.ndarray:
    file = resolve_path(ctx, path)
    with Image.open(file) as opened:
        return np.asarray(opened.convert("RGBA"))


def _save(path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(array, dtype=np.uint8)).save(path)


def _post(style: dict, rgba: np.ndarray, screen: str) -> np.ndarray:
    pixel = style.get("pixel") or {}
    if not pixel.get("enabled"):
        return rgba
    dither = pixel.get("dither")
    flag = False if dither in (None, "none", False, 0) else True
    return to_pixel(rgba, 1, list(style.get("palette") or []) or None, str(pixel.get("outline") or "none"), flag, int(pixel.get("colors") or 16))


def _square(rgba: np.ndarray, size: int) -> np.ndarray:
    resampling = Image.Resampling.BOX
    return np.asarray(Image.fromarray(rgba).resize((int(size), int(size)), resampling))


def _heal(ctx, step, rgba, prompt, negative, resolution, seed, axes) -> tuple[np.ndarray, float]:
    rolled = roll_half(np.asarray(rgba), axes)
    folder = attempt_dir(ctx)
    folder.mkdir(parents=True, exist_ok=True)
    guide = folder / f"{step}-guide.png"
    mask_path = folder / f"{step}-mask.png"
    _save(guide, rolled)
    band = max(2, min(int(rolled.shape[0]), int(rolled.shape[1])) // 8)
    _save(mask_path, seam_mask(int(rolled.shape[1]), int(rolled.shape[0]), band, axes))
    workspace = folder.parents[3]
    healed_files = image(
        ctx, step, prompt=prompt, negative=negative, resolution=resolution, seed=seed,
        guide=file_ref(ctx, str(guide.relative_to(workspace))),
        mask=file_ref(ctx, str(mask_path.relative_to(workspace))),
    )
    healed = unroll(_load(ctx, healed_files[0]), axes)
    return healed, float(seam_error(healed, axes))


def _heal_until(ctx, rgba, prompt, negative, resolution, seed, axes, step: str = "seam") -> tuple[np.ndarray, float, list]:
    healed, error = _heal(ctx, step, rgba, prompt, negative, resolution, seed, axes)
    if error > 1.5:
        healed, error = _heal(ctx, f"{step}-b", healed, prompt, negative, resolution, seed, axes)
    warnings = []
    if error > 1.5:
        warnings.append({"code": "seam_visible", "message": f"seam error {error:.3f} is above 1.5"})
    return healed, error, warnings


def _edge(left: np.ndarray, right: np.ndarray) -> float:
    wrap = np.abs(left[:, -1, :3].astype(np.float32) - right[:, 0, :3].astype(np.float32)).mean()
    interior = np.abs(np.diff(left[:, 1:-1, :3].astype(np.float32), axis=1)).mean() if left.shape[1] > 2 else 0.0
    return float(wrap / max(float(interior), 1e-6))


class TileGenerator:
    kind = "tile"

    def estimate(self, game: dict, asset: dict) -> dict[str, int]:
        return {"image": 2}

    def run(self, ctx: GenContext) -> AttemptResult:
        prompt, negative = build(ctx.game, ctx.asset, chroma=False)
        seed = _seed(ctx.asset)
        raw = image(ctx, "texture", prompt=prompt, negative=negative, resolution="1024x1024", seed=seed)
        healed, error, warnings = _heal_until(ctx, _load(ctx, raw[0]), prompt, negative, "1024x1024", seed, (0, 1))
        size = _size(ctx.game, ctx.asset)
        placed = _post(ctx.game.get("style") or {}, _square(healed, size), "magenta")
        folder = attempt_dir(ctx)
        main = folder / "main.png"
        _save(main, placed)
        workspace = folder.parents[3]
        metrics = {"seamError": round(error, 4), "sizePx": size}
        return AttemptResult(
            files={"main": str(main.relative_to(workspace))},
            metrics=metrics,
            warnings=warnings,
            provenance={"steps": list(ctx.steps)},
        )


def _sheet(cells: list[np.ndarray]) -> np.ndarray:
    height, width = cells[0].shape[:2]
    canvas = np.zeros((height * 3, width * 3, cells[0].shape[2]), dtype=np.uint8)
    for index, cell in enumerate(cells):
        row, col = divmod(index, 3)
        fitted = cell if cell.shape[:2] == (height, width) else _square(cell, width)
        canvas[row * height:(row + 1) * height, col * width:(col + 1) * width] = fitted
    return canvas


def _neighbor_errors(cells: list[np.ndarray]) -> dict[str, float]:
    by_name = dict(zip(_NAMES, cells))
    return {f"{left}-{right}": round(_edge(by_name[left], by_name[right]), 4) for left, right in _PAIRS}


class TilesetGenerator:
    kind = "tileset"

    def estimate(self, game: dict, asset: dict) -> dict[str, int]:
        return {"image": 2}

    def run(self, ctx: GenContext) -> AttemptResult:
        extra = "single ground platform chunk made of a 3 by 3 grid of tiles, grass top edge, dirt body, side view game terrain"
        prompt, negative = build(ctx.game, ctx.asset, extra)
        screen = screen_for(ctx.game, ctx.asset)
        seed = _seed(ctx.asset)
        raw = image(ctx, "chunk", prompt=prompt, negative=negative, resolution="1024x1024", seed=seed)
        keyed = key(ctx, "key", raw[0], screen)
        size = _size(ctx.game, ctx.asset)
        sheet = _square(crop_figure(_load(ctx, keyed)), size * 3)
        cells = slice_grid(sheet, 3, 3)
        center, error, warnings = _heal_until(
            ctx, _square(cells[4], _HEAL_SIDE), prompt, negative, f"{_HEAL_SIDE}x{_HEAL_SIDE}", seed, (0, 1),
        )
        cells[4] = _square(center, size)
        painted = _post(ctx.game.get("style") or {}, _sheet(cells), screen)
        cells = slice_grid(painted, 3, 3)
        folder = attempt_dir(ctx)
        folder.mkdir(parents=True, exist_ok=True)
        image_path = folder / "tileset.png"
        _save(image_path, painted)
        tiles = [{"name": name, "x": (index % 3) * size, "y": (index // 3) * size, "w": size, "h": size} for index, name in enumerate(_NAMES)]
        payload = {"names": list(_NAMES), "sizePx": size, "tiles": tiles, "seams": _neighbor_errors(cells), "centerSeam": round(error, 4)}
        (folder / "tiles.json").write_text(json.dumps(payload), encoding="utf-8")
        workspace = folder.parents[3]
        return AttemptResult(
            files={"main": str(image_path.relative_to(workspace)), "tiles": str((folder / "tiles.json").relative_to(workspace))},
            metrics={"seamError": round(error, 4), "seams": payload["seams"], "sizePx": size},
            warnings=warnings,
            provenance={"steps": list(ctx.steps)},
        )
