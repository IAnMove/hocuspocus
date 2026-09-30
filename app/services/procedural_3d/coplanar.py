"""Stop composed models from z-fighting.

Two primitives that share a face plane (a screen laid on a cabinet, a rug on a floor, a cushion on a
sofa seat) draw the same depth, so the two colours flicker as the camera moves. This finds triangles
that lie in the same plane, face the same way, overlap, and have different colours, and lifts the
ones of the smaller surface off the plane by a fixed step. Pure Python, CPU, deterministic.
"""
from __future__ import annotations

import math
from collections import defaultdict

LIFT = 0.004          # metres of model space per stacked surface
_PLANE = 1e-3         # tolerance when grouping triangles into one plane
_OVERLAP = 1e-4


def _unit_normal(a, b, c):
    u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
    cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    length = math.sqrt(sum(n * n for n in cross))
    return (cross[0] / length, cross[1] / length, cross[2] / length), length / 2 if length else 0.0


def _plane_key(normal, point):
    offset = sum(normal[i] * point[i] for i in range(3))
    return tuple(round(n / _PLANE) for n in normal), round(offset / _PLANE)


def _bounds(triangle):
    return ([min(p[i] for p in triangle) for i in range(3)], [max(p[i] for p in triangle) for i in range(3)])


def _overlap(a, b):
    """True when the two boxes overlap on at least two axes, which for coplanar faces means a shared area."""
    wide = sum(1 for i in range(3) if min(a[1][i], b[1][i]) - max(a[0][i], b[0][i]) > _OVERLAP)
    return wide >= 2


def separate_coplanar(vertices, normals, colors, lift: float = LIFT):
    """Return vertices with coplanar, overlapping, differently coloured faces lifted apart.

    ``vertices``, ``normals`` and ``colors`` are flat per-vertex lists, three vertices per triangle.
    Within a shared plane the surface with the most area stays put; each smaller surface is lifted one
    more step along the face normal. Triangles that do not share a plane are returned untouched.
    """
    count = len(vertices) // 3
    planes: dict = defaultdict(lambda: defaultdict(list))
    for t in range(count):
        tri = vertices[t * 3:t * 3 + 3]
        try:
            normal, area = _unit_normal(*tri)
        except ZeroDivisionError:
            continue
        if area <= 0:
            continue
        planes[_plane_key(normal, tri[0])][tuple(colors[t * 3])].append((t, normal, area, _bounds(tri)))
    lifted = [tuple(v) for v in vertices]
    for groups in planes.values():
        if len(groups) < 2:
            continue
        surfaces = sorted(groups.items(), key=lambda item: (-sum(f[2] for f in item[1]), item[0]))
        for rank, (_color, faces) in enumerate(surfaces[1:], start=1):
            under = [f for _c, other in surfaces[:rank] for f in other]
            for t, normal, _area, box in faces:
                if not any(_overlap(box, other[3]) for other in under):
                    continue
                for v in range(t * 3, t * 3 + 3):
                    lifted[v] = tuple(lifted[v][i] + normal[i] * lift * rank for i in range(3))
    return lifted
