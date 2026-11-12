"""Plain furniture as a GLB of named boxes, at its real size: a chair, a table, a bed... to sit on or at.

Metres, y up, the floor at y = 0 and the footprint centred on x = z = 0. The front is +z (a chair's seat, a sofa's
cushions, a bed's long side face it) and the length runs along x. Every part is its own named mesh node (``seat``,
``back``, ``top``, ``mattress``, ``leg_1``...), so ``glb_parts`` and the seat finder of Video 3D scenes read the seat
without guessing. No downloads, no GPU: a few boxes with flat normals and vertex colours, like ``model3d.compose``.
"""
from __future__ import annotations

import json
import math
import re
import struct

KINDS = ("chair", "stool", "bench", "sofa", "table", "desk", "bed", "nightstand")
# kind: (height, seat or top, width along x, depth along z), metres. A chair's seat is about half its height.
DEFAULTS = {
    "chair": (0.9, 0.46, 0.46, 0.46), "stool": (0.46, 0.46, 0.36, 0.36), "bench": (0.45, 0.45, 1.4, 0.4),
    "sofa": (0.85, 0.44, 1.8, 0.85), "table": (0.75, 0.75, 1.2, 0.8), "desk": (0.75, 0.75, 1.3, 0.65),
    "bed": (0.55, 0.55, 2.0, 1.4), "nightstand": (0.55, 0.55, 0.45, 0.4),
}
SEATS = ("chair", "stool", "bench", "sofa", "bed")
WOOD, FABRIC, LINEN, WHITE = "#8a5a3b", "#5b6b8a", "#e9e4da", "#f6f4ef"
_COLOURS = {"sofa": FABRIC, "bed": WOOD}
_LIMITS = {"height": (0.1, 3.0), "seat": (0.08, 1.5), "width": (0.2, 4.0), "depth": (0.2, 4.0)}
_KEYS = {"kind", "height", "seat", "width", "depth", "color"}
_LEG = 0.045


def furniture_spec(value) -> dict:
    """The stored ``furniture`` declaration: ``{kind, height, seat?, width, depth, color}`` with every size filled in."""
    if isinstance(value, str):
        value = {"kind": value}
    if not isinstance(value, dict) or set(value) - _KEYS or value.get("kind") not in KINDS:
        raise ValueError(f"furniture is a kind ({', '.join(KINDS)}) or {{kind, height?, seat?, width?, depth?, color?}} in metres")
    for key, (low, high) in _LIMITS.items():
        number = value.get(key)
        if number is not None and (type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high):
            raise ValueError(f"furniture.{key} is {low}-{high} m")
    color = value.get("color")
    if color is not None and not (isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color)):
        raise ValueError("furniture.color is #rrggbb")
    return _sized(value)


def _sized(value: dict) -> dict:
    kind = value["kind"]
    height, seat, width, depth = DEFAULTS[kind]
    given_height, given_seat = value.get("height"), value.get("seat")
    if kind in ("chair", "sofa"):
        height = given_height or (given_seat * height / seat if given_seat else height)
        seat = given_seat or round(height * DEFAULTS[kind][1] / DEFAULTS[kind][0], 4)
        if seat > height - 0.15:
            raise ValueError(f"furniture: a {kind}'s seat ({seat:g} m) must be at least 0.15 m under its height ({height:g} m)")
    else:
        height = given_height or given_seat or height
        seat = height
    spec = {"kind": kind, "height": round(float(height), 4), "width": float(value.get("width") or width),
            "depth": float(value.get("depth") or depth), "color": value.get("color") or _COLOURS.get(kind, WOOD)}
    if kind in SEATS:
        spec["seat"] = round(float(seat), 4)
    return spec


def furniture_glb(spec: dict) -> bytes:
    """The GLB of a ``furniture_spec``: one named node per box."""
    parts = _BUILDERS[spec["kind"]](spec)
    return _pack(spec["kind"], [(name, _box(low, high), colour) for name, low, high, colour in parts])


def _legs(width: float, depth: float, top: float, colour: str, inset: float = 0.03) -> list[tuple]:
    x, z = width / 2 - inset - _LEG / 2, depth / 2 - inset - _LEG / 2
    return [(f"leg_{index + 1}", (sx * x - _LEG / 2, 0.0, sz * z - _LEG / 2), (sx * x + _LEG / 2, top, sz * z + _LEG / 2), colour)
            for index, (sx, sz) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1)))]


def _chair(spec: dict) -> list[tuple]:
    w, d, seat, h, colour = spec["width"] / 2, spec["depth"] / 2, spec["seat"], spec["height"], spec["color"]
    return [("seat", (-w, seat - 0.05, -d), (w, seat, d), colour),
            ("back", (-w, seat, -d), (w, h, -d + 0.05), colour), *_legs(2 * w, 2 * d, seat - 0.05, colour, 0.0)]


def _seat_only(spec: dict) -> list[tuple]:
    w, d, seat, colour = spec["width"] / 2, spec["depth"] / 2, spec["seat"], spec["color"]
    return [("seat", (-w, seat - 0.05, -d), (w, seat, d), colour), *_legs(2 * w, 2 * d, seat - 0.05, colour)]


def _sofa(spec: dict) -> list[tuple]:
    w, d, seat, h, colour = spec["width"] / 2, spec["depth"] / 2, spec["seat"], spec["height"], spec["color"]
    arm, back, base = 0.16, 0.2, seat - 0.14
    return [("base", (-w, 0.06, -d), (w, base, d), colour), ("seat", (-w + arm, base, -d + back), (w - arm, seat, d), LINEN),
            ("back", (-w, base, -d), (w, h, -d + back), colour), ("arm_left", (-w, base, -d), (-w + arm, seat + 0.2, d), colour),
            ("arm_right", (w - arm, base, -d), (w, seat + 0.2, d), colour), *_legs(2 * w, 2 * d, 0.06, WOOD)]


def _table(spec: dict) -> list[tuple]:
    w, d, h, colour = spec["width"] / 2, spec["depth"] / 2, spec["height"], spec["color"]
    return [("top", (-w, h - 0.04, -d), (w, h, d), colour), *_legs(2 * w, 2 * d, h - 0.04, colour, 0.05)]


def _bed(spec: dict) -> list[tuple]:
    w, d, h, colour = spec["width"] / 2, spec["depth"] / 2, spec["seat"], spec["color"]
    frame = min(0.32, h * 0.6)
    return [("frame", (-w, 0.1, -d), (w, frame, d), colour), ("mattress", (-w + 0.06, frame, -d + 0.03), (w - 0.02, h, d - 0.03), LINEN),
            ("headboard", (-w, 0.1, -d), (-w + 0.06, h + 0.45, d), colour),
            ("pillow", (-w + 0.1, h, -d + 0.15), (-w + 0.5, h + 0.12, d - 0.15), WHITE), *_legs(2 * w, 2 * d, 0.1, colour, 0.0)]


def _nightstand(spec: dict) -> list[tuple]:
    w, d, h, colour = spec["width"] / 2, spec["depth"] / 2, spec["height"], spec["color"]
    return [("body", (-w, 0.08, -d), (w, h - 0.03, d), colour), ("top", (-w - 0.01, h - 0.03, -d - 0.01), (w + 0.01, h, d + 0.01), colour),
            *_legs(2 * w, 2 * d, 0.08, colour, 0.02)]


_BUILDERS = {"chair": _chair, "stool": _seat_only, "bench": _seat_only, "sofa": _sofa, "table": _table, "desk": _table,
             "bed": _bed, "nightstand": _nightstand}
def _quad(low, high, axis: int, side: int) -> list[tuple]:
    """The four corners of one face, counter-clockwise seen from outside the box."""
    b, c = [index for index in range(3) if index != axis]
    corners = []
    for u, v in ((0, 0), (1, 0), (1, 1), (0, 1)):
        point = [0.0, 0.0, 0.0]
        point[axis] = (low, high)[side][axis]
        point[b], point[c] = (low, high)[u][b], (low, high)[v][c]
        corners.append(tuple(point))
    first, second = [corners[1][i] - corners[0][i] for i in range(3)], [corners[2][i] - corners[0][i] for i in range(3)]
    normal_axis = first[(axis + 1) % 3] * second[(axis + 2) % 3] - first[(axis + 2) % 3] * second[(axis + 1) % 3]
    return corners if (normal_axis > 0) == (side == 1) else corners[::-1]


def _box(low, high) -> tuple[list, list]:
    """Twelve triangles of an axis-aligned box, outward normals, counter-clockwise from outside."""
    vertices, normals = [], []
    for axis in range(3):
        for side in (0, 1):
            a, b, c, d = _quad(low, high, axis, side)
            normal = tuple(float(side * 2 - 1) if index == axis else 0.0 for index in range(3))
            vertices.extend((a, b, c, a, c, d))
            normals.extend([normal] * 6)
    return vertices, normals


def _linear(colour: str) -> tuple[float, float, float]:
    rgb = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)


def _pack(name: str, parts: list[tuple]) -> bytes:
    """One mesh node per part, each one primitive with POSITION, NORMAL and COLOR_0."""
    blobs, views, accessors, meshes, nodes = [], [], [], [], []
    offset = 0
    for index, (part, (vertices, normals), colour) in enumerate(parts):
        first = len(accessors)
        for rows in (vertices, normals, [_linear(colour)] * len(vertices)):
            packed = struct.pack(f"<{len(rows) * 3}f", *(value for row in rows for value in row))
            views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(packed), "target": 34962})
            accessors.append({"bufferView": len(views) - 1, "componentType": 5126, "count": len(rows), "type": "VEC3"})
            blobs.append(packed)
            offset += len(packed)
        accessors[first].update(min=[min(v[i] for v in vertices) for i in range(3)], max=[max(v[i] for v in vertices) for i in range(3)])
        meshes.append({"name": part, "primitives": [{"attributes": {"POSITION": first, "NORMAL": first + 1, "COLOR_0": first + 2},
                                                     "material": 0, "mode": 4}]})
        nodes.append({"name": part, "mesh": index})
    document = {"asset": {"version": "2.0", "generator": "HocusPocus furniture"}, "scene": 0,
                "scenes": [{"name": name, "nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes,
                "materials": [{"name": "Flat vertex colors", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0,
                                                                                       "roughnessFactor": 1}}],
                "buffers": [{"byteLength": offset}], "bufferViews": views, "accessors": accessors}
    encoded = json.dumps(document, separators=(",", ":"), allow_nan=False).encode()
    encoded += b" " * (-len(encoded) % 4)
    binary = b"".join(blobs)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(encoded) + len(binary)) + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
            + struct.pack("<II", len(binary), 0x004E4942) + binary)
