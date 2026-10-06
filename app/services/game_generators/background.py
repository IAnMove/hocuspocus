"""Background layers. Separate is the default because the layered model is not installed.

Every layer is painted full frame with its own seed (``spec.seed`` plus the
layer index) and a depth phrase (far, middle, near). When ``loopX`` is on, the
raw frame is scaled to 1024 square, healed on the horizontal seam (the Qwen
inpaint size that completes), and scaled back. Layer 0 is the opaque sky. A
later layer is keyed after the heal, scaled to the frame, cut to its visible
rows and placed at the bottom of a transparent frame. Parallax factors are
0.1, 0.3, 0.6 and 1.0, and the last layer is always 1.0.
"""
from __future__ import annotations

import json

import numpy as np
from PIL import Image

from services.game_generators.base import AttemptResult, GenContext, attempt_dir, relative, spec_seed
from services.game_generators.tiles import _HEAL_SIDE, _heal_until, _load, _post, _resize, _save, _square
from services.game_image_ops import clean_alpha, despill
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
    return np.asarray(Image.fromarray(np.asarray(rgba, dtype=np.uint8)).resize((width, height), resampling))


def _to_bottom(rgba: np.ndarray) -> np.ndarray:
    """Cut the visible rows (full width, so the loop holds) and set them on the bottom edge."""
    cleaned = clean_alpha(rgba)
    rows = np.nonzero((cleaned[..., 3] > 128).any(axis=1))[0]
    if len(rows) == 0:
        return cleaned
    band = cleaned[int(rows[0]):int(rows[-1]) + 1]
    canvas = np.zeros_like(cleaned)
    canvas[canvas.shape[0] - band.shape[0]:] = band
    return canvas


def _depth(factor: float) -> str:
    if factor >= 1.0:
        return "near foreground layer, large shapes"
    if factor >= 0.6:
        return "middle distance layer, medium shapes"
    return "far distance layer, small hazy shapes"


def _spec(asset: dict) -> dict:
    return asset.get("spec") or {}


def _loops(asset: dict) -> bool:
    return bool(_spec(asset).get("loopX", True))


class BackgroundGenerator:
    kind = "background"

    def estimate(self, game: dict, asset: dict) -> dict[str, int]:
        layers = max(1, int(_spec(asset).get("layers") or 3))
        return {"image": layers * (2 if _loops(asset) else 1)}

    def run(self, ctx: GenContext) -> AttemptResult:
        method = str(_spec(ctx.asset).get("method") or "separate")
        if method == "layered" and not _installed(ctx):
            raise GameToolError("model_not_installed", _LAYERED_MODEL)
        return _separate(ctx)


def _layer_prompt(ctx: GenContext, index: int, factor: float, screen: str) -> tuple[str, str]:
    if index == 0:
        return build(ctx.game, ctx.asset, "wide open sky, full frame, no characters", chroma=False)
    return build(ctx.game, ctx.asset, f"{_depth(factor)}, silhouette band on flat {screen} backdrop, aligned to the bottom")


def _heal_frame(ctx, index, picture, prompt, negative, seed) -> tuple[np.ndarray, float, list]:
    """Heal the raw full frame at 1024 square, then scale it back to its own size."""
    height, width = picture.shape[:2]
    healed, error, warnings = _heal_until(
        ctx, _square(picture, _HEAL_SIDE), prompt, negative, f"{_HEAL_SIDE}x{_HEAL_SIDE}", seed, (1,), step=f"seam-{index}",
    )
    return _resize(healed, width, height), error, warnings


def _layer(ctx: GenContext, index: int, factor: float, frame: dict) -> tuple[np.ndarray, float | None, list]:
    """One layer at frame size: painted, healed when it loops, then keyed unless it is the sky."""
    prompt, negative = _layer_prompt(ctx, index, factor, frame["screen"])
    seed = frame["seed"] + index
    raw = image(ctx, f"layer-{index}", prompt=prompt, negative=negative, resolution=frame["resolution"], seed=seed)
    source, picture, error, warnings = raw[0], None, None, []
    if frame["loop"]:
        picture, error, warnings = _heal_frame(ctx, index, _load(ctx, raw[0]), prompt, negative, seed)
        source = frame["folder"] / f"layer-{index}-healed.png"
        _save(source, picture)
    if index == 0:
        sky = picture if picture is not None else _load(ctx, source)
        return _post(frame["style"], _fit(sky, frame["width"], frame["height"], frame["style"]), "magenta"), error, warnings
    keyed = _load(ctx, key(ctx, f"key-{index}", str(source), frame["screen"]))
    fitted = despill(_fit(keyed, frame["width"], frame["height"], frame["style"]), frame["screen"])
    return _post(frame["style"], _to_bottom(fitted), "magenta"), error, warnings


def _frame(ctx: GenContext) -> dict:
    spec = _spec(ctx.asset)
    width = int(spec.get("widthPx") or 640)
    height = int(spec.get("heightPx") or 360)
    folder = attempt_dir(ctx)
    folder.mkdir(parents=True, exist_ok=True)
    return {
        "width": width,
        "height": height,
        "resolution": f"{_snap(width, 1024)}x{_snap(height, 512)}",
        "screen": screen_for(ctx.game, ctx.asset),
        "seed": spec_seed(ctx.asset),
        "style": ctx.game.get("style") or {},
        "loop": _loops(ctx.asset),
        "folder": folder,
    }


def _separate(ctx: GenContext) -> AttemptResult:
    frame = _frame(ctx)
    folder = frame["folder"]
    layers = max(1, int(_spec(ctx.asset).get("layers") or 3))
    written = []
    warnings = []
    for index, factor in enumerate(parallax_for(layers)):
        name = f"layer-{index}.png"
        picture, error, found = _layer(ctx, index, factor, frame)
        warnings.extend({**item, "file": name} for item in found)
        _save(folder / name, picture)
        seam = None if error is None else round(float(error), 4)
        written.append({"file": name, "factor": factor, "seamError": seam})
    (folder / "parallax.json").write_text(json.dumps({"layers": written}), encoding="utf-8")
    files = {item["file"]: relative(ctx, folder / item["file"]) for item in written}
    files["parallax"] = relative(ctx, folder / "parallax.json")
    return AttemptResult(files=files, metrics={"layers": written}, warnings=warnings, provenance={"steps": list(ctx.steps)})
