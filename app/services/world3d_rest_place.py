"""Turn the stored ``beside`` and ``rest`` of a Video 3D scene into plain ``position``, ``rotationY`` and clips.

Run after every binding of a patch (and of the editor's arrange call), over the whole document, so a table that moves
or grows takes its chairs and sitters along. ``beside`` places furniture by the real boxes of both objects (no origins
to compute). ``rest`` seats a rigged character:

1. the seat: ``world3d_seats.seat_surface`` of the ``on`` object, put in the scene with that object's frame;
2. the facing: away from the backrest, else ``facing``, else toward ``at``, else the furniture's front;
3. the hips go over the seat near its front edge, the shins stand upright from the floor, and the slot is placed so
   the character's feet are on the furniture's floor (``grounded`` off: the y is exact, nothing re-grounds the pose);
4. the seated clip: the character's GLB with one more clip baked by ``sit_clip`` for this seat, in the character's own
   units (``model3d.animate`` interactions, the CPU worker), written once as ``world3d-rest/<name>-sit-<hash>.glb`` with
   its ``.humanoid.json`` next to it. The slot shows that file and holds the clip's seated end (a ``clips`` cue whose
   clock stops). The shared character GLB is never rewritten, so other scenes are unaffected; ``rest: null`` gives the
   object back its own file and clip (``restBase``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
from pathlib import Path

import numpy as np

from services.world3d_body_pose import body_of, measures
from services.world3d_mesh_solid import mesh_of
from services.world3d_rest_fields import BASE_FIELDS
from services.world3d_rest_hands import HAND_LIFT_M, Sitter, edge_distance as _edge_distance, resting_hands  # noqa: F401
from services.world3d_scene_bounds import resolve_workspace_glb, slot_native_bounds, slot_native_parts
from services.world3d_seats import seat_surface, table_top
from services.world3d_slot_frame import slot_frame, yaw_of

LOG = logging.getLogger(__name__)
FOLDER = "world3d-rest"
CLIP_NAME = "Rest Sit"
CLIP_SECONDS = 2.0
HOLD_AT = 1.9                 # seated from 1.0 s of the 2 s clip
VERSION = "rest-sit-4"
HIP_ABOVE_SEAT = 0.16         # leg lengths: sit_clip's hips joint over the seat surface
BAKER = None                  # tests replace the worker call (humanoid_animate_runner.execute_animate)


class Furniture:
    """A model object measured for placing: its native box, parts, mesh and scene frame."""

    def __init__(self, slot: dict, workspace: str, workspace_dir) -> None:
        self.slot = slot
        self.box = slot_native_bounds(slot, workspace, workspace_dir)
        self.ok = bool(self.box.get("ok"))
        self.parts = slot_native_parts(slot, workspace, workspace_dir)["parts"] if self.ok else []
        path, _reason = resolve_workspace_glb(slot.get("sourceUrl"), workspace, workspace_dir)
        self.mesh = mesh_of(path) if path is not None else None
        self.frame = slot_frame(slot, self.box) if self.ok else None

    def footprint(self) -> np.ndarray:
        """The four floor corners of the turned box, scene x and z."""
        low, high = self.box["min"], self.box["max"]
        corners = np.array([[x, low[1], z] for x in (low[0], high[0]) for z in (low[2], high[2])])
        return self.frame.to_world(corners)[:, [0, 2]]

    def floor_y(self) -> float:
        low, high = self.box["min"], self.box["max"]
        corners = np.array([[x, y, z] for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])])
        return float(self.frame.to_world(corners)[:, 1].min())


def resolve_placing(document: dict, workspace: str | None, workspace_dir) -> list[str]:
    """Place every ``beside`` (in dependency order), then seat every ``rest``. Returns warnings; refuses unknown targets and cycles."""
    slots = {slot.get("id"): slot for slot in document.get("slots") or [] if isinstance(slot, dict)}
    _check_targets(slots)
    if not workspace or workspace_dir is None:
        return []
    warnings: list[str] = []
    for slot in _beside_order(slots):
        warnings += place_beside(slot, slots[slot["beside"]["object"]], workspace, workspace_dir)
    for slot in [item for item in slots.values() if isinstance(item.get("rest"), dict)]:
        warnings += place_rest(slot, slots, document, workspace, workspace_dir)
    return warnings


def _refuse(code: str, message: str):
    from services.world3d_scenes import World3DSceneError
    return World3DSceneError(code, message)


def _check_targets(slots: dict) -> None:
    models = [key for key, slot in slots.items() if (slot.get("media") or "model3d") == "model3d"]
    for key, slot in slots.items():
        named = [("beside.object", (slot.get("beside") or {}).get("object")), ("rest.on", (slot.get("rest") or {}).get("on")),
                 ("rest.at", (slot.get("rest") or {}).get("at"))]
        for field, target in named:
            if target is not None and target not in models:
                others = ", ".join(str(item) for item in models if item != key) or "none"
                raise _refuse("unknown_object", f"{key}: {field} {target!r} is not a 3D model object of the scene (models: {others})")


def _beside_order(slots: dict) -> list[dict]:
    """Objects with ``beside``, each after the object it stands beside; a cycle is refused."""
    ordered, state = [], {}

    def visit(key: str, chain: tuple) -> None:
        if state.get(key) == "done" or not isinstance(slots[key].get("beside"), dict):
            return
        if key in chain:
            raise _refuse("beside_cycle", "beside goes round in a circle: " + " -> ".join([*chain, key]))
        visit(slots[key]["beside"]["object"], (*chain, key))
        state[key] = "done"
        ordered.append(slots[key])

    for key in slots:
        visit(key, ())
    return ordered


# ------------------------------------------------------------------------------------------------------------------ beside

def place_beside(slot: dict, target: dict, workspace: str, workspace_dir) -> list[str]:
    near = slot["beside"]
    other, mover = Furniture(target, workspace, workspace_dir), Furniture(slot, workspace, workspace_dir)
    if not other.ok or not mover.ok:
        missing = target.get("id") if not other.ok else slot.get("id")
        return [f"beside_unresolved: {slot.get('id')} beside {target.get('id')}: {missing} has no workspace GLB to measure yet"]
    angle = float(target.get("rotationY") or 0) + math.radians(near["side"])
    out = np.array([math.sin(angle), math.cos(angle)])
    slot["rotationY"] = round(_beside_turn(near["facing"], out, mover, target), 6)
    mover = Furniture(slot, workspace, workspace_dir)
    across = np.array([math.cos(angle), -math.sin(angle)])
    theirs, ours = other.footprint(), mover.footprint() - np.asarray(slot.get("position") or [0, 0, 0], dtype=float)[[0, 2]]
    along = float((theirs @ out).max()) + near["gap"] - float((ours @ out).min())
    side = float(((theirs @ across).min() + (theirs @ across).max()) / 2 + near["offset"] - ((ours @ across).min() + (ours @ across).max()) / 2)
    x, z = out * along + across * side
    slot["position"] = [round(float(x), 4), round(other.floor_y(), 4), round(float(z), 4)]
    slot["grounded"] = True
    return []


def _beside_turn(facing, out: np.ndarray, mover: Furniture, target: dict) -> float:
    """``rotationY`` of the mover: its front (away from a backrest, else +z) toward the object, away from it, as the object, or a yaw."""
    if facing == "same":
        return float(target.get("rotationY") or 0)
    if not isinstance(facing, str):
        return math.radians(facing)
    seat = seat_surface(mover.box, mover.frame.factor, mover.mesh, mover.parts)
    front = seat.front if seat is not None and seat.front is not None else [0.0, 1.0]
    wanted = -out if facing == "object" else out
    return yaw_of(wanted) - math.atan2(front[0], front[1])


# -------------------------------------------------------------------------------------------------------------------- rest

def place_rest(slot: dict, slots: dict, document: dict, workspace: str, workspace_dir) -> list[str]:
    """Seat one character on ``rest.on``; the warnings say what could not be done."""
    rest, name = slot["rest"], slot.get("id")
    base = slot.setdefault("restBase", _fresh_base(slot, workspace, workspace_dir))
    source_path, _reason = resolve_workspace_glb(base.get("sourceUrl"), workspace, workspace_dir)
    body = body_of(source_path) if source_path is not None else None
    if body is None:
        return [f"rest_needs_a_rigged_character: {name} has no workspace GLB with the standard humanoid skeleton; bind one (model3d.rig) before rest"]
    seat_slot = slots[rest["on"]]
    furniture = Furniture(seat_slot, workspace, workspace_dir)
    if not furniture.ok:
        return [f"rest_unresolved: {rest['on']} has no workspace GLB to sit on yet"]
    seat = _seat(rest, furniture)
    if seat is None:
        return [f"no_seat_surface: {rest['on']} has no flat face 0.1-1.2 m high and {0.18:g} m wide to sit on; give {name} "
                f"rest {{pose: \"sit\", on: \"{rest['on']}\", surface: {{point: [x, y, z]}}}} (the seat's top, scene metres) or another seat"]
    plan = _seat_plan(slot, body, Path(source_path), furniture, seat, slots, document, workspace, workspace_dir)
    warnings = _seat_notes(name, rest["on"], seat)
    try:
        index = _bake(Path(source_path), plan, workspace, workspace_dir)
    except Exception as error:  # noqa: BLE001 - a failed bake leaves the object as it was and says why
        LOG.exception("rest bake failed")
        return warnings + [f"rest_unresolved: {name} could not be given its seated clip ({error})"]
    _apply(slot, plan, index, workspace)
    return warnings


def _fresh_base(slot: dict, workspace: str, workspace_dir) -> dict:
    """What the object had before it sat. A slot already showing a seated file (copied, or opened from a scene that lost
    its ``restBase``) goes back to the character file that seated file was made from (``.rest.json`` beside it)."""
    base = {key: slot.get(key) for key in BASE_FIELDS}
    path, _reason = resolve_workspace_glb(slot.get("sourceUrl"), workspace, workspace_dir)
    record = path.with_suffix(".rest.json") if path is not None and path.parent.name == FOLDER else None
    if record is not None and record.is_file():
        try:
            original = json.loads(record.read_text(encoding="utf-8")).get("sourceUrl")
        except (OSError, ValueError):
            original = None
        if isinstance(original, str) and original:
            base.update(sourceUrl=original, sourceRef=None, clip=None, clips=None)
    return base


def _seat(rest: dict, furniture: Furniture):
    surface = rest.get("surface")
    if surface and "point" in surface:
        return _point_seat(surface["point"], furniture)
    return seat_surface(furniture.box, furniture.frame.factor, furniture.mesh, furniture.parts, surface)


def _point_seat(point: list, furniture: Furniture):
    from services.world3d_seats import Surface
    native = furniture.frame.to_native([point])[0]
    half = 0.15 / furniture.frame.factor
    return Surface(float(native[1]), [native[0] - half, native[2] - half], [native[0] + half, native[2] + half], "point")


def _seat_notes(name: str, on: str, seat) -> list[str]:
    if not seat.guessed:
        return []
    return [f"seat_surface_guessed: {on} is one mesh; {name} sits on its flat face at {seat.extra.get('heightM', 0):.2f} m found from its "
            f"faces. If that is not the seat give {name} rest {{pose: \"sit\", on: \"{on}\", surface: {{point: [x, y, z]}}}} (scene metres)"]


def _seat_plan(slot: dict, body, source: Path, furniture: Furniture, seat, slots: dict, document: dict, workspace: str, workspace_dir) -> dict:
    """Where the hips, the feet and the slot go, in the character's own units and in the scene."""
    frame = furniture.frame
    rect = frame.to_world([[seat.low[0], seat.y, seat.low[1]], [seat.high[0], seat.y, seat.low[1]],
                           [seat.high[0], seat.y, seat.high[1]], [seat.low[0], seat.y, seat.high[1]]])
    seat.extra["heightM"] = float(rect[:, 1].mean() - furniture.floor_y())
    facing = _facing(slot["rest"], seat, frame, rect, slots, document, workspace, workspace_dir)
    rest_joints = body.pose()
    size = measures(rest_joints)
    char_box = slot_native_bounds({"sourceUrl": slot["restBase"]["sourceUrl"]}, workspace, workspace_dir)
    factor = (1.7 / max(char_box["size"][1], 1e-3)) * float(slot.get("scale") or 1)
    point = _contact(rect, facing, size["thigh"] * factor)
    floor = furniture.floor_y()
    seat_up = (float(point[1]) - floor) / factor                                   # model units above the soles
    hips = rest_joints["Hips"]
    hip_y = body.box_low + seat_up + HIP_ABOVE_SEAT * size["leg"]
    thigh_y = hip_y - (hips[1] - (rest_joints["LeftUpLeg"][1] + rest_joints["RightUpLeg"][1]) / 2)
    knee_y = float((rest_joints["LeftLeg"][1] + rest_joints["RightLeg"][1]) / 2)
    reach = math.sqrt(max(size["thigh"] ** 2 - (thigh_y - knee_y) ** 2, (0.3 * size["thigh"]) ** 2))
    ankle_forward = float((rest_joints["LeftFoot"][2] + rest_joints["RightFoot"][2]) / 2) * body.facing
    seat_model = np.array([hips[0], body.box_low + seat_up, (ankle_forward - reach) * body.facing])
    yaw = yaw_of(facing) + (math.pi if body.facing < 0 else 0.0)
    turned = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    offset = turned @ (seat_model * factor)
    position = [float(point[0] - offset[0]), floor - body.box_low * factor, float(point[2] - offset[2])]
    sitter = Sitter(rest_joints, seat_model + np.array([0, HIP_ABOVE_SEAT * size["leg"], 0]) - hips, ankle_forward * body.facing,
                    float(seat_model[1]), size, facing, np.asarray(position), turned, factor)
    hands = _hands(slot["rest"], sitter, rect, slots, workspace, workspace_dir)
    return {"seat": seat_model, "hands": hands, "position": position, "yaw": yaw, "source": source, "base": slot["restBase"]}


def _facing(rest: dict, seat, frame, rect: np.ndarray, slots: dict, document: dict, workspace: str, workspace_dir) -> np.ndarray:
    """The scene floor direction the sitter faces."""
    if seat.front is not None and rest.get("facing") is None:
        return frame.direction(seat.front)
    centre = rect.mean(axis=0)[[0, 2]]
    if isinstance(rest.get("facing"), float):
        angle = math.radians(rest["facing"])
        return np.array([math.sin(angle), math.cos(angle)])
    table = slots.get(rest.get("at")) if rest.get("at") else None
    if table is not None:
        toward = Furniture(table, workspace, workspace_dir)
        if toward.ok:
            direction = toward.footprint().mean(axis=0) - centre
            if np.linalg.norm(direction) > 1e-6:
                direction = direction / np.linalg.norm(direction)
                return -direction if rest.get("facing") == "away" else direction
    return _open_side(seat, frame, centre, document)


def _open_side(seat, frame, centre: np.ndarray, document: dict) -> np.ndarray:
    """No backrest and nothing to face: the furniture's front (+z), or on a long seat (a bed) the long side nearest the camera."""
    width, depth = seat.size
    if depth <= 1.25 * width:
        return frame.direction([0.0, 1.0])
    eye = (document.get("camera") or {}).get("eye")
    sides = [frame.direction([1.0, 0.0]), frame.direction([-1.0, 0.0])]
    if not (isinstance(eye, list) and len(eye) == 3):
        return sides[0]
    toward = np.array([float(eye[0]), float(eye[2])]) - centre
    return max(sides, key=lambda side: float(side @ toward))


def _contact(rect: np.ndarray, facing: np.ndarray, thigh_m: float) -> np.ndarray:
    """The point of the seat under the hips: centred across, inset from the front edge along ``facing``."""
    centre = rect.mean(axis=0)
    flat = rect[:, [0, 2]] - centre[[0, 2]]
    half = float((flat @ facing).max())
    inset = min(max(0.6 * thigh_m, 0.06), max(2 * half - 0.1, half))
    point = centre.copy()
    point[[0, 2]] += facing * (half - inset)
    return point


def _hands(rest: dict, sitter: Sitter, seat_rect: np.ndarray, slots: dict, workspace: str, workspace_dir) -> list | None:
    """``rest.hands``: on the table of ``at``, else beside the hips on a wide seat, else on the thighs (``world3d_rest_hands``)."""
    corners = None
    table = Furniture(slots[rest["at"]], workspace, workspace_dir) if rest.get("at") and rest.get("hands") is not False else None
    top = table_top(table.box, table.frame.factor, table.mesh, table.parts) if table is not None and table.ok else None
    if top is not None:
        corners = table.frame.to_world([[top.low[0], top.y, top.low[1]], [top.high[0], top.y, top.low[1]],
                                        [top.high[0], top.y, top.high[1]], [top.low[0], top.y, top.high[1]]])
    return resting_hands(rest, sitter, seat_rect, corners)


# -------------------------------------------------------------------------------------------------------------------- bake

def _bake(source: Path, plan: dict, workspace: str, workspace_dir) -> int:
    """The derived GLB with the seated clip (made once per character file and seat); returns the clip's index."""
    data = source.read_bytes()
    request = {"seat": [round(float(value), 5) for value in plan["seat"]],
               "hands": None if plan["hands"] is None else [[round(float(value), 5) for value in point] for point in plan["hands"]]}
    digest = hashlib.sha256(data + json.dumps({**request, "v": VERSION}, sort_keys=True).encode()).hexdigest()[:12]
    stem = "".join(char if char.isalnum() or char in "-_" else "-" for char in source.stem)[:48].strip("-_") or "character"
    relative = f"{FOLDER}/{stem}-sit-{digest}.glb"
    target = Path(workspace_dir(workspace)) / relative
    plan["relative"] = relative
    from services.world3d_body_pose import body_of as read_body
    if not target.is_file():
        _write_derived(source, target, {**request, "sourceUrl": plan["base"]["sourceUrl"]})
    body = read_body(target)
    if body is None or CLIP_NAME not in body.clips:
        raise RuntimeError("the seated clip is missing from the derived file")
    return len(body.clips) - 1 - body.clips[::-1].index(CLIP_NAME)


def _write_derived(source: Path, target: Path, request: dict) -> None:
    from services.humanoid_animate_runner import execute_animate
    target.parent.mkdir(parents=True, exist_ok=True)
    interaction = {"kind": "sit", "seat": request["seat"], "duration": CLIP_SECONDS, "name": CLIP_NAME}
    if request["hands"] is not None:
        interaction["hands"] = request["hands"]
    temporary = target.with_suffix(".glb.tmp")
    try:
        (BAKER or execute_animate)({"mode": "animate", "source": str(source), "animations": [], "animation_bpm": 120,
                                    "interactions": [interaction]}, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    sidecar = source.with_suffix(".humanoid.json")
    if sidecar.is_file():
        shutil.copyfile(sidecar, target.with_suffix(".humanoid.json"))
    target.with_suffix(".rest.json").write_text(json.dumps({"sourceUrl": request["sourceUrl"]}), encoding="utf-8")


def _apply(slot: dict, plan: dict, index: int, workspace: str) -> None:
    from services.cc0_props import workspace_file_url
    clip = {"index": index, "name": CLIP_NAME}
    slot.update(sourceUrl=workspace_file_url(plan["relative"], workspace), clip=clip, grounded=False,
                position=[round(float(value), 4) for value in plan["position"]], rotationY=round(float(plan["yaw"]), 6),
                clips=[{"clip": dict(clip), "start": 0.0, "offset": HOLD_AT, "duration": 0.01, "loop": False}])
    for key in ("sourceRef", "performance", "inPlace", "motion", "clipPlayback"):
        slot.pop(key, None)
