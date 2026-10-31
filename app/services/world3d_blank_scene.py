"""A blank Video 3D starting point: the smallest document the editor opens, instantiates, inspects, patches and publishes.

An agent that wants to build a scene from nothing registers this as a personal template, then runs the usual flow::

    world3d.templates.user.put   {id: "user-blank-stage", title: "Blank stage", document: <blank_document()>}
    world3d.scene.instantiate    {template_id: "user-blank-stage"}
    world3d.scene.patch          {bindings: [{object_id: "tower", add: true, source_url: ..., fit: {heightM: 30}}], camera: {...}}
    world3d.scene.publish        -> opens in the Video 3D editor

Why a recipe and not a shipped card: the built-in cards are compiled from the UI's TypeScript templates and the catalogue
file is checked against them, so a card for a blank stage needs a TypeScript template. A personal template needs none.

The Python gate for a personal template only asks for a ``slots`` list, and the publish gate is looser than the editor's
(``DocumentInput``); the editor refuses a light without ``kind: "directional"`` or an fps outside 24/30/60 and shows
"Invalid Video3D scene". ``editor_shape_problems`` mirrors the editor's shape gate (``validScene3DShape`` in
ui/src/features/scene3d/documentValidation.ts) so a document can be checked without a browser.
"""
from __future__ import annotations

import math

from services.world3d_world_fx import world_fx_problems

ROLES = ("subject_1", "subject_2", "prop", "background")
CAMERA_FAMILIES = ("fixed", "establishment", "follow", "orbit", "reveal", "encounter", "pursuit", "product", "musical", "side",
                   "front", "chase", "hood", "wing")
FPS = (24, 30, 60)
MAX_SLOTS = 64
DEFAULT_CAMERA = {"family": "fixed", "eye": [0, 1.6, 6], "look": [0, 1, 0], "fov": 45}
DEFAULT_LIGHT = {"kind": "directional", "direction": [-0.4, -1, -0.3], "intensity": 1.2, "color": "#ffffff"}


def blank_document(*, width: int = 1280, height: int = 720, fps: int = 30, duration: float = 5, camera: dict | None = None,
                   light: dict | None = None, markers: list[tuple[str, str]] | None = None) -> dict:
    """An empty stage: a fixed camera on the origin, one sun and no objects. ``markers`` are optional ``(id, role)`` empty
    model objects for a cast (``subject_1``) the agent will bind; any other object is added later with ``add: true`` as a prop."""
    document = {
        "version": 1, "units": "meters", "up": "y", "templateId": "two-shot", "width": width, "height": height, "fps": fps,
        "duration": duration, "camera": dict(camera or DEFAULT_CAMERA), "light": dict(light or DEFAULT_LIGHT),
        "slots": [marker_slot(identifier, role) for identifier, role in markers or []],
    }
    problems = editor_shape_problems(document)
    if problems:
        raise ValueError("; ".join(problems))
    return document


def marker_slot(identifier: str, role: str = "prop") -> dict:
    """An empty 3D model object (a marker): it shows as a placeholder until a GLB is bound to it."""
    return {"id": identifier, "slot": role, "position": [0, 0, 0], "rotationY": 0, "scale": 1, "sourceUrl": "", "media": "model3d", "clip": None}


def blank_template_row(template_id: str = "user-blank-stage", title: str = "Blank stage", **document_fields) -> dict:
    """The input of ``world3d.templates.user.put`` for a blank stage."""
    return {"id": template_id, "title": title, "description": "An empty stage: camera, light and no objects.",
            "document": blank_document(**document_fields)}


WARNING = "editor_would_refuse"
MAX_WARNINGS = 8
WARNING_DOC = ("warnings may carry editor_would_refuse: <problem> when the document would not open in the Video 3D editor "
               "(a light without kind \"directional\", an fps outside 24/30/60...). Nothing is refused: fix it with a patch or a better template.")


def editor_warnings(document) -> list[str]:
    """``editor_shape_problems`` as warning strings for a reply (at most ``MAX_WARNINGS``, the rest counted). Never refuses."""
    problems = editor_shape_problems(document)
    shown = [f"{WARNING}: {problem}" for problem in problems[:MAX_WARNINGS]]
    return shown + ([f"{WARNING}: {len(problems) - MAX_WARNINGS} more"] if len(problems) > MAX_WARNINGS else [])


def editor_shape_problems(document) -> list[str]:
    """What the Video 3D editor's shape gate would refuse in a document, in words; ``[]`` when it opens.

    Checks the gate's own rules: version, units, up, size, fps, duration, camera, light and the objects' basics, plus a
    framing target that exists. The deeper checks of a framing move, a camera shake, a room or a box room are not mirrored."""
    if not isinstance(document, dict):
        return ["the document is not an object"]
    problems = []
    if document.get("version") != 1 or document.get("units") != "meters" or document.get("up") != "y":
        problems.append("needs version 1, units meters and up y")
    for key in ("width", "height", "duration"):
        if not _positive(document.get(key)):
            problems.append(f"{key} must be a number above 0")
    if _positive(document.get("duration")) and document["duration"] > 600:
        problems.append("duration is at most 600 seconds")
    if document.get("fps") not in FPS:
        problems.append("fps must be 24, 30 or 60")
    problems += _camera_problems(document.get("camera")) + _light_problems(document.get("light"))
    problems += _slots_problems(document.get("slots"), document.get("camera"))
    return problems + world_fx_problems(document)


def _finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _positive(value) -> bool:
    return _finite(value) and value > 0


def _whole(value) -> bool:
    """Number.isInteger(value) && value >= 0 (JSON may carry 1.0)."""
    return _finite(value) and value >= 0 and float(value).is_integer()


def _vector(value) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(_finite(item) for item in value)


def _camera_problems(camera) -> list[str]:
    if not isinstance(camera, dict):
        return ["camera is missing"]
    problems = []
    if not _vector(camera.get("eye")) or not _vector(camera.get("look")):
        problems.append("camera.eye and camera.look are [x, y, z] numbers")
    if not _positive(camera.get("fov")) or camera["fov"] >= 180:
        problems.append("camera.fov is above 0 and below 180")
    if camera.get("family") not in CAMERA_FAMILIES:
        problems.append("camera.family is not a known family")
    return problems


def _light_problems(light) -> list[str]:
    if not isinstance(light, dict):
        return ["light is missing"]
    direction = light.get("direction")
    ok = (light.get("kind") == "directional" and _vector(direction) and any(direction) and _finite(light.get("intensity"))
          and light["intensity"] >= 0 and isinstance(light.get("color"), str))
    return [] if ok else ['light must be {kind: "directional", direction [x, y, z] not all zero, intensity >= 0, color "#rrggbb"}']


def _slots_problems(slots, camera) -> list[str]:
    if not isinstance(slots, list):
        return ["slots is missing"]
    problems = [] if len(slots) <= MAX_SLOTS else [f"at most {MAX_SLOTS} objects"]
    ids = [slot.get("id") if isinstance(slot, dict) else None for slot in slots]
    for index, slot in enumerate(slots):
        problems += [f"slots[{index}]: {text}" for text in _slot_problems(slot)]
    if len(set(ids)) != len(ids):
        problems.append("object ids must be unique")
    target = (camera.get("framing") or {}).get("targetSlot") if isinstance(camera, dict) and isinstance(camera.get("framing"), dict) else None
    if target is not None and target not in ids:
        problems.append(f"camera.framing.targetSlot {target!r} is not an object of the scene")
    return problems


def _motion_lost(motion) -> bool:
    return motion is not None and not (isinstance(motion, dict) and _vector(motion.get("to")))


def _clip_problem(slot) -> str | None:
    clip = slot.get("clip")
    if clip is not None and not (isinstance(clip, dict) and _whole(clip.get("index")) and isinstance(clip.get("name"), str)):
        return "clip is null or {index, name}"
    return None


def _slot_problems(slot) -> list[str]:
    if not isinstance(slot, dict) or not isinstance(slot.get("id"), str) or not slot["id"]:
        return ["needs a text id"]
    problems = []
    if not _vector(slot.get("position")) or not _positive(slot.get("scale")) or not _finite(slot.get("rotationY")):
        problems.append("needs position [x, y, z], a scale above 0 and a rotationY")
    for key in ("rotationX", "rotationZ"):
        if key in slot and not _finite(slot.get(key)):
            problems.append(f"{key} must be a finite number of radians")
    if slot.get("slot") not in ROLES:
        problems.append(f"slot must be one of {', '.join(ROLES)}")
    if _motion_lost(slot.get("motion")):
        problems.append("motion needs to [x, y, z]; the editor drops a move without it")
    clip_problem = _clip_problem(slot)
    if clip_problem:
        problems.append(clip_problem)
    return problems
