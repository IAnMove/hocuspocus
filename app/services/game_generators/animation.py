"""Sprite cycles from a MiniMax H3 clip or one Qwen strip.

``GAME_ANIMATION_DEFAULTS`` is the J0 trial table. The trial text wins where
the brief disagrees: a loop warns above 5 percent, not 0.5. Actions are not
grouped. Warnings never block the attempt.

Every frame of an attempt gets one scale, measured on its first frame. H3
frames share one locked-off stage, so they share one placement and a jump
keeps its height. Strip figures share the strip's ground line and are centered
on their own feet. ``asset.candidates`` gives several candidates, as
``base.candidate_dirs`` lays them out.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from services.game_frames import drift_correct, extract_frames, find_cycle, key_frames, sample_frames
from services.game_generators.base import (
    AttemptResult, GenContext, attempt_dir, candidate_dirs, candidate_result, relative, seed_for_step, spec_seed,
)
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

# MiniMax H3 renders 24 frames per second. Used when the clip does not say.
_CLIP_FPS = 24.0

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


def animation_warnings(loop_error, identity: float, foot, halo_pct) -> list[str]:
    """Non-blocking warning codes. ``foot`` and ``halo_pct`` are ``None`` when they do not apply."""
    limits = GAME_ANIMATION_DEFAULTS["warnings"]
    found = []
    if loop_error is not None and float(loop_error) > float(limits["loopError"]):
        found.append("loop_not_closed")
    if float(identity) > float(limits["identityDrift"]):
        found.append("identity_drift")
    if foot is not None and float(foot) > float(limits["footDrift"]):
        found.append("foot_drift")
    if halo_pct is not None and float(halo_pct) > float(limits["haloPct"]):
        found.append("halo")
    return found


def clip_size() -> tuple[int, int]:
    """``(width, height)`` of the H3 canvas."""
    width, height = str(GAME_ANIMATION_DEFAULTS["resolution"]).lower().split("x", 1)
    return int(width), int(height)


def candidate_count(asset: dict) -> int:
    """``asset.candidates`` (a production job may set it), else one."""
    try:
        return max(1, int(asset.get("candidates") or 1))
    except (TypeError, ValueError):
        return 1


def candidate_step(name: str, index: int, count: int) -> str:
    """The tool step of candidate ``index``. One candidate keeps the plain name and its intent id."""
    return name if count == 1 else f"{name}-a{index}"


def render_clip(ctx: GenContext, step: str, *, prompt: str, start: str, end: str | None) -> Path:
    """One H3 first-and-last-frame clip. The tool answers a workspace file name, so it is resolved here."""
    video = video_fl2va(
        ctx, step, prompt=prompt, start=start, end=end,
        frames=int(GAME_ANIMATION_DEFAULTS["frames"]),
        model=str(GAME_ANIMATION_DEFAULTS["model"]),
        resolution=str(GAME_ANIMATION_DEFAULTS["resolution"]),
        steps=int(GAME_ANIMATION_DEFAULTS["steps"]), seed=seed_for_step(ctx.asset, step),
    )
    return resolve_path(ctx, video)


def clip_frames(video: Path, folder: Path) -> list[Path]:
    """Every frame of ``video`` as ``folder/frames/NNNN.png``. An empty clip is an error."""
    extracted = extract_frames(video, 0, 60, folder / "frames")
    if not extracted:
        raise GameToolError("empty_clip", "the clip has no frames")
    return extracted


def write_sheet(ctx: GenContext, folder: Path, sheet, atlas: dict, frames, fps: int) -> dict:
    """Save ``sheet.png``, ``sheet.json`` and ``preview.gif``, then drop the extracted frames.

    Returns the attempt ``files``, relative to the workspace.
    """
    folder.mkdir(parents=True, exist_ok=True)
    sheet_path = folder / "sheet.png"
    atlas_path = folder / "sheet.json"
    gif_path = folder / "preview.gif"
    sheet.save(sheet_path)
    atlas["meta"]["image"] = sheet_path.name
    atlas_path.write_text(json.dumps(atlas), encoding="utf-8")
    write_gif_preview(frames, fps, 1, gif_path)
    _remove_frames(folder / "frames")
    sheet_ref = relative(ctx, sheet_path)
    return {"main": sheet_ref, "sheet": sheet_ref, "atlas": relative(ctx, atlas_path), "preview": relative(ctx, gif_path)}


def fold_candidates(ctx: GenContext, written: list[dict]) -> AttemptResult:
    """``base.candidate_result``; each candidate keeps its own ``warnings``."""
    return candidate_result(written, [], ctx.steps)


def split_figures(rgba) -> list[np.ndarray]:
    """Figures left to right, cropped to the strip's common rows so they keep one ground line.

    Specks under 2 percent of the largest blob are dropped. Blobs whose columns
    overlap are one figure, so a detached head, hand or sword stays with its body.
    """
    image = np.asarray(rgba)
    mask = (image[..., 3] > 0).astype(np.uint8)
    count, _labels, stats, _centers = cv2.connectedComponentsWithStats(mask, connectivity=4)
    boxes = [(int(x), int(y), int(x + w), int(y + h)) for x, y, w, h in stats[1:int(count), :4]]
    kept = _merge_columns([box for box in boxes if _large_enough(box, boxes)])
    if not kept:
        return []
    top = min(box[1] for box in kept)
    bottom = max(box[3] for box in kept)
    return [image[top:bottom, x0:x1].copy() for x0, _y0, x1, _y1 in kept]


def _merge_columns(boxes) -> list[tuple[int, int, int, int]]:
    merged: list[tuple[int, int, int, int]] = []
    for box in sorted(boxes):
        if merged and box[0] < merged[-1][2]:
            last = merged[-1]
            merged[-1] = (last[0], min(last[1], box[1]), max(last[2], box[2]), max(last[3], box[3]))
        else:
            merged.append(box)
    return merged


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


def _wish(asset: dict) -> str:
    """The asset description when it says more than an action name such as ``idle`` or ``andar``."""
    text = " ".join(str(asset.get("description") or "").split())
    return "" if not text or resolve_action(text) else text


def _character(ctx: GenContext):
    wanted = str(_spec(ctx.asset).get("character") or "")
    if not wanted:
        return None
    for asset in ctx.game.get("assets") or []:
        if asset.get("id") == wanted:
            return asset
    return None


def _screen(ctx: GenContext) -> str:
    """The backdrop. The character's description counts too, so a green figure gets magenta."""
    words = [str(item.get("description") or "") for item in (_character(ctx) or {}, ctx.asset)]
    return screen_for(ctx.game, {**ctx.asset, "description": " ".join(words)})


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


def _open_rgb(path) -> np.ndarray:
    with Image.open(path) as opened:
        return np.asarray(opened.convert("RGB"))


def _h3_prompt(asset: dict, screen: str) -> str:
    wish = _wish(asset)
    note = _note(asset)
    lines = [
        "[STYLE] The output matches the first frame exactly: same character, colors, proportions and line work. The style never drifts.",
        "[STAGING] " + _STAGING.format(screen=screen),
        f"[ACTION] {_beat(asset)}. {wish}" if wish else f"[ACTION] {_beat(asset)}",
        "[AUDIO] Silence.",
    ]
    if note:
        lines.append(f"Fix: {note}")
    return "\n".join(lines)


def _strip_prompt(ctx: GenContext, screen: str) -> str:
    """Style traits, what is drawn (the character or the item), the cycle, the facing and the backdrop."""
    asset = ctx.asset
    figure = "object" if asset.get("kind") == "item" else "character"
    note = _note(asset)
    parts = [
        str((ctx.game.get("style") or {}).get("traits") or ""),
        str((_character(ctx) or {}).get("description") or ""),
        _wish(asset),
        f"{_frame_count(asset)} frames of {_beat(asset)} in a single row, evenly spaced",
        f"the same {figure} in every frame",
        "side view, facing right" if figure == "character" else "",
        f"flat solid {screen} background, no shadow, no floor",
        f"Fix: {note}" if note else "",
    ]
    return ", ".join(part.strip() for part in parts if part.strip())


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


def _resized(frame, scale: float, screen: str, pixel_on: bool) -> np.ndarray:
    """The whole frame times ``scale``. Illustration resizes premultiplied and despills; pixel art box-filters."""
    source = np.asarray(frame, dtype=np.uint8)
    height = max(1, round(source.shape[0] * float(scale)))
    if not pixel_on:
        return to_illustration(source, height, screen)
    width = max(1, round(source.shape[1] * float(scale)))
    if (width, height) == (source.shape[1], source.shape[0]):
        return source
    return np.asarray(Image.fromarray(source).resize((width, height), Image.Resampling.BOX))


def _pixelated(frame, style: dict, palette: list[str]) -> np.ndarray:
    pixel = style.get("pixel") or {}
    return to_pixel(
        frame, 1, palette or None, str(pixel.get("outline") or "none"),
        _dither(pixel), int(pixel.get("colors") or 16),
    )


def _painted(ctx: GenContext, frames, art: dict) -> tuple[list[np.ndarray], list[str], float]:
    """Every frame at one scale, the first frame's opaque height to the sprite height, then the style."""
    style = ctx.game.get("style") or {}
    pixel_on = bool((style.get("pixel") or {}).get("enabled"))
    palette = _palette(style, art.get("metrics") or {})
    scale = float(_target_height(ctx, art)) / float(_opaque_height(frames[0]))
    screen = _screen(ctx)
    resized = [_resized(frame, scale, screen, pixel_on) for frame in frames]
    if not pixel_on:
        return resized, palette, scale
    return [_pixelated(frame, style, palette) for frame in resized], palette, scale


def _feet(frames, shared_stage: bool) -> list[tuple[float, float]]:
    """One feet point per frame. A clip keeps the first frame's; a strip keeps its common ground line."""
    points = [feet_point(frame) for frame in frames]
    if shared_stage:
        return [points[0]] * len(points)
    ground = max(point[1] for point in points)
    return [(x, ground) for x, _y in points]


def _placed(frames, cell: tuple[int, int], shared_stage: bool) -> list[np.ndarray]:
    width, height = int(cell[0]), int(cell[1])
    pivot = (width / 2.0, float(height - 1))
    return [place_on_cell(frame, (width, height), pivot, feet) for frame, feet in zip(frames, _feet(frames, shared_stage))]


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


def _measure(chosen, loop_error, halo, shared_stage: bool):
    """Warnings and metrics. Foot drift only exists on a shared stage: strip figures are each centered."""
    identity = _mean_delta(chosen[0], chosen[len(chosen) // 2]) if chosen else 0.0
    foot = _foot_span(chosen) if shared_stage else None
    return animation_warnings(loop_error, identity, foot, halo), {
        "loopError": loop_error,
        "identityDrift": identity,
        "footDrift": foot,
        "haloPct": halo,
    }


def _spread(frames, count: int, loops: bool) -> list:
    """``count`` frames at even steps. A loop leaves out the closing frame; a one-shot ends on the last frame."""
    if loops or count < 2 or len(frames) < 2:
        return sample_frames(frames, 0, len(frames), count)
    last = len(frames) - 1
    return [frames[round(index * last / (count - 1))] for index in range(count)]


def _clip_fps(video) -> float:
    capture = cv2.VideoCapture(str(video))
    try:
        rate = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    finally:
        capture.release()
    return rate if 0.0 < rate <= 240.0 else _CLIP_FPS


def _pick(frames, asset: dict, clip_fps: float):
    """``(frames, loopError, cycleFrames)``. The loop period is searched in clip frames, at the clip's rate."""
    count = _frame_count(asset)
    if _loops(asset) and len(frames) >= 2:
        start, length, error = find_cycle(frames, clip_fps)
        return sample_frames(frames, start, max(length, 1), count), float(error), int(length)
    return _spread(frames, count, False), None, None


def _grid(style: dict) -> int:
    pixel = style.get("pixel") or {}
    if not pixel.get("enabled"):
        return 1
    return max(1, int(pixel.get("tile") or 1))


def _base_sprite(ctx: GenContext, art: dict) -> list[np.ndarray]:
    if not art.get("main"):
        return []
    try:
        return [_open_rgba(ctx, art["main"])]
    except OSError:
        return []


def _remove_frames(folder: Path) -> None:
    if not folder.is_dir():
        return
    for path in folder.glob("[0-9][0-9][0-9][0-9].png"):
        path.unlink()
    try:
        folder.rmdir()
    except OSError:
        return


def _finish(ctx: GenContext, slot: tuple[str, Path], frames, art: dict, report: tuple[list, dict], shared_stage: bool) -> dict:
    """Paint, place, pack and store one candidate as ``{"id", "files", "metrics", "warnings"}``."""
    attempt_id, folder = slot
    warnings, measured = report
    if not frames:
        raise GameToolError("empty_clip", "no frames were sampled")
    painted, palette, scale = _painted(ctx, frames, art)
    cell = uniform_cell(painted + _base_sprite(ctx, art), _grid(ctx.game.get("style") or {}), 1)
    placed = _placed(painted, cell, shared_stage)
    sheet, atlas = pack_rows([{
        "name": _action_name(ctx.asset),
        "frames": placed,
        "fps": _fps(ctx.asset),
        "loop": _loops(ctx.asset),
    }], cell)
    atlas["meta"]["mirror"] = bool(_spec(ctx.asset).get("mirror", True))
    metrics = {
        **measured,
        "palette": palette,
        "scale": scale,
        "method": "h3" if shared_stage else "strip",
        "frames": len(placed),
    }
    files = write_sheet(ctx, folder, sheet, atlas, placed, _fps(ctx.asset))
    return {"id": attempt_id, "files": files, "metrics": metrics, "warnings": list(warnings)}


def _uses_strip(asset: dict) -> bool:
    if _animated_item(asset) or asset.get("kind") == "item":
        return True
    explicit = _spec(asset).get("method")
    return method_for(_action_name(asset), explicit if explicit in ("h3", "strip") else None) == "strip"


def _write_start(ctx: GenContext, art: dict, screen: str) -> str:
    if not art.get("raw"):
        raise GameToolError("missing_character", "the approved character has no image")
    frame = compose_start_frame(
        _open_rgba(ctx, art["raw"]), clip_size(), screen,
        float(GAME_ANIMATION_DEFAULTS["heightFrac"]), float(GAME_ANIMATION_DEFAULTS["feetFrac"]),
    )
    folder = attempt_dir(ctx)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "start.png"
    Image.fromarray(np.asarray(frame, dtype=np.uint8)).save(path)
    return file_ref(ctx, relative(ctx, path))


def _h3_candidate(ctx: GenContext, art: dict, screen: str, start: str, slot: tuple[str, Path], step: str) -> dict:
    end = start if _closed_stance(ctx.asset) else None
    video = render_clip(ctx, step, prompt=_h3_prompt(ctx.asset, screen), start=start, end=end)
    extracted = clip_frames(video, slot[1])
    keyed = key_frames(extracted, screen)
    chosen, loop_error, cycle = _pick(keyed, ctx.asset, _clip_fps(video))
    if not chosen:
        raise GameToolError("empty_clip", "no frames were sampled")
    middle = len(keyed) // 2
    palette = _palette(ctx.game.get("style") or {}, art.get("metrics") or {})
    halo = _halo_pct(_open_rgb(extracted[middle]), keyed[middle], screen, palette)
    warnings, measured = _measure(chosen, loop_error, halo, True)
    measured["cycleFrames"] = cycle
    return _finish(ctx, slot, drift_correct(chosen), art, (warnings, measured), True)


def _run_h3(ctx: GenContext) -> AttemptResult:
    art = _art(ctx)
    screen = _screen(ctx)
    slots = candidate_dirs(ctx, candidate_count(ctx.asset))
    start = _write_start(ctx, art, screen)
    try:
        written = [
            _h3_candidate(ctx, art, screen, start, slot, candidate_step("clip", index, len(slots)))
            for index, slot in enumerate(slots, start=1)
        ]
    finally:
        (attempt_dir(ctx) / "start.png").unlink(missing_ok=True)
    return fold_candidates(ctx, written)


def _refs(ctx: GenContext, art: dict) -> list[str]:
    raw = art.get("raw")
    if not raw:
        return []
    file = resolve_path(ctx, raw)
    try:
        return [relative(ctx, file)]
    except ValueError:
        return [str(file)]


def _strip_candidate(ctx: GenContext, art: dict, screen: str, raw: str, slot: tuple[str, Path], step: str) -> dict:
    pre = _open_rgba(ctx, raw)
    post = _open_rgba(ctx, key(ctx, step, raw, screen))
    figures = split_figures(post)
    if not figures:
        raise GameToolError("empty_strip", "the strip did not contain a figure")
    requested = _frame_count(ctx.asset)
    warnings = [] if len(figures) == requested else ["strip_count_mismatch"]
    chosen = _spread(figures, requested, _loops(ctx.asset)) if len(figures) > requested else figures
    palette = _palette(ctx.game.get("style") or {}, art.get("metrics") or {})
    extra, measured = _measure(chosen, None, _halo_pct(pre, post, screen, palette), False)
    measured["stripFigures"] = len(figures)
    return _finish(ctx, slot, chosen, art, (warnings + extra, measured), False)


def _run_strip(ctx: GenContext) -> AttemptResult:
    art = _art(ctx)
    screen = _screen(ctx)
    _prompt, negative = build(ctx.game, ctx.asset)
    raws = image(
        ctx, "strip", prompt=_strip_prompt(ctx, screen), negative=negative,
        resolution=str(GAME_ANIMATION_DEFAULTS["stripResolution"]), refs=_refs(ctx, art),
        seed=spec_seed(ctx.asset), batch=candidate_count(ctx.asset),
    )
    slots = candidate_dirs(ctx, len(raws))
    written = [
        _strip_candidate(ctx, art, screen, raw, slot, candidate_step("strip-key", index, len(slots)))
        for index, (slot, raw) in enumerate(zip(slots, raws), start=1)
    ]
    return fold_candidates(ctx, written)


class AnimationGenerator:
    """One action. ``h3`` is a clip per candidate. ``strip`` is one batched Qwen job."""

    kind = "animation"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        family = "image" if _uses_strip(asset) else "h3"
        return {family: candidate_count(asset)}

    def run(self, ctx: GenContext) -> AttemptResult:
        if _uses_strip(ctx.asset):
            return _run_strip(ctx)
        return _run_h3(ctx)


class ItemGenerator:
    """A still item, or a spinning or bobbing strip when ``spec.anim`` is set."""

    kind = "item"

    def estimate(self, game: dict, asset: dict) -> dict[str, int]:
        if _animated_item(asset):
            return {"image": candidate_count(asset)}
        return StillGenerator("item").estimate(game, asset)

    def run(self, ctx: GenContext) -> AttemptResult:
        if _animated_item(ctx.asset):
            return _run_strip(ctx)
        return StillGenerator("item").run(ctx)
