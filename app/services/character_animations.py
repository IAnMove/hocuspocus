"""Small animations of one character: a few poses of the same figure joined into an equal-cell sprite sheet.

``app/shared/character_animations.json`` lists them (walk, run, wave, nod, point, anime expressions...). Each pose is one
Qwen picture made from the character's own picture as an identity reference, on a plain screen colour and keyed.
``pose_prompt`` builds that request; ``build_sheet`` crops the keyed poses, scales them together, stands them on one
ground line and writes the sheet that the Video 2D ``walk-cycle-sheet`` and ``character-reaction`` cards play.
The sheet keeps the contract those cards rely on: equal cells, the figure ``figure`` of a cell high, its boots (or the
bottom of a bust) on the line ``feet`` of the cell, its upper body centred.
"""
from __future__ import annotations

import json
import math
import os
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

import numpy as np
from PIL import Image

from services.character_kit_face_cleanup import CharacterKitFaceCleanupError, resolve_character_kit_image
from services.character_styles import character_style, screen_for, style_catalog

CATALOG = Path(__file__).resolve().parents[1] / "shared" / "character_animations.json"
LOOPS = ("loop", "pingpong", "once")
FACINGS = ("left", "right", "front")
REVIEW_STATES = ("pending", "approved", "rejected")
# What keeps a figure the same size from pose to pose: its height (a cycle: the framing the model drew, so a crouch stays lower than a
# stand), the width of its legs (a standing gesture: a raised hand makes it taller, not bigger, and arms hanging or raised change how
# wide the rest of the body is, but the legs do not move) or the size of its head (a bust: the model frames each pose a little
# differently, so a pose may show more of the body and a smaller head; the head is read with the face landmarks and, when they cannot
# be read, the height is used).
SCALE_BY = ("height", "base", "face")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_FRAME_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_GENERIC_BACKGROUND = ("Isolated on a plain flat solid {screen} background filling the whole image, no floor, no cast shadow, "
                       "no text, no frame. The character keeps its own colours and has no {screen} anywhere on it.")


class CharacterAnimationError(ValueError):
    """A request or a stored animation that cannot be used."""


@lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def animation(animation_id: str) -> dict[str, Any]:
    for item in catalog()["animations"]:
        if item["id"] == animation_id:
            return item
    raise KeyError(animation_id)


CUSTOM_VIEWS = {view: spec["resolution"] for view, spec in catalog()["custom"]["views"].items()}
MAX_CUSTOM_TEXT = catalog()["custom"]["maxText"]
MAX_CUSTOM_POSES = catalog()["custom"]["maxPoses"]
MAX_ANIMATIONS = catalog()["custom"]["maxAnimations"]


def _custom_pose(custom: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """An animation the author describes (a view and the words for one pose) instead of one the catalog lists."""
    view, text = custom.get("view"), " ".join(str(custom.get("text") or "").split())
    if view not in CUSTOM_VIEWS or not text or len(text) > MAX_CUSTOM_TEXT:
        raise CharacterAnimationError(f"A custom pose needs a view ({', '.join(CUSTOM_VIEWS)}) and a description of up to {MAX_CUSTOM_TEXT} characters")
    return {"view": view, "resolution": CUSTOM_VIEWS[view]}, {"prompt": text if text.endswith((".", "!", "?")) else text + "."}


def pose_prompt(animation_id: str, pose_id: str, description: str = "", style_id: str | None = None,
                screen: str | None = None, custom: dict[str, Any] | None = None) -> dict[str, str]:
    """Prompt, negative prompt, screen colour and resolution to generate one pose with the character as its reference."""
    if custom is not None:
        item, pose = _custom_pose(custom)
    else:
        item = animation(animation_id)
        pose = next((candidate for candidate in item["poses"] if candidate["id"] == pose_id), None)
    if pose is None:
        raise KeyError(pose_id)
    style = character_style(style_id) if style_id else None
    fragment = (style or {}).get("animation") or {}
    words = " ".join(str(description or "").split())
    screen = screen or screen_for(words)
    background = ((style or {}).get("background") or _GENERIC_BACKGROUND).replace("{screen}", style_catalog()["screens"][screen])
    identity = (fragment.get("identity") or catalog()["identity"]).replace("{description}", words).strip()
    identity += "" if identity.endswith((".", "!", "?", ":", ";")) else "."
    prompt = " ".join((identity, catalog()["views"][item["view"]], pose["prompt"], background))
    negative = ", ".join(part for part in (fragment.get("negative") or catalog()["negative"], catalog().get("viewNegatives", {}).get(item["view"])) if part)
    return {"prompt": prompt, "negative": negative, "screen": screen, "resolution": item["resolution"]}


def animation_def(animation_id: str, *, made: dict[str, Any] | None = None, custom: dict[str, Any] | None = None) -> dict[str, Any]:
    """What one animation is made from: the catalog's definition, the words the author gives now (``custom``: title, view and one
    text per pose), or the words the kit kept with the animation it already has (``made``, so one pose can be made again alone)."""
    if not _ID.fullmatch(str(animation_id or "")):
        raise CharacterAnimationError("An animation id is a lowercase slug")
    try:
        listed = animation(animation_id)
    except KeyError:
        listed = None
    if listed is not None:
        if custom is not None:
            raise CharacterAnimationError(f"{animation_id} is in the catalog; custom is for an animation of your own")
        return listed
    spec = catalog()["custom"]
    if custom is not None:
        view, texts = custom.get("view"), [" ".join(str(text or "").split()) for text in custom.get("poses") or []]
        title = _text(custom.get("title"), "Title", 80, required=True)
        base: dict[str, Any] = {"loop": spec["loop"], "fps": spec["fps"]}
    elif made is not None:
        view = made.get("view") if made.get("view") in spec["views"] else "bust"
        frames = [frame for frame in made.get("frames") or [] if isinstance(frame, dict)]
        if any(not str(frame.get("prompt") or "").strip() for frame in frames):
            raise CharacterAnimationError(f"{animation_id} was made without the words of its poses; describe it again with custom")
        title, texts = str(made.get("title") or animation_id), [str(frame["prompt"]) for frame in frames]
        base = {"loop": made.get("loop", spec["loop"]), "fps": made.get("fps", spec["fps"]),
                "poseIds": [frame["id"] for frame in frames], "poseLabels": [frame.get("label") or frame["id"] for frame in frames]}
    else:
        raise CharacterAnimationError(f"Unknown animation {animation_id}; to make one of your own give custom (title, view, poses)")
    if view not in spec["views"] or not 1 <= len(texts) <= MAX_CUSTOM_POSES or any(not text or len(text) > MAX_CUSTOM_TEXT for text in texts):
        raise CharacterAnimationError(f"A custom animation needs a view ({', '.join(spec['views'])}) and 1 to {MAX_CUSTOM_POSES} poses "
                                      f"of up to {MAX_CUSTOM_TEXT} characters each")
    by_view = spec["views"][view]
    ids = base.pop("poseIds", None) or [f"pose-{number}" for number in range(1, len(texts) + 1)]
    labels = base.pop("poseLabels", None) or [text[:40] for text in texts]
    poses = [{"id": pose_id, "label": {"es": label, "en": label}, "prompt": text} for pose_id, label, text in zip(ids, labels, texts)]
    return {"id": animation_id, "group": "custom", "view": view, "scaleBy": by_view["scaleBy"], "facing": by_view["facing"],
            "template": spec["template"], "resolution": by_view["resolution"], "title": {"es": title, "en": title}, "poses": poses,
            "custom": True, **base}


def _text(value: Any, label: str, maximum: int, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise CharacterAnimationError(f"{label} is required")
    if len(text) > maximum:
        raise CharacterAnimationError(f"{label} is too long")
    return text


def _source(value: Any, label: str) -> str:
    source = _text(value, label, 1200, required=True)
    if source.startswith("blob:"):
        raise CharacterAnimationError(f"{label} must be persistent, not a browser blob URL")
    return source


def _count(value: Any, label: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise CharacterAnimationError(f"{label} must be a whole number from {low} to {high}")
    return value


def _sheet(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CharacterAnimationError("An animation needs its sheet")
    cell = raw.get("cell") if isinstance(raw.get("cell"), dict) else {}
    count = _count(raw.get("count"), "Sheet count", 1, catalog()["sheet"]["maxPoses"])
    columns = _count(raw.get("columns"), "Sheet columns", 1, catalog()["sheet"]["maxPoses"])
    return {"source": _source(raw.get("source"), "Sheet source"), "count": count, "columns": columns,
            "rows": _count(raw.get("rows"), "Sheet rows", 1, catalog()["sheet"]["maxPoses"]),
            "width": _count(raw.get("width"), "Sheet width", 1, 16384), "height": _count(raw.get("height"), "Sheet height", 1, 16384),
            "cell": {"width": _count(cell.get("width"), "Cell width", 1, 16384), "height": _count(cell.get("height"), "Cell height", 1, 16384)}}


def _frames(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > catalog()["sheet"]["maxPoses"]:
        raise CharacterAnimationError("Animation frames must be a short list")
    frames = []
    for item in raw:
        if not isinstance(item, dict) or not _FRAME_ID.fullmatch(str(item.get("id") or "")):
            raise CharacterAnimationError("Every animation frame needs an id")
        frame = {"id": item["id"], "source": _source(item.get("source"), "Frame source")}
        # A pose of an animation the author described keeps its words, so it can be made again alone.
        for key, maximum in (("prompt", MAX_CUSTOM_TEXT), ("label", 80)):
            text = _text(item.get(key), f"Frame {key}", maximum)
            if text:
                frame[key] = text
        frames.append(frame)
    return frames


def normalize_animation(raw: Any, label: str = "Animation") -> dict[str, Any]:
    """One animation of a kit: its sheet, the keyed pose pictures it was joined from and how it plays."""
    if not isinstance(raw, dict):
        raise CharacterAnimationError(f"{label} must be an object")
    fps = raw.get("fps", 4)
    loop, facing = raw.get("loop", "loop"), raw.get("facing", "right")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not 1 <= fps <= 60:
        raise CharacterAnimationError(f"{label} fps must be from 1 to 60")
    if loop not in LOOPS or facing not in FACINGS or raw.get("reviewState", "pending") not in REVIEW_STATES:
        raise CharacterAnimationError(f"{label} loop, facing or review state is invalid")
    result: dict[str, Any] = {"sheet": _sheet(raw.get("sheet")), "frames": _frames(raw.get("frames")), "fps": fps, "loop": loop,
                              "facing": facing, "reviewState": raw.get("reviewState", "pending")}
    for key, maximum in (("view", 40), ("title", 80), ("prompt", 4000), ("model", 240), ("createdAt", 80)):
        text = _text(raw.get(key), f"{label} {key}", maximum)
        if text:
            result[key] = text
    if raw.get("scaleBy") is not None:
        if raw["scaleBy"] not in SCALE_BY:
            raise CharacterAnimationError(f"{label} scaleBy is one of {', '.join(SCALE_BY)}")
        result["scaleBy"] = raw["scaleBy"]
    return result


def normalize_kit_animations(raw: Any) -> dict[str, dict[str, Any]]:
    """The ``animations`` of a Character Kit, by animation id (a catalog id, or a slug of the author's own)."""
    if not isinstance(raw, dict) or len(raw) > MAX_ANIMATIONS:
        raise CharacterAnimationError(f"Character Kit animations must be an object with at most {MAX_ANIMATIONS} entries")
    for key in raw:
        if not _ID.fullmatch(str(key)):
            raise CharacterAnimationError("An animation id is a lowercase slug")
    return {key: normalize_animation(value, f"Animation {key}") for key, value in raw.items()}


def _torso_centre(figure: Image.Image, floor: int, share: float) -> float:
    """Where the upper body is, across the figure: the alpha-weighted mean of the top ``share`` of its rows. Legs and a
    swinging arm move the middle of a figure's outline; its head and trunk hold still."""
    alpha = np.asarray(figure.getchannel("A"), dtype=np.float64)
    top = np.where(alpha > floor, alpha, 0.0)[:max(1, round(figure.height * share))]
    columns = top.sum(axis=0)
    weight = columns.sum()
    return float((columns * np.arange(figure.width)).sum() / weight) if weight else figure.width / 2


def _open_pose(path: str, floor: int) -> Image.Image:
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    box = image.getchannel("A").point(lambda value: 255 if value > floor else 0).getbbox()
    if box is None:
        raise CharacterAnimationError(f"{os.path.basename(path)} has nothing in it: key it on its screen colour first")
    return image.crop(box)


def _band_width(figure: Image.Image, floor: int, top: float, bottom: float) -> float:
    """How wide the figure is in a band of its height (shares measured from the top): the 90th percentile of its rows' widths,
    so a stray boot or a bit of coat does not decide it."""
    mask = np.asarray(figure.getchannel("A")) > floor
    first = int(figure.height * top)
    widths = [int(columns[-1] - columns[0] + 1) for columns in (np.nonzero(row)[0] for row in mask[first:max(first + 1, int(figure.height * bottom))]) if len(columns)]
    return float(np.percentile(widths, 90)) if widths else 0.0


def body_measure(figure: Image.Image, floor: int, scale_by: str) -> float:
    """How big the body is in a pose, by a part of it that a gesture or an expression does not move."""
    if scale_by == "base":
        return _band_width(figure, floor, 0.8, 1.0)
    if scale_by == "face":
        return _face_size(figure)
    return float(figure.height)


def _face_size(figure: Image.Image) -> float:
    """The head's size in pixels from the face landmarks (the flat rig's), 0 when the model is not installed or finds no face."""
    from services.face_landmarks import detect
    try:
        found = detect(figure)
    except Exception:  # noqa: BLE001 - an optional CPU model: no face found is not an error
        return 0.0
    return float(found["face"]["head"]) if found else 0.0


def sheet_layout(poses: list[Image.Image], floor: int, torso: float, spec: dict[str, Any], scale_by: str = "height") -> dict[str, Any]:
    """The scale of each pose, the cell's width, each pose's torso centre and the mode really used. The model draws every pose at a
    slightly different size, so by `height` all share one scale (the tallest fills ``figure`` of a cell and a bob or a crouch is not
    flattened); by `base` or `face` each pose is scaled so its legs or its head are as big as in the others, whatever the arms and
    hands do. A part that cannot be measured in some pose (no face found) falls back to `height`."""
    measures = [body_measure(pose, floor, scale_by) for pose in poses]
    usable = scale_by != "height" and min(measures) > 0
    ratios = [float(np.median(measures)) / measure for measure in measures] if usable else [1.0] * len(poses)
    unit = spec["cellHeight"] * spec["figure"] / max(pose.height * ratio for pose, ratio in zip(poses, ratios))
    scales = [unit * ratio for ratio in ratios]
    centres = [_torso_centre(pose, floor, torso) for pose in poses]
    reach = max(max(centre, pose.width - centre) * scale for pose, centre, scale in zip(poses, centres, scales))
    return {"scales": scales, "cellWidth": math.ceil(2 * reach + spec["cellHeight"] * 0.04) // 2 * 2, "centres": centres,
            "scaleBy": scale_by if usable else "height", "measures": [round(measure, 1) for measure in measures]}


def build_sheet(sources: list[str], *, uploads_root: str, workspace_root: str, workspace: str, name: str = "animation",
                columns: int | None = None, output_dir: str | None = None, scale_by: str = "height") -> dict[str, Any]:
    """Join keyed pose pictures into one sprite sheet of equal cells, in the order given."""
    if scale_by not in SCALE_BY:
        raise CharacterAnimationError(f"scale_by is one of {', '.join(SCALE_BY)}")
    spec = catalog()["sheet"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= spec["maxPoses"]:
        raise CharacterAnimationError(f"Give 1 to {spec['maxPoses']} keyed pose pictures")
    paths = [resolve_character_kit_image(source, uploads_root=uploads_root, workspace_root=workspace_root) for source in sources]
    poses = [_open_pose(path, spec["alphaFloor"]) for path in paths]
    layout = sheet_layout(poses, spec["alphaFloor"], spec["torsoShare"], spec, scale_by)
    scales, cell_width, centres = layout["scales"], layout["cellWidth"], layout["centres"]
    cell_height = spec["cellHeight"]
    wide = max(1, min(len(poses), columns or len(poses)))
    rows = math.ceil(len(poses) / wide)
    sheet = Image.new("RGBA", (cell_width * wide, cell_height * rows), (0, 0, 0, 0))
    for index, (pose, centre, scale) in enumerate(zip(poses, centres, scales)):
        fitted = pose.resize((max(1, round(pose.width * scale)), max(1, round(pose.height * scale))), Image.Resampling.LANCZOS)
        left = (index % wide) * cell_width + round(cell_width / 2 - centre * scale)
        top = (index // wide) * cell_height + round(cell_height * spec["feet"] - fitted.height)
        layer = Image.new("RGBA", sheet.size, (0, 0, 0, 0))
        layer.paste(fitted, (left, top))
        sheet = Image.alpha_composite(sheet, layer)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "animation"
    destination_root = os.path.realpath(os.path.abspath(output_dir or workspace_root))
    os.makedirs(destination_root, exist_ok=True)
    filename = f"{stem}-sheet-{uuid.uuid4().hex[:8]}.png"
    destination = os.path.join(destination_root, filename)
    partial = f"{destination}.{os.getpid()}.partial"
    try:
        sheet.save(partial, format="PNG")
        os.replace(partial, destination)
    finally:
        if os.path.exists(partial):
            os.remove(partial)
    return {"filename": filename, "source": f"/api/v1/file/{quote(filename)}?workspace={quote(workspace)}", "path": destination,
            "width": sheet.width, "height": sheet.height, "count": len(poses), "columns": wide, "rows": rows,
            "cell": {"width": cell_width, "height": cell_height}, "feet": spec["feet"], "figure": spec["figure"], "scaleBy": layout["scaleBy"],
            "requestedScaleBy": scale_by, "measures": layout["measures"],
            "poses": [{"width": pose.width, "height": pose.height} for pose in poses]}


__all__ = ["CUSTOM_VIEWS", "CharacterAnimationError", "animation_def", "SCALE_BY", "body_measure", "CharacterKitFaceCleanupError", "animation", "build_sheet", "catalog", "normalize_animation",
           "normalize_kit_animations", "pose_prompt", "sheet_layout"]
