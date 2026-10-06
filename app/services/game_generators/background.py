"""Background layers. Separate is the default because the layered model is not installed.

Each layer is healed on the horizontal seam, then scaled to the frame. Parallax
factors are 0.1, 0.3, 0.6 and 1.0, and the last layer is always 1.0.
"""
from __future__ import annotations

import json

import numpy as np
from PIL import Image

from services.game_generators.base import AttemptResult, GenContext, attempt_dir
from services.game_generators.tiles import _heal_until, _load, _post, _save
from services.game_image_ops import crop_figure
from services.game_prompts import build, screen_for
from services.game_tools import GameToolError, image, key

_LAYERED_MODEL = "qwen_image_layered_20B"


def parallax_for(count: int) -> list[float]:
    """Leading factors from 0.1 / 0.3 / 0.6, then a foreground of 1.0."""
    count = max(1, int(count))
    if count == 1:
        return [1.0]
    head = [0.1, 0.3, 0.6]
    while len(head) < count - 1:
        head.append(0.6)
    return head[: count - 1] + [1.0]


def _snap(value, default: int) -> int:
    number = int(value or default)
    return max(32, int(round(number / 32.0) * 32))


def _installed(ctx: GenContext) -> bool:
    listed = ctx.call("media.options", {"version": 1, "input": {"workspace": ctx.workspace}})
    return _LAYERED_MODEL in json.dumps(listed)


def _fit(rgba: np.ndarray, width: int, height: int, style: dict) -> np.ndarray:
    pixel = bool((style.get("pixel") or {}).get("enabled"))
    resampling = Image.Resampling.BOX if pixel else Image.Resampling.LANCZOS
    resized = np.asarray(Image.fromarray(np.asarray(rgba, dtype=np.uint8)).resize((width, height), resampling))
    return _post(style, resized, "magenta")


class BackgroundGenerator:
    kind = "background"

    def estimate(self, game: dict, asset: dict) -> dict[str, int]:
        layers = max(1, int((asset.get("spec") or {}).get("layers") or 3))
        return {"image": layers * 2}

    def run(self, ctx: GenContext) -> AttemptResult:
        method = str((ctx.asset.get("spec") or {}).get("method") or "separate")
        if method == "layered" and not _installed(ctx):
            raise GameToolError("model_not_installed", _LAYERED_MODEL)
        return _separate(ctx)


def _layer_prompt(ctx: GenContext, index: int, screen: str) -> tuple[str, str]:
    if index == 0:
        return build(ctx.game, ctx.asset, "wide open sky, full frame, no characters", chroma=False)
    return build(ctx.game, ctx.asset, f"silhouette band on flat {screen} backdrop, aligned to the bottom")


def _layer_image(ctx, index, prompt, negative, resolution, seed, screen):
    raw = image(ctx, f"layer-{index}", prompt=prompt, negative=negative, resolution=resolution, seed=seed)
    if index == 0:
        return _load(ctx, raw[0])
    keyed = key(ctx, f"key-{index}", raw[0], screen)
    return crop_figure(_load(ctx, keyed))


def _separate(ctx: GenContext) -> AttemptResult:
    spec = ctx.asset.get("spec") or {}
    layers = max(1, int(spec.get("layers") or 3))
    width = int(spec.get("widthPx") or 640)
    height = int(spec.get("heightPx") or 360)
    resolution = f"{_snap(width, 1024)}x{_snap(height, 512)}"
    screen = screen_for(ctx.game, ctx.asset)
    seed = int(spec.get("seed") or 1)
    style = ctx.game.get("style") or {}
    folder = attempt_dir(ctx)
    folder.mkdir(parents=True, exist_ok=True)
    workspace = folder.parents[3]
    written = []
    warnings = []
    for index, factor in enumerate(parallax_for(layers)):
        prompt, negative = _layer_prompt(ctx, index, screen)
        picture = _layer_image(ctx, index, prompt, negative, resolution, seed, screen)
        healed, error, heal_warnings = _heal_until(
            ctx, picture, prompt, negative, resolution, seed, (1,), step=f"seam-{index}",
        )
        warnings.extend(heal_warnings)
        _save(folder / f"layer-{index}.png", _fit(healed, width, height, style))
        written.append({"file": f"layer-{index}.png", "factor": factor, "seamError": round(float(error), 4)})
    (folder / "parallax.json").write_text(json.dumps({"layers": written}), encoding="utf-8")
    files = {item["file"]: str((folder / item["file"]).relative_to(workspace)) for item in written}
    files["parallax"] = str((folder / "parallax.json").relative_to(workspace))
    return AttemptResult(files=files, metrics={"layers": written}, warnings=warnings, provenance={"steps": list(ctx.steps)})
