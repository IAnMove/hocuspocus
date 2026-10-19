"""A Series shot that names a metric box room, so the cast stands on the floor.

``set`` is a room stored on the series (``series["rooms"]``) or in the workspace file
``scene3d-rooms.json``. Each person carries ``at`` as ``{x, z}`` metres or ``near``, ``mid`` or ``far``.
A mold room (``location.set3d``) is a different path and is not merged with this one.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from services import room_plate
from services.room_box import camera_pose, normalize, prop_point

MODEL_HEIGHT = 1.7
ZONES = ("near", "mid", "far")
STORE = "scene3d-rooms.json"


def foreign_room(shot: dict) -> str | None:
    """``set`` and ``at`` belong to a ``kind: "3d"`` shot."""
    if shot.get("kind") == "3d":
        return None
    if shot.get("set") or any("at" in person for person in _people(shot)):
        return "set is only for a 3d shot"
    return None


def shot_problems(shot: dict, series: dict | None, root: str | None, location: dict | None) -> list[str]:
    """Why this shot cannot stand in its named room. Empty when the shot names no room."""
    people = _people(shot)
    named = shot.get("set")
    problems = []
    if any("at" in person for person in people) and not named:
        problems.append("at is only for a shot that names set")
    if not named:
        return problems
    if isinstance(location, dict) and location.get("set3d"):
        problems.append("this shot names set and the location already has a mold room")
    record = find_room(series, root, named)
    if record is None:
        problems.append(f"unknown room {named}")
        return problems
    try:
        spec = spec_of(record)
    except (TypeError, ValueError) as error:
        return [*problems, str(error)]
    problems.extend(_standing(spec, people))
    file = room_file(record, named)
    if root and not (Path(root) / file).is_file():
        problems.append(f"room file {file} is missing")
    scene = shot.get("scene3d") if isinstance(shot.get("scene3d"), dict) else {}
    count = 1 + len(scene.get("objects") or [])
    if count > 12:
        problems.append(f"object_limit: {count} requested; maximum 12")
    return problems


def dress_shot(shot: dict, series: dict | None, root: str | None, location: dict | None) -> dict:
    """The shot's scene3d for a named box room: the wide camera's template, the room GLB and each person's place."""
    del location
    config = dict(shot.get("scene3d") or {})
    if not config.get("scene"):
        config.setdefault("template", "two-shot")
    record = find_room(series, root, shot.get("set"))
    spec = _quiet_spec(record)
    if spec:
        config["roomBox"] = spec
        file = room_file(record, shot.get("set"))
        if not root or (Path(root) / file).is_file():
            config["objects"] = [_room_object(spec, file), *_without(config.get("objects"), "room-box")]
    config["cast"] = _dressed_cast(shot)
    return config


def look_digest(shot: dict, root: str | None) -> str | None:
    """How the stored room this shot stands in looks now: a changed look renders the shot again, a changed other room does not.

    None for a shot that is in no stored room, and for a room put before looks were kept, so their takes keep the digest
    they had. The room is read from the shot's ``room-box`` object, whose file is ``rooms/<name>.glb``."""
    scene = shot.get("scene3d") if isinstance(shot.get("scene3d"), dict) else {}
    item = next((row for row in scene.get("objects") or [] if isinstance(row, dict) and row.get("objectId") == "room-box"), None)
    if not root or not item or not isinstance(item.get("file"), str):
        return None
    from services import room_store
    try:
        record = room_store.record_of(Path(root), Path(item["file"]).stem)
    except (OSError, ValueError):
        return None
    paint = record.get("paint") if record else None
    look = paint.get("look") if isinstance(paint, dict) else None
    return look if isinstance(look, str) else None


def cutout_scale(entry: dict) -> dict:
    """The image binding that makes a cutout ``heightM`` tall. Empty when the shot did not name a height."""
    height = entry.get("heightM")
    if isinstance(height, bool) or not isinstance(height, (int, float)):
        return {}
    return {"scale": height / 2, "imageLook": {"grounded": True, "shadow": 0.45}, "grounded": True}


def box_camera(spec: dict, moved: Any = None) -> dict:
    """The shared wide frame: adult eye height, just outside the open side. A plate room's is the plate's own viewpoint, lens shift
    included, moved by the shot's ``camera`` ({shift: {x, y, z}, yaw, pitch}) when it has one."""
    plate = spec.get("plate")
    if plate:
        move = moved if isinstance(moved, dict) else {}
        pose = room_plate.pose_of(plate, move.get("shift"), move.get("yaw"), move.get("pitch"))
        return {"family": "fixed", "eye": pose["eye"], "look": pose["look"], "fov": pose["fov"], "lensShift": pose["lensShift"]}
    pose = camera_pose(float(spec["size"]["d"]))
    return {"family": "fixed", "eye": pose["eye"], "look": pose["look"], "fov": pose["fov"]}


def plate_warnings(shot: dict, series: dict | None, root: str | None) -> list[dict]:
    """``camera_breaks_plate`` for a shot that stands in a plate room and moves or turns its camera past the plate's range."""
    record = find_room(series, root, shot.get("set"))
    spec = _quiet_spec(record)
    if not spec or not spec.get("plate"):
        return []
    scene = shot.get("scene3d") if isinstance(shot.get("scene3d"), dict) else {}
    camera = box_camera(spec, scene.get("camera"))
    return room_plate.camera_report(spec["plate"], camera)


def box_cast_bindings(config: dict) -> list[dict]:
    """One grounded binding per person who named ``at``. Metres, y on the floor, facing the camera."""
    spec = config.get("roomBox")
    if not isinstance(spec, dict):
        return []
    bindings = []
    for entry in config.get("cast") or []:
        if not isinstance(entry, dict) or "at" not in entry:
            continue
        x, z = place(spec, entry.get("at"))
        height = entry.get("heightM")
        if isinstance(height, bool) or not isinstance(height, (int, float)):
            height = MODEL_HEIGHT
        bindings.append({"object_id": entry["objectId"], "position": [x, 0, z], "rotationY": 0,
                         "scale": round(float(height) / MODEL_HEIGHT, 4), "grounded": True})
    return bindings


def find_room(series: dict | None, root: str | None, name: Any) -> dict | None:
    """A raw box spec, or ``{spec, file}``, from the series or from ``scene3d-rooms.json``."""
    rooms = series.get("rooms") if isinstance(series, dict) else None
    if isinstance(rooms, dict) and isinstance(rooms.get(name), dict):
        return rooms[name]
    if not root or not isinstance(name, str):
        return None
    path = Path(root) / STORE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    record = (data.get("rooms") or {}).get(name) if isinstance(data, dict) else None
    return record if isinstance(record, dict) else None


def spec_of(record: dict) -> dict:
    """The normalised box. A stored record keeps its spec beside the GLB path and is not normalised as a whole."""
    if record.get("kind") == "room":
        return normalize(record)
    spec = record.get("spec")
    if isinstance(spec, dict):
        return normalize(spec)
    raise ValueError("unknown room")


def room_file(record: dict | None, name: Any) -> str:
    file = record.get("file") if isinstance(record, dict) and record.get("kind") != "room" else None
    if isinstance(file, str) and file and ".." not in file.split("/"):
        return file
    return f"rooms/{name}.glb"


def place(spec: dict, at: Any) -> tuple[float, float]:
    """``at`` as metres on the floor. ``near`` is toward the camera, ``far`` toward the back wall."""
    size = spec["size"]
    if at in ZONES:
        if spec.get("plate"):
            return 0.0, room_plate.zones(spec["plate"])[at]
        z = {"near": -size["d"] / 2 + 0.75, "mid": 0.0, "far": size["d"] / 2 - 0.75}[at]
        return 0.0, round(z, 4)
    if not isinstance(at, dict) or "x" not in at or "z" not in at:
        raise ValueError("at is {x, z} in metres or near, mid or far")
    x, z = at.get("x"), at.get("z")
    if isinstance(x, bool) or isinstance(z, bool) or not isinstance(x, (int, float)) or not isinstance(z, (int, float)):
        raise ValueError("at is {x, z} in metres or near, mid or far")
    if not (math.isfinite(x) and math.isfinite(z) and -100 <= x <= 100 and -100 <= z <= 100):
        raise ValueError("at is {x, z} in metres or near, mid or far")
    return float(x), float(z)


def _standing(spec: dict, people: list[dict]) -> list[str]:
    problems = []
    for person in people:
        who = person.get("characterId")
        if not who:
            continue
        if "at" not in person:
            problems.append(f"{who} needs at")
            continue
        problems.extend(_one_stand(spec, who, person.get("at")))
    return problems


def _one_stand(spec: dict, who: str, at: Any) -> list[str]:
    try:
        x, z = place(spec, at)
    except ValueError as error:
        return [f"{who}: {error}"]
    size = spec["size"]
    if abs(x) > size["w"] / 2 or abs(z) > size["d"] / 2:
        return [f"{who} stands outside the room floor"]
    problems = []
    plate = spec.get("plate")
    if plate and z < plate["visible"]["near_z"] - 1e-6:
        problems.append(f"{who} stands below the plate's frame: the nearest floor it shows is z {plate['visible']['near_z']:g}")
    if _on_door(spec, x, z):
        problems.append(f"{who} stands on the door")
    if _on_furniture(spec, x, z):
        problems.append(f"{who} stands on furniture")
    return problems


def _on_door(spec: dict, x: float, z: float) -> bool:
    door, size = spec["door"], spec["size"]
    if not door:
        return False
    along, wall = _wall_distances(size, door["wall"], door["x"], x, z)
    return along <= door["w"] / 2 + 0.15 and wall <= 0.35


def _on_furniture(spec: dict, x: float, z: float) -> bool:
    for prop in spec.get("props") or []:
        px, _py, pz = prop_point(spec["size"], prop)
        if prop.get("on") == "floor" and math.hypot(x - px, z - pz) <= prop["height_m"] * 0.25:
            return True
        if prop.get("on") == "wall" and _against_prop(spec, prop, x, z):
            return True
    return False


def _against_prop(spec: dict, prop: dict, x: float, z: float) -> bool:
    px, _py, pz = prop_point(spec["size"], prop)
    along, wall = _wall_distances(spec["size"], prop["wall"], px if prop["wall"] == "back" else pz, x, z)
    return along <= 0.25 * prop["height_m"] and wall <= 0.35


def _wall_distances(size: dict, wall: str, centre: float, x: float, z: float) -> tuple[float, float]:
    """Distance along the wall from ``centre``, and distance from the person to that wall."""
    if wall == "back":
        return abs(x - centre), abs(z - size["d"] / 2)
    edge = -size["w"] / 2 if wall == "left" else size["w"] / 2
    return abs(z - centre), abs(x - edge)


def _people(shot: dict) -> list[dict]:
    from services.series_script import _cast_entry
    return [_cast_entry(raw) for raw in shot.get("cast") or [] if isinstance(_cast_entry(raw), dict)]


def _quiet_spec(record: dict | None) -> dict | None:
    if not isinstance(record, dict):
        return None
    try:
        return spec_of(record)
    except (TypeError, ValueError):
        return None


def _room_object(spec: dict, file: str) -> dict:
    return {"objectId": "room-box", "add": True, "media": "model3d", "file": file,
            "position": [0, 0, 0], "scale": round(float(spec["size"]["h"]) / MODEL_HEIGHT, 4), "grounded": False}


def _dressed_cast(shot: dict) -> list[dict]:
    rows = []
    for index, person in enumerate(_people(shot)):
        if not person.get("characterId"):
            continue
        row = {"characterId": person["characterId"], "objectId": person.get("objectId") or f"subject_{index + 1}",
               "poseId": person.get("poseId") or "base"}
        for key in ("at", "heightM", "mark"):
            if key in person:
                row[key] = person[key]
        rows.append(row)
    return rows


def _without(objects: Any, object_id: str) -> list:
    if not isinstance(objects, list):
        return []
    return [item for item in objects if not (isinstance(item, dict) and item.get("objectId") == object_id)]
