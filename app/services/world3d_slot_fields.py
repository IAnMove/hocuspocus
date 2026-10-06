"""Slot fields that a Video 3D binding checks before it stores them: a clip sequence, a hand hold and an appearance.

The bounds are the editor's (``ui/src/features/scene3d/clipCues.ts``, ``handHold.ts`` and ``parseAppearance`` in
``cinematicSettings.ts``), so a document written here opens in the editor unchanged. Where the editor clamps or drops a
bad value, these checks refuse it and say what is wrong. Each check returns the value to store or raises ``ValueError``.
"""
from __future__ import annotations

import math
import re
from typing import Any

MAX_CLIP_CUES = 32
HANDS = ("left", "right")
MAX_HOLD_OFFSET = 2.0
MAX_HOLD_TURN = round(math.tau, 4)
DEFAULT_APPEARANCE = {"duration": 0.9, "color": "#83e8ff"}
_CUE_NUMBERS = {"start": (0, 600), "duration": (0, 600), "fade": (0, 10), "speed": (0.1, 4), "offset": (0, 600)}
_CUE_KEYS = {"clip", "loop", *_CUE_NUMBERS}
_HOLD_KEYS = {"carrier", "hand", "offset", "rotation"}
_APPEARANCE_KEYS = {"start", "duration", "color"}
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _number(value: Any, low: float, high: float) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def clip_ref(value: Any, named: bool = False) -> str | dict[str, Any]:
    """A clip as ``{index, name}``, or with ``named`` also its name alone (Series resolves it in the model)."""
    if named and isinstance(value, str) and 0 < len(value) <= 200:
        return value
    if isinstance(value, dict) and type(value.get("index")) is int and value["index"] >= 0 \
            and isinstance(value.get("name"), str) and 0 < len(value["name"]) <= 200:
        return {"index": value["index"], "name": value["name"]}
    raise ValueError("clip must be {index, name}" + (" or a clip name" if named else ""))


def clip_cues(value: Any, named: bool = False) -> list[dict[str, Any]]:
    """``clips``: 1-32 cues ``{clip, start, duration?, fade?, speed?, offset?, loop?}`` in scene seconds, sorted by start."""
    if not isinstance(value, list) or not 0 < len(value) <= MAX_CLIP_CUES:
        raise ValueError(f"clips must be a list of 1-{MAX_CLIP_CUES} cues {{clip, start, duration?, fade?, speed?, offset?, loop?}}")
    cues = [_cue(index, cue, named) for index, cue in enumerate(value)]
    return sorted(cues, key=lambda cue: cue["start"])


def _cue(index: int, cue: Any, named: bool) -> dict[str, Any]:
    where = f"clips[{index}]"
    if not isinstance(cue, dict) or set(cue) - _CUE_KEYS:
        raise ValueError(f"{where} must be {{clip, start, duration?, fade?, speed?, offset?, loop?}}")
    try:
        result: dict[str, Any] = {"clip": clip_ref(cue.get("clip"), named)}
    except ValueError as error:
        raise ValueError(f"{where}.{error}") from None
    for key, (low, high) in _CUE_NUMBERS.items():
        if cue.get(key) is None and key != "start":
            continue
        if not _number(cue.get(key), low, high) or (key == "duration" and cue[key] <= 0):
            raise ValueError(f"{where}.{key} must be a number {'above' if key == 'duration' else 'from'} {low} to {high}")
        result[key] = float(cue[key])
    if cue.get("loop") is not None:
        if not isinstance(cue["loop"], bool):
            raise ValueError(f"{where}.loop must be true or false")
        result["loop"] = cue["loop"]
    return result


def hold(value: Any, object_id: str) -> dict[str, Any]:
    """``hold``: carried in the whole hand of another model object. ``offset`` is metres in the hand bone's frame;
    ``rotation`` is radians, Euler XYZ in that frame, applied after the bone's rotation."""
    if not isinstance(value, dict) or set(value) - _HOLD_KEYS:
        raise ValueError("hold must be {carrier, hand: left | right, offset?, rotation?}")
    carrier = value.get("carrier")
    if not isinstance(carrier, str) or not 0 < len(carrier) <= 160:
        raise ValueError("hold.carrier must be the id of the model object whose hand carries it")
    if carrier == object_id:
        raise ValueError("an object cannot hold itself")
    if value.get("hand") not in HANDS:
        raise ValueError("hold.hand must be left or right")
    result: dict[str, Any] = {"carrier": carrier, "hand": value["hand"]}
    for key, limit, unit in (("offset", MAX_HOLD_OFFSET, "metres"), ("rotation", MAX_HOLD_TURN, "radians")):
        if value.get(key) is None:
            continue
        triple = value[key]
        if not isinstance(triple, (list, tuple)) or len(triple) != 3 or not all(_number(item, -limit, limit) for item in triple):
            raise ValueError(f"hold.{key} must be [x, y, z], each -{limit} to {limit} {unit}")
        result[key] = [float(item) for item in triple]
    return result


def appearance(value: Any) -> dict[str, Any]:
    """``appearance``: hidden until ``start``, then it materializes over ``duration`` seconds in ``color``."""
    if not isinstance(value, dict) or set(value) - _APPEARANCE_KEYS:
        raise ValueError("appearance must be {start, duration?, color?}")
    if not _number(value.get("start"), 0, 600):
        raise ValueError("appearance.start must be 0-600 seconds")
    duration = value.get("duration", DEFAULT_APPEARANCE["duration"])
    if not _number(duration, 0.1, 30):
        raise ValueError("appearance.duration must be 0.1-30 seconds")
    color = value.get("color", DEFAULT_APPEARANCE["color"])
    if not isinstance(color, str) or not _COLOR.match(color):
        raise ValueError("appearance.color must be #rrggbb")
    return {"start": float(value["start"]), "duration": float(duration), "color": color}
