"""Directional 2D figures in a Series 3D shot: the drawing that faces the camera, and a walk by the ground it covers.

A cast entry of a ``kind: "3d"`` shot may say where it looks and where it goes::

    {"characterId": "ana", "at": {"x": 1.5, "z": 0}, "heading": "right",          # 0 toward the camera, 90 screen right, 180 away
     "walkTo": {"x": -1.5, "z": 0}, "walkSpeed": 1.2, "walkAt": 0.5}               # metres, m/s (default 1.2), seconds into the shot

The renderer (``ui/src/features/scene3d/directionalSprite.ts``) then draws the character as a flat figure that turns to the
camera: of the five directions its Character Kit has (``kit.animations[id]`` with ``motion`` walk | idle and ``dir`` front |
front34 | side | back34 | back; ``side`` looks right and the left is its mirror) it shows the one of the angle between where the
figure looks and where the camera is, so a still figure changes drawing when the camera orbits, and a walking one plays its walk
cycle by the ground it covers (a cycle is two steps of 0.75 m). While the character speaks it shows its talking pose and does not
walk. A direction the kit lacks is drawn by the nearest one, and with no sheet at all the base pose glides. The numbers are
``app/shared/directional_sprites.json``, which the renderer reads too.

``cast_fields`` is the script's normalisation, ``kit_sheets`` and ``block`` make the ``screen.directional`` of the scene object,
and ``check_shot`` and ``render_warnings`` are the checks.
"""
from __future__ import annotations

import math
from typing import Any
from urllib.parse import quote

from services.directional_sprite import DIRECTIONS, LOOPS, MOTIONS, SPEC, SPEED_RANGE, WALK_SPEED, anchor, direction_of, heading_degrees, number as _number, sector_of

KEYS = ("heading", "walkTo", "walkSpeed", "walkAt", "lightTint")
LATERAL = tuple(SPEC["lateral"])
VIEW_DIRECTION = {"side": "side", "front": "front"}
REACH = 100
LATE = 600
_SAMPLE_METERS = 0.25
_ASSET_PREFIXES = ("/api/", "http://", "https://")


def _point(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    x, z = _number(value.get("x"), -REACH, REACH), _number(value.get("z"), -REACH, REACH)
    return None if x is None or z is None else {"x": x, "z": z}


def cast_fields(entry: dict[str, Any]) -> dict[str, Any]:
    """The valid ``heading``, ``walkTo``, ``walkSpeed`` and ``walkAt`` of a cast entry, as the scene stores them. A speed or a start
    without a destination is nothing, and a bad value is dropped (the script check says which)."""
    fields: dict[str, Any] = {}
    heading = heading_degrees(entry.get("heading")) if "heading" in entry else None
    if heading is not None:
        fields["heading"] = heading
    destination = _point(entry.get("walkTo"))
    if destination:
        fields["walkTo"] = destination
        for key, low, high in (("walkSpeed", *SPEED_RANGE), ("walkAt", 0, LATE)):
            value = _number(entry.get(key), low, high)
            if value is not None:
                fields[key] = value
    tint = _number(entry.get("lightTint"), 0, 1)
    if tint is not None and ("heading" in fields or "walkTo" in fields):
        fields["lightTint"] = tint
    return fields


def uses_direction(entry: dict[str, Any]) -> bool:
    """True when the entry says where it looks or goes: only then does it turn to the camera (the rest of the cast is untouched)."""
    fields = cast_fields(entry)
    return "heading" in fields or "walkTo" in fields


# The kit's sheets ---------------------------------------------------------------------------

def _group(animations: dict[str, Any], name: str) -> str | None:
    from services.series_cast_animation import animation_group
    return animation_group(animations, name)


def _motion(name: str, made: dict[str, Any], animations: dict[str, Any]) -> str | None:
    """What the sheet shows: its own ``motion``, else a cycle whose id starts with ``walk`` or ``idle``."""
    if made.get("motion") in MOTIONS:
        return str(made["motion"])
    if _group(animations, name) != "cycle":
        return None
    return next((motion for motion in MOTIONS if name.startswith(motion)), None)


def _direction(made: dict[str, Any]) -> tuple[str, bool] | None:
    """The side the sheet is drawn from and whether it is the kit's own drawing of the other side (``side_r``, which looks left): its
    own ``dir``, else its view (side and front)."""
    if made.get("dir") is not None:
        return direction_of(made["dir"])
    found = VIEW_DIRECTION.get(str(made.get("view")))
    return (found, False) if found else None


def _count(value: Any, high: int) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= high else None


def file_url(source: str, workspace: str) -> str:
    """The URL a scene loads a workspace picture from; a URL stays as it is."""
    if source.startswith(_ASSET_PREFIXES):
        return source
    return f"/api/v1/file/{quote(source.removeprefix('outputs/'))}?workspace={quote(workspace)}"


def _grid(sheet: dict[str, Any]) -> list[int | None]:
    cell = sheet.get("cell") if isinstance(sheet.get("cell"), dict) else {}
    return [_count(sheet.get("count"), 64), _count(sheet.get("columns"), 64), _count(sheet.get("rows"), 64),
            _count(cell.get("width"), 16384), _count(cell.get("height"), 16384)]


def _playing(made: dict[str, Any], direction: tuple[str, bool]) -> dict[str, Any]:
    """How a kit animation plays and where its mouth and eyes are, as the scene stores them."""
    fps = _number(made.get("fps"), 1, 60)
    found: dict[str, Any] = {"fps": fps if fps is not None else 8, "loop": made["loop"] if made.get("loop") in LOOPS else "loop"}
    if direction[1] or made.get("facing") == "left":
        found["facing"] = "left"
    found.update({key: value for key in ("mouth", "eyes") if (value := anchor(made.get(key)))})
    return found


def _sheet(name: str, made: Any, animations: dict[str, Any], workspace: str) -> dict[str, Any] | None:
    if not isinstance(made, dict) or made.get("reviewState") != "approved" or not isinstance(made.get("sheet"), dict):
        return None
    motion, direction, sheet = _motion(name, made, animations), _direction(made), made["sheet"]
    count, columns, rows, width, height = _grid(sheet)
    if not motion or not direction or None in (count, columns, rows, width, height) or not isinstance(sheet.get("source"), str) or not sheet["source"]:
        return None
    return {"id": name, "motion": motion, "dir": direction[0], "source": file_url(sheet["source"], workspace), "columns": columns, "rows": rows,
            "count": count, "cell": {"width": width, "height": height}, **_playing(made, direction)}


def kit_sheets(kit: Any, workspace: str = "") -> list[dict[str, Any]]:
    """The approved animations of a Character Kit that are a walk or an idle of one direction, as scene sheets."""
    animations = kit.get("animations") if isinstance(kit, dict) and isinstance(kit.get("animations"), dict) else {}
    return [sheet for name, made in animations.items() if (sheet := _sheet(str(name), made, animations, workspace))]


def block(entry: dict[str, Any], kit: Any, windows: list[Any] | None, workspace: str) -> dict[str, Any] | None:
    """The ``screen.directional`` of a cast member's object: its sheets, where it looks, where it walks and when it speaks. None for
    a member who says neither."""
    fields = cast_fields(entry)
    if "heading" not in fields and "walkTo" not in fields:
        return None
    result: dict[str, Any] = {"sheets": kit_sheets(kit, workspace)}
    if "heading" in fields:
        result["heading"] = fields["heading"]
    if "walkTo" in fields:
        result["walk"] = {"to": [fields["walkTo"]["x"], fields["walkTo"]["z"]], "speed": fields.get("walkSpeed", WALK_SPEED), "start": fields.get("walkAt", 0)}
    if windows:
        result["speech"] = [[float(start), float(end)] for start, end in windows]
    if "lightTint" in fields:
        result["lightTint"] = fields["lightTint"]
    return result


def directional_bindings(config: dict[str, Any], kits: dict[str, Any], characters: dict[str, str], windows: dict[str, list[Any]],
                         workspace: str) -> list[dict[str, Any]]:
    """The scene bindings (``world3d.scene.patch``) that make each directional cast member of the shot turn to the camera."""
    rows = []
    for entry in config.get("cast") or []:
        who = entry.get("characterId")
        found = block(entry, kits.get(characters.get(who)) or {}, windows.get(who), workspace)
        if found:
            rows.append({"object_id": entry["objectId"], "directional": found})
    return rows


def speech_windows(beats: list[dict[str, Any]], timing: list[tuple[float, float]]) -> dict[str, list[list[float]]]:
    """When each character speaks in the shot, from its lines and their timing: ``{characterId: [[start, end], ...]}``."""
    found: dict[str, list[list[float]]] = {}
    for beat, (start, end) in zip(beats, timing):
        if str(beat.get("text") or "").strip():
            found.setdefault(str(beat.get("characterId")), []).append([round(float(start), 3), round(float(end), 3)])
    return found


# Which directions a shot will ask for ----------------------------------------------------------

def nearest_direction(target: str, available: set[str] | frozenset[str]) -> str | None:
    """The direction the picture takes when ``target`` is missing: the nearest on the five, a tie going toward the front."""
    order = {name: index for index, name in enumerate(DIRECTIONS)}
    return min(available, key=lambda name: (abs(order[name] - order[target]), order[name]), default=None)


Sector = tuple[str, bool]
"""A direction and whether the figure looks to the left of the camera (a negative angle), which a right-looking sheet mirrors."""


def _signed(theta: float, walking: bool = False) -> Sector:
    return sector_of(theta, walking)


def _sector(theta: float, walking: bool = False) -> str:
    return _signed(theta, walking)[0]


def _angle(facing: tuple[float, float], at: tuple[float, float], eye: tuple[float, float]) -> float | None:
    """Degrees of where ``facing`` looks against the line from the camera to ``at``: 0 toward the camera, positive to its right."""
    dx, dz = at[0] - eye[0], at[1] - eye[1]
    length = math.hypot(dx, dz)
    if length < 1e-6:
        return None
    ax, az = dx / length, dz / length
    return math.degrees(math.atan2(facing[0] * -az + facing[1] * ax, -(facing[0] * ax + facing[1] * az)))


def _heading_facing(heading: float, at: tuple[float, float], eye: tuple[float, float]) -> tuple[float, float]:
    dx, dz = at[0] - eye[0], at[1] - eye[1]
    length = math.hypot(dx, dz) or 1.0
    ax, az, turn = dx / length, dz / length, math.radians(heading)
    return -ax * math.cos(turn) - az * math.sin(turn), -az * math.cos(turn) + ax * math.sin(turn)


def _box_eye(spec: dict[str, Any]) -> tuple[float, float]:
    from services.room_box import camera_pose
    eye = camera_pose(float(spec["size"]["d"]))["eye"]
    return float(eye[0]), float(eye[2])


def _every() -> set[Sector]:
    """Every sector, when any camera may go round the figure: both sides of the lateral directions."""
    return {(name, negative) for name in DIRECTIONS for negative in ((False, True) if name in LATERAL else (False,))}


def _sector_at(facing: tuple[float, float], at: tuple[float, float], eye: tuple[float, float], walking: bool = False) -> Sector:
    theta = _angle(facing, at, eye)
    return _signed(theta if theta is not None else 0.0, walking)


def _sectors(entry: dict[str, Any], start: tuple[float, float] | None, spec: dict[str, Any] | None) -> dict[str, set[Sector]]:
    """The sectors of each motion a fixed camera will ask for: along the path for the walk (a walking figure faces where it goes, so the
    larger part of its movement decides: ``directional_sprite.edges``), at the ends for the idle (a figure with no heading stands facing where it went,
    so it keeps the sectors of the walk). With no fixed camera (a template, an orbit)
    any of them."""
    fields = cast_fields(entry)
    if spec is None or start is None:
        return {"walk": _every() if "walkTo" in fields else set(), "idle": _every()}
    eye = _box_eye(spec)
    heading = fields.get("heading")
    rest = _heading_facing(heading, start, eye) if heading is not None else None
    if "walkTo" not in fields:
        return {"walk": set(), "idle": {_sector_at(rest or (0.0, 1.0), start, eye)}}
    end = (fields["walkTo"]["x"], fields["walkTo"]["z"])
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    travel = ((end[0] - start[0]) / length, (end[1] - start[1]) / length) if length > 1e-9 else (0.0, 1.0)
    along = (min(length, step * _SAMPLE_METERS) for step in range(int(length / _SAMPLE_METERS) + 2))
    walk = {_sector_at(travel, (start[0] + travel[0] * metres, start[1] + travel[1] * metres), eye, walking=True) for metres in along}
    return {"walk": walk, "idle": {_sector_at(rest or travel, point, eye, walking=rest is None) for point in (start, end)}}


def needed_directions(entry: dict[str, Any], start: tuple[float, float], spec: dict[str, Any] | None) -> set[str]:
    """Every direction the entry's shot can ask for. ``spec`` is the box room of a shot with a fixed camera, else None (any camera)."""
    return {name for sectors in _sectors(entry, start, spec).values() for name, _negative in sectors}


# The script check ---------------------------------------------------------------------------

_SPEED_TEXT = f"{SPEED_RANGE[0]:g} to {SPEED_RANGE[1]:g} m/s"
_NAMES = ", ".join(SPEC["headings"])
_FIX = "make them in Characters › Animaciones"


def _entry_problems(entry: dict[str, Any], where: str) -> list[str]:
    who = f"{where}: {entry.get('characterId')}"
    problems = []
    if "heading" in entry and heading_degrees(entry["heading"]) is None:
        problems.append(f"{who} heading must be degrees (0 toward the camera, 90 screen right, 180 away) or one of {_NAMES}")
    if "walkTo" in entry and _point(entry["walkTo"]) is None:
        problems.append(f"{who} walkTo must be {{x, z}} in metres, from -{REACH} to {REACH}")
    for key, low, high, unit in (("walkSpeed", *SPEED_RANGE, _SPEED_TEXT), ("walkAt", 0, LATE, f"0 to {LATE} s")):
        if key not in entry:
            continue
        if "walkTo" not in entry:
            problems.append(f"{who} {key} needs walkTo, the place it walks to")
        elif _number(entry[key], low, high) is None:
            problems.append(f"{who} {key} must be {unit}")
    if "lightTint" in entry:
        if "heading" not in entry and "walkTo" not in entry:
            problems.append(f"{who} lightTint needs heading or walkTo: only a figure that turns to the camera takes the light")
        elif _number(entry["lightTint"], 0, 1) is None:
            problems.append(f"{who} lightTint must be 0 to 1 (0 turns the light tint off)")
    return problems


def _kit_of(checker: Any, character_id: str) -> dict[str, Any]:
    character = checker.characters.get(character_id) or {}
    return checker.kits.get(((character.get("voiceProfile") or {}).get("characterKitRef") or {}).get("id") or "") or {}


def _box_spec(shot: dict[str, Any], series: dict[str, Any], root: str | None) -> dict[str, Any] | None:
    from services import series_room_box as box
    if not shot.get("set"):
        return None
    record = box.find_room(series, root, shot.get("set"))
    try:
        return box.spec_of(record) if record else None
    except (TypeError, ValueError):
        return None


def _start(entry: dict[str, Any], spec: dict[str, Any] | None) -> tuple[float, float] | None:
    """Where the entry stands: its ``at`` in a box room, None when the shot does not say."""
    from services import series_room_box as box
    if spec is None or "at" not in entry:
        return None
    try:
        return box.place(spec, entry["at"])
    except ValueError:
        return None


def _missing_text(sheets: list[dict[str, Any]], needed: dict[str, set[Sector]]) -> str | None:
    if not sheets:
        return f"has no walk or idle sheet in its kit, so it moves and turns in its base pose: {_FIX}"
    gaps = []
    for motion in MOTIONS:
        have = {sheet["dir"] for sheet in sheets if sheet["motion"] == motion}
        for direction in DIRECTIONS:
            if direction in {name for name, _negative in needed.get(motion, set())} and direction not in have:
                near = nearest_direction(direction, have) if have else None
                gaps.append(f"{motion} {direction} (nearest: {near})" if near else f"{motion} {direction} (nothing nearer: the idle or the pose is drawn)")
    return f"has no sheet for {', '.join(gaps)}, so the nearest one is drawn: {_FIX}" if gaps else None


def _mouth_text(sheets: list[dict[str, Any]], needed: dict[str, set[Sector]]) -> str | None:
    """While a figure speaks it stands on its idle sheet; one with no mouth anchor shows the talking pose (a front picture) instead."""
    idle = [sheet for sheet in sheets if sheet["motion"] == "idle"]
    if not idle:
        return None
    voiced = {sheet["dir"] for sheet in idle if sheet.get("mouth")}
    have = {sheet["dir"] for sheet in idle}
    wanted = {name for sectors in needed.values() for name, _negative in sectors}
    silent = [name for name in DIRECTIONS if name in wanted and (nearest_direction(name, have) if name not in have else name) not in voiced]
    if not silent:
        return None
    return (f"speaks in this shot but its idle sheet for {', '.join(silent)} has no mouth, so while it faces that way it shows its talking pose "
            f"(a front picture) instead: give those sheets a mouth anchor (kit animation mouth {{offsetX, offsetY, scale}})")


def _mirror_text(sheets: list[dict[str, Any]], needed: dict[str, set[Sector]]) -> str | None:
    """The motions and directions a right-looking sheet will be mirrored for, because the kit drew no ``_r`` sheet of that side."""
    flips = []
    for motion in MOTIONS:
        if not any(sheet["motion"] == motion for sheet in sheets):
            continue
        drawn_left = {sheet["dir"] for sheet in sheets if sheet["motion"] == motion and sheet.get("facing") == "left"}
        flips += [f"{motion} {name}" for name in LATERAL if (name, True) in needed.get(motion, set()) and name not in drawn_left]
    if not flips:
        return None
    names = sorted({flip.split()[1] for flip in flips})
    return (f"is asymmetric (its kit says so) and the shot mirrors its {', '.join(flips)}, so what it wears on one side flips to the other: "
            f"draw the opposite side as {', '.join(f'{name}_r' for name in names)} ({_FIX})")


def _warn(warnings: list[dict[str, Any]], code: str, who: str, shot_id: str, text: str) -> None:
    from services.series_script_warnings import group_warning
    group_warning(warnings, code, who, shot_id, text)


def _outside(entry: dict[str, Any], spec: dict[str, Any]) -> str | None:
    destination = cast_fields(entry).get("walkTo")
    if not destination:
        return None
    half_w, half_d = spec["size"]["w"] / 2, spec["size"]["d"] / 2
    if abs(destination["x"]) <= half_w and abs(destination["z"]) <= half_d:
        return None
    return f"walks to x {destination['x']:g}, z {destination['z']:g}, outside the room floor ({spec['size']['w']:g} x {spec['size']['d']:g} m)"


def _entry_warnings(checker: Any, entry: dict[str, Any], spec: dict[str, Any] | None, speaks: bool, shot_id: str, warnings: list[dict[str, Any]]) -> None:
    who = str(entry.get("characterId"))
    kit = _kit_of(checker, who)
    sheets = kit_sheets(kit)
    needed = _sectors(entry, _start(entry, spec), spec)
    for code, text in (("direction_sheet_missing", _missing_text(sheets, needed)),
                       ("direction_sheet_no_mouth", _mouth_text(sheets, needed) if speaks else None),
                       ("mirror_flips_detail", _mirror_text(sheets, needed) if kit.get("asymmetric") is True else None),
                       ("walk_path_outside_room", _outside(entry, spec) if spec else None),
                       ("walk_blocked_by_speech", "walks and speaks in this shot: it stops walking, and shows its talking pose or a sheet with a mouth, while "
                        "its own voice runs" if speaks and "walkTo" in cast_fields(entry) else None)):
        if text:
            _warn(warnings, code, who, shot_id, text)


def _used(shot: dict[str, Any]) -> list[dict[str, Any]]:
    """The cast entries of a script shot that say anything of where they look or go."""
    from services.series_script import _cast_entry
    return [entry for entry in (_cast_entry(raw) for raw in shot.get("cast") or []) if any(key in entry for key in KEYS)]


def check_shot(checker: Any, shot: dict[str, Any], where: str, shot_id: str, warnings: list[dict[str, Any]], series: dict[str, Any],
               root: str | None = None) -> None:
    """Problems that stop the script (a bad value, or the fields on a shot that is not 3D) and the grouped warnings that do not:
    ``direction_sheet_missing`` (the kit lacks a direction the shot can ask for: the nearest one is drawn), ``direction_sheet_no_mouth``
    (the character speaks and its sheet of a direction has no mouth: the talking pose shows), ``mirror_flips_detail`` (an asymmetric
    kit is mirrored for lack of its ``_r`` sheet), ``walk_path_outside_room`` (the destination is off the floor of the box room) and
    ``walk_blocked_by_speech`` (the character speaks in the shot, and a speaking figure stands still)."""
    used = _used(shot)
    if not used:
        return
    if shot.get("kind") != "3d":
        checker.problems.append(f"{where}: heading and walkTo are only for a 3d shot")
        return
    checker.problems.extend(problem for entry in used for problem in _entry_problems(entry, where))
    spec = _box_spec(shot, series, root)
    speakers = {line.get("who") for line in shot.get("lines") or [] if isinstance(line, dict)}
    for entry in (entry for entry in used if uses_direction(entry)):
        _entry_warnings(checker, entry, spec, entry.get("characterId") in speakers, shot_id, warnings)


# The render's check ---------------------------------------------------------------------------

def _paused(windows: list[list[float]], begin: float, length: float, speed: float) -> float:
    """Seconds the walk waits for the voice: the speech inside the walk, which moves its end later by as much."""
    waited, end = 0.0, begin + length / speed
    for start, stop in sorted(windows):
        overlap = max(0.0, min(end + waited, stop) - max(begin, start))
        waited += overlap
    return waited


def render_warnings(shot: dict[str, Any], windows: dict[str, list[list[float]]], start: Any, shot_id: str) -> list[dict[str, Any]]:
    """``walk_blocked_by_speech`` for each walker whose own voice, once recorded, falls inside its walk: how long it waits and so how
    much later it arrives. ``start`` is where the figures were put, a point or ``{objectId: point}``."""
    config = series_shot3d_config(shot)
    found: list[dict[str, Any]] = []
    for entry in config.get("cast") or []:
        fields = cast_fields(entry)
        spoken = windows.get(str(entry.get("characterId")))
        origin = start.get(entry.get("objectId")) if isinstance(start, dict) else start
        if "walkTo" not in fields or not spoken or origin is None:
            continue
        length = math.hypot(fields["walkTo"]["x"] - origin[0], fields["walkTo"]["z"] - origin[1])
        waited = _paused(spoken, fields.get("walkAt", 0.0), length, fields.get("walkSpeed", WALK_SPEED))
        if waited > 0.05:
            _warn(found, "walk_blocked_by_speech", str(entry.get("characterId")), shot_id,
                  f"stops walking for {waited:.3g} s while its own voice runs, so it arrives {waited:.3g} s later than walkAt and walkSpeed say")
    return found


def series_shot3d_config(shot: dict[str, Any]) -> dict[str, Any]:
    from services.series_shot3d import normalize_scene3d
    return normalize_scene3d(shot.get("scene3d")) or {}


def note(item: dict[str, Any], found: list[dict[str, Any]]) -> None:
    """Put ``found`` on a render job item's ``warnings`` in place of the ``walk_blocked_by_speech`` it had (a shot rendered again must
    not list them twice); the key goes away when nothing is left."""
    kept = [warning for warning in item.get("warnings") or [] if warning.get("code") != "walk_blocked_by_speech"]
    if kept or found:
        item["warnings"] = [*kept, *found]
    else:
        item.pop("warnings", None)


def object_starts(document: Any) -> dict[str, tuple[float, float]]:
    """Where each object of a scene document stands on the ground: ``{objectId: (x, z)}``."""
    slots = document.get("slots") if isinstance(document, dict) else None
    return {str(slot["id"]): (float(slot["position"][0]), float(slot["position"][2])) for slot in slots or []
            if isinstance(slot, dict) and isinstance(slot.get("position"), list) and len(slot["position"]) == 3}
