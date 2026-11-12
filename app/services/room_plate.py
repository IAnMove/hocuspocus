"""A painted plate as the back wall of a metric box room, with a floor you can walk on in front of it.

``scene3d.room.put`` takes ``walls`` as a picture of the workspace (``{file}`` or ``{asset}``) instead of words. The picture
is then not a texture that repeats: it is the view from one camera, and the room is built so that camera sees the picture
again, pixel for pixel. The room keeps the plate's own numbers, the same ones ``location.layout2d.stage`` keeps for a 2D shot::

    stage = {"horizon": 0.22, "ref": {"baseY": 0.72, "heightPct": 0.62, "heightM": 2.0}, "floorTop": 0.72}

all fractions of the plate's height, from the top. A level camera at eye height sees the horizon at ``horizon``; an object of
``ref.heightM`` metres stands with its foot at ``baseY`` and is ``heightPct`` tall. Those four numbers fix the scale:

* the camera is ``eye = (baseY - horizon) * heightM / heightPct`` metres high (the same number ``series_stage.eye_height_m`` gives);
* the plate is a card standing on the floor at ``distance`` metres from the camera (where the floor meets it at row ``floorTop``,
  which is ``baseY`` unless the stage says people may stand farther), as tall as the lens sees there;
* the floor in front of the card is the plate's own floor rows, projected from that camera: the same pixels at the same place,
  so the painted floor and the 3D floor are one floor;
* the card, the side walls and the ceiling are the box the camera sees into; what the plate does not show is the plate's edge
  mirrored, blurred and darkened (``room_plate_extend``), so a camera that moves a little finds more room, not a void.

The horizon is rarely the middle of the picture, so the camera keeps its lens level and moves the picture's centre instead
(``lensShift``, the fraction of the frame's height the horizon sits above its middle): verticals stay vertical, as in the plate.

Coordinates are those of ``room_box``: the origin is the middle of the floor, ``z`` runs away from the camera, the back wall is
``z = d/2`` and the camera stands on the open side ``z = -d/2``. A camera looking along +z has world +x on its left.
"""
from __future__ import annotations

import math
from typing import Any, Callable

FOV = 48.0
RANGE = {"orbit_deg": 25.0, "shift_m": 0.5}
# A stage nobody measured: a 1.6 m camera, the floor from 74 % down, a 2 m door 40 % of the plate tall (``stage_assumed``).
DEFAULT_STAGE = {"horizon": 0.42, "ref": {"baseY": 0.74, "heightPct": 0.40, "heightM": 2.0}}
RECIPE = 1
EYE_NOTE = (1.0, 2.4)
SIDES = ("back", "left", "right")
Resolve = Callable[[dict], dict]
_REF = {"file", "asset"}
_PLATE_FIELDS = {"back", "left", "right", "stage", "stage_assumed", "fov", "range", "camera", "metres", "visible", "recipe"}
_MIN_BELOW = 0.01


# ---------------------------------------------------------------- the numbers


def _number(value: Any, low: float, high: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= float(value) <= high or not math.isfinite(value):
        raise ValueError(f"{what} is a number from {low:g} to {high:g}")
    return round(float(value), 4)


def normalize_stage(value: Any) -> dict:
    """The plate's perspective (the contract of ``location.layout2d.stage``): bounded, with ``heightM`` 2 by default."""
    if not isinstance(value, dict) or not isinstance(value.get("ref"), dict):
        raise ValueError("stage is {horizon, ref: {baseY, heightPct, heightM}, floorTop?}, fractions of the plate's height")
    ref = value["ref"]
    horizon = _number(value.get("horizon"), 0, 0.95, "stage.horizon")
    base = _number(ref.get("baseY"), 0.05, 1, "stage.ref.baseY")
    stage = {"horizon": horizon, "ref": {"baseY": base, "heightPct": _number(ref.get("heightPct"), 0.01, 1.5, "stage.ref.heightPct"),
                                         "heightM": _number(ref.get("heightM", 2.0), 0.05, 30, "stage.ref.heightM")}}
    if base - horizon < _MIN_BELOW:
        raise ValueError(f"stage.ref.baseY ({base}) must be below the horizon ({horizon}): the floor starts under the eye line")
    if value.get("floorTop") is not None:
        top = _number(value["floorTop"], 0, 0.98, "stage.floorTop")
        if top - horizon < _MIN_BELOW:
            raise ValueError(f"stage.floorTop ({top}) must be below the horizon ({horizon})")
        stage["floorTop"] = top
    return stage


def eye_height(stage: dict) -> float:
    """Metres between the reference's foot and the horizon: how high the camera is."""
    ref = stage["ref"]
    return (ref["baseY"] - stage["horizon"]) * ref["heightM"] / ref["heightPct"]


def geometry(plate: dict) -> dict:
    """Everything a stage, a lens and a picture's size fix, in metres. ``plate`` has ``back {w, h}``, ``stage`` and ``fov``."""
    stage, fov = plate["stage"], float(plate["fov"])
    ref, horizon = stage["ref"], stage["horizon"]
    top = stage.get("floorTop", ref["baseY"])
    lens = 2 * math.tan(math.radians(fov) / 2)
    eye = eye_height(stage)
    card_h = ref["heightM"] / ref["heightPct"] * (ref["baseY"] - horizon) / (top - horizon)
    distance = card_h / lens
    aspect = plate["back"]["w"] / plate["back"]["h"]
    width, height = card_h * aspect, card_h * top
    if not (0.4 <= eye <= 8 and 1 <= width <= 120 and 1 <= distance <= 120 and 1 <= height <= 60):
        raise ValueError(f"the stage puts the camera {eye:.2f} m high and the plate {width:.1f} m wide: re-read the horizon and the reference")
    near = distance * (top - horizon) / (1 - horizon)
    shift = round(0.5 - horizon, 4)
    return {"horizon": horizon, "eye_height": round(eye, 4), "distance": round(distance, 4), "plate_h": round(card_h, 4), "plate_w": round(width, 4),
            "top": round(height, 4), "base_row": top, "near_s": round(near, 4), "lens": round(lens, 6), "aspect": round(aspect, 6),
            "camera": {"eye": [0.0, round(eye, 4), round(-distance / 2, 4)], "look": [0.0, round(eye, 4), round(distance / 2, 4)],
                       "fov": fov, "lensShift": shift},
            "visible": {"near_z": round(-distance / 2 + near, 4), "far_z": round(distance / 2, 4)}}


def eye_note(stage: dict) -> str | None:
    height = eye_height(stage)
    if EYE_NOTE[0] <= height <= EYE_NOTE[1]:
        return None
    return (f"this stage puts the camera {height:.2f} m high (a person's eye level is about 1.6 m); re-read the horizon and "
            "the reference on the grid unless the plate really is a low or a high angle")


def project(plate: dict, point: tuple[float, float, float]) -> tuple[float, float]:
    """Where a world point lands on the plate (u, v fractions from the top left) seen from the plate's own camera."""
    geo = geometry(plate)
    eye, _look, _fov = geo["camera"]["eye"], geo["camera"]["look"], geo["camera"]["fov"]
    depth = point[2] - eye[2]
    return (0.5 - (point[0] - eye[0]) / (depth * geo["lens"] * geo["aspect"]),
            0.5 - plate_shift(plate) - (point[1] - eye[1]) / (depth * geo["lens"]))


def plate_shift(plate: dict) -> float:
    return 0.5 - plate["stage"]["horizon"]


# ---------------------------------------------------------------- the spec


def is_plate_ref(value: Any) -> bool:
    return isinstance(value, dict) and len(value) == 1 and next(iter(value)) in _REF and isinstance(next(iter(value.values())), str)


def _wall_refs(walls: Any) -> dict | None:
    """The pictures a raw ``walls`` names: ``{file|asset}`` is the back wall, ``{back, left, right}`` one per wall."""
    if is_plate_ref(walls):
        return {"back": walls}
    if isinstance(walls, dict) and walls and set(walls) <= set(SIDES):
        if not all(is_plate_ref(item) for item in walls.values()) or "back" not in walls:
            raise ValueError("walls names pictures as {back: {file}, left?: {file}, right?: {file}}: the back wall's picture is the plate")
        return dict(walls)
    if isinstance(walls, dict):
        raise ValueError("walls is words, a picture {file} or {asset}, or {back, left?, right?} pictures")
    return None


def wants_plate(room: Any) -> bool:
    """A raw room whose ``walls`` is a picture. It is built by ``prepare`` first."""
    return isinstance(room, dict) and isinstance(room.get("walls"), dict)


def prepare(room: dict, resolve: Resolve) -> dict:
    """The room with every picture it names resolved to ``{file, w, h}`` (``resolve`` reads the workspace), the plate's
    own options gathered under ``plate`` and ``walls`` / ``floor`` given words. A room with no plate keeps its words."""
    room = dict(room)
    refs = _wall_refs(room.get("walls"))
    own = [key for key in ("stage", "fov", "range") if key in room]
    if refs is None and own:
        raise ValueError(f"{', '.join(own)} belongs to a room whose walls is a picture (the plate)")
    if refs is not None:
        room["plate"] = _plate_input(room, refs, resolve)
        room["walls"], room["floor"] = "the walls of the plate", room.get("floor") or "the floor of the plate"
        for key in own:
            room.pop(key)
    if isinstance(room.get("props"), list):
        room["props"] = [_resolved_prop(prop, resolve) for prop in room["props"]]
    return room


def _plate_input(room: dict, refs: dict, resolve: Resolve) -> dict:
    if "size" in room:
        raise ValueError("size comes from the plate (its stage and its picture): leave it out")
    if room.get("windows") or room.get("ceiling"):
        raise ValueError("a plate room's windows and ceiling are in the picture: leave them out")
    plate: dict = {side: resolve(ref) for side, ref in refs.items()}
    for key in ("stage", "fov", "range"):
        if room.get(key) is not None:
            plate[key] = room[key]
    return plate


def _resolved_prop(prop: Any, resolve: Resolve) -> Any:
    if isinstance(prop, dict) and is_plate_ref(prop.get("image")):
        return {**prop, "image": resolve(prop["image"])}
    return prop


def normalize_plate(value: Any) -> dict:
    """The canonical plate: pictures as ``{file, w, h}``, a stage, a lens, the range and every derived number. The derived
    numbers are always recomputed, never trusted."""
    if not isinstance(value, dict) or set(value) - _PLATE_FIELDS:
        raise ValueError(f"plate is {{back, left?, right?, stage?, fov?, range?}}; unknown: {', '.join(sorted(set(value or {}) - _PLATE_FIELDS))}")
    plate: dict = {side: _picture(value.get(side), side) for side in SIDES if side in value}
    if "back" not in plate:
        raise ValueError("plate.back is the picture of the back wall")
    assumed = value.get("stage") is None or bool(value.get("stage_assumed"))
    plate["stage"] = normalize_stage(DEFAULT_STAGE if assumed else value["stage"])
    plate["stage_assumed"] = assumed
    plate["fov"] = FOV if value.get("fov") is None else _number(value["fov"], 20, 90, "fov")
    plate["range"] = _range(value.get("range"))
    geo = geometry(plate)
    plate.update(camera=geo["camera"], visible=geo["visible"],
                 metres={key: geo[key] for key in ("eye_height", "distance", "plate_w", "plate_h", "top")}, recipe=RECIPE)
    return plate


def _picture(value: Any, side: str) -> dict:
    ok = isinstance(value, dict) and isinstance(value.get("file"), str) and value["file"]
    if not ok or set(value) - {"file", "w", "h"} or not all(type(value.get(key)) is int and 8 <= value[key] <= 16384 for key in ("w", "h")):
        raise ValueError(f"plate.{side} is a workspace picture {{file}} (read by scene3d.room.put)")
    return {"file": value["file"], "w": value["w"], "h": value["h"]}


def _range(value: Any) -> dict:
    if value is None:
        return dict(RANGE)
    if not isinstance(value, dict) or set(value) - set(RANGE):
        raise ValueError("range is {orbit_deg, shift_m}: how far the camera may turn and move before the plate shows its edges")
    return {"orbit_deg": _number(value.get("orbit_deg", RANGE["orbit_deg"]), 0, 60, "range.orbit_deg"),
            "shift_m": _number(value.get("shift_m", RANGE["shift_m"]), 0, 3, "range.shift_m")}


def canonical_size(plate: dict) -> dict:
    geo = geometry(plate)
    return {"w": round(geo["plate_w"], 4), "d": round(geo["distance"], 4), "h": round(geo["top"], 4)}


# ---------------------------------------------------------------- standing and looking


def zones(plate: dict) -> dict:
    """``near``, ``mid`` and ``far`` as the floor depth (``z``) a person stands at, inside the part of the floor the plate shows."""
    near, far = plate["visible"]["near_z"], plate["visible"]["far_z"]
    span = far - near
    return {"near": round(near + 0.2 * span, 4), "mid": round(near + 0.5 * span, 4), "far": round(near + 0.88 * span, 4)}


def pose_of(plate: dict, shift: Any = None, yaw: Any = None, pitch: Any = None) -> dict:
    """The plate's camera, moved by ``shift`` metres ({x, y, z}), turned ``yaw`` degrees to the left and tipped ``pitch`` up."""
    base = plate["camera"]
    move = shift if isinstance(shift, dict) else {}
    eye = [round(base["eye"][i] + float(move.get(axis, 0) or 0), 4) for i, axis in enumerate("xyz")]
    heading, tilt = math.radians(float(yaw or 0)), math.radians(float(pitch or 0))
    reach = plate["metres"]["distance"]
    flat = math.cos(tilt) * reach
    look = [round(eye[0] + math.sin(heading) * flat, 4), round(eye[1] + math.sin(tilt) * reach, 4), round(eye[2] + math.cos(heading) * flat, 4)]
    return {**base, "eye": eye, "look": look}


def camera_report(plate: dict, camera: dict) -> list[dict]:
    """``camera_breaks_plate`` for a camera ``{eye, look, fov?}``: it moved or turned farther than the plate's ``range``."""
    base, limit = plate["camera"], plate["range"]
    eye, look = camera.get("eye") or base["eye"], camera.get("look") or base["look"]
    moved = math.dist(eye, base["eye"])
    forward = [look[0] - eye[0], look[1] - eye[1], look[2] - eye[2]]
    yaw = math.degrees(math.atan2(forward[0], forward[2]))
    pitch = math.degrees(math.atan2(forward[1], math.hypot(forward[0], forward[2])))
    zoom = abs(float(camera.get("fov") or base["fov"]) - base["fov"])
    found = []
    if moved > limit["shift_m"] + 1e-6:
        found.append(f"the camera is {moved:.2f} m from the plate's viewpoint (the plate holds to {limit['shift_m']:g} m)")
    if max(abs(yaw), abs(pitch)) > limit["orbit_deg"] + 1e-6:
        found.append(f"the camera turns {max(abs(yaw), abs(pitch)):.0f} degrees from the plate's view (the plate holds to {limit['orbit_deg']:g})")
    if zoom > 8:
        found.append(f"the lens is {zoom:.0f} degrees away from the plate's {base['fov']:g}")
    if not found:
        return []
    return [{"code": "camera_breaks_plate", "message": "; ".join(found) + ": the edges of the plate show. Keep the camera inside the range or paint a wider plate.",
             "moved_m": round(moved, 3), "yaw_deg": round(yaw, 1), "pitch_deg": round(pitch, 1)}]


# ---------------------------------------------------------------- the room


def normalize_room(entry: dict) -> dict:
    """The canonical plate room. ``entry`` is one ``prepare`` made, or one this function returned earlier."""
    from services import room_box

    if not isinstance(entry.get("plate"), dict) or isinstance(entry.get("walls"), dict):
        raise ValueError("walls is a picture: store the room with scene3d.room.put, which reads the picture")
    plate = normalize_plate(entry["plate"])
    size = canonical_size(plate)
    if "size" in entry and entry["size"] != size:
        raise ValueError("size comes from the plate (its stage, its lens and its picture): leave it out")
    if entry.get("windows") or entry.get("ceiling"):
        raise ValueError("a plate room's windows and ceiling are in the picture: leave them out")
    for key in ("prompt", "floor", "walls"):
        room_box._text(entry.get(key), key)
    props = room_box._props(entry.get("props", []), size)
    for index, prop in enumerate(props):
        if "image" not in prop:
            raise ValueError(f"props[{index}] needs image: a PNG with alpha of the workspace, cut out of the scene it stands in")
        if prop["on"] == "wall" and prop["wall"] != "back":
            raise ValueError(f"props[{index}] stands on the floor or the back wall: the side walls are the plate's edges")
    spec = {"kind": "room", "prompt": entry["prompt"].strip(), "size": size, "floor": entry["floor"].strip(), "walls": entry["walls"].strip(),
            "door": _door_note(entry.get("door"), size), "windows": [], "props": props, "tile": room_box.TILE, "plate": plate}
    seed = room_box._seed(entry.get("seed"))
    if seed is not None:
        spec["seed"] = seed
    return spec


def _door_note(value: Any, size: dict) -> dict | None:
    """The plate's door, in metres from the middle of the back wall: it only keeps people off it; the picture draws it."""
    if value is None:
        return None
    from services import room_box

    if not isinstance(value, dict) or set(value) - room_box._DOOR or value.get("wall", "back") != "back":
        raise ValueError("door is {x, w, h} in metres on the back wall: where the plate's door is (x from the middle, +x toward the left of the frame)")
    door = {"wall": "back", "x": room_box._measure(value.get("x", 0), -size["w"] / 2, size["w"] / 2, "door.x"),
            "w": room_box._measure(value.get("w", 0.9), 0.4, 6, "door.w"), "h": room_box._measure(value.get("h", 2.0), 1.0, size["h"], "door.h")}
    return door
