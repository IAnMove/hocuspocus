"""Is everyone where the author meant? Warnings from the scene's own numbers, with the corrected value, without rendering.

``world3d_scene_collisions`` looks at things that move. The defects of a staged room are static: a sleeper sunk into the bed, a
body that hangs half a metre past the end of its couch, a person under the floor, a subject the camera cuts in half or shows as
a dot. A picture shows them to a reviewer for thousands of tokens; the numbers show them to the author for a few. The replies of
``world3d.scene.inspect`` and ``world3d.scene.patch`` carry ``layout.placement`` (a list of issues) and a ``placement_<code>: ...``
warning for each. Every issue says what is wrong and, when it can, **the position that fixes it**, so one patch repairs it:

    {code: "sinks_into_support", id: "subject_1", support: "bed", detail: "lowest point 0.41 is 0.14 m under the top of bed (0.55)", fix: {position: [0, 0.72, -1.3]}}

Codes: ``outside_room``, ``sinks_into_support``, ``overhangs_support``, ``below_floor``, ``floating``, ``cropped``, ``tiny``.

A *support* is a room block or another prop (not a character) whose top is within ``REST_BAND`` of the lowest point of the object and
that it overlaps from above. A person lowered into a seat (a model with no sit clip) is *meant* to be inside a seat block: seat-like
blocks are never a collision and never a "below floor". Only objects that stand still are checked (a mover is the collision check's
business); the camera is sampled at the start, the middle and the end for a fixed camera or a ``framing`` move that follows an object.
"""
from __future__ import annotations

import math

REST_BAND = 0.18                  # a lowest point this near a top (above or below) means "resting on it"
SINK_TOLERANCE = 0.04             # deeper than this under the top is sunk, not touching
OVERHANG = 0.15                   # past the edge of the support by more than this is hanging off it
OUT_TOLERANCE = 0.05
FLOAT_GAP = 0.12                  # a character with nothing under it and this far above the floor floats
CROPPED_BELOW = 0.7               # share of the subject's box that is in frame
TINY_BELOW = 0.08                 # of the frame height
MAX_ISSUES = 12
MAX_WARNINGS = 6
SEAT_KINDS = frozenset({"seat", "bench", "sofa", "chair", "stool", "audience"})
SOFT_KINDS = frozenset({"duvet", "pillow", "rug"})          # a figure may lie in or on these: they give way, so it is not "sunk" into them


def scene_placement(document: dict, items: list[dict]) -> dict:
    """``{issues, warnings}``; never raises (a scene that cannot be checked reports none)."""
    try:
        moving = {slot.get("id") for slot in document.get("slots") or [] if slot.get("motion")}
        bodies = [_body(item, item.get("id") not in moving) for item in items if _checkable(item)]
        bodies = [body for body in bodies if body]
        supports = _supports(document, items)
        centers = {item.get("id"): item["boundsM"].get("center") for item in items if item.get("boundsM")}
        issues = _collect_issues(document, bodies, supports, centers)
        return {"issues": issues, "warnings": placement_warnings(issues, items)}
    except Exception:  # noqa: BLE001 - an object that cannot be checked never fails an inspect
        return {"issues": [], "warnings": []}


# ---- bodies and supports ---------------------------------------------------------------------------------------------------

def _collect_issues(document: dict, bodies: list[dict], supports: list[dict], centers: dict) -> list[dict]:
    issues: list[dict] = []
    for body in bodies:
        if not body["character"]:
            continue
        issues += _room_issues(document, body) + _rest_issues(body, supports) + _frame_issues(document, _above_seat(body, supports), centers)
    for body in bodies:
        if not body["character"]:
            issues += _room_issues(document, body)
    return _dedupe(issues)[:MAX_ISSUES]


def _checkable(item: dict) -> bool:
    return bool(item.get("boundsM")) and item.get("media", "model3d") == "model3d" and not item.get("hidden")


def _body(item: dict, still: bool = True) -> dict | None:
    box = item["boundsM"]
    lo, hi = list(box["min"]), list(box["max"])
    if not all(math.isfinite(v) for v in (*lo, *hi)):
        return None
    if item.get("clip"):
        lo, hi = _idle_box(item, box, lo, hi)
    return {"id": item.get("id"), "role": item.get("role"), "lo": lo, "hi": hi, "character": bool(item.get("clip")) and still,
            "position": list(item.get("position") or [0, 0, 0])}


def _idle_box(item: dict, box: dict, lo: list[float], hi: list[float]) -> tuple[list[float], list[float]]:
    """The box of an animated character at rest in an idle pose. ``boundsM`` is the model's bind pose, and a humanoid's is a T: its arms span
    the height, which made a sleeper wider than her bed. Shoulders are 0.125 of the height each side of the centre, the rest is the box's own
    height and depth, turned by the object's own rotation (Euler XYZ)."""
    size, centre = box.get("size"), box.get("center")
    if not (size and centre and len(size) == 3 and all(isinstance(v, (int, float)) and v > 0 for v in size)):
        return lo, hi
    rot = [float(item.get(key) or 0.0) for key in ("rotationX", "rotationY", "rotationZ")]
    axes = [_turn(unit, rot) for unit in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))]
    half = (0.125 * size[1], size[1] / 2, max(size[2], 0.2) / 2)
    reach = [sum(abs(axes[k][i]) * half[k] for k in range(3)) for i in range(3)]
    return [centre[i] - reach[i] for i in range(3)], [centre[i] + reach[i] for i in range(3)]


def _supports(document: dict, items: list[dict]) -> list[dict]:
    found = []
    mold = (document.get("room") or {}).get("mold") or {}
    replaced = set((document.get("room") or {}).get("libraryBlocks") or [])
    for block in mold.get("blocks") or []:
        if block.get("id") in replaced:
            continue
        lo, hi = _block_box(block)
        found.append({"id": block.get("id"), "kind": block.get("kind"), "lo": lo, "hi": hi})
    for item in items:
        body = _body(item) if _checkable(item) else None
        if body and not body["character"] and not item.get("clip"):
            found.append({"id": body["id"], "kind": "prop", "lo": body["lo"], "hi": body["hi"]})
    return found


def _block_box(block: dict) -> tuple[list[float], list[float]]:
    """The axis-aligned box of a block (a turned block: of its eight turned corners)."""
    x, y, z, w, h, d = block["box"]
    cx, cy, cz = x, y + h / 2, z
    rot = block.get("rot")
    corners = [(sx * w / 2, sy * h / 2, sz * d / 2) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    if rot:
        corners = [_turn(c, rot) for c in corners]
    return ([cx + min(c[0] for c in corners), cy + min(c[1] for c in corners), cz + min(c[2] for c in corners)],
            [cx + max(c[0] for c in corners), cy + max(c[1] for c in corners), cz + max(c[2] for c in corners)])


def _turn(point, rot):
    """Euler XYZ, the same matrix as ``set_molds._turned_half`` and three.js (R = Rz Ry Rx, X applied first)."""
    x, y, z = point
    sx, sy, sz = (math.sin(a) for a in rot)
    cx, cy, cz = (math.cos(a) for a in rot)
    return (
        cy * cz * x - cy * sz * y + sy * z,
        (cx * sz + sx * sy * cz) * x + (cx * cz - sx * sy * sz) * y - sx * cy * z,
        (sx * sz - cx * sy * cz) * x + (sx * cz + cx * sy * sz) * y + cx * cy * z,
    )


def _overlap(a_lo, a_hi, b_lo, b_hi, axis: int) -> float:
    return min(a_hi[axis], b_hi[axis]) - max(a_lo[axis], b_lo[axis])


# ---- the room and what a body rests on -------------------------------------------------------------------------------------

def _room_issues(document: dict, body: dict) -> list[dict]:
    mold = (document.get("room") or {}).get("mold") or {}
    dims = mold.get("dimensions")
    if not dims or len(dims) != 3:
        return []
    w, d, h = dims
    out = []
    for axis, (lo, hi) in ((0, (-w / 2, w / 2)), (2, (-d / 2, d / 2))):
        if body["lo"][axis] < lo - OUT_TOLERANCE:
            out.append((axis, lo - body["lo"][axis]))
        elif body["hi"][axis] > hi + OUT_TOLERANCE:
            out.append((axis, hi - body["hi"][axis]))
    if body["hi"][1] > h + OUT_TOLERANCE:
        out.append((1, h - body["hi"][1]))
    if not out:
        return []
    shift = [0.0, 0.0, 0.0]
    for axis, delta in out:
        shift[axis] = delta
    names = ("x", "y", "z")
    return [_issue("outside_room", body, f"goes {', '.join(f'{abs(delta):.2f} m past the room along {names[axis]}' for axis, delta in out)}", _moved(body, shift))]


def _above_seat(body: dict, supports: list[dict]) -> dict:
    """A person lowered into a seat shows from the cushion up: the camera is not asked to see the legs that went into it."""
    for s in supports:
        if s["kind"] in SEAT_KINDS and _overlap(body["lo"], body["hi"], s["lo"], s["hi"], 0) > 0 and _overlap(body["lo"], body["hi"], s["lo"], s["hi"], 2) > 0 and body["lo"][1] < s["hi"][1]:
            return {**body, "lo": [body["lo"][0], s["hi"][1], body["lo"][2]]}
    return body


def _rest_issues(body: dict, supports: list[dict]) -> list[dict]:
    issues = []
    low = body["lo"][1]
    support = _support_of(body, supports)
    in_seat = any(s["kind"] in SEAT_KINDS and _overlap(body["lo"], body["hi"], s["lo"], s["hi"], 0) > 0 and _overlap(body["lo"], body["hi"], s["lo"], s["hi"], 2) > 0 for s in supports)
    if support is None:
        if low < -SINK_TOLERANCE and not in_seat:
            issues.append(_issue("below_floor", body, f"lowest point {low:.2f} is {-low:.2f} m under the floor", _moved(body, [0, -low, 0])))
        elif low > FLOAT_GAP and body["character"]:
            issues.append(_issue("floating", body, f"lowest point is {low:.2f} m above the floor and nothing is under it", _moved(body, [0, -low, 0])))
        return issues
    top = support["hi"][1]
    if support["kind"] not in SEAT_KINDS | SOFT_KINDS and low < top - SINK_TOLERANCE:
        issues.append(_issue("sinks_into_support", body, f"lowest point {low:.2f} is {top - low:.2f} m under the top of {support['id']} ({top:.2f})", _moved(body, [0, top - low, 0]), support["id"]))
    overhang = _overhang(body, support)
    if overhang:
        issues.append(overhang)
    return issues


def _overhang(body: dict, support: dict) -> dict | None:
    shift = [0.0, 0.0, 0.0]
    notes = []
    for axis, name in ((0, "x"), (2, "z")):
        before, after = support["lo"][axis] - body["lo"][axis], body["hi"][axis] - support["hi"][axis]
        if before > OVERHANG or after > OVERHANG:
            centre = (support["lo"][axis] + support["hi"][axis]) / 2 - (body["lo"][axis] + body["hi"][axis]) / 2
            shift[axis] = centre
            notes.append(f"{max(before, after):.2f} m past the {'start' if before > after else 'end'} of {support['id']} along {name}")
    if not notes:
        return None
    return _issue("overhangs_support", body, "hangs " + ", ".join(notes), _moved(body, shift), support["id"])


def _support_of(body: dict, supports: list[dict]) -> dict | None:
    """The highest top within the band of the body's lowest point that the body overlaps from above (its centre over the footprint)."""
    cx, cz = (body["lo"][0] + body["hi"][0]) / 2, (body["lo"][2] + body["hi"][2]) / 2
    best = None
    for s in supports:
        if s["id"] == body["id"]:
            continue
        inside = s["lo"][0] - OVERHANG <= cx <= s["hi"][0] + OVERHANG and s["lo"][2] - OVERHANG <= cz <= s["hi"][2] + OVERHANG
        if inside and abs(body["lo"][1] - s["hi"][1]) <= REST_BAND and (best is None or s["hi"][1] > best["hi"][1]):
            best = s
    return best


def _moved(body: dict, shift: list[float]) -> dict:
    return {"position": [round(body["position"][i] + shift[i], 3) for i in range(3)]}


def _issue(code: str, body: dict, detail: str, fix: dict | None = None, support: str | None = None) -> dict:
    issue = {"code": code, "id": body["id"], "detail": detail}
    if support:
        issue["support"] = support
    if fix:
        issue["fix"] = fix
    return issue


# ---- the camera ------------------------------------------------------------------------------------------------------------

def _frame_issues(document: dict, body: dict, centers: dict) -> list[dict]:
    camera = document.get("camera") or {}
    if camera.get("family", "fixed") != "fixed" or not body["character"]:
        return []
    aspect = float(document.get("width") or 16) / float(document.get("height") or 9)
    worst = _worst_sample(camera, centers, aspect, body)
    if worst is None:
        return []
    frac, height, label = worst
    if frac < CROPPED_BELOW:
        return [_issue("cropped", body, f"only {frac * 100:.0f}% of it is in frame at the {label}; a camera or a position change is needed")]
    sizes = [_in_frame(v, aspect, body)[1] for v in (_camera_at(camera, k, centers) for k in (0.0, 0.5, 1.0)) if v]
    if sizes and max(sizes) < TINY_BELOW:
        return [_issue("tiny", body, f"is {max(sizes) * 100:.0f}% of the frame height at its largest")]
    return []


def _worst_sample(camera: dict, centers: dict, aspect: float, body: dict):
    worst = None
    for k, label in ((0.0, "start"), (0.5, "middle"), (1.0, "end")):
        view = _camera_at(camera, k, centers)
        if view is None:
            continue
        frac, height = _in_frame(view, aspect, body)
        if worst is None or frac < worst[0]:
            worst = (frac, height, label)
    return worst


def _camera_at(camera: dict, k: float, centers: dict):
    eye, look = camera.get("eye"), camera.get("look")
    framing = camera.get("framing")
    if framing and not framing.get("relativeToFacing"):
        anchor = centers.get(framing.get("targetSlot"))
        if anchor is None:
            return None
        eye = [anchor[i] + _lerp(framing.get("from", [0, 0, 0])[i], framing.get("to", framing.get("from", [0, 0, 0]))[i], k) for i in range(3)]
        lf = framing.get("lookFrom", [0, 0, 0])
        look = [anchor[i] + _lerp(lf[i], framing.get("lookTo", lf)[i], k) for i in range(3)]
    if not eye or not look:
        return None
    return {"eye": eye, "look": look, "fov": float(camera.get("fov") or 50)}


def _lerp(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


def _in_frame(view: dict, aspect: float, body: dict) -> tuple[float, float]:
    """(share of the body's projected box inside the frame, its height as a share of the frame height)."""
    eye, look = view["eye"], view["look"]
    f = _norm([look[i] - eye[i] for i in range(3)])
    right = _norm(_cross(f, (0.0, 1.0, 0.0)))
    up = _cross(right, f)
    tan = math.tan(math.radians(view["fov"]) / 2)
    xs, ys = [], []
    for sx in (body["lo"][0], body["hi"][0]):
        for sy in (body["lo"][1], body["hi"][1]):
            for sz in (body["lo"][2], body["hi"][2]):
                v = (sx - eye[0], sy - eye[1], sz - eye[2])
                depth = sum(v[i] * f[i] for i in range(3))
                if depth < 0.05:
                    return 0.0, 0.0
                xs.append(sum(v[i] * right[i] for i in range(3)) / (depth * tan * aspect))
                ys.append(sum(v[i] * up[i] for i in range(3)) / (depth * tan))
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    if width <= 0 or height <= 0:
        return 0.0, 0.0
    seen = max(0.0, min(1.0, max(xs)) - max(-1.0, min(xs))) * max(0.0, min(1.0, max(ys)) - max(-1.0, min(ys)))
    return seen / (width * height), height / 2


def _norm(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / n for c in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


# ---- the reply -------------------------------------------------------------------------------------------------------------

def _dedupe(issues: list[dict]) -> list[dict]:
    seen, out = set(), []
    for issue in issues:
        key = (issue["code"], issue["id"], issue.get("support"))
        if key not in seen:
            seen.add(key)
            out.append(issue)
    return out


def _combined(issues: list[dict], items: list[dict], at_least: int = 2) -> dict:
    """One position that applies every fix of an object (they are shifts from its current position, so they add up); only objects with ``at_least`` fixes."""
    position = {item.get("id"): list(item.get("position") or [0, 0, 0]) for item in items}
    total: dict[str, list[float]] = {}
    count: dict[str, int] = {}
    for issue in issues:
        fix = (issue.get("fix") or {}).get("position")
        if not fix or issue["id"] not in position:
            continue
        shift = total.setdefault(issue["id"], [0.0, 0.0, 0.0])
        for i in range(3):
            shift[i] += fix[i] - position[issue["id"]][i]
        count[issue["id"]] = count.get(issue["id"], 0) + 1
    return {id_: [round(position[id_][i] + shift[i], 3) for i in range(3)] for id_, shift in total.items() if count[id_] >= at_least}


def placement_fixes(issues: list[dict], items: list[dict], only=None) -> dict:
    """``{object id: position}`` that applies every position fix of the listed issues (the objects in ``only``, or all): what ``world3d.scene.fix_placement`` writes."""
    fixes = _combined(issues, items, at_least=1)
    return {id_: position for id_, position in fixes.items() if not only or id_ in only}


def placement_warnings(issues: list[dict], items: list[dict]) -> list[str]:
    """The reply's warning strings of ``layout.placement``, one per issue and, when an object has several fixes, one with them all applied."""
    shown = [f"placement_{i['code']}: {i['id']} {i['detail']}" + (f"; fix: position {i['fix']['position']}" if i.get("fix") else "") for i in issues[:MAX_WARNINGS]]
    shown += [f"placement_fix_all: {id_} position {position}" for id_, position in _combined(issues, items).items()]
    return shown + ([f"placement: {len(issues) - MAX_WARNINGS} more"] if len(issues) > MAX_WARNINGS else [])
