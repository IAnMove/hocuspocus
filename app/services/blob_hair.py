"""Hair for the lofted anime head: a helmet plus curved clumps, from the ``hair`` trait.

Styles: ``short``, ``bangs``, ``bob``, ``long``, ``twin_tails``, ``spiky``, ``ponytail``,
``bun``; ``none`` adds nothing. Every clump is a quadratic curve from a root on the
helmet, through a pull point, to a tip, lofted as a flattened tube that thins to the
tip (``blob_loft.curve_tube``), so the silhouette is hair from every angle and the
toon ink outlines each clump. The mesh is written as its own ``hair`` primitive so
the toon look can put a gloss band on it. Head space: the egg's centre and radii from
the layout, +Z the face; roots are given as (yaw degrees from the face, latitude
degrees) on the helmet surface.
"""
from __future__ import annotations

import math

from services.blob_loft import Mesh, _st, _tube, _egg_radius, bezier, curve_tube, skull_point, _emit

HELMET = 1.10
_SAMPLES = 7


def hair_mesh(L: dict, hair: dict) -> Mesh:
    mesh = Mesh()
    style, color = hair["style"], hair["color"]
    if style == "none":
        return mesh
    head = _Head(L)
    _helmet(mesh, head, color, hairline=34 if style in ("short", "spiky", "bun") else 26)
    if style == "short":
        _crown(mesh, head, color)
    _STYLES[style](mesh, head, color)
    return mesh


class _Head:
    def __init__(self, L: dict) -> None:
        self.L = L
        self.cx, self.cy, self.cz = 0.0, L["head_y"], 0.0
        self.rx, self.ry, self.rz = L["sx"] / 2, L["sy"] / 2, L["sz"] / 2
        self.h = L["h"]
        self.chin = L["head_y"] - self.ry
        self.chest = L["torso_top"] - L["torso_h"] * 0.25
        self.back_z = -L["torso_d"] / 2

    def at(self, yaw: float, lat: float, out: float = HELMET):
        """A point ``out`` times outside the skull, at yaw degrees from the face and lat degrees up."""
        return skull_point(self.L, yaw, lat, out)

    def off(self, point, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0):
        return (point[0] + self.rx * dx, point[1] + self.ry * dy, point[2] + self.rz * dz)


def _helmet(mesh: Mesh, head: _Head, color: str, hairline: float) -> None:
    """Hair round the crown and the back, on the skull's own surface: full rings above the hairline, back arcs below it."""
    from services.procedural_3d.compose import linear_color
    full = [j * 360.0 / 24 for j in range(24)]
    back = [70 + 220.0 * j / 24 for j in range(25)]
    for yaws, lats, closed in ((back, [-30 + (hairline + 30) * k / 7 for k in range(8)], False),
                               (full, [hairline + (90 - hairline) * k / 8 for k in range(9)], True)):
        grid, colors = [], []
        for lat in lats:
            # thin at the temples and the nape (no inflated balloon), fuller only toward the crown
            out = 1.05 + 0.05 * max(0.0, min(1.0, (lat - 30) / 30)) + 0.04 * max(0.0, min(1.0, (lat - 60) / 30))
            ring = [skull_point(head.L, yaw, lat, out) for yaw in yaws]
            if lat >= 89.9:
                ring = [(0.0, head.cy + head.ry * out, 0.0)] * len(ring)
            grid.append(ring)
            colors.append([linear_color(color)] * len(ring))
        centers = [(0.0, head.cy + head.ry * math.sin(math.radians(lat)), 0.0) for lat in lats]
        _emit(mesh, grid, colors, centers, closed, None)


def _clump(mesh: Mesh, head: _Head, color: str, root, pull, tip, r0: float, r1: float = 0.15, flat: float = 0.3, ring: int = 8) -> None:
    """A lofted strand: radii in head-width units from the root to the tip."""
    points = bezier(root, pull, tip, _SAMPLES)
    # narrow at the root (it disappears under the hair above, no square top edge), full by a fifth of the way, then thinning to the tip
    radii = [head.rx * (r0 + (r1 - r0) * i / (_SAMPLES - 1)) * min(1.0, 0.4 + 3.0 * i / (_SAMPLES - 1)) for i in range(_SAMPLES)]
    radii[-1] = max(radii[-1], head.rx * 0.012)
    curve_tube(mesh, points, radii, color, ring=ring, flat=flat, hug=(head.cx, head.cy, head.cz))


def _crown(mesh: Mesh, head: _Head, color: str) -> None:
    """Four wide flat clumps swept back over the crown: the dome's outline breaks into hair, not a cap."""
    for yaw, lat, lean in ((-35, 62, -0.25), (-12, 70, -0.3), (12, 70, 0.3), (35, 62, 0.25)):
        root = head.at(yaw, lat, 1.02)
        pull = head.at(yaw + lean * 20, lat + 18, 1.3)
        tip = head.at(yaw + lean * 50, min(89, lat + 8), 1.32)
        _clump(mesh, head, color, root, pull, tip, 0.42, 0.06, flat=0.16)


def _fringe(mesh: Mesh, head: _Head, color: str, count: int = 7, length: float = 0.62) -> None:
    """Pointed locks from a root on the dome's hairline (outside the face patch) down over the forehead to the brows, in three lengths so
    the tips stagger, flaring a little to the sides."""
    levels = (1.0, 0.85, 0.92)
    for i in range(count):
        u = (i - (count - 1) / 2) / max(1, (count - 1) / 2)
        yaw = u * 48
        reach = length * levels[i % 3]
        root = head.at(yaw, 46, 1.05)
        pull = head.off(head.at(yaw * 1.05, 32, 1.11), dy=0.02)
        tip = head.off(head.at(yaw * 1.2, 56 - reach * 95, 1.06), dx=u * 0.08)
        _clump(mesh, head, color, root, pull, tip, 0.36, 0.04, flat=0.18)


def _side_locks(mesh: Mesh, head: _Head, color: str, length: float) -> None:
    """One lock in front of each ear. ``length`` is in head heights below the chin (0 ends at the jaw)."""
    for sign in (-1, 1):
        root = head.at(sign * 58, 46, 1.05)
        pull = head.off(head.at(sign * 74, -16, 1.13), dz=0.1)
        tip = (root[0] + sign * head.rx * 0.1, head.chin - head.ry * length, head.cz + head.rz * 0.18)
        _clump(mesh, head, color, root, pull, tip, 0.30, 0.04, flat=0.36)


def _short(mesh: Mesh, head: _Head, color: str) -> None:
    _fringe(mesh, head, color)
    for i in range(10):
        yaw = 54 + i * 28
        root = head.at(yaw, 24)
        pull = head.at(yaw, -2, 1.16)
        tip = head.at(yaw, -20, 1.08)
        _clump(mesh, head, color, root, pull, tip, 0.3, 0.08, flat=0.4)


def _bangs(mesh: Mesh, head: _Head, color: str) -> None:
    _fringe(mesh, head, color)
    _side_locks(mesh, head, color, 0.1)


def _bob(mesh: Mesh, head: _Head, color: str) -> None:
    _fringe(mesh, head, color)
    for i in range(14):
        yaw = 42 + i * 23.5
        root = head.at(yaw, 26)
        pull = head.at(yaw, -10, 1.2)
        tip = head.off(head.at(yaw, -42, 1.0), dy=-0.35)
        _clump(mesh, head, color, root, pull, tip, 0.3, 0.12, flat=0.4)


def _long(mesh: Mesh, head: _Head, color: str) -> None:
    _fringe(mesh, head, color)
    _side_locks(mesh, head, color, 1.4)
    for i in range(9):
        yaw = 112 + i * 17
        root = head.at(yaw, 14)
        pull = head.off(head.at(yaw, -25, 1.18), dy=-0.2)
        tip = (root[0] * 0.9, head.chest, head.back_z * 1.1 + (head.rz * 0.1 if abs(yaw - 180) > 40 else 0.0))
        _clump(mesh, head, color, root, pull, tip, 0.3, 0.14, flat=0.35)


def _twin_tails(mesh: Mesh, head: _Head, color: str) -> None:
    _fringe(mesh, head, color)
    _side_locks(mesh, head, color, 0.15)
    for sign in (-1, 1):
        knot = head.at(sign * 105, 28)
        _clump(mesh, head, color, head.at(sign * 100, 40, 1.0), head.off(knot, dx=sign * 0.12, dy=0.1), head.off(knot, dx=sign * 0.16), 0.2, 0.2, flat=1.0, ring=10)
        for k, (dx, dz) in enumerate(((0.0, 0.0), (0.12, 0.1), (0.06, -0.12))):
            root = head.off(knot, dx=sign * (0.1 + dx * 0.5), dz=dz * 0.5)
            pull = head.off(knot, dx=sign * (0.55 + dx), dy=-0.3, dz=dz)
            tip = (knot[0] + sign * head.rx * (0.45 + dx), head.chest + head.ry * 0.2 - k * head.ry * 0.1, knot[2] + head.rz * dz)
            _clump(mesh, head, color, root, pull, tip, 0.2, 0.06, flat=0.6)


def _spiky(mesh: Mesh, head: _Head, color: str) -> None:
    _fringe(mesh, head, color, count=5)
    # a mirror-symmetric crown of curved, tapered clumps swept back (toward yaw 180), none below the ear line
    spikes = ((20, 58), (-20, 58), (50, 58), (-50, 58), (85, 64), (-85, 64), (120, 62), (-120, 62), (150, 58), (-150, 58), (180, 56))
    for k, (yaw, lat) in enumerate(spikes):
        way = (yaw > 0) - (yaw < 0)
        root = head.at(yaw, lat, 1.0)
        pull = head.at(yaw + way * 8, lat + 16, 1.15)
        tip = head.at(yaw + way * 20, min(84, lat + 18), 1.26 + 0.04 * (k % 3))
        _clump(mesh, head, color, root, pull, tip, 0.3, 0.04, flat=0.35)


def _ponytail(mesh: Mesh, head: _Head, color: str) -> None:
    _fringe(mesh, head, color)
    _side_locks(mesh, head, color, 0.05)
    knot = head.at(180, 30)
    for k, (dx, dz) in enumerate(((0.0, 0.0), (0.16, -0.05), (-0.16, -0.05), (0.0, -0.12))):
        root = head.off(knot, dx=dx * 0.5, dz=dz * 0.5)
        pull = head.off(knot, dx=dx, dy=0.35, dz=-0.7 + dz)
        tip = (knot[0] + head.rx * dx * 1.2, head.chest + head.ry * 0.1 - k * head.ry * 0.08, head.back_z * 1.15 + head.rz * dz)
        _clump(mesh, head, color, root, pull, tip, 0.2, 0.05, flat=0.6)


def _bun(mesh: Mesh, head: _Head, color: str) -> None:
    _fringe(mesh, head, color)
    top = head.at(170, 62, 1.0)
    bun = [_st((top[0], top[1] + head.ry * 0.05, top[2]), head.rx * 0.2, head.rz * 0.2, color),
           _st((top[0], top[1] + head.ry * 0.3, top[2] - head.rz * 0.05), head.rx * 0.34, head.rz * 0.34, color),
           _st((top[0], top[1] + head.ry * 0.52, top[2] - head.rz * 0.08), head.rx * 0.2, head.rz * 0.2, color)]
    _tube(mesh, bun, "y", ring=12)


_STYLES = {"short": _short, "bangs": _bangs, "bob": _bob, "long": _long, "twin_tails": _twin_tails,
           "spiky": _spiky, "ponytail": _ponytail, "bun": _bun}
