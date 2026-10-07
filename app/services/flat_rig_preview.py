"""Preview a pose's warp mouths at a mouth line, without saving anything (the Face Rig mouth editor, MCP).

The editor moves a point on the mouth line and a width handle and shows the warped states as they would be rigged:
the same line placement (``flat_rig_warp.mouth_line``, from the point, else the saved hint, else the landmarks or the
rig's painted mouth) and the same patches. Saving is a re-rig with the point as the pose's hint
(``characters.rig.flat`` ``hints``), so what the preview shows is what the rig makes.

Landmarks are cached per image file, so dragging only warps (a few tens of milliseconds a state).
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import threading
from collections import OrderedDict
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from services import face_landmarks, flat_rig_warp
from services.character_kit_library import read_character_kit_library
from services.flat_rig import (
    FlatRigError, _figure_box, _pose_guides, _saved_hints, _url, _workspace_file, pose_source, rig_hints, rig_pose,
)
from services.flat_rig_base import INK, STATES
from services.flat_rig_look import rig_style

# What the editor shows by default: rest, then the vowels i, e, a, o, u.
PREVIEW_STATES = ("closed", "small", "medium", "wide", "round", "pucker")
TILE = 256
BACKDROP = (42, 42, 46, 255)
_CACHE: OrderedDict[tuple, Any] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_SIZE = 32


def _landmarks(path: str, image: Image.Image):
    """``face_landmarks.detect`` for a pose file, remembered while the file is unchanged."""
    stat = os.stat(path)
    key = (os.path.realpath(path), stat.st_mtime_ns, stat.st_size)
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    found = face_landmarks.detect(image)
    with _CACHE_LOCK:
        _CACHE[key] = found
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return found


def _states(value: Any) -> tuple[str, ...]:
    if value is None:
        return PREVIEW_STATES
    if not isinstance(value, list) or not value or len(value) > len(STATES) or any(state not in STATES for state in value):
        raise FlatRigError("invalid_states", f"states must list mouth states: {', '.join(STATES)}")
    return tuple(dict.fromkeys(value))


def _hint(kit: dict[str, Any], pose: str, mouth: Any, width: Any) -> dict[str, Any] | None:
    """The asked point and width (validated like rig hints) over the pose's saved hint; the saved one alone without them."""
    saved = _saved_hints(kit).get(pose) or {}
    asked = {key: value for key, value in (("mouth", mouth), ("mouthWidth", width)) if value is not None}
    if not asked:
        return saved or None
    # The editor's point is placed by a person looking at the face: shown where it is, as a save keeps it (exact).
    return {**saved, **(rig_hints({pose: asked})[pose] or {}), **({"exact": True} if "mouth" in asked else {})}


def _view(line: flat_rig_warp.MouthLine) -> tuple[int, int, int, int]:
    """The face around the mouth the tiles show: the lips, the chin and what moves, square."""
    cx, cy = line.centre
    w = line.width
    return int(round(cx - 1.3 * w)), int(round(cy - 0.9 * w)), int(round(cx + 1.3 * w)), int(round(cy + 1.7 * w))


def _over(canvas: Image.Image, image: Image.Image, x: int, y: int) -> None:
    """``image`` composited over ``canvas`` with its top-left corner at (x, y), clipped to the canvas."""
    left, top = max(0, x), max(0, y)
    right, bottom = min(canvas.width, x + image.width), min(canvas.height, y + image.height)
    if right > left and bottom > top:
        canvas.alpha_composite(image, (left, top), (left - x, top - y, right - x, bottom - y))


def _tile(figure: Image.Image, patch: Image.Image, box, view) -> Image.Image:
    x0, y0, _side = box
    canvas = Image.new("RGBA", (view[2] - view[0], view[3] - view[1]), BACKDROP)
    _over(canvas, figure, -view[0], -view[1])
    _over(canvas, patch, x0 - view[0], y0 - view[1])
    return canvas.resize((TILE, TILE), Image.LANCZOS)


def _data_url(tile: Image.Image) -> str:
    buffer = io.BytesIO()
    tile.convert("RGB").save(buffer, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _sheet(tiles: dict[str, Image.Image]) -> Image.Image:
    sheet = Image.new("RGB", (TILE * len(tiles), TILE + 22), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    for index, (state, tile) in enumerate(tiles.items()):
        sheet.paste(tile.convert("RGB"), (index * TILE, 22))
        draw.text((index * TILE + 6, 5), state, fill=(30, 30, 30))
    return sheet


def _save_sheet(sheet: Image.Image, workspace_dir: str, workspace: str, name: str) -> str:
    """One preview sheet per pose, written over the last (a dot file: the media library does not list it)."""
    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG")
    data = buffer.getvalue()
    temporary = os.path.join(workspace_dir, f"{name}.{os.getpid()}.tmp")
    with open(temporary, "wb") as handle:
        handle.write(data)
    os.replace(temporary, os.path.join(workspace_dir, name))
    return f"{_url(name, workspace)}&v={hashlib.sha256(data).hexdigest()[:8]}"


def _percent(points: np.ndarray, frame) -> list[list[float]]:
    left, top, width, height = frame
    return [[round(float(x + left) / width * 100, 3), round(float(y + top) / height * 100, 3)] for x, y in points]


def preview_mouth(workspace_dir: str, workspace: str, kit_id: str, pose: str, *, mouth: Any = None, mouth_width: Any = None,
                  states: Any = None, sheet: bool = False) -> dict[str, Any]:
    """The warped states of ``pose`` at the mouth line through ``mouth`` (``[x, y]`` in % of the pose image) and
    ``mouth_width`` corners apart (% of its width), each a JPEG data URL of the face around the mouth, or with ``sheet``
    one PNG strip in the workspace (for agents; one per pose, kept out of the media library). Also the line it used, in
    % of the pose image, and ``faceSize`` (``flat_rig_warp.face_scale``: a small face is warped enlarged, as the rig does)."""
    library = read_character_kit_library(workspace_dir)
    kit = (library.get("kits") or {}).get(kit_id)
    if kit is None:
        raise FlatRigError("character_not_found", "Character not found", 404)
    asset = kit.get("base") if pose == "base" else (kit.get("poses") or {}).get(pose)
    if not isinstance(pose, str) or not asset:
        raise FlatRigError("unknown_pose", f"The character has no pose {pose}")
    wanted = _states(states)
    hint = _hint(kit, pose, mouth, mouth_width)
    path = _workspace_file(pose_source(kit, pose), workspace, workspace_dir)
    with Image.open(path) as image:
        image.load()
        cleaned, crop = _figure_box(image)
        figure = cleaned.crop(crop)
        landmarks = _landmarks(path, image)
        near, guide = _pose_guides(image, crop, figure.size, hint, landmarks)
        seeds = {"point": near.get("mouth"), "width": near.get("mouthWidth"), "lips": guide.get("mouth_points"),
                 "lips_score": guide.get("mouth_score"), "face": (landmarks or {}).get("face"),
                 "exact": bool((hint or {}).get("exact"))}
        painted, ink = None, INK
        if seeds["point"] is None and seeds["lips"] is None:
            # Nothing places the line but the rig's own search: run it for the painted mouth.
            rig = rig_pose(image, rig_style({"mouthStyle": "warp"}), hint, landmarks)
            painted, ink = flat_rig_warp.painted_seed(rig), rig.get("ink") or INK
        frame = (crop[0], crop[1], image.width, image.height)
    pixels = np.array(figure)
    k, face = flat_rig_warp.face_scale(seeds, painted)
    line = flat_rig_warp.rig_line(pixels, seeds, painted, k)
    box, patches = flat_rig_warp.pose_patches(pixels, line, ink, states=wanted, k=k)
    view = _view(line)
    tiles = {state: _tile(figure, patches[state], box, view) for state in wanted}
    xs = np.linspace(line.x0, line.x1, 9)
    result = {"pose": pose, **flat_rig_warp.line_hint(line, frame), "faceSize": face,
              "line": _percent(np.stack([xs, line.y(xs)], 1), frame),
              "view": _percent(np.array([view[:2], view[2:]], float), frame), "hint": hint,
              "warnings": flat_rig_warp.line_warnings(line, seeds)}
    if sheet:
        result["sheet"] = _save_sheet(_sheet(tiles), workspace_dir, workspace, f".kit-{kit_id}-{pose}-warp-preview.png")
    else:
        result["states"] = {state: _data_url(tile) for state, tile in tiles.items()}
    return result
