"""A ``stage-<mold>`` document: the mold staged on ``two-shot`` in Python, field for field as ``stageRoomSet`` does
in the editor, so ``world3d.templates.get``, ``world3d.scene.instantiate`` (and with it a Series ``kind: "3d"`` shot)
and ``world3d.scene.apply_query`` open the same scene the editor would.

The production spec takes the same id: ``resolve_production_stage`` turns ``scene3d.template: "stage-<mold>"`` (with
an optional ``roomCamera`` and ``size``) into the ``two-shot`` + ``background: {room}`` the compiler already reads,
before the browser sees it. A ``background`` the shot names itself (a ``sets`` room with its Qwen skin) is kept.
"""
from __future__ import annotations

import math
from copy import deepcopy

from services.set_molds import light_preset, resolve_mold
from services.world3d_stage_cards import DEFAULT_CAMERA, SUBJECT_ROLES, is_stage, mold_of, speaking_marks

BASE = "two-shot"
DUST_ID = "room-dust"
ENVIRONMENT = {"reflectiveFloor": False, "platform": False, "bloom": 0, "floorStyle": "none"}


def room_of(template_id: str, size: str = "medium", camera: str = DEFAULT_CAMERA) -> dict:
    """``{mold, skin, camera}`` as ``background.room`` carries it: the resolved mold with its own default skin."""
    mold = resolve_mold(mold_of(template_id), size)
    if camera not in {entry["id"] for entry in mold["cameras"]}:
        raise ValueError(f"unknown room camera: {camera}")
    return {"mold": mold, "skin": deepcopy(mold["defaultSkin"]), "camera": camera}


def room_dust(room: dict, duration) -> dict:
    """Low motes over the whole shot, sized to the room (``roomDust`` in roomSet.ts)."""
    width, depth, _height = room["mold"]["dimensions"]
    scale = min(6, max(1.4, math.floor(max(width, depth) / 3 * 100 + 0.5) / 100))
    return {"id": DUST_ID, "kind": "dust", "start": 0, "end": duration, "position": {"x": 0, "y": 0.03, "z": 0},
            "rotation": {"x": 0, "y": 0, "z": 0}, "scale": scale, "intensity": 0.3, "color": "#c4a574", "seed": 7, "sound": False, "volume": 0}


def _room_image(slot: dict) -> dict:
    if slot.get("media") != "image":
        return slot
    surface = slot.get("surface") or "cutout"
    grounded = {"imageLook": {"grounded": True, **(slot.get("imageLook") or {})}} if surface == "cutout" else {}
    return {**slot, "surface": surface, **grounded}


def stage(document: dict, room: dict) -> dict:
    """What ``stageRoomSet`` does to a document: the room, a fixed mold camera, its light preset and the dust."""
    mold = room["mold"]
    named = next(entry for entry in mold["cameras"] if entry["id"] == room["camera"])
    document["room"] = deepcopy(room)
    document["dressing"] = "none"
    document["slots"] = [_room_image(slot) for slot in document["slots"] if slot.get("slot") != "background"]
    document["environment"] = dict(ENVIRONMENT)
    document["camera"] = {"family": "fixed", "eye": list(named["position"]), "look": list(named["lookAt"]), "fov": named["fov"]}
    document["light"] = {"kind": "directional", **light_preset(mold)}
    cues = [cue for cue in document.get("worldSfx") or [] if cue.get("id") != DUST_ID]
    if mold.get("ambient", True):
        cues.append(room_dust(room, document["duration"]))
    if cues:
        document["worldSfx"] = cues
    else:
        document.pop("worldSfx", None)
    return document


def place_subjects(document: dict, mold: dict) -> None:
    """The subject markers on the first speaking marks, as the Series room templates place them."""
    subjects = [slot for slot in document["slots"] if slot.get("slot") in SUBJECT_ROLES]
    for slot, mark in zip(subjects, speaking_marks(mold)):
        slot["position"] = list(mark["position"])
        slot["rotationY"] = mark["facing"] * math.pi / 180


def stage_document(template_id: str, base: dict, *, size: str = "medium", camera: str = DEFAULT_CAMERA) -> dict:
    """``base`` is the compiled ``two-shot`` document (the node tool builds it); the stage keeps nothing else of it."""
    room = room_of(template_id, size, camera)
    document = stage(deepcopy(base), room)
    place_subjects(document, room["mold"])
    document["templateId"] = template_id
    return document


def resolve_production_stage(config):
    """``scene3d.template: "stage-<mold>"`` as the compiler reads it; any other config comes back as it is."""
    if not isinstance(config, dict) or not is_stage(config.get("template")):
        return config
    camera = config.get("roomCamera", DEFAULT_CAMERA)
    resolved = {key: value for key, value in config.items() if key != "size"}
    resolved["template"] = BASE
    if "background" not in resolved:
        resolved["background"] = {"room": room_of(config["template"], config.get("size", "medium"), camera)}
        resolved["roomCamera"] = camera
    return resolved


def stage_camera(config) -> dict | None:
    """The fixed camera a Series stage shot picks with ``roomCamera``; None when the shot is not on a stage id."""
    if not isinstance(config, dict) or not is_stage(config.get("template")) or not config.get("roomCamera"):
        return None
    room = room_of(config["template"], config.get("size", "medium"), config["roomCamera"])
    named = next(entry for entry in room["mold"]["cameras"] if entry["id"] == room["camera"])
    return {"family": "fixed", "eye": list(named["position"]), "look": list(named["lookAt"]), "fov": named["fov"]}
