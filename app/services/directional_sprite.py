"""The ``screen.directional`` block of a Video 3D object: what a 2D figure that turns to the camera is made of.

A Character Kit's walk and idle sheets, one for each side the figure is drawn from, plus where it looks, where it walks and when it
speaks (``series_directional`` builds one from a Series cast entry, ``world3d.scene.patch`` stores one). The bounds are the
renderer's (``ui/src/features/scene3d/directionalSprite.ts``, ``parseDirectional``), and the numbers are
``app/shared/directional_sprites.json``, which both read, so a block written here opens in the editor unchanged. Where the editor
drops a bad value, ``normalize`` refuses it and says what is wrong.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

SPEC = json.loads((Path(__file__).resolve().parents[1] / "shared" / "directional_sprites.json").read_text(encoding="utf-8"))
DIRECTIONS: tuple[str, ...] = tuple(SPEC["directions"])
MOTIONS: tuple[str, ...] = tuple(SPEC["motions"])
WALK_SPEED: float = SPEC["walkSpeed"]
SPEED_RANGE: tuple[float, float] = (SPEC["walkSpeedRange"][0], SPEC["walkSpeedRange"][1])
LOOPS = ("loop", "pingpong", "once")
FACINGS = ("left", "right", "front")
MAX_HEADING = 3600
MAX_SHEETS = 24
MAX_WINDOWS = 64
SECONDS = 3600
REACH = 1000
# What the renderer clamps a walk to; a stored one outside it is refused.
STORED_SPEED = (0.05, 20.0)


def number(value: Any, low: float, high: float) -> float | None:
    """``value`` as a float when it is a finite number from ``low`` to ``high``, else None (a bool is not a number)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        return None
    return float(value)


def wrap(angle: float) -> float:
    """An angle in (-180, 180]."""
    wrapped = (angle + 180) % 360 - 180
    return 180.0 if wrapped == -180 else round(wrapped, 4)


def heading_degrees(value: Any) -> float | None:
    """A heading as degrees in (-180, 180]: a number, or ``toward``, ``right``, ``away``, ``left``; None when it is neither."""
    if isinstance(value, str):
        value = SPEC["headings"].get(value)
    found = number(value, -MAX_HEADING, MAX_HEADING)
    return None if found is None else wrap(found)


def _integer(value: Any, high: int) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= high else None


def _sheet(index: int, raw: Any) -> dict[str, Any]:
    where = f"directional.sheets[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{where} must be {{motion, dir, source, columns, rows, count, cell {{width, height}}, fps?, loop?}}")
    if raw.get("motion") not in MOTIONS or raw.get("dir") not in DIRECTIONS:
        raise ValueError(f"{where} needs motion ({', '.join(MOTIONS)}) and dir ({', '.join(DIRECTIONS)})")
    source = raw.get("source")
    if not isinstance(source, str) or not 0 < len(source) <= 2000:
        raise ValueError(f"{where}.source must be the URL of the sheet picture")
    cell = raw.get("cell") if isinstance(raw.get("cell"), dict) else {}
    counts = {key: _integer(raw.get(key), 64) for key in ("columns", "rows", "count")}
    size = {key: _integer(cell.get(key), 16384) for key in ("width", "height")}
    if None in counts.values() or None in size.values():
        raise ValueError(f"{where} needs columns, rows and count (1-64) and cell {{width, height}}")
    sheet: dict[str, Any] = {"motion": raw["motion"], "dir": raw["dir"], "source": source, **counts, "cell": size}
    fps = number(raw.get("fps", 8), 1, 60)
    if fps is None or raw.get("loop", "loop") not in LOOPS:
        raise ValueError(f"{where}.fps must be 1-60 and loop one of {', '.join(LOOPS)}")
    sheet.update(fps=fps, loop=raw.get("loop", "loop"))
    if isinstance(raw.get("id"), str) and len(raw["id"]) <= 80:
        sheet["id"] = raw["id"]
    if raw.get("facing") in FACINGS:
        sheet["facing"] = raw["facing"]
    for key in ("feet", "figure"):
        if number(raw.get(key), 0.0001, 1) is not None:
            sheet[key] = float(raw[key])
    return sheet


def _walk(raw: Any) -> dict[str, Any]:
    to = raw.get("to") if isinstance(raw, dict) else None
    if not isinstance(to, list) or len(to) != 2 or any(number(item, -REACH, REACH) is None for item in to):
        raise ValueError(f"directional.walk must be {{to: [x, z] metres, speed m/s, start s}}")
    speed, start = number(raw.get("speed"), *STORED_SPEED), number(raw.get("start"), 0, SECONDS)
    if speed is None or start is None:
        raise ValueError(f"directional.walk.speed must be {STORED_SPEED[0]:g} to {STORED_SPEED[1]:g} m/s and start 0 to {SECONDS} s")
    return {"to": [float(to[0]), float(to[1])], "speed": speed, "start": start}


def _speech(raw: Any) -> list[list[float]]:
    if not isinstance(raw, list) or len(raw) > MAX_WINDOWS:
        raise ValueError(f"directional.speech must be a list of at most {MAX_WINDOWS} windows [start, end]")
    windows = []
    for item in raw:
        start, end = (number(item[0], 0, SECONDS), number(item[1], 0, SECONDS)) if isinstance(item, list) and len(item) == 2 else (None, None)
        if start is None or end is None or end <= start:
            raise ValueError("directional.speech windows are [start, end] in seconds, with end after start")
        windows.append([start, end])
    merged: list[list[float]] = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def normalize(value: Any) -> dict[str, Any]:
    """``directional``: the sheets of a figure, ``heading`` (degrees against the camera at the start of the shot, or toward | right |
    away | left), ``walk`` ``{to: [x, z], speed, start}`` and ``speech`` windows. Returns what to store or raises ``ValueError``."""
    if not isinstance(value, dict) or set(value) - {"sheets", "heading", "walk", "speech"}:
        raise ValueError("directional must be {sheets, heading?, walk?, speech?}")
    sheets = value.get("sheets", [])
    if not isinstance(sheets, list) or len(sheets) > MAX_SHEETS:
        raise ValueError(f"directional.sheets must be a list of at most {MAX_SHEETS} sheets")
    result: dict[str, Any] = {"sheets": [_sheet(index, sheet) for index, sheet in enumerate(sheets)]}
    if "heading" in value:
        heading = heading_degrees(value["heading"])
        if heading is None:
            raise ValueError("directional.heading must be degrees or one of " + ", ".join(SPEC["headings"]))
        result["heading"] = heading
    if "walk" in value:
        result["walk"] = _walk(value["walk"])
    if "speech" in value:
        result["speech"] = _speech(value["speech"])
    if not result["sheets"] and "heading" not in result and "walk" not in result:
        raise ValueError("directional needs sheets, a heading or a walk")
    return result
