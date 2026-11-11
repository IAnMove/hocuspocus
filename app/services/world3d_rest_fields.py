"""The declarative placing fields of a ``world3d.scene.patch`` binding: ``height``, ``beside`` and ``rest``.

They say what is meant instead of where it lands, and the server works out the numbers (``world3d_rest_place``):

- ``height: 0.75`` this object is really 0.75 m tall. It is ``fit: {heightM: 0.75}`` (every model is drawn 1.7 m x
  ``scale``), so it sets ``scale`` and is not stored; inspect shows the real size as ``layout.items[].boundsM.size``.
- ``beside: {object, side?, gap?, offset?, facing?}`` stand next to another object on one side of its box, on its floor.
  ``side`` is degrees around it from its front (+z, turned with it) toward its right (+x seen from the front), or
  ``front`` (0), ``right`` (90), ``back`` (180), ``left`` (270); ``gap`` metres between the boxes (default 0, negative
  tucks in); ``offset`` metres along that side (toward +90 degrees); ``facing`` ``object`` (default: its front toward
  the object), ``away``, ``same`` (the object's turn) or degrees (a scene yaw).
- ``rest: {pose: "sit", on, at?, surface?, facing?, hands?}`` a character sits on ``on``: hips on its seat, feet on the
  floor, facing away from its backrest (or toward ``at``, or ``facing`` in scene degrees), held seated for the whole shot.
  ``at`` is the table (desk, bar) it sits at: the reply checks the top against its hips and chest and its reach, and puts
  both hands on the top unless ``hands: false``. ``surface: {part: <name or index>}`` or ``{point: [x, y, z]}`` names the
  seat when the finder cannot.

``beside`` and ``rest`` are stored on the object and resolved again on every patch (a moved table takes its chairs and
sitters along); ``null`` removes them (a sitter stands up and gets its own model and clip back). A binding that gives
``position``, ``rotationY`` or ``motion`` (and, for ``rest``, ``clip`` or ``clips``) without restating the field drops it:
the explicit numbers win.
"""
from __future__ import annotations

import math

SIDES = {"front": 0.0, "right": 90.0, "back": 180.0, "left": 270.0}
BESIDE_FACINGS = ("object", "away", "same")
REST_POSES = ("sit",)
REST_FACINGS = ("at", "away")
_BESIDE_KEYS = {"object", "side", "gap", "offset", "facing"}
_REST_KEYS = {"pose", "on", "at", "surface", "facing", "hands"}
_PLACING = ("position", "rotationY", "rotation_y", "motion")
_CLIP_FIELDS = ("clip", "clips")
BASE_FIELDS = ("sourceUrl", "sourceRef", "clip", "clips", "clipPlayback", "grounded", "performance", "inPlace", "motion")
DECLARED = ("beside", "rest")
SEATED_RECIPE = ("People seated at a table or on a bed, by intent (no coordinates to compute): 1) the furniture, "
                 "{object_id: \"table\", add: true, furniture: {kind: \"table\"}} (or any workspace GLB with height in metres); 2) seats "
                 "beside it, {object_id: \"chair_1\", add: true, furniture: {kind: \"chair\"}, beside: {object: \"table\", side: \"left\"}}; "
                 "3) each character at its real height and seated, {object_id: \"ana\", height: 1.62, rest: {pose: \"sit\", on: \"chair_1\", "
                 "at: \"table\"}}; 4) read layout.contacts and the warnings and apply every fix binding (seat and table heights for short "
                 "legs, beside gap) until none is left. On the edge of a bed: rest {pose: \"sit\", on: \"bed\"}.")
PLACING_DOC = ("height: metres, the object's real height (the same as fit {heightM}). beside: {object, side? degrees around it from its "
               "front toward its right, or front|right|back|left, gap? m between the boxes (negative tucks in), offset? m along that side, "
               "facing? object|away|same|degrees}: stands next to another object on its floor (chairs round a table, a bedside table). "
               "rest: {pose: sit, on: <seat object>, at?: <table object>, surface? {part} | {point [x,y,z]}, facing? degrees|at|away, "
               "hands? (default true with at)}: a character sits on the seat with its feet on the floor and holds it for the shot; the "
               "server sets its position, turn and a held seated clip from its own legs (no coordinates needed). beside and rest are kept "
               "and re-solved on every patch; null removes them; giving position, rotationY or motion drops them. Replies list "
               "layout.contacts per character (pose, seat, table, limbs inside furniture) with fix: bindings to paste.")


def _refuse(code: str, message: str):
    from services.world3d_scenes import World3DSceneError
    return World3DSceneError(code, message)


def _number(value, low: float, high: float) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def height_fit(slot: dict, binding: dict) -> dict | None:
    """``height`` as the ``fit`` binding it is, or None. Refuses it with ``fit`` or ``scale``."""
    if "height" not in binding:
        return None
    value = binding["height"]
    if any(key in binding for key in ("fit", "scale")):
        raise _refuse("invalid_fit", f"{slot.get('id')}: give height, fit or scale in a binding, not two of them")
    if not _number(value, 0.01, 10_000) or value <= 0:
        raise _refuse("invalid_height", f"{slot.get('id')}: height is the object's real height in metres, a number above 0 "
                      "(it sets scale; inspect shows it as boundsM.size[1])")
    return {"fit": {"heightM": float(value)}}


def bind_declared(slot: dict, binding: dict, workspace: str | None, workspace_dir) -> list[str]:
    """``beside``, ``rest``, ``furniture`` and ``height`` (or ``fit``) of one binding, after its plain fields are on the slot."""
    from services.world3d_furniture import bind_furniture
    from services.world3d_scene_fit import apply_fit
    bind_placing(slot, binding)
    bind_furniture(slot, binding, workspace, workspace_dir)
    return apply_fit(slot, height_fit(slot, binding) or binding, workspace, workspace_dir)


def bind_placing(slot: dict, binding: dict) -> None:
    """Drop declarations an explicit placement replaces, then check and store ``beside`` and ``rest`` (``null`` removes)."""
    _release(slot, binding)
    if isinstance(slot.get("restBase"), dict) and ("sourceUrl" in binding or "source_url" in binding):
        slot["restBase"]["sourceUrl"] = slot.get("sourceUrl")       # another character sits in its place
    if "beside" in binding:
        slot.pop("beside", None)
        if binding["beside"] is not None:
            slot["beside"] = beside(binding["beside"], slot)
    if "rest" in binding:
        if binding["rest"] is None:
            stand_up(slot, binding)
        else:
            if any(key in binding for key in ("motion",)) and binding.get("motion") is not None:
                raise _refuse("invalid_rest", f"{slot.get('id')}: an object that rests cannot also move; give rest or motion")
            slot["rest"] = rest(binding["rest"], slot)


def _release(slot: dict, binding: dict) -> None:
    placed = any(key in binding for key in _PLACING)
    if slot.get("beside") and placed and "beside" not in binding:
        slot.pop("beside", None)
    if slot.get("rest") and "rest" not in binding and (placed or any(key in binding for key in _CLIP_FIELDS)):
        stand_up(slot, binding)


def stand_up(slot: dict, binding: dict) -> None:
    """Forget ``rest`` and give back what the object had before it sat (its model, clip, grounding), except what ``binding`` sets."""
    slot.pop("rest", None)
    base = slot.pop("restBase", None)
    if not isinstance(base, dict):
        return
    for key in BASE_FIELDS:
        if key in binding or _snake(key) in binding:
            continue
        if base.get(key) is not None or key == "clip":          # a slot always carries clip, null when it has none
            slot[key] = base.get(key)
        else:
            slot.pop(key, None)


def _snake(key: str) -> str:
    return "".join(f"_{char.lower()}" if char.isupper() else char for char in key)


def beside(value, slot: dict) -> dict:
    """The stored ``beside``: ``{object, side (degrees), gap, offset, facing}``."""
    name = slot.get("id")
    if not isinstance(value, dict) or set(value) - _BESIDE_KEYS:
        raise _refuse("invalid_beside", f"{name}: beside is {{object, side?, gap?, offset?, facing?}}")
    target = value.get("object")
    if not isinstance(target, str) or not target or target == name:
        raise _refuse("invalid_beside", f"{name}: beside.object is the id of another object of the scene")
    side = value.get("side", 0.0)
    side = SIDES.get(side, side) if isinstance(side, str) else side
    if not _number(side, -360, 360):
        raise _refuse("invalid_beside", f"{name}: beside.side is degrees (-360 to 360) or front, right, back, left")
    for key, low, high in (("gap", -2.0, 10.0), ("offset", -10.0, 10.0)):
        if value.get(key) is not None and not _number(value[key], low, high):
            raise _refuse("invalid_beside", f"{name}: beside.{key} is {low:g} to {high:g} metres")
    facing = value.get("facing", "object")
    if facing not in BESIDE_FACINGS and not _number(facing, -360, 360):
        raise _refuse("invalid_beside", f"{name}: beside.facing is object, away, same or degrees")
    return {"object": target, "side": float(side) % 360, "gap": float(value.get("gap") or 0.0), "offset": float(value.get("offset") or 0.0),
            "facing": facing if isinstance(facing, str) else float(facing)}


def rest(value, slot: dict) -> dict:
    """The stored ``rest``: ``{pose, on, at?, surface?, facing?, hands?}``."""
    name = slot.get("id")
    if (slot.get("media") or "model3d") != "model3d" or slot.get("hold"):
        raise _refuse("invalid_rest", f"{name}: rest seats a 3D character that is not held in a hand")
    if not isinstance(value, dict) or set(value) - _REST_KEYS:
        raise _refuse("invalid_rest", f"{name}: rest is {{pose: sit, on, at?, surface?, facing?, hands?}}")
    if value.get("pose", "sit") not in REST_POSES:
        raise _refuse("invalid_rest", f"{name}: rest.pose is sit (lying and standing at a counter are not made yet)")
    stored = {"pose": "sit"}
    for key in ("on", "at"):
        target = value.get(key)
        if target is None and key == "at":
            continue
        if not isinstance(target, str) or not target or target == name:
            raise _refuse("invalid_rest", f"{name}: rest.{key} is the id of another object of the scene")
        stored[key] = target
    if value.get("surface") is not None:
        stored["surface"] = _surface(value["surface"], name)
    facing = value.get("facing")
    if facing is not None:
        if facing not in REST_FACINGS and not _number(facing, -360, 360):
            raise _refuse("invalid_rest", f"{name}: rest.facing is degrees (0 faces +z), at or away")
        stored["facing"] = facing if isinstance(facing, str) else float(facing)
    if value.get("hands") is not None:
        if not isinstance(value["hands"], bool):
            raise _refuse("invalid_rest", f"{name}: rest.hands is true or false")
        stored["hands"] = value["hands"]
    return stored


def _surface(value, name) -> dict:
    if isinstance(value, dict) and set(value) == {"part"} and (isinstance(value["part"], str) and value["part"] or type(value["part"]) is int):
        return {"part": value["part"]}
    point = value.get("point") if isinstance(value, dict) and set(value) == {"point"} else None
    if isinstance(point, list) and len(point) == 3 and all(_number(item, -10_000, 10_000) for item in point):
        return {"point": [float(item) for item in point]}
    raise _refuse("invalid_rest", f"{name}: rest.surface is {{part: <name or index>}} or {{point: [x, y, z]}} in scene metres")


def referenced(document: dict, object_id: str) -> list[str]:
    """The objects whose ``beside`` or ``rest`` names ``object_id``."""
    found = []
    for slot in document.get("slots") or []:
        near, resting = slot.get("beside") or {}, slot.get("rest") or {}
        if object_id in (near.get("object"), resting.get("on"), resting.get("at")):
            found.append(str(slot.get("id")))
    return found
