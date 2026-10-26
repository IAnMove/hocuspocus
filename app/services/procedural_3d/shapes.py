"""Capsule, frustum and optional smooth normals for composed primitives.

Local points sit in the unit box. ``compose`` scales, rotates and translates them.
Smooth normals are radial on a round side and axial on a flat cap, so a cap does
not blend into the wall. A capsule's caps are hemispheres, so they meet the side.
"""
from __future__ import annotations

import math


def iter_triangles(piece: dict, smooth: bool):
    """Yield ``(local triangle, normals or None)``. Normals are axis-aligned, before rotation."""
    kind = piece["type"]
    if kind == "capsule":
        yield from _capsule(piece, smooth)
    elif kind == "frustum":
        yield from _frustum(piece, smooth)
    elif kind == "sphere":
        yield from _sphere(piece, smooth)
    elif kind in ("cylinder", "cone"):
        yield from _tube(piece, smooth)
    else:
        raise ValueError(f"No smooth shape for {kind}")


def local_faces(piece: dict):
    """Local triangles of a capsule or frustum, for callers that only need positions."""
    for tri, _norms in iter_triangles(piece, False):
        yield tri


def _count(piece: dict) -> int:
    if piece["segments"]:
        return int(piece["segments"])
    return 8


def _angles(count: int):
    return [index * math.tau / count for index in range(count)]


def _norm(value):
    length = math.sqrt(sum(item * item for item in value))
    if length <= 1e-12:
        return (0.0, 1.0, 0.0)
    return tuple(item / length for item in value)


def _quad(a, b, c, d, na, nb, nc, nd, smooth: bool):
    """Wall triangles. ``a,b`` are one rim and ``c,d`` the other, cylinder winding."""
    yield (a, c, d), ((na, nc, nd) if smooth else None)
    yield (a, d, b), ((na, nd, nb) if smooth else None)


def _fan(center, rim, normal, flip: bool, smooth: bool):
    count = len(rim)
    for index in range(count):
        a, b = rim[index], rim[(index + 1) % count]
        if flip:
            yield (center, b, a), ((normal, normal, normal) if smooth else None)
        else:
            yield (center, a, b), ((normal, normal, normal) if smooth else None)


def _rim(count: int, y: float, radius: float):
    return [(math.cos(phi) * radius, y, math.sin(phi) * radius) for phi in _angles(count)]


def _tube(piece: dict, smooth: bool):
    count = _count(piece)
    kind = piece["type"]
    bottom = _rim(count, -0.5, 0.5)
    apex = kind == "cone"
    top = [(0.0, 0.5, 0.0)] * count if apex else _rim(count, 0.5, 0.5)
    side = [_tube_normal(phi, piece["scale"], kind) for phi in _angles(count)]
    for index in range(count):
        nxt = (index + 1) % count
        if apex:
            yield (bottom[index], top[index], bottom[nxt]), ((side[index], side[index], side[nxt]) if smooth else None)
        else:
            yield from _quad(bottom[index], bottom[nxt], top[index], top[nxt], side[index], side[nxt], side[index], side[nxt], smooth)
    yield from _fan((0.0, -0.5, 0.0), bottom, (0.0, -1.0, 0.0), False, smooth)
    if not apex:
        yield from _fan((0.0, 0.5, 0.0), top, (0.0, 1.0, 0.0), True, smooth)


def _tube_normal(phi: float, scale, kind: str):
    if kind == "cylinder":
        return _norm((math.cos(phi) / scale[0], 0.0, math.sin(phi) / scale[2]))
    # Unit cone: base radius 0.5 at y=-0.5, apex at y=0.5. The side rises 1 as the radius falls 0.5.
    return _norm((math.cos(phi) / scale[0], 0.5 / scale[1], math.sin(phi) / scale[2]))


def _sphere(piece: dict, smooth: bool):
    """Same corners as the flat sphere. ``segments`` omitted keeps 6 rings, not ``count // 2``."""
    count = _count(piece)
    rings = 6 if piece["segments"] is None else count // 2
    scale = piece["scale"]

    def at(lat: int, lon: int):
        theta, phi = lat * math.pi / rings, lon * math.tau / count
        point = (0.5 * math.sin(theta) * math.cos(phi), 0.5 * math.cos(theta), 0.5 * math.sin(theta) * math.sin(phi))
        return point, _norm((point[0] / scale[0], point[1] / scale[1], point[2] / scale[2]))

    for lat in range(rings):
        for lon in range(count):
            a, b = at(lat, lon), at(lat, lon + 1)
            c, d = at(lat + 1, lon), at(lat + 1, lon + 1)
            if lat > 0:
                yield (a[0], b[0], c[0]), ((a[1], b[1], c[1]) if smooth else None)
            if lat < rings - 1:
                yield (b[0], d[0], c[0]), ((b[1], d[1], c[1]) if smooth else None)


def _capsule(piece: dict, smooth: bool):
    sx, sy, sz = piece["scale"]
    cap = min(sx, sz) / 2.0
    body = sy - 2.0 * cap
    if body <= 1e-6:
        yield from _sphere(piece, smooth)
        return
    count = _count(piece)
    rings = max(2, count // 4)
    yield from _hemisphere(piece, body / 2.0, cap, rings, count, smooth, top=True)
    yield from _hemisphere(piece, -body / 2.0, cap, rings, count, smooth, top=False)
    yield from _capsule_wall(piece, body / 2.0, count, smooth)


def _hemisphere(piece, center_y: float, cap: float, rings: int, count: int, smooth: bool, top: bool):
    sign = 1.0 if top else -1.0
    rows = [_ellipse_row(piece, center_y + sign * cap * math.cos(alpha), math.sin(alpha), count, center_y, cap)
            for alpha in (ring * (math.pi / 2.0) / rings for ring in range(rings + 1))]
    for ring in range(rings):
        inner, outer = rows[ring], rows[ring + 1]
        for index in range(count):
            nxt = (index + 1) % count
            if ring == 0:
                tri = (inner[index][0], outer[nxt][0], outer[index][0])
                norms = (inner[index][1], outer[nxt][1], outer[index][1])
                yield tri, (norms if smooth else None)
            elif top:
                yield from _quad(outer[index][0], outer[nxt][0], inner[index][0], inner[nxt][0],
                                 outer[index][1], outer[nxt][1], inner[index][1], inner[nxt][1], smooth)
            else:
                yield from _quad(inner[index][0], inner[nxt][0], outer[index][0], outer[nxt][0],
                                 inner[index][1], inner[nxt][1], outer[index][1], outer[nxt][1], smooth)


def _ellipse_row(piece, y_world: float, radius: float, count: int, center_y: float, cap: float):
    sx, sy, sz = piece["scale"]
    row = []
    for phi in _angles(count):
        wx = (sx / 2.0) * radius * math.cos(phi)
        wz = (sz / 2.0) * radius * math.sin(phi)
        normal = _norm((wx / (sx / 2.0) ** 2, (y_world - center_y) / cap ** 2, wz / (sz / 2.0) ** 2))
        row.append(((wx / sx, y_world / sy, wz / sz), normal))
    return row


def _capsule_wall(piece, half_body: float, count: int, smooth: bool):
    """Rings about a diameter apart. One long quad has no vertices for the rig to bind."""
    sx, _sy, sz = piece["scale"]
    length = half_body * 2.0
    steps = max(1, math.ceil(length / max(min(sx, sz), 1e-6)))
    rows = [_wall_row(piece, -half_body + length * step / steps, count) for step in range(steps + 1)]
    for row in range(steps):
        low, high = rows[row], rows[row + 1]
        for index in range(count):
            nxt = (index + 1) % count
            yield from _quad(low[index][0], low[nxt][0], high[index][0], high[nxt][0],
                             low[index][1], low[nxt][1], high[index][1], high[nxt][1], smooth)


def _wall_row(piece, y_world: float, count: int):
    sx, sy, sz = piece["scale"]
    row = []
    for phi in _angles(count):
        wx, wz = (sx / 2.0) * math.cos(phi), (sz / 2.0) * math.sin(phi)
        row.append(((wx / sx, y_world / sy, wz / sz), _norm((math.cos(phi) / sx, 0.0, math.sin(phi) / sz))))
    return row


def _frustum(piece: dict, smooth: bool):
    count = _count(piece)
    taper = float(piece["taper"])
    bottom = _rim(count, -0.5, 0.5)
    top = _rim(count, 0.5, 0.5 * taper)
    normals = [_frustum_normal(phi, piece["scale"], taper) for phi in _angles(count)]
    for index in range(count):
        nxt = (index + 1) % count
        yield from _quad(bottom[index], bottom[nxt], top[index], top[nxt], normals[index], normals[nxt], normals[index], normals[nxt], smooth)
    yield from _fan((0.0, -0.5, 0.0), bottom, (0.0, -1.0, 0.0), False, smooth)
    yield from _fan((0.0, 0.5, 0.0), top, (0.0, 1.0, 0.0), True, smooth)


def _frustum_normal(phi: float, scale, taper: float):
    sx, sy, sz = scale
    drx = (sx / 2.0) * (taper - 1.0)
    drz = (sz / 2.0) * (taper - 1.0)
    rx, rz = sx / 2.0, sz / 2.0
    c, s = math.cos(phi), math.sin(phi)
    return _norm((sy * rz * c, -drx * rz * c * c - drz * rx * s * s, sy * rx * s))
