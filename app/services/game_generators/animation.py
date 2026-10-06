"""Sprite cycles from a MiniMax H3 clip or one Qwen strip.

``GAME_ANIMATION_DEFAULTS`` is the J0 trial table. The trial text wins where
the brief disagrees: a loop warns above 5 percent, not 0.5. Actions are not
grouped. Warnings never block the attempt.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from services.game_frames import drift_correct, extract_frames, find_cycle, key_frames, sample_frames
from services.game_generators.base import AttemptResult, GenContext, attempt_dir
from services.game_generators.still import StillGenerator
from services.game_image_ops import SCREEN_RGB, compose_start_frame, feet_point, place_on_cell, to_illustration
from services.game_library import resolve_action
from services.game_pixel import pixel_metrics, to_pixel
from services.game_prompts import build, screen_for
from services.game_sheet import pack_rows, uniform_cell, write_gif_preview
from services.game_tools import GameToolError, file_ref, image, key, resolve_path, video_fl2va


GAME_ANIMATION_DEFAULTS = {
    "model": "minimax_h3",
    "steps": 30,
    "resolution": "544x960",
    "frames": 124,
    "groupActions": False,
    "screen": "magenta",
    "chroma": "#FF00FF",
    "heightFrac": 0.62,
    "feetFrac": 0.85,
    "stripResolution": "1536x512",
    "byAction": {
        "walk": "strip",
        "run": "strip",
        "spin": "strip",
        "bob": "strip",
    },
    "warnings": {
        "loopError": 0.05,
        "identityDrift": 0.20,
        "footDrift": 0.20,
        "haloPct": 2.0,
    },
}

_STAGING = (
    "Solid flat {screen} backdrop, one uniform tone edge to edge, no gradient, "
    "no floor line, no shadow. Side view, the character faces right. "
    "Long telephoto lens, near-orthographic. The camera is locked off: no zoom, no pan, no shake."
)


def method_for(action: str, explicit: str | None = None) -> str:
    """The trial method for ``action``. An explicit ``h3`` or ``strip`` wins."""
    if explicit in ("h3", "strip"):
        return str(explicit)
    return str(GAME_ANIMATION_DEFAULTS["byAction"].get(str(action or ""), "h3"))


def animation_warnings(loop_error, identity: float, foot: float, halo_pct) -> list[str]:
    """Non-blocking warning codes. ``halo_pct`` is ``None`` when the backdrop is gone."""
    limits = GAME_ANIMATION_DEFAULTS["warnings"]
    found = []
    if loop_error is not None and float(loop_error) > float(limits["loopError"]):
        found.append("loop_not_closed")
    if float(identity) > float(limits["identityDrift"]):
        found.append("identity_drift")
    if float(foot) > float(limits["footDrift"]):
        found.append("foot_drift")
    if halo_pct is not None and float(halo_pct) > float(limits["haloPct"]):
        found.append("halo")
    return found


def split_figures(rgba) -> list[np.ndarray]:
    """Alpha blobs, left to right. Specks under 2 percent of the largest blob are dropped."""
    image = np.asarray(rgba)
    mask = (image[..., 3] > 0).astype(np.uint8)
    count, labels = cv2.connectedComponents(mask, connectivity=4)
    boxes = [box for box in (_bounds(labels, label) for label in range(1, int(count))) if box]
    kept = [box for box in boxes if _large_enough(box, boxes)]
    kept.sort(key=lambda box: box[0])
    return [image[y0:y1, x0:x1].copy() for x0, y0, x1, y1 in kept]


def _bounds(labels, label: int):
    ys, xs = np.nonzero(labels == label)
    if len(xs) == 0:
        return None
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def _large_enough(box, boxes) -> bool:
    area = (box[2] - box[0]) * (box[3] - box[1])
    largest = max((item[2] - item[0]) * (item[3] - item[1]) for item in boxes)
    return area >= max(4, int(largest * 0.02))


def _spec(asset: dict) -> dict:
    spec = asset.get("spec")
    return spec if isinstance(spec, dict) else {}


def _anim(asset: dict) -> dict:
    anim = _spec(asset).get("anim")
    return anim if isinstance(anim, dict) else {}


def _action_name(asset: dict) -> str:
    return str(_anim(asset).get("action") or _spec(asset).get("action") or "idle")


def _frame_count(asset: dict) -> int:
    value = _anim(asset).get("frames", _spec(asset).get("frames", 6))
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 6


def _fps(asset: dict) -> int:
    spec = _spec(asset)
    if spec.get("fps"):
        return max(1, int(spec["fps"]))
    action = resolve_action(_action_name(asset))
    if action and action.get("fps"):
        return max(1, int(action["fps"]))
    return 8


def _loops(asset: dict) -> bool:
    spec = _spec(asset)
    if "loop" in spec:
        return bool(spec.get("loop"))
    action = resolve_action(_action_name(asset))
    return bool(action.get("loop")) if action else True


def _animated_item(asset: dict) -> bool:
    return bool(_anim(asset))


def _beat(asset: dict) -> str:
    action = resolve_action(_action_name(asset))
    if action and action.get("beat"):
        return str(action["beat"])
    return _action_name(asset)


def _closed_stance(asset: dict) -> bool:
    action = resolve_action(_action_name(asset))
    if action is None:
        return True
    return bool(action.get("endsInStance", True))


def _note(asset: dict) -> str:
    text = ""
    for attempt in asset.get("attempts") or []:
        if attempt.get("decision") == "rejected" and str(attempt.get("note") or "").strip():
            text = str(attempt["note"]).strip()
    return text


def _screen(ctx: GenContext) -> str:
    return screen_for(ctx.game, ctx.asset)


def _seed(ctx: GenContext) -> int:
    try:
        return int(_spec(ctx.asset).get("seed") or 1)
    except (TypeError, ValueError):
        return 1


def _character(ctx: GenContext):
    wanted = str(_spec(ctx.asset).get("character") or "")
    if not wanted:
        return None
    for asset in ctx.game.get("assets") or []:
        if asset.get("id") == wanted:
            return asset
    return None


def _approved_attempt(asset):
    if not isinstance(asset, dict) or asset.get("status") != "approved":
        return None
    attempt_id = asset.get("approvedAttemptId")
    for attempt in asset.get("attempts") or []:
        if attempt.get("id") == attempt_id and attempt.get("status") == "ok":
            return attempt
    return None


def _art(ctx: GenContext) -> dict:
    character = _character(ctx)
    attempt = _approved_attempt(character)
    files = (attempt or {}).get("files") or {}
    raw = files.get("rawKey") or files.get("main")
    metrics = (attempt or {}).get("metrics") if isinstance((attempt or {}).get("metrics"), dict) else {}
    return {"character": character, "raw": raw, "metrics": metrics or {}, "main": files.get("main")}


def _open_rgba(ctx: GenContext, path) -> np.ndarray:
    with Image.open(resolve_path(ctx, path)) as opened:
        return np.asarray(opened.convert("RGBA"))


def _relative(ctx: GenContext, path: Path) -> str:
    root = Path(ctx.workspace_dir(ctx.workspace))
    return str(path.relative_to(root))


def _canvas(resolution: str) -> tuple[int, int]:
    width, height = str(resolution).lower().split("x", 1)
    return int(width), int(height)


def _h3_prompt(beat: str, screen: str, note: str) -> str:
    lines = [
        "[STYLE] The output matches the first frame exactly: same character, colors, proportions and line work. The style never drifts.",
        "[STAGING] " + _STAGING.format(screen=screen),
        f"[ACTION] {beat}",
        "[AUDIO] Silence.",
    ]
    if note:
        lines.append(f"Fix: {note}")
    return "\n".join(lines)


def _strip_prompt(asset: dict, screen: str, note: str) -> str:
    text = (
        f"{_frame_count(asset)} frames of {_beat(asset)} in a single row, evenly spaced, "
        f"same character, side view, flat {screen} background"
    )
    return f"{text}. Fix: {note}" if note else text


def _opaque_height(frame) -> int:
    rows = np.nonzero((np.asarray(frame)[..., 3] > 128).any(axis=1))[0]
    if len(rows) == 0:
        return max(1, int(np.asarray(frame).shape[0]))
    return max(1, int(rows[-1] - rows[0] + 1))


def _target_height(ctx: GenContext, art: dict) -> int:
    character = art.get("character") or {}
    spec = character.get("spec") if isinstance(character.get("spec"), dict) else {}
    if spec.get("heightPx"):
        return max(1, int(spec["heightPx"]))
    own = _spec(ctx.asset)
    if own.get("sizePx"):
        return max(1, int(own["sizePx"]))
    pixel = ((ctx.game.get("style") or {}).get("pixel") or {})
    return max(1, int(pixel.get("spriteHeight") or 48))


def _one_scale(metrics: dict, first, height_px: int) -> float:
    """One multiplier for every frame. The approved character scale wins when it is set."""
    recorded = metrics.get("scale")
    if isinstance(recorded, (int, float)) and not isinstance(recorded, bool) and float(recorded) > 0:
        return float(recorded)
    return float(height_px) / float(_opaque_height(first))


def _palette(style: dict, metrics: dict) -> list[str]:
    recorded = metrics.get("palette")
    if isinstance(recorded, list) and recorded:
        return [str(item) for item in recorded]
    colors = style.get("palette")
    if isinstance(colors, list) and colors:
        return [str(item) for item in colors]
    return []


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


def _scaled(frame, scale: float, pixel_on: bool) -> np.ndarray:
    if abs(float(scale) - 1.0) < 1e-6:
        return np.asarray(frame)
    image = Image.fromarray(np.asarray(frame, dtype=np.uint8))
    width = max(1, int(round(image.width * float(scale))))
    height = max(1, int(round(image.height * float(scale))))
    resampling = Image.Resampling.NEAREST if pixel_on else Image.Resampling.LANCZOS
    return np.asarray(image.resize((width, height), resampling))


def _paint(frame, style: dict, palette: list[str], screen: str, pixel_on: bool) -> np.ndarray:
    if not pixel_on:
        return to_illustration(frame, _opaque_height(frame), screen)
    pixel = style.get("pixel") or {}
    return to_pixel(
        frame, 1, palette or None, str(pixel.get("outline") or "none"),
        _dither(pixel), int(pixel.get("colors") or 16),
    )


def _on_cell(frame, cell: tuple[int, int]) -> np.ndarray:
    width, height = int(cell[0]), int(cell[1])
    feet_x, feet_y = feet_point(frame)
    return place_on_cell(frame, (width, height), (width / 2.0, float(height - 1)), (feet_x, feet_y))


def _mean_delta(left, right) -> float:
    first = np.asarray(left)
    other = np.asarray(right)
    if first.shape != other.shape:
        resized = Image.fromarray(other).resize((first.shape[1], first.shape[0]), Image.Resampling.BOX)
        other = np.asarray(resized)
    mask = (first[..., 3] > 128) | (other[..., 3] > 128)
    if not np.any(mask):
        return 0.0
    delta = np.abs(first[..., :3].astype(np.int16) - other[..., :3].astype(np.int16))
    return float(delta[mask].mean() / 255.0)


def _foot_span(frames) -> float:
    if len(frames) < 2:
        return 0.0
    xs = [feet_point(frame)[0] for frame in frames]
    width = max(1, int(np.asarray(frames[0]).shape[1]))
    return float(max(xs) - min(xs)) / float(width)


def _corners_match(frame, screen: str) -> bool:
    image = np.asarray(frame)
    if image.ndim != 3 or image.shape[2] < 3:
        return False
    if image.shape[2] > 3 and int(image[0, 0, 3]) < 250:
        return False
    color = np.array(SCREEN_RGB.get(screen, SCREEN_RGB["magenta"]), dtype=np.int16)
    corners = (image[0, 0, :3], image[0, -1, :3], image[-1, 0, :3], image[-1, -1, :3])
    return all(int(np.max(np.abs(np.asarray(pixel, dtype=np.int16) - color))) <= 12 for pixel in corners)


def _halo_pct(raw_frame, keyed_frame, screen: str, palette: list[str]):
    if raw_frame is None or keyed_frame is None or not _corners_match(raw_frame, screen):
        return None
    return float(pixel_metrics(keyed_frame, palette or ["#000000"], screen)["haloPct"])


def _pick(frames, asset: dict):
    count = _frame_count(asset)
    if _loops(asset) and len(frames) >= 2:
        start, length, error = find_cycle(frames, _fps(asset))
        return sample_frames(frames, start, max(length, 1), count), float(error)
    return sample_frames(frames, 0, max(len(frames), 1), count), None


def _measure(chosen, loop_error, raw_mid, keyed_mid, screen: str, palette: list[str]):
    identity = _mean_delta(chosen[0], chosen[len(chosen) // 2]) if chosen else 0.0
    foot = _foot_span(chosen)
    halo = _halo_pct(raw_mid, keyed_mid, screen, palette)
    return animation_warnings(loop_error, identity, foot, halo), {
        "loopError": loop_error,
        "identityDrift": identity,
        "footDrift": foot,
        "haloPct": halo,
    }


def _grid(style: dict) -> int:
    pixel = style.get("pixel") or {}
    if not pixel.get("enabled"):
        return 1
    return max(1, int(pixel.get("tile") or 1))


def _base_sprite(ctx: GenContext, art: dict):
    if not art.get("main"):
        return None
    try:
        return _open_rgba(ctx, art["main"])
    except OSError:
        return None


def _remove_frames(folder: Path) -> None:
    if not folder.is_dir():
        return
    for path in folder.glob("[0-9][0-9][0-9][0-9].png"):
        path.unlink()
    try:
        folder.rmdir()
    except OSError:
        return


def _store(ctx: GenContext, sheet, atlas: dict, frames, metrics: dict, warnings: list[str]) -> AttemptResult:
    folder = attempt_dir(ctx)
    folder.mkdir(parents=True, exist_ok=True)
    sheet_path = folder / "sheet.png"
    atlas_path = folder / "sheet.json"
    gif_path = folder / "preview.gif"
    sheet.save(sheet_path)
    atlas["meta"]["image"] = "sheet.png"
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
    return AttemptResult(files=files, metrics=metrics, warnings=warnings, provenance={"steps": list(ctx.steps)})


def _pack(ctx: GenContext, frames, art: dict, warnings: list[str], measured: dict) -> AttemptResult:
    if not frames:
        raise GameToolError("empty_clip", "no frames were sampled")
    style = ctx.game.get("style") or {}
    pixel_on = bool((style.get("pixel") or {}).get("enabled"))
    screen = _screen(ctx)
    palette = _palette(style, art.get("metrics") or {})
    scale = _one_scale(art.get("metrics") or {}, frames[0], _target_height(ctx, art))
    painted = [_paint(_scaled(frame, scale, pixel_on), style, palette, screen, pixel_on) for frame in frames]
    sources = list(painted)
    base = _base_sprite(ctx, art)
    if base is not None:
        sources.append(base)
    cell = uniform_cell(sources, _grid(style), 1)
    placed = [_on_cell(frame, cell) for frame in painted]
    sheet, atlas = pack_rows([{
        "name": _action_name(ctx.asset),
        "frames": placed,
        "fps": _fps(ctx.asset),
        "loop": _loops(ctx.asset),
    }], cell)
    metrics = {
        **measured,
        "palette": palette,
        "scale": scale,
        "method": "strip" if _uses_strip(ctx.asset) else "h3",
        "frames": len(placed),
    }
    return _store(ctx, sheet, atlas, placed, metrics, warnings)


def _uses_strip(asset: dict) -> bool:
    if _animated_item(asset) or asset.get("kind") == "item":
        return True
    explicit = _spec(asset).get("method")
    return method_for(_action_name(asset), explicit if explicit in ("h3", "strip") else None) == "strip"


def _write_start(ctx: GenContext, art: dict) -> str:
    if not art.get("raw"):
        raise GameToolError("missing_character", "the approved character has no image")
    screen = _screen(ctx)
    size = _canvas(str(GAME_ANIMATION_DEFAULTS["resolution"]))
    frame = compose_start_frame(
        _open_rgba(ctx, art["raw"]), size, screen,
        float(GAME_ANIMATION_DEFAULTS["heightFrac"]), float(GAME_ANIMATION_DEFAULTS["feetFrac"]),
    )
    folder = attempt_dir(ctx)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "start.png"
    Image.fromarray(np.asarray(frame, dtype=np.uint8)).save(path)
    return file_ref(ctx, _relative(ctx, path))


def _render_h3(ctx: GenContext, start_ref: str) -> str:
    screen = _screen(ctx)
    prompt = _h3_prompt(_beat(ctx.asset), screen, _note(ctx.asset))
    end = start_ref if _closed_stance(ctx.asset) else None
    video = video_fl2va(
        ctx, "clip", prompt=prompt, start=start_ref, end=end,
        frames=int(GAME_ANIMATION_DEFAULTS["frames"]),
        model=str(GAME_ANIMATION_DEFAULTS["model"]),
        resolution=str(GAME_ANIMATION_DEFAULTS["resolution"]),
        steps=int(GAME_ANIMATION_DEFAULTS["steps"]),
    )
    start = attempt_dir(ctx) / "start.png"
    if start.is_file():
        start.unlink()
    return video


def _open_rgb(path) -> np.ndarray:
    with Image.open(path) as opened:
        return np.asarray(opened.convert("RGB"))


def _run_h3(ctx: GenContext) -> AttemptResult:
    art = _art(ctx)
    start = _write_start(ctx, art)
    video = _render_h3(ctx, start)
    extracted = extract_frames(video, 0, 60, attempt_dir(ctx) / "frames")
    if not extracted:
        raise GameToolError("empty_clip", "the clip has no frames")
    screen = _screen(ctx)
    raw_mid = _open_rgb(extracted[len(extracted) // 2])
    keyed = key_frames(extracted, screen)
    chosen, loop_error = _pick(keyed, ctx.asset)
    if not chosen:
        raise GameToolError("empty_clip", "no frames were sampled")
    palette = _palette(ctx.game.get("style") or {}, art.get("metrics") or {})
    warnings, measured = _measure(chosen, loop_error, raw_mid, keyed[len(keyed) // 2], screen, palette)
    return _pack(ctx, drift_correct(chosen), art, warnings, measured)


def _refs(ctx: GenContext, art: dict) -> list[str]:
    raw = art.get("raw")
    if not raw:
        return []
    file = resolve_path(ctx, raw)
    root = Path(ctx.workspace_dir(ctx.workspace))
    try:
        return [str(file.relative_to(root))]
    except ValueError:
        return [str(file)]


def _run_strip(ctx: GenContext) -> AttemptResult:
    art = _art(ctx)
    screen = _screen(ctx)
    _built, negative = build(ctx.game, ctx.asset)
    raws = image(
        ctx, "strip", prompt=_strip_prompt(ctx.asset, screen, _note(ctx.asset)), negative=negative,
        resolution=str(GAME_ANIMATION_DEFAULTS["stripResolution"]), refs=_refs(ctx, art), seed=_seed(ctx),
    )
    pre = _open_rgba(ctx, raws[0])
    post = _open_rgba(ctx, key(ctx, "strip-key", raws[0], screen))
    figures = split_figures(post)
    if not figures:
        raise GameToolError("empty_strip", "the strip did not contain a figure")
    requested = _frame_count(ctx.asset)
    warnings = ["strip_count_mismatch"] if len(figures) < requested else []
    chosen = figures[:requested]
    palette = _palette(ctx.game.get("style") or {}, art.get("metrics") or {})
    extra, measured = _measure(chosen, None, pre, post, screen, palette)
    measured["stripFigures"] = len(figures)
    return _pack(ctx, drift_correct(chosen), art, warnings + extra, measured)


class AnimationGenerator:
    """One action. ``h3`` is a clip. ``strip`` is a single wide still."""

    kind = "animation"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        copies = _spec(asset).get("candidates") or asset.get("candidates") or 1
        count = copies if isinstance(copies, int) and copies > 0 else 1
        family = "image" if _uses_strip(asset) else "h3"
        return {family: count}

    def run(self, ctx: GenContext) -> AttemptResult:
        if _uses_strip(ctx.asset):
            return _run_strip(ctx)
        return _run_h3(ctx)


class ItemGenerator:
    """A still item, or a spinning or bobbing strip when ``spec.anim`` is set."""

    kind = "item"

    def estimate(self, game: dict, asset: dict) -> dict[str, int]:
        if _animated_item(asset):
            return {"image": 1}
        return StillGenerator("item").estimate(game, asset)

    def run(self, ctx: GenContext) -> AttemptResult:
        if _animated_item(ctx.asset):
            return _run_strip(ctx)
        return StillGenerator("item").run(ctx)
