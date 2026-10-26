"""One smooth lofted body for the anime family, in the spirit of a PS2-era humanoid.

Every part is a tube: elliptical rings strung along an axis (``_tube``), with
radial smooth normals, so an elbow or a knee is a run of rings the rig blends
over, not a ball between two capsules. The torso tapers from the shoulders to
the waist and out again at the hips, the neck is a real neck, the head is an
egg with a jaw, the hands are mittens with a thumb, the shoes have a sole, and
the hair is geometry: a helmet round the back and crown, bangs, side locks or
spikes, in the hair colour. Clothes are colour regions of the same mesh
(lapels and a shirt V by angle round a ring, a pleated skirt by a wave on the
hem). The silhouette stays a T-pose with a gap between the legs and the skirt
as two thin sheets, which is what the humanoid rig looks for.

Opt-in with ``traits.mesh: "loft"``; the default body stays the primitives.
Metres, Y up, +Z forward. Pure: no files, no rig.
"""
from __future__ import annotations

import math

from services.procedural_3d.compose import linear_color

RING = 16
_JAW = 0.35
_HELMET = 1.07


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


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


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


def _color_at(station: dict, axis: str, t: float):
    """The station colour, or its ``front`` colour inside a half-angle of the forward direction (+Z, or +Y for a z tube)."""
    front = station.get("front")
    if front:
        color, half = front
        ahead = math.pi / 2  # z = b sin t peaks at t = 90 degrees (y tubes), the same for +Y on a z tube
        if axis == "x":
            ahead = math.pi / 2
        delta = abs((t - ahead + math.pi) % (2 * math.pi) - math.pi)
        if delta <= math.radians(half):
            return linear_color(color)
    return linear_color(station["color"])


def _tube(mesh: Mesh, stations: list[dict], axis: str = "y", arc: tuple[float, float] | None = None,
          caps: bool = True, ring: int = RING) -> None:
    """Quads between consecutive rings, outward smooth normals, optional flat caps. ``arc`` (degrees) makes an open strip."""
    closed = arc is None
    count = ring if closed else ring + 1
    if closed:
        angles = [j * math.tau / ring for j in range(ring)]
    else:
        start, end = math.radians(arc[0]), math.radians(arc[1])
        angles = [start + (end - start) * j / ring for j in range(ring + 1)]
    grid = [[_point(st, axis, t) for t in angles] for st in stations]
    colors = [[_color_at(st, axis, t) for t in angles] for st in stations]
    normals = [[_normal_at(grid, i, j, closed, stations[i]["p"]) for j in range(count)] for i in range(len(stations))]
    for i in range(len(stations) - 1):
        for j in range(count if closed else count - 1):
            k = (j + 1) % count
            a, b, c, d = grid[i][j], grid[i][k], grid[i + 1][k], grid[i + 1][j]
            na, nb, nc, nd = normals[i][j], normals[i][k], normals[i + 1][k], normals[i + 1][j]
            ca, cb, cc, cd = colors[i][j], colors[i][k], colors[i + 1][k], colors[i + 1][j]
            if _degenerate(a, b, c) and _degenerate(a, c, d):
                continue
            # wind so the face points the way the smooth normal does
            if _dot(_cross(_sub(b, a), _sub(c, a)), na) < 0:
                mesh.triangle((a, c, b), (na, nc, nb), (ca, cc, cb))
                mesh.triangle((a, d, c), (na, nd, nc), (ca, cd, cc))
            else:
                mesh.triangle((a, b, c), (na, nb, nc), (ca, cb, cc))
                mesh.triangle((a, c, d), (na, nc, nd), (ca, cc, cd))
    if caps and closed:
        _cap(mesh, grid[0], colors[0], stations[0]["p"], axis, -1.0)
        _cap(mesh, grid[-1], colors[-1], stations[-1]["p"], axis, 1.0)


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


def _cap(mesh: Mesh, ring_points, ring_colors, center, axis, sign: float) -> None:
    normal = {"y": (0.0, sign, 0.0), "x": (sign, 0.0, 0.0), "z": (0.0, 0.0, sign)}[axis]
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


def _head(mesh: Mesh, L: dict, skin: str) -> None:
    rx, ry, rz = L["sx"] / 2, L["sy"] / 2, L["sz"] / 2
    stations = []
    steps = 14
    for k in range(steps + 1):
        phi = -math.pi / 2 + math.pi * k / steps
        r = _egg_radius(phi)
        stations.append(_st((0, L["head_y"] + ry * math.sin(phi), 0), max(rx * r, 1e-4), max(rz * r, 1e-4), skin))
    _tube(mesh, stations, "y", caps=True)


def _helmet(mesh: Mesh, L: dict, color: str) -> None:
    """Hair round the crown and the back: full rings above the hairline, back arcs below it, just outside the face cap."""
    rx, ry, rz = L["sx"] / 2 * _HELMET, L["sy"] / 2 * _HELMET, L["sz"] / 2 * _HELMET
    hairline = math.radians(42)
    top, back = [], []
    for k in range(9):
        phi = hairline + (math.pi / 2 - hairline) * k / 8
        r = _egg_radius(phi)
        top.append(_st((0, L["head_y"] + ry * math.sin(phi), -rz * 0.04), max(rx * r, 1e-4), max(rz * r, 1e-4), color))
    for k in range(8):
        phi = math.radians(-28) + (hairline - math.radians(-28)) * k / 7
        r = _egg_radius(phi)
        back.append(_st((0, L["head_y"] + ry * math.sin(phi), -rz * 0.04), rx * r, rz * r, color))
    _tube(mesh, back, "y", arc=(160.0, 380.0), caps=False)
    _tube(mesh, top, "y", caps=True)


def _bangs(mesh: Mesh, L: dict, color: str) -> None:
    """Flat strands lying on the forehead, just under the helmet's hairline: volume in profile, no teeth from the front."""
    rx, ry, rz = L["sx"] / 2, L["sy"] / 2, L["sz"] / 2
    for x in (-0.6, -0.22, 0.22, 0.6):
        stations = []
        for k in range(4):
            y = L["head_y"] + ry * (0.66 - 0.3 * k / 3)
            z = rz * 1.06 * math.sqrt(max(0.0, 1 - ((y - L["head_y"]) / ry) ** 2))
            r = rx * (0.12 - 0.1 * k / 3)
            stations.append(_st((rx * x * (1 + 0.06 * k), y, z), r, r * 0.25, color))
        _tube(mesh, stations, "y", ring=8)


def _side_locks(mesh: Mesh, L: dict, color: str, long: bool) -> None:
    rx, ry, rz = L["sx"] / 2, L["sy"] / 2, L["sz"] / 2
    # Side locks end at the jaw like the drawn ones; long hair is the fall down the back.
    bottom = L["head_y"] - ry * 1.05
    for sign in (-1, 1):
        stations = [
            _st((sign * rx * 0.9, L["head_y"] + ry * 0.4, rz * 0.15), rx * 0.18, rz * 0.3, color),
            _st((sign * rx * 1.0, L["head_y"] - ry * 0.35, rz * 0.2), rx * 0.16, rz * 0.26, color),
            _st((sign * rx * 0.98, bottom, rz * 0.12), rx * 0.08, rz * 0.16, color),
        ]
        _tube(mesh, stations, "y", ring=8)
    if long:
        fall = [
            _st((0, L["head_y"] + ry * 0.3, -rz * 0.74), rx * 0.9, rz * 0.28, color),
            _st((0, L["head_y"] - ry * 0.7, -rz * 0.8), rx * 0.82, rz * 0.26, color),
            _st((0, L["torso_top"] - L["torso_h"] * 0.22, -L["torso_d"] / 2 * 1.05), rx * 0.72, rz * 0.2, color),
            _st((0, L["torso_top"] - L["torso_h"] * 0.5, -L["torso_d"] / 2 * 1.06), rx * 0.5, rz * 0.12, color),
        ]
        _tube(mesh, fall, "y", ring=10)


def _spikes(mesh: Mesh, L: dict, color: str) -> None:
    rx, ry, rz = L["sx"] / 2, L["sy"] / 2, L["sz"] / 2
    for x, z, lean_x, lean_z, length in ((0.0, 0.1, 0.0, -0.35, 0.5), (0.45, 0.0, 0.5, -0.2, 0.42), (-0.45, 0.0, -0.5, -0.2, 0.42),
                                         (0.25, -0.5, 0.3, -0.6, 0.4), (-0.25, -0.5, -0.3, -0.6, 0.4), (0.0, 0.55, 0.0, 0.3, 0.36)):
        base = (rx * x, L["head_y"] + ry * 0.78, rz * z)
        tip = (rx * (x + lean_x), base[1] + ry * length, rz * (z + lean_z))
        stations = [_st(base, rx * 0.16, rz * 0.16, color), _st(((base[0] + tip[0]) / 2, (base[1] + tip[1]) / 2, (base[2] + tip[2]) / 2), rx * 0.1, rz * 0.1, color),
                    _st(tip, rx * 0.012, rz * 0.012, color)]
        _tube(mesh, stations, "y", ring=8)


def _hair(mesh: Mesh, L: dict, hair: dict) -> None:
    style, color = hair["style"], hair["color"]
    if style == "none":
        return
    _helmet(mesh, L, color)
    if style == "spiky":
        _spikes(mesh, L, color)
        return
    # A painted front already draws its fringe; strands over it read as teeth. Only the bangs style adds them.
    if style == "bangs":
        _bangs(mesh, L, color)
    if style in ("long", "twin_tails", "ponytail"):
        _side_locks(mesh, L, color, long=True)
    elif style == "bangs":
        _side_locks(mesh, L, color, long=False)


def _shoulder_top(L: dict) -> float:
    """Where the torso closes round the neck: a neck's length under the chin. The primitives' torso_top reaches into the head."""
    return L["head_y"] - L["sy"] / 2 - 0.05 * L["h"]


def _torso(mesh: Mesh, L: dict, spec: dict, wear: dict) -> None:
    top, bottom = spec["colors"]["top"], spec["colors"]["bottom"]
    h, w, d = L["h"], L["torso_w"], L["torso_d"]
    hip_w = L["waist_w"] * (1.3 if wear["skirt"] else 1.12)
    neck_w = min(L["sx"] * 0.36, w * 0.42)
    chest = L["torso_bottom"] + L["torso_h"] * 0.64
    closing = _shoulder_top(L)
    shirt = wear.get("shirt")
    lapel = lambda half: {"front": (shirt, half)} if shirt else {}
    stations = [
        _st((0, L["leg_top"] - 0.01 * h, 0), hip_w / 2 * 0.92, d / 2 * 0.86, bottom),
        _st((0, L["leg_top"] + 0.035 * h, 0), hip_w / 2, d / 2 * 0.98, bottom),
        _st((0, L["waist_y"] + 0.015 * h, 0), L["waist_w"] / 2, d / 2 * 0.84, bottom if wear["skirt"] else top),
        _st((0, L["waist_y"] + 0.05 * h, 0), L["waist_w"] / 2 * 1.04, d / 2 * 0.86, top),
        _st((0, chest, 0), w / 2 * 0.95, d / 2, top, **lapel(10)),
        _st((0, L["shoulder_y"], 0), w / 2, d / 2 * 0.95, top, **lapel(22)),
        _st((0, closing - 0.012 * h, 0), w / 2 * 0.62, d / 2 * 0.72, top, **lapel(32)),
        _st((0, closing + 0.004 * h, 0), neck_w / 2 * 1.3, d / 2 * 0.42, top, **lapel(42)),
    ]
    _tube(mesh, stations, "y")
    skin = spec["colors"]["head"]
    neck = [_st((0, closing - 0.02 * h, 0), neck_w / 2, neck_w / 2 * 0.92, skin),
            _st((0, L["head_y"] - L["sy"] * 0.3, 0), neck_w / 2 * 0.96, neck_w / 2 * 0.9, skin)]
    _tube(mesh, neck, "y")


def _arms(mesh: Mesh, L: dict, spec: dict) -> None:
    sleeve, skin = spec["colors"]["sleeves"], spec["colors"]["hands"]
    y, r = L["shoulder_y"], L["arm_d"] / 2
    x0, elbow, wrist, tip = L["torso_w"] / 2 - 0.03 * L["h"], L["elbow_x"], L["wrist_x"], L["tip_x"]
    bend = (elbow - x0) * 0.08
    for sign in (-1, 1):
        def at(x, k, color):
            return _st((sign * x, y, 0), r * k, r * k, color)
        arm = [at(x0, 1.0, sleeve), at(x0 + (elbow - x0) * 0.35, 1.0, sleeve), at(elbow - bend, 0.93, sleeve), at(elbow, 0.9, sleeve),
               at(elbow + bend, 0.88, sleeve), at(elbow + (wrist - elbow) * 0.6, 0.8, sleeve), at(wrist, 0.68, sleeve)]
        _tube(mesh, arm, "x")
        d = r * 2
        hand = [_st((sign * (wrist - 0.004), y, 0), d * 0.36, d * 0.3, skin), _st((sign * (wrist + (tip - wrist) * 0.3), y, 0), d * 0.5, d * 0.3, skin),
                _st((sign * (wrist + (tip - wrist) * 0.7), y, 0), d * 0.44, d * 0.25, skin), _st((sign * tip, y, 0), d * 0.18, d * 0.13, skin)]
        _tube(mesh, hand, "x")
        px = sign * (wrist + (tip - wrist) * 0.28)
        thumb = [_st((px, y + d * 0.05, d * 0.2), d * 0.15, d * 0.14, skin), _st((px + sign * d * 0.1, y + d * 0.12, d * 0.5), d * 0.12, d * 0.11, skin),
                 _st((px + sign * d * 0.2, y + d * 0.16, d * 0.68), d * 0.06, d * 0.06, skin)]
        _tube(mesh, thumb, "z", ring=8)


def _legs(mesh: Mesh, L: dict, spec: dict, wear: dict) -> None:
    bottom, skin, shoes = spec["colors"]["bottom"], spec["colors"]["head"], spec["colors"]["shoes"]
    r, x = L["leg_d"] / 2, L["leg_x"]
    top, knee, ankle = L["leg_top"] + 0.06 * L["h"], L["knee"], L["leg_bottom"] + L["foot"] * 0.55
    sock = wear.get("socks")
    for sign in (-1, 1):
        def at(y, k, color):
            return _st((sign * x, y, 0), r * k, r * k * 0.95, color)
        leg_color = skin if wear["skirt"] else bottom
        low = sock or leg_color
        leg = [at(top, 1.15, bottom), at(top - (top - knee) * 0.35, 1.08, leg_color), at(knee + (top - knee) * 0.12, 0.9, leg_color),
               at(knee, 0.82, leg_color), at(knee - (knee - ankle) * 0.1, 0.84, low), at(knee - (knee - ankle) * 0.35, 0.88, low),
               at(knee - (knee - ankle) * 0.7, 0.68, low), at(ankle, 0.55, low)]
        _tube(mesh, leg, "y")
        sole_d, sole_h = L["leg_d"] * 1.9, L["foot"] * 0.42
        shoe = [_st((sign * x, sole_h * 0.9, -sole_d * 0.42), r * 1.0, sole_h * 0.9, shoes), _st((sign * x, sole_h * 1.1, -sole_d * 0.1), r * 1.12, sole_h * 1.1, shoes),
                _st((sign * x, sole_h * 1.0, sole_d * 0.3), r * 1.05, sole_h * 1.0, shoes), _st((sign * x, sole_h * 0.7, sole_d * 0.58), r * 0.6, sole_h * 0.6, shoes)]
        _tube(mesh, shoe, "z")


def _skirt(mesh: Mesh, L: dict, color: str) -> None:
    """Two thin pleated sheets, front and back, so the rig still sees the legs and the feet."""
    h = L["h"]
    length = max(L["waist_y"] - L["knee"], h * 0.12)
    hem = max(L["torso_w"] * 1.5, L["leg_d"] * 4.2)
    thin = max(0.014 * h, 0.012)
    for sign in (1, -1):
        z = sign * (L["torso_d"] / 2 - thin * 0.2)
        stations = []
        for k in range(5):
            u = k / 4
            y = L["waist_y"] + 0.01 * h - length * u
            a = (L["waist_w"] / 2 * 1.08) * (1 - u) + hem / 2 * u
            stations.append(_st((0, y, z), a, thin / 2 + a * 0.08 * u, color, wave=(0.07 * u, 9)))
        _tube(mesh, stations, "y", ring=24)


def _collar_and_ribbon(mesh: Mesh, L: dict, wear: dict) -> None:
    h = L["h"]
    neck_w = min(L["sx"] * 0.36, L["torso_w"] * 0.42)
    top = _shoulder_top(L)
    if wear.get("collar"):
        # The collar sits on the shoulders, under the chin, not on the neck.
        collar = [_st((0, top + 0.002 * h, 0), neck_w / 2 * 1.15, neck_w / 2 * 1.0, wear["collar"]),
                  _st((0, top - 0.028 * h, 0), neck_w / 2 * 2.0, neck_w / 2 * 1.45, wear["collar"])]
        _tube(mesh, collar, "y")
    if wear.get("ribbon"):
        z = L["torso_d"] / 2 * 0.99
        # A small bow: a knot and two short tails, not a bib.
        knot = [_st((0, top - 0.032 * h, z), 0.013 * h, 0.004 * h, wear["ribbon"]), _st((0, top - 0.042 * h, z), 0.017 * h, 0.004 * h, wear["ribbon"]),
                _st((0, top - 0.068 * h, z), 0.006 * h, 0.003 * h, wear["ribbon"])]
        _tube(mesh, knot, "y", ring=8)
    if wear.get("tie"):
        z = L["torso_d"] / 2 * 1.0
        tie = [_st((0, top - 0.025 * h, z), 0.009 * h, 0.004 * h, wear["tie"]), _st((0, top - 0.08 * h, z * 1.01), 0.014 * h, 0.005 * h, wear["tie"]),
               _st((0, top - 0.14 * h, z * 1.02), 0.006 * h, 0.003 * h, wear["tie"])]
        _tube(mesh, tie, "y", ring=8)


def _wear(spec: dict) -> dict:
    """What the accessories mean on a lofted body: colour regions, a collar, a ribbon or a tie."""
    kinds = {item["kind"]: item["color"] for item in spec["accessories"]}
    skirt = "skirt" in kinds
    return {
        "skirt": kinds.get("skirt") if skirt else None,
        "socks": "#F7F4EF" if skirt else None,
        "collar": kinds.get("school_collar") or kinds.get("collar"),
        "ribbon": kinds["tie"] if skirt and "tie" in kinds else ("#1B2350" if skirt and "school_collar" in kinds else None),
        "tie": kinds["tie"] if not skirt and "tie" in kinds else None,
        "shirt": kinds.get("school_collar") if "jacket" in kinds else None,
    }


def loft_mesh(spec: dict, layout: dict) -> Mesh:
    """The whole body as one mesh. ``spec`` is a normalized anime body, ``layout`` its ``blob_builder._layout``."""
    mesh = Mesh()
    wear = _wear(spec)
    _torso(mesh, layout, spec, wear)
    _arms(mesh, layout, spec)
    _legs(mesh, layout, spec, wear)
    if wear["skirt"]:
        _skirt(mesh, layout, wear["skirt"])
    _collar_and_ribbon(mesh, layout, wear)
    _head(mesh, layout, spec["colors"]["head"])
    _hair(mesh, layout, spec["hair"])
    return mesh


def loft_glb(spec: dict, layout: dict, name: str = "blob") -> bytes:
    from services.procedural_3d.compose import pack_mesh

    mesh = loft_mesh(spec, layout)
    return pack_mesh(name, mesh.vertices, mesh.normals, mesh.colors)
