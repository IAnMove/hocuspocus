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
from collections.abc import Collection
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
SECTOR_DEGREES = 45.0
HALF_SECTOR = SECTOR_DEGREES / 2


def number(value: Any, low: float, high: float) -> float | None:
    """``value`` as a float when it is a finite number from ``low`` to ``high``, else None (a bool is not a number)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        return None
    return float(value)


def wrap(angle: float) -> float:
    """An angle in (-180, 180]."""
    wrapped = (angle + 180) % 360 - 180
    return 180.0 if wrapped == -180 else round(wrapped, 4)


def edges(walking: bool = False, drawn: Collection[str] | None = None) -> tuple[float, float, float, float]:
    """The four angles off the line to the camera where ``front`` gives way to ``front34``, ``front34`` to ``side``, ``side`` to ``back34`` and
    ``back34`` to ``back`` (``sectorEdges`` of ``ui/src/features/scene3d/directionalSprite.ts``). A standing figure has equal sectors (22.5, 67.5,
    112.5, 157.5). A walking one, which faces where it goes, has its three-quarter band ``walkDiagonalDeg`` either side of 45 and 135, so the larger
    part of its movement decides front, side or back. A diagonal that ``drawn`` (the directions of the sheets) lacks has no band: its two edges meet
    at 45 (or 135) degrees."""
    reach = min(max(float(SPEC["walkDiagonalDeg"]), 0.0), HALF_SECTOR) if walking else HALF_SECTOR
    front34 = reach if drawn is None or "front34" in drawn else 0.0
    back34 = reach if drawn is None or "back34" in drawn else 0.0
    return SECTOR_DEGREES - front34, SECTOR_DEGREES + front34, 3 * SECTOR_DEGREES - back34, 3 * SECTOR_DEGREES + back34


def sector_of(theta: float, walking: bool = False, drawn: Collection[str] | None = None) -> tuple[str, bool]:
    """``(direction, negative)`` of an angle off the line to the camera: 0 front, 45 front34, 90 side, 135 back34, 180 back, and a negative angle is
    the same sector seen from the left. The renderer also keeps the sector held before for a few degrees (hysteresis); a check has no history."""
    angle = wrap(theta)
    reach = abs(angle)
    return DIRECTIONS[sum(1 for edge in edges(walking, drawn) if reach > edge)], angle < 0


def heading_degrees(value: Any) -> float | None:
    """A heading as degrees in (-180, 180]: a number, or ``toward``, ``right``, ``away``, ``left``; None when it is neither."""
    if isinstance(value, str):
        value = SPEC["headings"].get(value)
    found = number(value, -MAX_HEADING, MAX_HEADING)
    return None if found is None else wrap(found)


def anchor(value: Any) -> dict[str, float] | None:
    """A mouth or an eye on a cell: ``{offsetX, offsetY, scale, rotation?}`` in % of the cell's longer edge (the pose anchors of the kit),
    None when it is not one (the editor drops it too)."""
    if not isinstance(value, dict):
        return None
    offset_x, offset_y = number(value.get("offsetX"), -200, 200), number(value.get("offsetY"), -200, 200)
    size = number(value.get("scale"), 0.001, 20)
    turn = number(value.get("rotation", 0), -360, 360)
    if None in (offset_x, offset_y, size, turn):
        return None
    return {"offsetX": offset_x, "offsetY": offset_y, "scale": size, "rotation": turn}


def direction_of(value: Any) -> tuple[str, bool] | None:
    """``(direction, reversed)``: one of the five, or a lateral one with ``_r`` (``side_r``: the kit's own drawing of the other side,
    which looks left). None for anything else."""
    text = value if isinstance(value, str) else ""
    reversed_ = text.endswith("_r")
    base = text[:-2] if reversed_ else text
    if base not in DIRECTIONS or (reversed_ and base not in SPEC["lateral"]):
        return None
    return base, reversed_


def _integer(value: Any, high: int) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= high else None


def _grid(where: str, raw: dict[str, Any]) -> dict[str, Any]:
    cell = raw.get("cell") if isinstance(raw.get("cell"), dict) else {}
    counts = {key: _integer(raw.get(key), 64) for key in ("columns", "rows", "count")}
    size = {key: _integer(cell.get(key), 16384) for key in ("width", "height")}
    if None in counts.values() or None in size.values():
        raise ValueError(f"{where} needs columns, rows and count (1-64) and cell {{width, height}}")
    return {**counts, "cell": size}


def _extras(sheet: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw.get("id"), str) and len(raw["id"]) <= 80:
        sheet["id"] = raw["id"]
    if "facing" not in sheet and raw.get("facing") in FACINGS:
        sheet["facing"] = raw["facing"]
    for key in ("feet", "figure"):
        if number(raw.get(key), 0.0001, 1) is not None:
            sheet[key] = float(raw[key])
    for key in ("mouth", "eyes"):
        if key not in raw:
            continue
        found = anchor(raw[key])
        if found is None:
            raise ValueError(f"directional sheet {key} must be {{offsetX, offsetY, scale, rotation?}} in % of the cell's longer edge (offsets -200 to 200)")
        sheet[key] = found
    return sheet


def _sheet(index: int, raw: Any) -> dict[str, Any]:
    where = f"directional.sheets[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{where} must be {{motion, dir, source, columns, rows, count, cell {{width, height}}, fps?, loop?}}")
    direction = direction_of(raw.get("dir"))
    if raw.get("motion") not in MOTIONS or direction is None:
        raise ValueError(f"{where} needs motion ({', '.join(MOTIONS)}) and dir ({', '.join(DIRECTIONS)}; side_r, front34_r and back34_r look left)")
    source = raw.get("source")
    if not isinstance(source, str) or not 0 < len(source) <= 2000:
        raise ValueError(f"{where}.source must be the URL of the sheet picture")
    fps = number(raw.get("fps", 8), 1, 60)
    if fps is None or raw.get("loop", "loop") not in LOOPS:
        raise ValueError(f"{where}.fps must be 1-60 and loop one of {', '.join(LOOPS)}")
    sheet: dict[str, Any] = {"motion": raw["motion"], "dir": direction[0], "source": source, **_grid(where, raw), "fps": fps, "loop": raw.get("loop", "loop")}
    if direction[1]:
        sheet["facing"] = "left"
    return _extras(sheet, raw)


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


def _optional(value: dict[str, Any]) -> dict[str, Any]:
    """The heading, walk, speech windows and light tint a block says."""
    result: dict[str, Any] = {}
    if "heading" in value:
        heading = heading_degrees(value["heading"])
        if heading is None:
            raise ValueError("directional.heading must be degrees or one of " + ", ".join(SPEC["headings"]))
        result["heading"] = heading
    if "walk" in value:
        result["walk"] = _walk(value["walk"])
    if "speech" in value:
        result["speech"] = _speech(value["speech"])
    if "lightTint" in value:
        tint = number(value["lightTint"], 0, 1)
        if tint is None:
            raise ValueError("directional.lightTint must be 0 to 1 (0 turns the light tint off)")
        result["lightTint"] = tint
    return result


def normalize(value: Any) -> dict[str, Any]:
    """``directional``: the sheets of a figure, ``heading`` (degrees against the camera at the start of the shot, or toward | right |
    away | left), ``walk`` ``{to: [x, z], speed, start}``, ``speech`` windows and ``lightTint`` (0 to 1: how much of the key light's colour the
    figure takes). A sheet may say where its ``mouth`` and ``eyes`` are, and ``side_r`` is a sheet that looks left. Returns what to store or
    raises ``ValueError``."""
    if not isinstance(value, dict) or set(value) - {"sheets", "heading", "walk", "speech", "lightTint"}:
        raise ValueError("directional must be {sheets, heading?, walk?, speech?, lightTint?}")
    sheets = value.get("sheets", [])
    if not isinstance(sheets, list) or len(sheets) > MAX_SHEETS:
        raise ValueError(f"directional.sheets must be a list of at most {MAX_SHEETS} sheets")
    result: dict[str, Any] = {"sheets": [_sheet(index, sheet) for index, sheet in enumerate(sheets)], **_optional(value)}
    if not result["sheets"] and "heading" not in result and "walk" not in result:
        raise ValueError("directional needs sheets, a heading or a walk")
    return result
