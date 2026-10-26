"""Hair and clothes as overlapped pieces. Hair stays off the drawn face.

A skirt is two thin sheets, front and back, so the rig still sees the gap
between the legs and the feet under the hem. A solid skirt would hide that gap.
"""
from __future__ import annotations

import math

_LIMB = 12
_HAIR = 16


def hair_pieces(layout: dict, hair: dict) -> list:
    """Smooth volumes on the skull. ``none`` adds nothing."""
    style = hair["style"]
    if style == "none":
        return []
    return _HAIR_BUILDERS[style](layout, hair["color"])


def _piece(kind, pos, scale, color, rot=(0.0, 0.0, 0.0), segments=_LIMB, taper=None) -> dict:
    item = {
        "type": kind,
        "position": [float(v) for v in pos],
        "scale": [float(v) for v in scale],
        "rotation": [float(v) for v in rot],
        "color": color,
    }
    if kind != "box":
        item["segments"] = int(segments)
        item["smooth"] = True
    if taper is not None:
        item["taper"] = float(taper)
    return item


def _pair(item: dict) -> list:
    other = _piece(
        item["type"], (-item["position"][0], item["position"][1], item["position"][2]),
        item["scale"], item["color"], (item["rotation"][0], -item["rotation"][1], -item["rotation"][2]),
        item.get("segments", _LIMB), item.get("taper"),
    )
    return [item, other]


def _crown(layout, color):
    """A cap whose bottom sits just above the brow line (0.30 of the head height)."""
    scale_y = layout["sy"] * 0.34
    y = layout["head_y"] + layout["sy"] * 0.33 + scale_y / 2
    return _piece("sphere", (0, y, -layout["sz"] * 0.05), (layout["sx"] * 0.98, scale_y, layout["sz"] * 0.90), color, segments=_HAIR)


def _back(layout, color):
    """The hair mass behind the head. It sits at the back of the skull, so the face stays clear."""
    return _piece("sphere", (0, layout["head_y"] + layout["sy"] * 0.04, -layout["sz"] * 0.24),
                  (layout["sx"] * 1.08, layout["sy"] * 1.02, layout["sz"] * 0.62), color, segments=_HAIR)


def _locks(layout, color):
    """Two locks beside the face. They hang past 70 degrees round the head, outside the face drawn on the front."""
    length = layout["sy"] * 0.62
    y = layout["head_y"] + layout["sy"] * 0.24 - length / 2
    lock = _piece("capsule", (layout["sx"] * 0.47, y, -layout["sz"] * 0.06),
                  (layout["sx"] * 0.13, length, layout["sz"] * 0.30), color, segments=_LIMB)
    return _pair(lock)


def _cranium(layout, color):
    return [_crown(layout, color), _back(layout, color)]


def _short(layout, color):
    return _cranium(layout, color)


def _bangs(layout, color):
    scale_y = layout["sy"] * 0.12
    y = layout["head_y"] + layout["sy"] * 0.33 + scale_y / 2
    fringe = _piece("sphere", (0, y, layout["sz"] * 0.28), (layout["sx"] * 0.70, scale_y, layout["sz"] * 0.20), color, segments=_HAIR)
    return [*_cranium(layout, color), fringe, *_locks(layout, color)]


def _spike(layout, color, x, z, height):
    base = layout["head_y"] + layout["sy"] * 0.30
    return _piece("cone", (x, base + height / 2, z), (layout["sx"] * 0.14, height, layout["sx"] * 0.14), color, segments=_LIMB)


def _spiky(layout, color):
    center = _spike(layout, color, 0.0, -layout["sz"] * 0.10, layout["sy"] * 0.55)
    side = _spike(layout, color, layout["sx"] * 0.22, -layout["sz"] * 0.12, layout["sy"] * 0.38)
    return [*_cranium(layout, color), center, *_pair(side)]


def _tail(layout, color, length, thick, z):
    top = layout["head_y"] + layout["sy"] * 0.16
    return _piece("capsule", (0, top - length / 2, z), (thick, length, thick), color, segments=_LIMB)


def _long(layout, color):
    length = max(layout["torso_h"] * 0.95, layout["sy"] * 1.5)
    return [*_cranium(layout, color), *_locks(layout, color), _tail(layout, color, length, layout["sz"] * 0.34, -layout["sz"] * 0.58)]


def _ponytail(layout, color):
    size = layout["sx"] * 0.28
    bun = _piece("sphere", (0, layout["head_y"] + layout["sy"] * 0.18, -layout["sz"] * 0.50), (size, size, size), color, segments=_HAIR)
    length = max(layout["torso_h"] * 0.62, layout["sy"])
    return [*_cranium(layout, color), bun, _tail(layout, color, length, layout["sx"] * 0.15, -layout["sz"] * 0.64)]


def _twin_tails(layout, color):
    knot = layout["sx"] * 0.24
    x, z = layout["sx"] * 0.40, -layout["sz"] * 0.30
    ball = _piece("sphere", (x, layout["head_y"] + layout["sy"] * 0.04, z), (knot, knot, knot), color, segments=_LIMB)
    length = max(layout["sy"] * 1.2, layout["h"] * 0.18)
    tail = _piece("capsule", (x, layout["head_y"] - length * 0.32, z - layout["sz"] * 0.06), (knot * 0.55, length, knot * 0.55), color, segments=_LIMB)
    return [*_cranium(layout, color), *_locks(layout, color), *_pair(ball), *_pair(tail)]


def _bun(layout, color):
    bun = _piece(
        "sphere", (0, layout["head_y"] + layout["sy"] * 0.52, -layout["sz"] * 0.10),
        (layout["sx"] * 0.32, layout["sy"] * 0.28, layout["sz"] * 0.32), color, segments=_HAIR,
    )
    return [*_cranium(layout, color), bun]


def _skirt(layout, color):
    knee, waist = layout["knee"], layout["waist_y"]
    length = max(waist - knee, layout["h"] * 0.12)
    center_y = waist - length / 2
    hem = max(layout["torso_w"] * 1.45, layout["leg_d"] * 4.2)
    thin = max(0.016 * layout["h"], 0.012)
    taper = min(0.85, max(0.35, layout["waist_w"] / hem))
    bite = layout["torso_d"] / 2 - thin * 0.15
    front = _piece("frustum", (0, center_y, bite), (hem, length, thin), color, segments=_LIMB, taper=taper)
    back = _piece("frustum", (0, center_y, -bite), (hem, length, thin), color, segments=_LIMB, taper=taper)
    return [front, back]


def _jacket(layout, color):
    """The body's barrel and dome, 8 percent bigger and 10 percent shorter. Its hem is wider than the body at that height, so no skin shows through."""
    from services.blob_builder import torso_shell
    drop = layout["torso_h"] * 0.10
    short = {**layout, "torso_bottom": layout["torso_bottom"] + drop, "torso_h": layout["torso_h"] - drop}
    body_taper = layout["waist_taper"]
    body_at_hem = body_taper + 0.14 * (1.0 - body_taper)
    taper = min(1.0, body_at_hem * 1.06 / 1.08)
    return torso_shell(short, color, grow=1.08, taper=None if taper > 0.97 else taper)


def _sleeves_long(layout, color):
    turn = (0.0, 0.0, math.pi / 2)
    y = layout["shoulder_y"]
    thick = layout["arm_d"] * 1.16
    upper = _piece("capsule", (layout["upper_x"], y, 0), (thick, layout["upper_len"], thick), color, turn, _LIMB)
    fore = _piece("capsule", (layout["fore_x"], y, 0), (thick * 0.88, layout["fore_len"], thick * 0.88), color, turn, _LIMB)
    elbow = _piece("sphere", (layout["elbow_x"], y, 0), (thick * 0.82, thick * 0.82, thick * 0.82), color, segments=_LIMB)
    return _pair(upper) + _pair(elbow) + _pair(fore)


def _shorts(layout, color):
    length = layout["leg_len"] * 0.32
    y = layout["leg_top"] - length * 0.38
    thick = layout["leg_d"] * 1.10
    return _pair(_piece("capsule", (layout["leg_x"], y, 0), (thick, length, thick * 0.92), color, segments=_LIMB))


def _school_collar(layout, color):
    """Two lapels in a V and a small flap, on the chest below the chin line."""
    y = layout["head_y"] - layout["sy"] / 2 - layout["h"] * 0.034
    z = layout["torso_d"] * 0.46
    width = min(layout["sx"] * 0.62, layout["torso_w"] * 0.60)
    lapel = _piece("box", (width * 0.30, y, z), (width * 0.55, layout["h"] * 0.034, layout["h"] * 0.010), color, (0.0, 0.0, -0.55))
    flap = _piece("box", (0, y - layout["h"] * 0.026, z + layout["h"] * 0.002), (width * 0.30, layout["h"] * 0.030, layout["h"] * 0.008), color)
    return [*_pair(lapel), flap]


def _cape(layout, color):
    """Shoulder to waist, behind the body. It does not reach the ankles."""
    height = layout["torso_h"] * 0.58
    y = layout["shoulder_y"] - height * 0.28
    depth = max(0.02 * layout["h"], 0.014)
    z = -(layout["torso_d"] / 2 + depth / 2 - depth * 0.5)
    return [_piece("box", (0, y, z), (layout["torso_w"] * 0.92, height, depth), color)]


_HAIR_BUILDERS = {
    "short": _short, "bangs": _bangs, "spiky": _spiky, "long": _long,
    "ponytail": _ponytail, "twin_tails": _twin_tails, "bun": _bun,
}

CLOTHES = {
    "skirt": _skirt, "jacket": _jacket, "sleeves_long": _sleeves_long,
    "shorts": _shorts, "school_collar": _school_collar, "cape": _cape,
}
