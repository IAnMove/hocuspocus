"""Bounded CPU primitive composition into a self-contained, flat shaded GLB.

Metres, Y-up, radians; rotations apply X then Y then Z. Vertices are split
per triangle so normals never interpolate across faces. No model downloads.
"""
from __future__ import annotations

import json
import math
import re
import struct

KINDS = ("box", "sphere", "cylinder", "cone")
MAX_PIECES = 128
SEGMENTS = 8


def vector(value, default, *, positive=False):
    values = default if value is None else value
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise ValueError("Transforms must contain three finite numbers")
    if any(type(n) not in (int, float) or not math.isfinite(n) or abs(n) > 1000 for n in values):
        raise ValueError("Transform components must be finite numbers within ±1000")
    if positive and any(n <= 0 for n in values):
        raise ValueError("Scale components must be positive")
    return tuple(float(n) for n in values)


def linear_color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Colors must be #RRGGBB")
    rgb = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb)


def normalized_pieces(pieces):
    if not isinstance(pieces, list) or not 1 <= len(pieces) <= MAX_PIECES:
        raise ValueError(f"Use 1..{MAX_PIECES} pieces")
    normalized = []
    for piece in pieces:
        if not isinstance(piece, dict) or piece.get("type") not in KINDS:
            raise ValueError("Each piece needs type box|sphere|cylinder|cone")
        if set(piece) - {"type", "position", "scale", "rotation", "color"}:
            raise ValueError("Unknown piece field")
        normalized.append({
            "type": piece["type"], "position": vector(piece.get("position"), [0, 0, 0]),
            "scale": vector(piece.get("scale"), [1, 1, 1], positive=True),
            "rotation": vector(piece.get("rotation"), [0, 0, 0]),
            "color": linear_color(piece.get("color", "#FFFFFF")),
        })
    return normalized


def _box():
    vertices = [(x, y, z) for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)]
    for a, b, c, d in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
                        (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        yield vertices[a], vertices[b], vertices[c]
        yield vertices[a], vertices[c], vertices[d]


def _radial(kind):
    for i in range(SEGMENTS):
        angles = [i * math.tau / SEGMENTS, (i + 1) * math.tau / SEGMENTS]
        a, b = [(math.cos(t) * .5, -.5, math.sin(t) * .5) for t in angles]
        yield (0, -.5, 0), a, b
        if kind == "cone":
            yield a, (0, .5, 0), b
        else:
            c, d = [(v[0], .5, v[2]) for v in (a, b)]
            yield a, c, d
            yield a, d, b
            yield (0, .5, 0), d, c


def _sphere():
    rings = 6
    def point(lat, lon):
        theta, phi = lat * math.pi / rings, lon * math.tau / SEGMENTS
        return .5 * math.sin(theta) * math.cos(phi), .5 * math.cos(theta), .5 * math.sin(theta) * math.sin(phi)
    for lat in range(rings):
        for lon in range(SEGMENTS):
            a, b, c, d = point(lat, lon), point(lat, lon + 1), point(lat + 1, lon), point(lat + 1, lon + 1)
            if lat > 0:
                yield a, b, c
            if lat < rings - 1:
                yield b, d, c


def _transform(v, piece):
    x, y, z = [v[i] * piece["scale"][i] for i in range(3)]
    rx, ry, rz = piece["rotation"]
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
    return tuple(n + piece["position"][i] for i, n in enumerate((x, y, z)))


def _normal(a, b, c):
    u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
    cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    length = math.sqrt(sum(n * n for n in cross))
    if length <= 0:
        raise ValueError("Degenerate primitive face")
    return tuple(n / length for n in cross)


def compose_glb(pieces, name="Composed model") -> bytes:
    vertices, normals, colors = [], [], []
    for piece in normalized_pieces(pieces):
        kind = piece["type"]
        faces = _box() if kind == "box" else _sphere() if kind == "sphere" else _radial(kind)
        for face in faces:
            points = [_transform(p, piece) for p in face]
            normal = _normal(*points)
            vertices.extend(points)
            normals.extend([normal] * 3)
            colors.extend([piece["color"]] * 3)
    return _pack(name, vertices, normals, colors)


def _pack(name, vertices, normals, colors):
    count = len(vertices)
    blobs = [struct.pack(f"<{count * 3}f", *(v for row in array for v in row)) for array in (vertices, normals, colors)]
    size = len(blobs[0])
    accessors = [{"bufferView": i, "componentType": 5126, "count": count, "type": "VEC3"} for i in range(3)]
    accessors[0].update(min=[min(v[i] for v in vertices) for i in range(3)],
                        max=[max(v[i] for v in vertices) for i in range(3)])
    doc = {
        "asset": {"version": "2.0", "generator": "HocusPocus model3d.compose"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"name": name, "mesh": 0}],
        "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "COLOR_0": 2}, "material": 0, "mode": 4}]}],
        "materials": [{"name": "Flat vertex colors", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0, "roughnessFactor": 1}}],
        "buffers": [{"byteLength": size * 3}],
        "bufferViews": [{"buffer": 0, "byteOffset": i * size, "byteLength": size, "target": 34962} for i in range(3)],
        "accessors": accessors,
    }
    encoded = json.dumps(doc, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    encoded += b" " * (-len(encoded) % 4)
    binary = b"".join(blobs)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(encoded) + len(binary))
            + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
            + struct.pack("<II", len(binary), 0x004E4942) + binary)
