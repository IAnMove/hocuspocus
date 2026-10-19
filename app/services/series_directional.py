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

from services.directional_sprite import DIRECTIONS, LOOPS, MOTIONS, SPEC, SPEED_RANGE, WALK_SPEED, heading_degrees, number as _number, wrap as _wrap

KEYS = ("heading", "walkTo", "walkSpeed", "walkAt")
VIEW_DIRECTION = {"side": "side", "front": "front"}
REACH = 100
LATE = 600
_HALF_SECTOR = 22.5
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


def _direction(made: dict[str, Any]) -> str | None:
    """The side the sheet is drawn from: its own ``dir``, else its view (side and front)."""
    if made.get("dir") in DIRECTIONS:
        return str(made["dir"])
    return VIEW_DIRECTION.get(str(made.get("view")))


def _count(value: Any, high: int) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= high else None


def file_url(source: str, workspace: str) -> str:
    """The URL a scene loads a workspace picture from; a URL stays as it is."""
    if source.startswith(_ASSET_PREFIXES):
        return source
    return f"/api/v1/file/{quote(source.removeprefix('outputs/'))}?workspace={quote(workspace)}"


def _sheet(name: str, made: Any, animations: dict[str, Any], workspace: str) -> dict[str, Any] | None:
    if not isinstance(made, dict) or made.get("reviewState") != "approved" or not isinstance(made.get("sheet"), dict):
        return None
    motion, direction, sheet = _motion(name, made, animations), _direction(made), made["sheet"]
    cell = sheet.get("cell") if isinstance(sheet.get("cell"), dict) else {}
    numbers = [_count(sheet.get("count"), 64), _count(sheet.get("columns"), 64), _count(sheet.get("rows"), 64),
               _count(cell.get("width"), 16384), _count(cell.get("height"), 16384)]
    if not motion or not direction or None in numbers or not isinstance(sheet.get("source"), str) or not sheet["source"]:
        return None
    fps = _number(made.get("fps"), 1, 60)
    result = {"id": name, "motion": motion, "dir": direction, "source": file_url(sheet["source"], workspace), "columns": numbers[1], "rows": numbers[2],
              "count": numbers[0], "cell": {"width": numbers[3], "height": numbers[4]}, "fps": fps if fps is not None else 8,
              "loop": made["loop"] if made.get("loop") in LOOPS else "loop"}
    if made.get("facing") == "left":
        result["facing"] = "left"
    return result


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


def _sector(theta: float) -> str:
    reach = abs(_wrap(theta))
    return DIRECTIONS[0 if reach <= _HALF_SECTOR else min(len(DIRECTIONS) - 1, math.ceil((reach - _HALF_SECTOR) / 45))]


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


def _needed(entry: dict[str, Any], start: tuple[float, float], spec: dict[str, Any] | None) -> dict[str, set[str]]:
    """The directions of each motion a fixed camera will ask for: along the path for the walk, at the ends for the idle."""
    if spec is None:
        every = set(DIRECTIONS)
        return {"walk": set(every) if "walkTo" in entry else set(), "idle": set(every)}
    eye, fields = _box_eye(spec), cast_fields(entry)
    heading = fields.get("heading")
    rest = _heading_facing(heading, start, eye) if heading is not None else None
    if "walkTo" not in fields:
        theta = _angle(rest or (0.0, 1.0), start, eye)
        return {"walk": set(), "idle": {_sector(theta if theta is not None else 0.0)}}
    end = (fields["walkTo"]["x"], fields["walkTo"]["z"])
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    travel = ((end[0] - start[0]) / length, (end[1] - start[1]) / length) if length > 1e-9 else (0.0, 1.0)
    walk = set()
    for step in range(int(length / _SAMPLE_METERS) + 2):
        along = min(length, step * _SAMPLE_METERS)
        theta = _angle(travel, (start[0] + travel[0] * along, start[1] + travel[1] * along), eye)
        walk.add(_sector(theta if theta is not None else 0.0))
    idle = {_sector(_angle(rest or travel, point, eye) or 0.0) for point in (start, end)}
    return {"walk": walk, "idle": idle}


def needed_directions(entry: dict[str, Any], start: tuple[float, float], spec: dict[str, Any] | None) -> set[str]:
    """Every direction the entry's shot can ask for. ``spec`` is the box room of a shot with a fixed camera, else None (any camera)."""
    found = _needed(entry, start, spec)
    return found["walk"] | found["idle"]


# The script check ---------------------------------------------------------------------------

_SPEED_TEXT = f"{SPEED_RANGE[0]:g} to {SPEED_RANGE[1]:g} m/s"
_NAMES = ", ".join(SPEC["headings"])


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


def _missing_text(sheets: list[dict[str, Any]], needed: dict[str, set[str]]) -> str | None:
    if not sheets:
        return "has no walk or idle sheet in its kit, so it moves and turns in its base pose: make them in Characters › Animaciones"
    gaps = []
    for motion in MOTIONS:
        have = {sheet["dir"] for sheet in sheets if sheet["motion"] == motion}
        for direction in DIRECTIONS:
            if direction in needed.get(motion, set()) and direction not in have:
                near = nearest_direction(direction, have) if have else None
                gaps.append(f"{motion} {direction} (nearest: {near})" if near else f"{motion} {direction} (nothing nearer: the idle or the pose is drawn)")
    if not gaps:
        return None
    return f"has no sheet for {', '.join(gaps)}, so the nearest one is drawn: make them in Characters › Animaciones"


def _outside(entry: dict[str, Any], spec: dict[str, Any]) -> str | None:
    fields = cast_fields(entry)
    destination = fields.get("walkTo")
    if not destination:
        return None
    half_w, half_d = spec["size"]["w"] / 2, spec["size"]["d"] / 2
    if abs(destination["x"]) <= half_w and abs(destination["z"]) <= half_d:
        return None
    return f"walks to x {destination['x']:g}, z {destination['z']:g}, outside the room floor ({spec['size']['w']:g} x {spec['size']['d']:g} m)"


def _warn(warnings: list[dict[str, Any]], code: str, who: str, shot_id: str, text: str) -> None:
    from services.series_script_warnings import group_warning
    group_warning(warnings, code, who, shot_id, text)


def check_shot(checker: Any, shot: dict[str, Any], where: str, shot_id: str, warnings: list[dict[str, Any]], series: dict[str, Any],
               root: str | None = None) -> None:
    """Problems that stop the script (a bad value, or the fields on a shot that is not 3D) and the grouped warnings that do not:
    ``direction_sheet_missing`` (the kit lacks a direction the shot can ask for: the nearest one is drawn),
    ``walk_path_outside_room`` (the destination is off the floor of the box room) and ``walk_blocked_by_speech`` (the character
    speaks in the shot, and a speaking figure stands still)."""
    from services.series_script import _cast_entry
    entries = [_cast_entry(raw) for raw in shot.get("cast") or []]
    used = [entry for entry in entries if any(key in entry for key in KEYS)]
    if not used:
        return
    if shot.get("kind") != "3d":
        checker.problems.append(f"{where}: heading and walkTo are only for a 3d shot")
        return
    problems = [problem for entry in used for problem in _entry_problems(entry, where)]
    checker.problems.extend(problems)
    spec = _box_spec(shot, series, root)
    speakers = {line.get("who") for line in shot.get("lines") or [] if isinstance(line, dict)}
    for entry in (entry for entry in used if uses_direction(entry)):
        who = str(entry.get("characterId"))
        start = _start(entry, spec)
        found = _missing_text(kit_sheets(_kit_of(checker, who)), _needed(entry, start, spec if start else None))
        if found:
            _warn(warnings, "direction_sheet_missing", who, shot_id, found)
        outside = _outside(entry, spec) if spec else None
        if outside:
            _warn(warnings, "walk_path_outside_room", who, shot_id, outside)
        if "walkTo" in cast_fields(entry) and who in speakers:
            _warn(warnings, "walk_blocked_by_speech", who, shot_id,
                  "walks and speaks in this shot: it stops walking, and shows its talking pose, while its own voice runs")


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
