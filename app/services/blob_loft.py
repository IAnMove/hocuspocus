"""One smooth lofted body for the anime family, in the spirit of a PS2-era humanoid.

Every part is a tube: elliptical rings strung along an axis or a curve (``_tube``,
``curve_tube``), with radial smooth normals, so an elbow or a knee is a run of
rings the rig blends over, not a ball between two capsules. The torso tapers
from the shoulders to the waist and out again at the hips, the neck is a real
neck, the head is an egg with a jaw, the hands are mittens with fingers and a
thumb, the shoes have a sole, and the hair is geometry (``blob_hair``) in the hair
colour, written as its own primitive so the toon look can gloss it. Clothes are
colour regions of the same mesh (lapels and a shirt V by angle round a ring, a
pleated skirt by a wave on the hem) chosen by the ``outfit`` trait. The
silhouette stays a T-pose with a gap between the legs, which is what the
humanoid rig looks for.

Opt-in with ``traits.mesh: "loft"``; the default body stays the primitives.
Metres, Y up, +Z forward. Pure: no files, no rig.
"""
from __future__ import annotations

import bisect
import math

from services.procedural_3d.compose import linear_color

RING = 16
_JAW = 0.35
FACE_BOX, BACK_BOX = 2.7, 2.2
OUTFITS = ("school", "casual", "sport")


class Mesh:
    def __init__(self) -> None:
        self.vertices: list[tuple[float, float, float]] = []
        self.normals: list[tuple[float, float, float]] = []
        self.colors: list[tuple[float, float, float]] = []

    def triangle(self, points, normals, colors) -> None:
        self.vertices.extend(points)
        self.normals.extend(normals)
        self.colors.extend(colors)


def _unit(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (0.0, 1.0, 0.0) if length <= 1e-12 else (v[0] / length, v[1] / length, v[2] / length)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def darker(color: str, k: float) -> str:
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return "#%02X%02X%02X" % (min(255, int(r * k)), min(255, int(g * k)), min(255, int(b * k)))


def _point(station: dict, axis: str, t: float):
    """A ring point. ``a`` is the half-width across, ``b`` the half-depth; a wave ripples the hem of a skirt."""
    a, b = station["a"], station["b"]
    wave = station.get("wave")
    if wave:
        amp, count = wave
        a, b = a * (1 + amp * math.cos(count * t)), b * (1 + amp * math.cos(count * t))
    px, py, pz = station["p"]
    c, s = math.cos(t), math.sin(t)
    if axis == "y":
        return (px + a * c, py, pz + b * s)
    if axis == "x":
        return (px, py + a * c, pz + b * s)
    return (px + a * c, py + b * s, pz)


def _color_at(station: dict, t: float):
    """The station colour, or its ``front`` colour inside a half-angle of the forward direction (t = 90 degrees)."""
    front = station.get("front")
    if front:
        color, half = front
        delta = abs((t - math.pi / 2 + math.pi) % (2 * math.pi) - math.pi)
        if delta <= math.radians(half):
            return linear_color(color)
    return linear_color(station["color"])


def _emit(mesh: Mesh, grid, colors, centers, closed: bool, caps: tuple | None) -> None:
    """Quads between consecutive rings of ``grid`` with outward smooth normals; ``caps`` are the two end normals."""
    count = len(grid[0])
    normals = [[_normal_at(grid, i, j, closed, centers[i]) for j in range(count)] for i in range(len(grid))]
    for i in range(len(grid) - 1):
        for j in range(count if closed else count - 1):
            k = (j + 1) % count
            a, b, c, d = grid[i][j], grid[i][k], grid[i + 1][k], grid[i + 1][j]
            na, nb, nc, nd = normals[i][j], normals[i][k], normals[i + 1][k], normals[i + 1][j]
            ca, cb, cc, cd = colors[i][j], colors[i][k], colors[i + 1][k], colors[i + 1][j]
            if _degenerate(a, b, c) and _degenerate(a, c, d):
                continue
            if _dot(_cross(_sub(b, a), _sub(c, a)), na) < 0:
                mesh.triangle((a, c, b), (na, nc, nb), (ca, cc, cb))
                mesh.triangle((a, d, c), (na, nd, nc), (ca, cd, cc))
            else:
                mesh.triangle((a, b, c), (na, nb, nc), (ca, cb, cc))
                mesh.triangle((a, c, d), (na, nc, nd), (ca, cc, cd))
    if caps and closed:
        _cap(mesh, grid[0], colors[0], centers[0], caps[0])
        _cap(mesh, grid[-1], colors[-1], centers[-1], caps[1])


def _tube(mesh: Mesh, stations: list[dict], axis: str = "y", arc: tuple[float, float] | None = None,
          caps: bool = True, ring: int = RING) -> None:
    """Rings along an axis. ``arc`` (degrees) makes an open strip."""
    closed = arc is None
    if closed:
        angles = [j * math.tau / ring for j in range(ring)]
    else:
        start, end = math.radians(arc[0]), math.radians(arc[1])
        angles = [start + (end - start) * j / ring for j in range(ring + 1)]
    grid = [[_point(st, axis, t) for t in angles] for st in stations]
    colors = [[_color_at(st, t) for t in angles] for st in stations]
    axis_normal = {"y": (0.0, 1.0, 0.0), "x": (1.0, 0.0, 0.0), "z": (0.0, 0.0, 1.0)}[axis]
    _emit(mesh, grid, colors, [st["p"] for st in stations], closed, (_mul(axis_normal, -1.0), axis_normal) if caps else None)


def bezier(p0, p1, p2, count: int) -> list:
    """``count`` points of a quadratic curve from ``p0`` through the pull of ``p1`` to ``p2``."""
    out = []
    for i in range(count):
        u = i / (count - 1)
        w0, w1, w2 = (1 - u) ** 2, 2 * u * (1 - u), u * u
        out.append(tuple(w0 * p0[k] + w1 * p1[k] + w2 * p2[k] for k in range(3)))
    return out


def curve_tube(mesh: Mesh, points: list, radii: list, color: str, ring: int = 8, flat: float = 1.0, caps: bool = True) -> None:
    """A clump along ``points``: rings in the plane normal to the curve, ``radii[i]`` across and ``flat`` times that deep."""
    count = len(points)
    grid, colors = [], []
    up = (0.0, 1.0, 0.0)
    for i, p in enumerate(points):
        tangent = _unit(_sub(points[min(i + 1, count - 1)], points[max(i - 1, 0)]))
        ref = (1.0, 0.0, 0.0) if abs(_dot(tangent, up)) > 0.9 else up
        side = _unit(_cross(ref, tangent))
        deep = _unit(_cross(tangent, side))
        r = radii[i]
        grid.append([_add(p, _add(_mul(side, r * math.cos(t)), _mul(deep, r * flat * math.sin(t)))) for t in (j * math.tau / ring for j in range(ring))])
        colors.append([linear_color(color)] * ring)
    start = _unit(_sub(points[0], points[1]))
    end = _unit(_sub(points[-1], points[-2]))
    _emit(mesh, grid, colors, list(points), True, (start, end) if caps else None)


def _degenerate(a, b, c) -> bool:
    n = _cross(_sub(b, a), _sub(c, a))
    return _dot(n, n) < 1e-14


def _normal_at(grid, i, j, closed, center):
    count = len(grid[i])
    if closed:
        around = _sub(grid[i][(j + 1) % count], grid[i][(j - 1) % count])
    else:
        around = _sub(grid[i][min(j + 1, count - 1)], grid[i][max(j - 1, 0)])
    along = _sub(grid[min(i + 1, len(grid) - 1)][j], grid[max(i - 1, 0)][j])
    n = _cross(around, along)
    outward = _sub(grid[i][j], center)
    if _dot(n, n) < 1e-14:
        n = outward
    if _dot(n, outward) < 0:
        n = (-n[0], -n[1], -n[2])
    return _unit(n)


def _cap(mesh: Mesh, ring_points, ring_colors, center, normal) -> None:
    count = len(ring_points)
    for j in range(count):
        a, b = ring_points[j], ring_points[(j + 1) % count]
        if _degenerate(center, a, b):
            continue
        tri = (center, a, b) if _dot(_cross(_sub(a, center), _sub(b, center)), normal) > 0 else (center, b, a)
        mesh.triangle(tri, (normal, normal, normal), (ring_colors[j], ring_colors[j], ring_colors[(j + 1) % count]))


def _st(p, a, b, color, **extra) -> dict:
    return {"p": tuple(float(v) for v in p), "a": float(a), "b": float(b), "color": color, **extra}


def _egg_radius(phi: float) -> float:
    """Radius share of an egg at latitude ``phi``: a sphere above the equator, a jaw that narrows toward the chin."""
    return math.cos(phi) * (1.0 - _JAW * max(0.0, -math.sin(phi)) ** 2)


def egg_scale(sin_lat: float) -> float:
    """The same jaw formula as the head egg, for a cap that must hug it (``faceDecal.taper``)."""
    return 1.0 - _JAW * max(0.0, -sin_lat) ** 2


def _lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, u))


# The anime skull, measured from Qwen-drawn bald anime head sheets (front and side), crown ``v`` = 1 to chin ``v`` = 0:
# half-width (share of the widest ring), front depth and back depth (shares of the head's half depth, centre at the widest
# ring). The widest ring sits at 60 % of the height, the crown is a flat dome, the jaw is a V down to a small chin.
SKULL = (
    (0.00, 0.150, 0.853, 0.475), (0.05, 0.420, 0.876, 0.460), (0.10, 0.580, 0.900, 0.465), (0.15, 0.700, 0.924, 0.490),
    (0.20, 0.820, 0.936, 0.560), (0.25, 0.870, 0.940, 0.656), (0.30, 0.900, 0.940, 0.758), (0.35, 0.920, 0.941, 0.840),
    (0.40, 0.945, 0.948, 0.900), (0.45, 0.955, 0.964, 0.940), (0.50, 0.978, 0.997, 0.964), (0.55, 0.993, 1.023, 0.975),
    (0.60, 1.000, 1.027, 0.973), (0.65, 0.990, 1.019, 0.962), (0.70, 0.971, 0.997, 0.935), (0.75, 0.936, 0.962, 0.898),
    (0.80, 0.877, 0.905, 0.846), (0.85, 0.797, 0.822, 0.772), (0.90, 0.684, 0.706, 0.662), (0.93, 0.590, 0.610, 0.575),
    (0.95, 0.500, 0.520, 0.500), (0.96, 0.456, 0.463, 0.468), (0.97, 0.400, 0.404, 0.415), (0.98, 0.330, 0.332, 0.350),
    (0.99, 0.240, 0.236, 0.254), (1.00, 0.000, 0.000, 0.000),
)
_SKULL_V = [row[0] for row in SKULL]


def _catmull(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)


def skull_profile(lat: float) -> tuple[float, float, float, float]:
    """The anime skull at latitude ``lat`` (degrees, -90 chin to 90 crown): ``(width, back depth, front depth, boxiness)``
    as shares of the head radii, read from the measured ``SKULL`` table. ``boxiness`` is 0 at the poles and 1 at the widest
    ring: the rings are superellipses, round at the crown and chin and a little squarer where the face is."""
    v = (math.sin(math.radians(lat)) + 1.0) / 2.0
    i = min(len(SKULL) - 2, max(0, bisect.bisect_right(_SKULL_V, v) - 1))
    t = (v - SKULL[i][0]) / (SKULL[i + 1][0] - SKULL[i][0])
    out = []
    for column in (1, 2, 3):
        a, b = SKULL[i][column], SKULL[i + 1][column]
        p0, p3 = SKULL[max(0, i - 1)][column], SKULL[min(len(SKULL) - 1, i + 2)][column]
        out.append(max(0.0, min(_catmull(p0, a, b, p3, t), max(a, b) * 1.04 + 0.02)))
    return out[0], out[2], out[1], 1.0 - abs(2 * v - 1) ** 3


def _spow(x: float, e: float) -> float:
    return math.copysign(abs(x) ** e, x)


def skull_point(L: dict, yaw: float, lat: float, out: float = 1.0):
    """A point on the skull at ``yaw`` degrees from the face (+Z) and ``lat`` degrees up, ``out`` times outside it."""
    rx, ry, rz = L["sx"] / 2 * out, L["sy"] / 2 * out, L["sz"] / 2 * out
    width, back, front, box = skull_profile(lat)
    t = math.radians(yaw)
    s, c = math.sin(t), math.cos(t)
    exponent = 2.0 / (2.0 + ((FACE_BOX if c >= 0 else BACK_BOX) - 2.0) * box)
    return (rx * width * _spow(s, exponent), L["head_y"] + ry * math.sin(math.radians(lat)), rz * (front if c >= 0 else back) * _spow(c, exponent))


def _skull_ring(L: dict, lat: float, out: float, yaws) -> list:
    return [skull_point(L, yaw, lat, out) for yaw in yaws]


def _head(mesh: Mesh, L: dict, skin: str) -> None:
    yaws = [j * 360.0 / 24 for j in range(24)]
    lats = [-90 + 180 * k / 28 for k in range(29)]
    grid, colors = [], []
    for lat in lats:
        ring = _skull_ring(L, lat, 1.0, yaws)
        if abs(lat) >= 89.9:
            centre = (0.0, L["head_y"] + L["sy"] / 2 * math.sin(math.radians(lat)), 0.0)
            ring = [centre] * len(yaws)
        grid.append(ring)
        colors.append([linear_color(skin)] * len(yaws))
    centers = [(0.0, L["head_y"] + L["sy"] / 2 * math.sin(math.radians(lat)), 0.0) for lat in lats]
    _emit(mesh, grid, colors, centers, True, None)
    rx, ry, rz = L["sx"] / 2, L["sy"] / 2, L["sz"] / 2
    # a small nose ridge at the drawn nose's height (NOSE_Y of the head face), not a second nose above it
    base = skull_point(L, 0, -36, 1.0)
    nose = [_st((0, base[1] + ry * 0.03, base[2] - rz * 0.01), rx * 0.03, ry * 0.04, skin), _st((0, base[1] - ry * 0.01, base[2] + rz * 0.03), rx * 0.025, ry * 0.025, skin),
            _st((0, base[1] - ry * 0.03, base[2] + rz * 0.04), rx * 0.015, ry * 0.015, skin)]
    _tube(mesh, nose, "z", ring=8)
    # ears at the eye line, as tall as a fifth of the head
    for sign in (-1, 1):
        at = skull_point(L, sign * 90, -16, 1.0)
        ear = [_st((at[0] * 0.94, at[1], at[2] - rz * 0.06), rx * 0.12, ry * 0.2, skin),
               _st((at[0] * 1.08, at[1] + ry * 0.02, at[2] - rz * 0.07), rx * 0.1, ry * 0.17, skin),
               _st((at[0] * 1.14, at[1] + ry * 0.02, at[2] - rz * 0.08), rx * 0.01, ry * 0.03, skin)]
        _tube(mesh, ear, "x", ring=8)


FACE_YAWS = [-100 + 200.0 * j / 24 for j in range(25)]
FACE_LATS = [-86 + (48 + 86) * k / 16 for k in range(17)]


def face_patch(L: dict, fit) -> tuple[Mesh, list]:
    """The face as its own surface: the skull's front between the chin and the hairline, a hair's breadth outside it,
    white vertex colours (the picture multiplies them) and UVs that project the kit picture from the front: ``fit`` is
    ``[cu, cv, ru, rv]``, the drawn skull's centre and half-size as fractions of the picture."""
    mesh = Mesh()
    cu, cv, ru, rv = fit
    rx, ry = L["sx"] / 2, L["sy"] / 2
    grid, colors, uvs = [], [], []
    for lat in FACE_LATS:
        ring = _skull_ring(L, lat, 1.012, FACE_YAWS)
        grid.append(ring)
        colors.append([(1.0, 1.0, 1.0)] * len(ring))
        uvs.append([(cu + (p[0] / ry) * rv, 1.0 - (cv - ((p[1] - L["head_y"]) / ry) * rv)) for p in ring])
    centers = [(0.0, L["head_y"] + ry * math.sin(math.radians(lat)), 0.0) for lat in FACE_LATS]
    _emit(mesh, grid, colors, centers, False, None)
    out = []
    count = len(FACE_YAWS)
    for i in range(len(grid) - 1):
        for j in range(count - 1):
            k = j + 1
            a, b, c, d = grid[i][j], grid[i][k], grid[i + 1][k], grid[i + 1][j]
            ua, ub, uc, ud = uvs[i][j], uvs[i][k], uvs[i + 1][k], uvs[i + 1][j]
            if _degenerate(a, b, c) and _degenerate(a, c, d):
                continue
            na = _normal_at(grid, i, j, False, centers[i])
            if _dot(_cross(_sub(b, a), _sub(c, a)), na) < 0:
                out += [ua, uc, ub, ua, ud, uc]
            else:
                out += [ua, ub, uc, ua, uc, ud]
    assert len(out) == len(mesh.vertices)
    return mesh, out


def shoulder_top(L: dict) -> float:
    """Where the torso closes round the neck: a short neck under the chin. The primitives' torso_top reaches into the head."""
    return L["head_y"] - L["sy"] / 2 - 0.035 * L["h"]


def neck_width(L: dict) -> float:
    return min(L["sx"] * 0.42, L["torso_w"] * 0.46)


def _torso(mesh: Mesh, L: dict, spec: dict, wear: dict) -> None:
    top, bottom = wear["top"], wear["bottom"]
    h, w, d = L["h"], L["torso_w"], L["torso_d"]
    hip_w = L["waist_w"] * (1.16 if wear["legs"] == "skirt" else 1.06)
    neck_w = neck_width(L)
    chest = L["torso_bottom"] + L["torso_h"] * 0.64
    closing = shoulder_top(L)
    arm_y = wear["arm_y"]
    shirt = wear.get("shirt")
    lapel = lambda half: {"front": (shirt, half)} if shirt else {}
    lower = bottom if wear["legs"] != "skirt" else wear["legs_color"]
    stations = [
        _st((0, L["leg_top"] - 0.01 * h, 0), hip_w / 2 * 0.94, d / 2 * 0.86, lower),
        _st((0, L["leg_top"] + 0.035 * h, 0), hip_w / 2, d / 2 * 0.98, lower),
        _st((0, L["waist_y"] + 0.015 * h, 0), L["waist_w"] / 2 * 1.08, d / 2 * 0.86, lower),
        # the same ring twice: a colour change between rings would blend navy into white across the quad
        _st((0, L["waist_y"] + 0.015 * h + 0.0005, 0), L["waist_w"] / 2 * 1.08, d / 2 * 0.86, top),
        _st((0, L["waist_y"] + 0.05 * h, 0), L["waist_w"] / 2 * 1.1, d / 2 * 0.88, top),
        _st((0, chest, 0), w / 2 * 0.95, d / 2, top, **lapel(10)),
        _st((0, arm_y - 0.015 * h, 0), w / 2, d / 2 * 0.95, top, **lapel(22)),
        _st((0, arm_y + 0.012 * h, 0), w / 2 * 0.84, d / 2 * 0.86, top, **lapel(30)),
        _st((0, closing - 0.008 * h, 0), w / 2 * 0.5, d / 2 * 0.66, top, **lapel(38)),
        _st((0, closing + 0.004 * h, 0), neck_w / 2 * 1.25, d / 2 * 0.42, top, **lapel(44)),
    ]
    _tube(mesh, stations, "y")
    skin = spec["colors"]["head"]
    neck = [_st((0, closing - 0.02 * h, 0), neck_w / 2, neck_w / 2 * 0.92, skin),
            _st((0, L["head_y"] - L["sy"] * 0.3, 0), neck_w / 2 * 0.96, neck_w / 2 * 0.9, skin)]
    _tube(mesh, neck, "y")


def _arms(mesh: Mesh, L: dict, spec: dict, wear: dict) -> None:
    sleeve, skin = wear["sleeves"], spec["colors"]["hands"]
    y, r = wear["arm_y"], L["arm_d"] / 2
    x0, elbow, wrist, tip = L["torso_w"] / 2 - 0.03 * L["h"], L["elbow_x"], L["wrist_x"], L["tip_x"]
    bend = (elbow - x0) * 0.08
    short = wear["sleeves_len"] == "short"
    cuff = x0 + (elbow - x0) * 0.55
    for sign in (-1, 1):
        def at(x, k, color):
            return _st((sign * x, y, 0), r * k, r * k, color)
        arm = [at(x0 - 0.01 * L["h"], 1.18, sleeve), at(x0, 1.2, sleeve), at(x0 + (elbow - x0) * 0.22, 1.12, sleeve), at(x0 + (elbow - x0) * 0.55, 1.0, sleeve)]
        if short:
            arm += [at(cuff, 1.04, sleeve), at(cuff + 0.001, 0.9, skin)]
        lower = skin if short else sleeve
        arm += [at(elbow - bend, 0.92, lower), at(elbow, 0.9, lower), at(elbow + bend, 0.9, lower),
                at(elbow + (wrist - elbow) * 0.35, 0.86, lower), at(elbow + (wrist - elbow) * 0.75, 0.7, lower), at(wrist, 0.58, lower)]
        _tube(mesh, arm, "x")
        d = r * 2
        palm_end = wrist + (tip - wrist) * 0.52
        hand = [_st((sign * (wrist - 0.004), y, 0), d * 0.34, d * 0.3, skin), _st((sign * (wrist + (tip - wrist) * 0.22), y, 0), d * 0.58, d * 0.36, skin),
                _st((sign * palm_end, y, 0), d * 0.58, d * 0.34, skin), _st((sign * (palm_end + (tip - palm_end) * 0.55), y, 0), d * 0.5, d * 0.28, skin),
                _st((sign * (palm_end + (tip - palm_end) * 0.92), y, 0), d * 0.22, d * 0.16, skin)]
        _tube(mesh, hand, "x")
        # four fingers fanned from the palm's end, the thumb from its side
        for k, (dy, length) in enumerate(((0.3, 0.86), (0.1, 1.0), (-0.1, 0.96), (-0.3, 0.8))):
            fx0 = sign * (palm_end + (tip - palm_end) * 0.3)
            fx1 = sign * (palm_end + (tip - palm_end) * length)
            finger = [_st((fx0, y + d * dy, 0), d * 0.15, d * 0.13, skin), _st(((fx0 + fx1) / 2, y + d * dy * 1.05, 0), d * 0.13, d * 0.12, skin),
                      _st((fx1, y + d * dy * 1.1, 0), d * 0.08, d * 0.08, skin)]
            _tube(mesh, finger, "x", ring=6)
        px = sign * (wrist + (tip - wrist) * 0.2)
        thumb = [_st((px, y + d * 0.1, d * 0.16), d * 0.13, d * 0.12, skin), _st((px + sign * d * 0.12, y + d * 0.16, d * 0.42), d * 0.1, d * 0.1, skin),
                 _st((px + sign * d * 0.22, y + d * 0.2, d * 0.58), d * 0.05, d * 0.05, skin)]
        _tube(mesh, thumb, "z", ring=6)


def _legs(mesh: Mesh, L: dict, spec: dict, wear: dict) -> None:
    skin, shoes = spec["colors"]["head"], wear["shoes"]
    r, x = L["leg_d"] / 2, L["leg_x"]
    top, knee, ankle = L["leg_top"] + 0.06 * L["h"], L["knee"], L["leg_bottom"] + L["foot"] * 0.55
    legs, legs_color, sock = wear["legs"], wear["legs_color"], wear.get("socks")
    for sign in (-1, 1):
        def at(y, k, color):
            return _st((sign * x, y, 0), r * k, r * k * 0.95, color)
        upper = skin if legs in ("skirt", "shorts") else legs_color
        low = sock or (skin if legs in ("skirt", "shorts") else legs_color)
        under = legs_color if legs in ("skirt", "shorts") else upper   # under a skirt or shorts the thigh is hidden: never skin beside the waist
        leg = [at(top, 1.15, legs_color), at(top - 0.0005, 1.15, under), at(top - (top - knee) * 0.3, 1.1, under)]
        if legs == "shorts":
            hem = top - (top - knee) * 0.42
            leg += [at(hem, 1.12, legs_color), at(hem - 0.001, 1.0, skin)]
        leg += [at(knee + (top - knee) * 0.12, 0.9, upper), at(knee, 0.82, upper), at(knee - (knee - ankle) * 0.1, 0.84, upper),
                at(knee - (knee - ankle) * 0.1 - 0.0005, 0.84, low),
                at(knee - (knee - ankle) * 0.35, 0.88, low), at(knee - (knee - ankle) * 0.7, 0.68, low), at(ankle, 0.55, low)]
        _tube(mesh, leg, "y")
        sole_d, sole_h = L["leg_d"] * 1.9, L["foot"] * 0.42
        sneaker = wear["shoe_style"] == "sneaker"
        shoe = [_st((sign * x, sole_h * 0.95, -sole_d * 0.42), r * 1.0, sole_h * 0.95, shoes), _st((sign * x, sole_h * 1.15, -sole_d * 0.1), r * 1.14, sole_h * 1.15, shoes),
                _st((sign * x, sole_h * 1.05, sole_d * 0.3), r * 1.08, sole_h * 1.05, shoes), _st((sign * x, sole_h * 0.75, sole_d * 0.58), r * 0.62, sole_h * 0.62, shoes)]
        _tube(mesh, shoe, "z")
        sole_color = "#F2F0EC" if sneaker else darker(shoes, 0.55)
        sole = [_st((sign * x, sole_h * 0.3, -sole_d * 0.46), r * 1.04, sole_h * 0.3, sole_color), _st((sign * x, sole_h * 0.3, sole_d * 0.1), r * 1.18, sole_h * 0.3, sole_color),
                _st((sign * x, sole_h * 0.28, sole_d * 0.62), r * 0.7, sole_h * 0.28, sole_color)]
        _tube(mesh, sole, "z")


def _skirt(mesh: Mesh, L: dict, color: str) -> None:
    """One flared pleated tube (no front and back sheets, so it reads from the side too)."""
    h = L["h"]
    length = max(L["waist_y"] - L["knee"], h * 0.12)
    hem = max(L["torso_w"] * 1.5, L["leg_d"] * 4.2)
    stations = []
    for k in range(6):
        u = k / 5
        y = L["waist_y"] + 0.012 * h - length * u
        a = (L["waist_w"] / 2 * 1.1) * (1 - u) + hem / 2 * u
        b = (L["torso_d"] / 2 * 0.9) * (1 - u) + hem / 2 * 0.72 * u
        stations.append(_st((0, y, 0), a, b, color, wave=(0.06 * u, 12)))
    _tube(mesh, stations, "y", ring=36, caps=False)
    # the hem's underside, so no light shines through from below
    under = stations[-1]
    _tube(mesh, [under, _st((0, under["p"][1] + 0.001, 0), under["a"] * 0.4, under["b"] * 0.4, darker(color, 0.7))], "y", ring=36, caps=False)


def _collar_and_ribbon(mesh: Mesh, L: dict, wear: dict) -> None:
    h = L["h"]
    neck_w = neck_width(L)
    top = shoulder_top(L)
    if wear.get("collar"):
        collar = [_st((0, top + 0.002 * h, 0), neck_w / 2 * 1.15, neck_w / 2 * 1.0, wear["collar"]),
                  _st((0, top - 0.028 * h, 0), neck_w / 2 * 2.0, neck_w / 2 * 1.45, wear["collar"])]
        _tube(mesh, collar, "y")
    if wear.get("ribbon"):
        z = L["torso_d"] / 2 * 0.99
        y = top - 0.04 * h
        # A bow: two flat loops to the sides of a small knot. Not a tail hanging as a dark triangle.
        for sign in (-1, 1):
            loop = [_st((sign * 0.004 * h, y, z), 0.006 * h, 0.004 * h, wear["ribbon"]), _st((sign * 0.02 * h, y + 0.002 * h, z), 0.011 * h, 0.004 * h, wear["ribbon"]),
                    _st((sign * 0.034 * h, y, z), 0.004 * h, 0.003 * h, wear["ribbon"])]
            _tube(mesh, loop, "x", ring=8)
        _tube(mesh, [_st((0, y - 0.008 * h, z), 0.006 * h, 0.004 * h, wear["ribbon"]), _st((0, y + 0.008 * h, z), 0.006 * h, 0.004 * h, wear["ribbon"])], "y", ring=8)
    if wear.get("tie"):
        z = L["torso_d"] / 2 * 1.0
        tie = [_st((0, top - 0.025 * h, z), 0.009 * h, 0.004 * h, wear["tie"]), _st((0, top - 0.08 * h, z * 1.01), 0.014 * h, 0.005 * h, wear["tie"]),
               _st((0, top - 0.14 * h, z * 1.02), 0.006 * h, 0.003 * h, wear["tie"])]
        _tube(mesh, tie, "y", ring=8)


def wear_of(spec: dict, L: dict) -> dict:
    """What the outfit and the accessories mean on a lofted body: colour regions, sleeve and leg lengths, collar, bow, tie, shoes."""
    kinds = {item["kind"]: item["color"] for item in spec["accessories"]}
    colors = spec["colors"]
    outfit = spec.get("outfit", "school")
    skirt = "skirt" in kinds
    found = {
        "top": colors["top"], "sleeves": colors["sleeves"], "bottom": colors["bottom"], "shoes": colors["shoes"],
        "sleeves_len": "long", "legs": "skirt" if skirt else "trousers", "legs_color": kinds.get("skirt", colors["bottom"]),
        "socks": None, "collar": None, "ribbon": None, "tie": None, "shirt": None, "shoe_style": "loafer",
        "arm_y": max(L["shoulder_y"], shoulder_top(L) - 0.03 * L["h"]),
    }
    if outfit == "school":
        found.update({
            "socks": "#F7F4EF" if skirt else None,
            "collar": kinds.get("school_collar") or kinds.get("collar"),
            "ribbon": kinds["tie"] if skirt and "tie" in kinds else ("#1B2350" if skirt and "school_collar" in kinds else None),
            "tie": kinds["tie"] if not skirt and "tie" in kinds else None,
            "shirt": kinds.get("school_collar") if "jacket" in kinds else None,
        })
    elif outfit == "casual":
        found.update({"sleeves_len": "short", "legs": "skirt" if skirt else "shorts" if "shorts" in kinds else "trousers",
                      "legs_color": kinds.get("skirt") or kinds.get("shorts") or colors["bottom"], "shoe_style": "sneaker",
                      "socks": "#F7F4EF" if (skirt or "shorts" in kinds) else None})
    else:  # sport: a tracksuit, long sleeves and trousers, sneakers
        found.update({"sleeves_len": "long", "legs": "trousers", "legs_color": colors["bottom"], "shoe_style": "sneaker", "socks": None})
    return found


# The drawn skull box of the programmatic faces (blob_face_head.SKULL): what a body made without a kit projects on its face.
DEFAULT_FIT = [0.5, 0.458984375, 0.29296875, 0.3369140625]


def loft_parts(spec: dict, layout: dict, fit=None) -> list[tuple[Mesh, str, list | None]]:
    """The body, the face patch and the hair: ``[(mesh, material, uvs or None)]``. ``spec`` is a normalized anime body;
    ``fit`` is the face picture's skull box, so the face UVs and the kit agree."""
    from services.blob_hair import hair_mesh

    mesh = Mesh()
    wear = wear_of(spec, layout)
    _torso(mesh, layout, spec, wear)
    _arms(mesh, layout, spec, wear)
    _legs(mesh, layout, spec, wear)
    if wear["legs"] == "skirt":
        _skirt(mesh, layout, wear["legs_color"])
    _collar_and_ribbon(mesh, layout, wear)
    _head(mesh, layout, spec["colors"]["head"])
    face, uvs = face_patch(layout, fit or DEFAULT_FIT)
    hair = hair_mesh(layout, spec["hair"])
    parts = [(mesh, "body", None), (face, "face", uvs)]
    if hair.vertices:
        parts.append((hair, "hair", None))
    return parts


def loft_mesh(spec: dict, layout: dict) -> Mesh:
    """Everything in one mesh, for callers that only count triangles."""
    whole = Mesh()
    for part, _name, _uvs in loft_parts(spec, layout):
        whole.triangle(part.vertices, part.normals, part.colors)
    return whole


def loft_glb(spec: dict, layout: dict, name: str = "blob", fit=None) -> bytes:
    from services.procedural_3d.compose import pack_parts

    return pack_parts(name, [(part.vertices, part.normals, part.colors, material, uvs) for part, material, uvs in loft_parts(spec, layout, fit)])
