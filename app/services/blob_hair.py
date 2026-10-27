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

from services.blob_loft import Mesh, _add, _cross, _dot, _mul, _st, _sub, _tube, _unit, bezier, skull_point, _emit
from services.procedural_3d.compose import linear_color

HELMET = 1.10
_SAMPLES = 7


class UVMesh(Mesh):
    """A mesh with texture coordinates. Geometry added without any (the scalp, a bun) gets ``default_uv(point)``: strands that
    run from the crown down the head, in the opaque part of the strand texture (``ui/src/features/scene3d/hairStrands.ts``)."""

    def __init__(self, default_uv) -> None:
        super().__init__()
        self.uvs: list[tuple[float, float]] = []
        self._default = default_uv

    def triangle(self, points, normals, colors, uvs=None) -> None:
        super().triangle(points, normals, colors)
        self.uvs.extend(uvs if uvs is not None else [self._default(p) for p in points])


def hair_mesh(L: dict, hair: dict) -> UVMesh:
    head = _Head(L)
    mesh = UVMesh(_scalp_uv(head))
    style, color = hair["style"], hair["color"]
    if style == "none":
        return mesh
    if L.get("relief"):
        _real_cap(mesh, head, color)   # a painted face brings its own hairline and fringe: only the cap and the back
        return mesh
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


def _scalp_uv(head: _Head):
    """Strands from the crown down the head: ``u`` mirrors left and right (no seam at the nape), ``v`` grows downward."""
    top, span = head.cy + head.ry, 2 * head.ry

    def uv(point):
        yaw = math.atan2(point[0] - head.cx, point[2] - head.cz)
        return (0.3 + 0.4 * abs(yaw) / math.pi, 0.02 + 0.44 * max(0.0, min(1.0, (top - point[1]) / span)))
    return uv


def _real_cap(mesh: Mesh, head: _Head, color: str) -> None:
    """Short hair for a head with a painted face: a cap over the crown above the painted hairline (lat 50 and up), the flanks above
    the ears (yaw 58 to 302, lat 18 to 50) and the back behind them (yaw 104 to 256, down to the nape). The forehead, the temples in
    front of 58 degrees and the ears stay the painting's; the cap gives the head a hair silhouette instead of an egg's."""
    from services.procedural_3d.compose import linear_color

    def band(yaws, lats, closed, out_of):
        grid, colors = [], []
        for lat in lats:
            out = out_of(lat)
            ring = [skull_point(head.L, yaw, lat, out) for yaw in yaws]
            if lat >= 89.9:
                ring = [(0.0, head.cy + head.ry * out, 0.0)] * len(ring)
            grid.append(ring)
            colors.append([linear_color(color)] * len(ring))
        centers = [(0.0, head.cy + head.ry * math.sin(math.radians(lat)), 0.0) for lat in lats]
        _emit(mesh, grid, colors, centers, closed, None)

    thick = lambda lat: 1.045 + 0.03 * max(0.0, min(1.0, (lat - 40) / 40))
    band([j * 360.0 / 24 for j in range(24)], [50 + 40 * k / 8 for k in range(9)], True, thick)
    band([58 + 244.0 * j / 24 for j in range(25)], [16 + 36 * k / 6 for k in range(7)], False, lambda lat: 1.045)
    band([104 + 152.0 * j / 16 for j in range(17)], [-26 + 44 * k / 6 for k in range(7)], False, lambda lat: 1.04)


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
    """A lock: a curved card from the root through the pull to the tip, ``r0`` and ``r1`` the half width in head-width units
    (narrow at the very root, so it vanishes under the hair above). A thick lock (``flat`` 0.5 or more: a tail, a ponytail)
    is two cards crossed, so it has volume from every side."""
    points = bezier(root, pull, tip, _SAMPLES)
    widths = [1.35 * head.rx * (r0 + (r1 - r0) * i / (_SAMPLES - 1)) * min(1.0, 0.4 + 3.0 * i / (_SAMPLES - 1)) for i in range(_SAMPLES)]
    widths[-1] = max(widths[-1], head.rx * 0.012)
    _card(mesh, head, color, points, widths, 0.0)
    if flat >= 0.5:
        _card(mesh, head, color, points, widths, math.pi / 2)


def _card(mesh: Mesh, head: _Head, color: str, points: list, widths: list, turn: float, cols: int = 3) -> None:
    """A strip along ``points`` with ``cols`` segments across, bowed outward a little, with strand UVs (``u`` across, ``v``
    from the root 0 to the tip 1), roots a shade darker, both faces. ``turn`` rotates it round the path."""
    base = linear_color(color)
    rows = len(points)
    grid = []
    for i, point in enumerate(points):
        tangent = _unit(_sub(points[min(i + 1, rows - 1)], points[max(i - 1, 0)]))
        out = _sub(point, (head.cx, head.cy, head.cz))
        out = _sub(out, _mul(tangent, _dot(out, tangent)))
        deep = _unit(out) if _dot(out, out) > 1e-12 else (0.0, 0.0, 1.0)
        side = _unit(_cross(tangent, deep))
        if turn:
            side, deep = _add(_mul(side, math.cos(turn)), _mul(deep, math.sin(turn))), _add(_mul(deep, math.cos(turn)), _mul(side, -math.sin(turn)))
        shade = 0.72 + 0.28 * (i / (rows - 1)) ** 0.7
        row = []
        for j in range(cols + 1):
            t = j / cols
            s = 2 * t - 1
            position = _add(_add(point, _mul(side, widths[i] * s)), _mul(deep, widths[i] * 0.3 * (1 - s * s)))
            row.append((position, _unit(_add(deep, _mul(side, s * 0.45))), tuple(c * shade for c in base), (t, i / (rows - 1))))
        grid.append(row)
    for i in range(rows - 1):
        for j in range(cols):
            a, b, c, d = grid[i][j], grid[i][j + 1], grid[i + 1][j + 1], grid[i + 1][j]
            for tri in ((a, b, c), (a, c, d)):
                mesh.triangle([v[0] for v in tri], [v[1] for v in tri], [v[2] for v in tri], [v[3] for v in tri])
                back = tri[::-1]
                mesh.triangle([v[0] for v in back], [_mul(v[1], -1.0) for v in back], [v[2] for v in back], [v[3] for v in back])


def _crown(mesh: Mesh, head: _Head, color: str) -> None:
    """Four wide flat clumps swept back over the crown: the dome's outline breaks into hair, not a cap."""
    for yaw, lat, lean in ((-35, 62, -0.25), (-12, 70, -0.3), (12, 70, 0.3), (35, 62, 0.25)):
        root = head.at(yaw, lat, 1.02)
        pull = head.at(yaw + lean * 20, lat + 18, 1.3)
        tip = head.at(yaw + lean * 50, min(89, lat + 8), 1.32)
        _clump(mesh, head, color, root, pull, tip, 0.42, 0.06, flat=0.16)


def _fringe(mesh: Mesh, head: _Head, color: str, count: int = 11, length: float = 0.62) -> None:
    """Pointed locks from a root on the dome's hairline (outside the face patch) down over the forehead to the brows, in three lengths so
    the tips stagger, flaring a little to the sides."""
    levels = (1.0, 0.85, 0.92)
    if head.L.get("real"):
        length *= 0.78   # a real fringe ends at the brow, it does not cover the eyes
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
        inner = head.at(sign * 52, 42, 1.06)   # a second, shorter lock in front of it: the side of the face is hair, not a gap
        _clump(mesh, head, color, inner, head.off(head.at(sign * 66, 0, 1.12), dz=0.12), (inner[0] + sign * head.rx * 0.05, head.chin + head.ry * 0.2, head.cz + head.rz * 0.34), 0.24, 0.04, flat=0.3)


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
    for i in range(14):
        yaw = 106 + i * 11.7
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
    _fringe(mesh, head, color, count=9)
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
