"""Does a moving Video 3D object pass through something? Warnings from the scene's own numbers, without rendering.

A first film had a toy biplane fly through a house and nothing said so. For each object that moves (``motion``) this
samples where it is over the seconds it moves, with the formulas of the renderer (``world3d_scene_motion``), and compares
its box with the *parts* of every other object (``glb_parts``: one box per mesh node, so a village is its houses and not
one 42 x 17 x 60 m box). A collision is reported when the box sinks deeper than ``MIN_DEPTH_M`` into a part:

    {a: "avioneta", b: "village", part: 28, partName: "House 11", from_s: 2.35, to_s: 3.0, at: [x, y, z], depth_m: 0.33}

``at`` is the middle of the overlap where it is deepest. Nothing is refused: the replies of ``world3d.scene.inspect`` and
``world3d.scene.patch`` carry ``layout.collisions`` and a ``collision: ...`` warning for each, and the author decides
(a ghost or a spirit says ``collide: false`` and is left out; so is an object held in a hand or not yet appeared).

What counts and what does not:

- Two objects that both stand still are the author's placement and are never compared.
- A move is checked only while it runs (``motion.start`` to ``motion.end``): that is when it can pass through something.
- A *ground-like* part (flat, ten times wider than thick, in the lowest quarter of its model: a ground slab, a cobbled
  lane, a rug) is not an obstacle, so a walker standing on a street or a plane above it does not "hit the floor".
- A box is the rest pose of the mesh nodes (``glb_bounds`` says why that is the model's bind pose, not an animation) and
  an axis-aligned box of a node, so a turned or concave part is a little bigger than the thing: a graze is not a hit
  (``MIN_DEPTH_M``), and a window in a wall is not a hole.

``camera_inside_geometry``: a fixed camera whose eye is inside a part's box (an interior shot may be right; the warning says it).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from services.world3d_scene_bounds import normalisation, slot_native_bounds, slot_native_parts
from services.world3d_scene_motion import is_timed, pose_at, window

LOG = logging.getLogger(__name__)
MAX_BODIES = 32
MIN_DEPTH_M = 0.1                 # a graze shallower than this is not a collision (and at most a fifth of the mover's thinnest side)
GROUND_THIN = 0.1                 # a part this much thinner than it is wide ...
GROUND_BAND = 0.25                # ... and in this share of its model's height from the bottom is ground
SAMPLES_PER_SECOND = 60
MIN_SAMPLES, MAX_SAMPLES = 30, 480
MAX_PER_PAIR = 4                  # the deepest passages one object makes through another
MAX_COLLISIONS = 12
MAX_WARNINGS = 6
EYE_TIMES = 3                     # a moving object is checked against the camera at the start, the middle and the end


@dataclass
class Body:
    """A model object that can be hit or hit something: its slot, its native box and parts, and the renderer's factor."""
    slot: dict
    box: dict
    parts: list[dict]
    factor: float
    moving: bool
    ground: set[int] = field(default_factory=set)

    @property
    def id(self) -> str:
        return self.slot["id"]


def scene_collisions(document: dict, workspace: str | None, workspace_dir) -> dict:
    """``{collisions, omitted, warnings}`` of a scene document (``omitted``: passages left out of the cap). Never raises: a scene that cannot be checked reports none."""
    try:
        bodies = _bodies(document, workspace, workspace_dir)
        duration = float(document.get("duration") or 0)
        found, omitted = _collisions(bodies, duration)
        return {"collisions": found, "omitted": omitted, "warnings": [*_collision_warnings(found, omitted), *_camera_warnings(document, bodies, duration)]}
    except Exception:  # noqa: BLE001 - an object that cannot be checked never fails an inspect
        LOG.exception("world3d collision check failed")
        return {"collisions": [], "omitted": 0, "warnings": []}


def _bodies(document: dict, workspace: str | None, workspace_dir) -> list[Body]:
    if not workspace or workspace_dir is None:
        return []
    found = []
    for slot in [item for item in document.get("slots") or [] if isinstance(item, dict)][:MAX_BODIES]:
        body = _body(slot, workspace, workspace_dir)
        if body is not None:
            found.append(body)
    return found


def _body(slot: dict, workspace: str, workspace_dir) -> Body | None:
    if (slot.get("media") or "model3d") != "model3d" or slot.get("collide") is False or slot.get("hold") or not isinstance(slot.get("id"), str):
        return None
    box = slot_native_bounds(slot, workspace, workspace_dir)
    parts = slot_native_parts(slot, workspace, workspace_dir)
    if not box["ok"] or not parts["ok"]:
        return None
    scale = float(slot.get("scale") or 1)
    body = Body(slot, box, parts["parts"], normalisation(box) * scale, _moves(slot))
    body.ground = {part["index"] for part in body.parts if _ground_like(part, box)}
    return body


def _moves(slot: dict) -> bool:
    motion = slot.get("motion")
    if not isinstance(motion, dict) or not isinstance(motion.get("to"), list):
        return False
    here = slot.get("position") or [0, 0, 0]
    return bool(motion.get("via") or motion.get("points") or any(abs(a - b) > 1e-6 for a, b in zip(motion["to"], here)))


def _ground_like(part: dict, box: dict) -> bool:
    """Flat, wide and low in its model: the floor something stands or flies over."""
    size = [part["max"][axis] - part["min"][axis] for axis in range(3)]
    flat = size[1] <= GROUND_THIN * max(size[0], size[2])
    return flat and part["max"][1] - box["min"][1] <= GROUND_BAND * max(box["size"][1], 1e-9)


# ---------------------------------------------------------------------------------------------------------------- placing

def _frame(body: Body, position: list[float], rotation: float) -> tuple:
    """What the renderer does to a model: scale it, turn it about y, move it; a grounded one is lifted so its lowest point sits at ``position[1]``."""
    lift = position[1] - body.box["min"][1] * body.factor if body.slot.get("grounded") else position[1]
    return body.factor, math.cos(rotation), math.sin(rotation), position[0], lift, position[2]


def _place(low: list[float], high: list[float], frame: tuple) -> tuple[list[float], list[float]]:
    """The world box of a native box under a frame (the corners turned about y, so the box grows a little when it turns)."""
    factor, cos, sin, px, lift, pz = frame
    xs, zs = [], []
    for x in (low[0], high[0]):
        for z in (low[2], high[2]):
            xs.append(px + x * factor * cos + z * factor * sin)       # three.js rotation.y: x' = x cos + z sin, z' = -x sin + z cos
            zs.append(pz - x * factor * sin + z * factor * cos)
    return [min(xs), low[1] * factor + lift, min(zs)], [max(xs), high[1] * factor + lift, max(zs)]


def _overlap(a: tuple, b: tuple) -> list[float] | None:
    """How far the boxes sink into each other on each axis, or None while they do not touch."""
    depth = [min(a[1][axis], b[1][axis]) - max(a[0][axis], b[0][axis]) for axis in range(3)]
    return depth if all(value > 0 for value in depth) else None


def _middle(a: tuple, b: tuple) -> list[float]:
    return [(max(a[0][axis], b[0][axis]) + min(a[1][axis], b[1][axis])) / 2 for axis in range(3)]


def _visible(body: Body, seconds: float) -> bool:
    appearance = body.slot.get("appearance")
    start = appearance.get("start") if isinstance(appearance, dict) else None
    return not isinstance(start, (int, float)) or seconds >= start


# ------------------------------------------------------------------------------------------------------------- collisions

def _times(body: Body, duration: float) -> list[float]:
    """The seconds a move is checked at: evenly from ``motion.start`` to ``motion.end`` (inside the scene), including both."""
    start, end = window(body.slot["motion"], duration)
    start, end = max(0.0, min(start, duration)), max(0.0, min(end, duration))
    count = max(MIN_SAMPLES, min(MAX_SAMPLES, math.ceil((end - start) * SAMPLES_PER_SECOND)))
    return [start + (end - start) * index / count for index in range(count + 1)]


def _collisions(bodies: list[Body], duration: float) -> tuple[list[dict], int]:
    hits: list[dict] = []
    for position, mover in enumerate(bodies):
        if not mover.moving:
            continue
        others = [other for index, other in enumerate(bodies) if other is not mover and not (other.moving and index < position)]
        hits += _passes(mover, others, duration)
    return _report(hits)


def _passes(mover: Body, others: list[Body], duration: float) -> list[dict]:
    """Every sample at which ``mover`` is sunk into a part of ``others``: ``{a, b, part, partName, i, t, depth, at}``."""
    resting = {other.id: _solid(other, 0.0, 0.0) for other in others if not other.moving}
    hits = []
    for number, seconds in enumerate(_times(mover, duration)):
        if not _visible(mover, seconds):
            continue
        position, rotation = pose_at(mover.slot, seconds, duration)
        box = _place(mover.box["min"], mover.box["max"], _frame(mover, position, rotation))
        floor = min(MIN_DEPTH_M, 0.2 * min(high - low for low, high in zip(*box)))
        for other in others:
            if _visible(other, seconds):
                whole, parts = resting[other.id] if other.id in resting else _solid(other, seconds, duration)
                if _overlap(box, whole) is not None:
                    hits += _sunk(mover, other, box, parts, floor, (number, seconds))
    return hits


def _solid(body: Body, seconds: float, duration: float) -> tuple[tuple, list[tuple]]:
    """``(world box, [(part, world box)])`` of a body at a time; ground-like parts are not obstacles."""
    position, rotation = pose_at(body.slot, seconds, duration)
    frame = _frame(body, position, rotation)
    whole = _place(body.box["min"], body.box["max"], frame)
    return whole, [(part, _place(part["min"], part["max"], frame)) for part in body.parts if part["index"] not in body.ground]


def _sunk(mover: Body, other: Body, box: tuple, parts: list[tuple], floor: float, sample: tuple[int, float]) -> list[dict]:
    hits = []
    for part, part_box in parts:
        depth = _overlap(box, part_box)
        if depth is not None and min(depth) >= floor:
            hits.append({"a": mover.id, "b": other.id, "part": part["index"], "partName": part.get("name"), "i": sample[0], "t": sample[1],
                         "depth": min(depth), "at": _middle(box, part_box)})
    return hits


def _report(hits: list[dict]) -> tuple[list[dict], int]:
    """Samples one after another in the same part become one passage; the deepest passages of each pair are kept."""
    passages: dict[tuple, list[dict]] = {}
    for hit in hits:
        runs = passages.setdefault((hit["a"], hit["b"], hit["part"]), [])
        if runs and hit["i"] - runs[-1]["i"] <= 1:
            _extend(runs[-1], hit)
        else:
            runs.append({**hit, "from": hit["t"], "to": hit["t"], "seen": [hit]})
    return _kept([_deepest(run) for runs in passages.values() for run in runs])


def _extend(run: dict, hit: dict) -> None:
    run["i"], run["to"] = hit["i"], hit["t"]
    run["seen"].append(hit)


def _deepest(run: dict) -> dict:
    """The passage's depth and place: where it sank deepest, the middle of that stretch when it stayed as deep for a while."""
    top = max(hit["depth"] for hit in run["seen"])
    deepest = [hit for hit in run["seen"] if hit["depth"] >= top - 1e-6]
    middle = deepest[len(deepest) // 2]
    return {**run, "depth": top, "at": middle["at"]}


def _kept(runs: list[dict]) -> tuple[list[dict], int]:
    pairs: dict[tuple, int] = {}
    chosen = []
    for run in sorted(runs, key=lambda item: -item["depth"]):
        pair = (run["a"], run["b"])
        if pairs.get(pair, 0) < MAX_PER_PAIR:
            pairs[pair] = pairs.get(pair, 0) + 1
            chosen.append(run)
    shown = sorted(chosen, key=lambda item: (item["from"], -item["depth"]))[:MAX_COLLISIONS]
    return [_row(run) for run in shown], len(runs) - len(shown)


def _row(run: dict) -> dict:
    row = {"a": run["a"], "b": run["b"], "part": run["part"], "from_s": round(run["from"], 3), "to_s": round(run["to"], 3),
           "at": [round(value, 3) for value in run["at"]], "depth_m": round(run["depth"], 3)}
    if run.get("partName"):
        row["partName"] = run["partName"]
    return row


def _collision_warnings(found: list[dict], omitted: int) -> list[str]:
    lines = [f"collision: {row['a']} passes through {row['b']} (part {row['part']}{_named(row)}) at {row['from_s']:g}-{row['to_s']:g} s "
             f"near {[round(value, 1) for value in row['at']]}, {row['depth_m']:g} m deep; fix the path, move {row['b']}, or give {row['a']} collide: false"
             for row in found[:MAX_WARNINGS]]
    more = len(found) - MAX_WARNINGS if len(found) > MAX_WARNINGS else 0
    rest = more + omitted
    return lines + ([f"collision: {rest} more passages ({more} listed in layout.collisions, {omitted} beyond its cap)"] if rest else [])


def _named(row: dict) -> str:
    return f' "{row["partName"]}"' if row.get("partName") else ""


# ----------------------------------------------------------------------------------------------------------------- camera

def _camera_warnings(document: dict, bodies: list[Body], duration: float) -> list[str]:
    eye = _fixed_eye(document)
    if eye is None:
        return []
    seen = []
    for body in bodies:
        found = _inside(body, eye, duration)
        if found is not None:
            seen.append(f"camera_inside_geometry: the fixed camera's eye {[round(float(v), 2) for v in eye]} is inside {body.id} "
                        f"(part {found['index']}{_named({'partName': found.get('name')})}); move the camera or the object (an interior shot may be meant)")
    return seen[:MAX_WARNINGS]


def _fixed_eye(document: dict) -> list | None:
    """The eye of a fixed camera (the one family whose eye is the document's own); None for the others."""
    camera = document.get("camera")
    eye = camera.get("eye") if isinstance(camera, dict) and camera.get("family") == "fixed" else None
    ok = isinstance(eye, list) and len(eye) == 3 and all(isinstance(item, (int, float)) and math.isfinite(item) for item in eye)
    return eye if ok else None


def _inside(body: Body, eye: list, duration: float) -> dict | None:
    """The first part whose box holds the eye, when the body is at the start (a mover: also the middle and the end)."""
    times = [duration * index / (EYE_TIMES - 1) for index in range(EYE_TIMES)] if body.moving else [0.0]
    return next((part for seconds in times if _visible(body, seconds) for part in _eye_in(body, eye, seconds, duration)), None)


def _eye_in(body: Body, eye: list, seconds: float, duration: float) -> list[dict]:
    return [part for part, part_box in _solid(body, seconds, duration)[1]
            if all(part_box[0][axis] <= eye[axis] <= part_box[1][axis] for axis in range(3))]
