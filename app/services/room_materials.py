"""Procedural, tileable materials for box rooms: no model, no GPU, deterministic.

A room never has to be a grey box. ``pick`` reads the words of a surface (``"oak parquet"``, ``"paneles metálicos
remachados color crema"``) and chooses one of ``MATERIALS`` and a base colour; ``make`` draws it with numpy. Every
material is periodic by construction (noise on an integer lattice that wraps, joints on exact divisors of the
picture), so the wrap seam is as smooth as any interior pixel and the surface repeats cleanly every ``tile_m`` metres.
The same seed and the same arguments give the same picture. ``VERSION`` goes up when a drawing changes, so a stored
room can tell that its default look is out of date.

``scene3d.room.paint`` replaces these by pictures from the image model and keeps these when the model fails.
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
from PIL import Image

VERSION = 1
SIZE = 512

# material -> (default colour, metres one repeat of the 512 px picture covers)
MATERIALS: dict[str, tuple[tuple[int, int, int], float]] = {
    "plaster": ((228, 218, 198), 2.0),
    "concrete": ((150, 150, 146), 2.0),
    "wood_planks": ((172, 134, 92), 1.2),
    "parquet": ((168, 120, 72), 1.2),
    "metal_panels": ((150, 156, 162), 2.4),
    "riveted_steel": ((118, 126, 134), 2.4),
    "tile": ((210, 206, 196), 1.2),
    "carpet": ((120, 96, 92), 1.0),
    "brick": ((158, 82, 62), 1.2),
    "stone": ((150, 142, 130), 2.0),
    "linoleum": ((124, 140, 112), 2.0),
}

# Checked in this order: the more specific word wins ("riveted metal" is riveted steel, not just metal).
_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("riveted_steel", ("remach", "rivet")),
    ("metal_panels", ("metal", "acero", "steel", "alumin", "chapa", "cromo", "chrome", "aleacion", "alloy", "casco de nave", "hull")),
    ("parquet", ("parquet", "entarimad", "herringbone", "espiga")),
    ("brick", ("ladrillo", "brick")),
    ("stone", ("piedra", "stone", "losa", "flagstone", "granit", "marmol", "marble", "adoquin", "cobble")),
    ("concrete", ("hormigon", "concret", "cemento", "cement")),
    ("tile", ("azulej", "baldosa", "tile", "ceramic", "mosaic", "damero", "checker")),
    ("linoleum", ("linole", "linoleum", "vinil", "vinyl", "pvc", "goma", "rubber")),
    ("carpet", ("alfombr", "moqueta", "carpet", "rug", "felpudo")),
    ("wood_planks", ("tablon", "plank", "madera", "wood", "tablas", "boards", "roble", "oak", "nogal", "walnut", "pino", "pine",
                     "cerezo", "cherry", "teca", "teak", "arce", "maple", "deck")),
    ("plaster", ("yeso", "plaster", "pintura", "paint", "estuco", "stucco", "enlucido", "wallpaper", "papel pintado", "pared lisa")),
)
_COLORS: tuple[tuple[tuple[str, ...], tuple[int, int, int]], ...] = (
    (("crema", "cream", "marfil", "ivory"), (232, 222, 190)),
    (("beige", "arena", "sand"), (214, 196, 160)),
    (("blanco", "white"), (236, 236, 230)),
    (("negro", "black"), (50, 50, 52)),
    (("verde", "green"), (108, 150, 112)),
    (("azul", "blue"), (96, 126, 168)),
    (("rojo", "red"), (170, 70, 60)),
    (("amarill", "yellow"), (214, 184, 80)),
    (("naranja", "orange"), (210, 125, 60)),
    (("turquesa", "teal", "cian", "cyan"), (90, 150, 150)),
    (("rosa", "pink"), (214, 150, 160)),
    (("morad", "purple", "violet"), (120, 90, 150)),
    (("plata", "silver", "plateado"), (178, 182, 186)),
    (("gris", "gray", "grey"), (150, 150, 150)),
    (("marron", "brown", "chocolate"), (120, 84, 56)),
    (("roble", "oak"), (174, 128, 78)),
    (("nogal", "walnut"), (96, 62, 42)),
    (("pino", "pine"), (208, 170, 110)),
    (("cerezo", "cherry"), (150, 78, 52)),
    (("ebano", "ebony"), (50, 38, 32)),
    (("arce", "maple"), (210, 176, 126)),
    (("teca", "teak"), (150, 104, 60)),
)
_DARK = ("oscur", "dark")
_LIGHT = ("claro", "light", "pale", "pastel")
# What a surface wears when its words name nothing: warm boards, painted walls, a wooden door.
_DEFAULT = {"floor": "wood_planks", "walls": "plaster", "ceiling": "plaster", "door": "wood_planks", "trim": "plaster"}
_METAL = ("metal_panels", "riveted_steel")


# ---------------------------------------------------------------- noise on a lattice that wraps


def _noise(rng: np.random.Generator, fx: int, fy: int | None = None, n: int = SIZE) -> np.ndarray:
    """Smooth periodic value noise in [0, 1]: ``fx`` by ``fy`` random cells across the picture, joined by a smoothstep."""
    fy = fy or fx
    grid = rng.random((fy, fx))
    xs, ys = np.arange(n) * fx / n, np.arange(n) * fy / n
    x0, y0 = xs.astype(int), ys.astype(int)
    tx, ty = xs - x0, ys - y0
    tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
    x1, y1 = (x0 + 1) % fx, (y0 + 1) % fy
    top = grid[y0][:, x0] * (1 - tx) + grid[y0][:, x1] * tx
    bottom = grid[y1][:, x0] * (1 - tx) + grid[y1][:, x1] * tx
    return top * (1 - ty)[:, None] + bottom * ty[:, None]


def _fbm(rng: np.random.Generator, octaves: tuple[tuple[int, int, float], ...], n: int = SIZE) -> np.ndarray:
    """Zero-mean periodic noise in about [-1, 1] from ``(fx, fy, weight)`` octaves."""
    total = sum(weight for _fx, _fy, weight in octaves)
    return sum(weight * (_noise(rng, fx, fy, n) - 0.5) * 2 for fx, fy, weight in octaves) / total


def _grain(rng: np.random.Generator, n: int, amount: float) -> np.ndarray:
    """Per-pixel grain, softened by a 3 x 3 box that wraps."""
    raw = rng.random((n, n)) - 0.5
    blurred = sum(np.roll(np.roll(raw, dy, 0), dx, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1)) / 9
    return blurred * amount * 2


def _smooth(edge0: float, edge1: float, value: np.ndarray) -> np.ndarray:
    t = np.clip((value - edge0) / (edge1 - edge0), 0, 1)
    return t * t * (3 - 2 * t)


def _stamp(canvas: np.ndarray, cy: int, cx: int, patch: np.ndarray) -> None:
    """Add ``patch`` centred on (cy, cx); a patch that crosses an edge continues on the other side."""
    half = patch.shape[0] // 2
    rows = (np.arange(patch.shape[0]) + cy - half) % canvas.shape[0]
    cols = (np.arange(patch.shape[1]) + cx - half) % canvas.shape[1]
    canvas[np.ix_(rows, cols)] += patch


def _disc(radius: int, lit: float) -> np.ndarray:
    """A shaded dome: light from the top left, dark rim at the lower right."""
    size = radius * 2 + 3
    yy, xx = np.mgrid[:size, :size] - size // 2
    dist = np.hypot(yy, xx) / radius
    dome = np.clip(1 - dist, 0, 1) ** 0.5
    shade = (-(yy + xx) / (radius * 2.0)) * lit * dome
    ring = _smooth(0.8, 1.15, dist) * (dist < 1.25) * -lit * 0.6
    return np.where(dist < 1.25, shade + ring, 0.0)


# ---------------------------------------------------------------- the materials. Each returns float RGB 0..255.


def _paint(base: tuple, light: np.ndarray) -> np.ndarray:
    return np.asarray(base, dtype=float)[None, None, :] * light[..., None]


def _plaster(rng, base, n):
    light = 1 + 0.06 * _fbm(rng, ((2, 2, 0.5), (4, 4, 0.3), (9, 9, 0.2)), n) + 0.03 * _fbm(rng, ((24, 24, 1.0),), n) + _grain(rng, n, 0.05)
    light += 0.02 * (_noise(rng, 70, 3, n) - 0.5) * 2
    stain = np.clip(_fbm(rng, ((3, 3, 1.0), (7, 7, 0.5)), n) - 0.15, 0, 1)
    light -= 0.12 * stain
    light -= 0.12 * (_noise(rng, 160, 160, n) > 0.96)
    return _paint(base, light)


def _concrete(rng, base, n):
    light = 1 + 0.11 * _fbm(rng, ((3, 3, 0.5), (8, 8, 0.4), (24, 24, 0.3), (64, 64, 0.2)), n) + _grain(rng, n, 0.05)
    light -= 0.24 * (_noise(rng, 140, 140, n) > 0.93)
    yy, xx = np.mgrid[:n, :n]
    for step in (n // 2,):
        light -= 0.22 * ((yy % step) < 2) + 0.12 * ((xx % step) < 2)
    tie = np.zeros((n, n))
    for row in (n // 4, 3 * n // 4):
        for col in (n // 4, 3 * n // 4):
            _stamp(tie, row, col, -_disc(7, 0.5) * 0.9)
    return _paint(base, light + tie)


def _plank_tones(rng, planks: int) -> np.ndarray:
    return 1 + 0.13 * (rng.random((planks, 2)) - 0.5) * 2


def _wood_planks(rng, base, n, planks: int = 8):
    yy, xx = np.mgrid[:n, :n]
    row, local = (yy * planks // n), ((yy * planks / n) % 1.0)
    tones = _plank_tones(rng, planks)
    start = rng.integers(0, n, planks)
    # Two boards per row, one joint each way round: a plank is a metre or more, not a parquet block.
    cut = (start + rng.integers(n // 3, n // 2 + n // 6, planks)) % n
    part = ((xx - start[row]) % n >= (cut[row] - start[row]) % n).astype(int)
    tone = tones[row, part]
    warp = _noise(rng, 3, planks * 2, n)
    phase = rng.random(planks)[row]
    rings = 0.5 + 0.5 * np.sin(2 * np.pi * (5 * local + 2.2 * warp + phase))
    streak = _noise(rng, 6, 240, n) - 0.5
    light = tone * (1 + 0.10 * (rings - 0.5) * 2 + 0.09 * streak) + _grain(rng, n, 0.025)
    gap = np.minimum(local, 1 - local) * (n / planks)
    light *= 1 - 0.65 * _smooth(2.2, 0.4, gap)
    light *= 1 + 0.12 * ((local * n / planks > 2) & (local * n / planks < 4))
    joint = np.zeros((n, n))
    for plank in range(planks):
        for edge in (start[plank], cut[plank]):
            joint[(row == plank) & (((xx - edge) % n) < 2)] = 1
    return _paint(base, light * (1 - 0.6 * joint))


def _parquet(rng, base, n, blocks: int = 4, strips: int = 4):
    yy, xx = np.mgrid[:n, :n]
    block = n // blocks
    bi, bj = yy // block, xx // block
    lu, lv = (xx % block) / block, (yy % block) / block
    across = np.where(((bi + bj) & 1) == 0, lv, lu)
    strip = np.floor(across * strips).astype(int)
    ident = (bi * blocks + bj) * strips + strip
    tones = 1 + 0.15 * (rng.random(blocks * blocks * strips) - 0.5) * 2
    along = np.where(((bi + bj) & 1) == 0, _noise(rng, 2, 96, n), _noise(rng, 96, 2, n))
    light = tones[ident] * (1 + 0.16 * (along - 0.5) * 2) + _grain(rng, n, 0.025)
    local = (across * strips) % 1.0
    gap = np.minimum(local, 1 - local) * (block / strips)
    light *= 1 - 0.7 * _smooth(1.8, 0.3, gap)
    light *= 1 + 0.10 * ((local * block / strips > 1.5) & (local * block / strips < 3.5))
    return _paint(base, light)


def _panel_edges(n: int, cols: int, rows: int) -> tuple[np.ndarray, ...]:
    yy, xx = np.mgrid[:n, :n]
    pw, ph = n / cols, n / rows
    pu, pv = (xx % pw), (yy % ph)
    return pu, pv, pw, ph, (xx // pw).astype(int), (yy // ph).astype(int)


def _plates(rng, base, n, cols: int, rows: int, seam: float, wear: float):
    pu, pv, pw, ph, ci, ri = _panel_edges(n, cols, rows)
    tones = 1 + 0.07 * (rng.random((rows, cols)) - 0.5) * 2
    brushed = _noise(rng, 2, n // 2, n) - 0.5
    dirt = np.clip(_fbm(rng, ((n // 8, 2, 1.0),), n) - 0.1, 0, 1)
    light = tones[ri, ci] * (1 + 0.09 * brushed * 2) + _grain(rng, n, 0.02) - 0.08 * dirt
    edge = np.minimum(np.minimum(pu, pw - pu), np.minimum(pv, ph - pv))
    light *= 1 - 0.55 * _smooth(seam, 0.3, edge)
    lit = ((pu < 7) | (pv < 7)) & (edge > seam)
    shade = ((pu > pw - 7) | (pv > ph - 7)) & (edge > seam)
    light *= 1 + 0.12 * lit - 0.14 * shade
    rust = np.clip(_fbm(rng, ((6, 6, 1.0), (20, 20, 0.5)), n) - 0.4, 0, 1) * wear
    return light, rust, (ci, ri, pw, ph)


def _metal_panels(rng, base, n):
    light, rust, (_ci, _ri, pw, ph) = _plates(rng, base, n, 2, 2, 2.2, 0.5)
    canvas = np.zeros((n, n))
    for row in range(2):
        for col in range(2):
            for fy, fx in ((0.07, 0.07), (0.07, 0.93), (0.93, 0.07), (0.93, 0.93)):
                _stamp(canvas, int((row + fy) * ph), int((col + fx) * pw), _disc(6, 0.34))
    colour = _paint(base, light + canvas)
    return colour * (1 - rust[..., None] * 0.5) + rust[..., None] * np.array([110, 70, 44]) * 0.5


def _riveted_steel(rng, base, n):
    cols = rows = 3
    light, rust, (_ci, _ri, pw, ph) = _plates(rng, base, n, cols, rows, 2.4, 0.9)
    canvas = np.zeros((n, n))
    per_side = 8
    for row in range(rows):
        for col in range(cols):
            for k in range(per_side):
                t = (k + 0.5) / per_side
                for fy, fx in ((0.06, t), (0.94, t), (t, 0.06), (t, 0.94)):
                    _stamp(canvas, int((row + fy) * ph), int((col + fx) * pw), _disc(5, 0.4))
    colour = _paint(base, light + canvas)
    return colour * (1 - rust[..., None] * 0.6) + rust[..., None] * np.array([120, 66, 36]) * 0.6


def _tile(rng, base, n, count: int = 4):
    yy, xx = np.mgrid[:n, :n]
    size = n / count
    pu, pv = (xx % size) / size, (yy % size) / size
    ident = ((yy // size).astype(int) * count + (xx // size).astype(int))
    tones = 1 + 0.07 * (rng.random(count * count) - 0.5) * 2
    gloss = 1 + 0.06 * (1 - (pu + pv)) + 0.05 * (_noise(rng, 5, 5, n) - 0.5)
    light = tones[ident] * gloss + _grain(rng, n, 0.025)
    edge = np.minimum(np.minimum(pu, 1 - pu), np.minimum(pv, 1 - pv)) * size
    grout = _smooth(2.6, 0.8, edge)
    light *= 1 + 0.07 * ((pu < 0.05) | (pv < 0.05))
    wear = np.clip(_fbm(rng, ((4, 4, 1.0), (14, 14, 0.5)), n) - 0.3, 0, 1)
    colour = _paint(base, light - 0.08 * wear)
    mortar = np.asarray((176, 172, 162), dtype=float)[None, None, :] * (1 - 0.18 * wear[..., None])
    return colour * (1 - grout[..., None]) + mortar * grout[..., None]


def _carpet(rng, base, n):
    raw = rng.random((n, n)) - 0.5
    fibre = 0.5 * raw + 0.5 * (np.roll(raw, 1, 0) + np.roll(raw, -1, 1)) / 2
    loops = (_noise(rng, 96, 96, n) - 0.5) * 2
    mid = _fbm(rng, ((10, 10, 0.5), (28, 28, 0.5)), n)
    lines = np.sin(2 * np.pi * (6 * np.arange(n)[:, None] / n + 0.6 * _noise(rng, 3, 3, n)))
    light = 1 + 0.15 * fibre + 0.10 * loops + 0.08 * mid + 0.035 * lines + 0.07 * _fbm(rng, ((3, 3, 0.6), (6, 6, 0.4)), n)
    wear = np.clip(_fbm(rng, ((2, 2, 1.0), (5, 5, 0.5)), n) - 0.2, 0, 1)
    return _paint(base, light + 0.11 * wear)


def _brick(rng, base, n, rows: int = 16, cols: int = 5):
    yy, xx = np.mgrid[:n, :n]
    course = (yy * rows // n)
    v = (yy * rows / n) % 1.0
    along = xx * cols / n + 0.5 * (course % 2)
    index = np.floor(along).astype(int) % cols
    u = along % 1.0
    tones = 1 + 0.16 * (rng.random((rows, cols)) - 0.5) * 2
    hue = (rng.random((rows, cols)) - 0.5) * 2
    face = tones[course, index]
    light = face * (1 + 0.10 * _fbm(rng, ((16, 16, 0.6), (48, 48, 0.4)), n)) + _grain(rng, n, 0.05)
    light *= 1 + 0.08 * (0.5 - v)
    colour = _paint(base, light)
    colour[..., 1] *= 1 + 0.08 * hue[course, index]
    colour[..., 2] *= 1 + 0.12 * hue[course, index]
    brick_h = n / rows
    dv = np.minimum(v, 1 - v) * brick_h
    du = np.minimum(u, 1 - u) * (n / cols)
    mortar = np.maximum(_smooth(2.4, 0.4, dv), _smooth(2.4, 0.4, du))
    sand = np.asarray((176, 170, 156), dtype=float)[None, None, :] * (1 + 0.10 * _fbm(rng, ((32, 32, 1.0),), n)[..., None])
    return colour * (1 - mortar[..., None]) + sand * mortar[..., None]


def _wrapped(n: int, yy, xx, cy: float, cx: float) -> np.ndarray:
    dy, dx = np.abs(yy - cy), np.abs(xx - cx)
    return np.hypot(np.minimum(dy, n - dy), np.minimum(dx, n - dx))


def _stone(rng, base, n, points: int = 18):
    yy, xx = np.mgrid[:n, :n]
    centres = rng.random((points, 2)) * n
    nearest = np.full((n, n), 1e9)
    ident = np.zeros((n, n), dtype=int)
    for index, (cy, cx) in enumerate(centres):
        dist = _wrapped(n, yy, xx, cy, cx)
        closer = dist < nearest
        ident = np.where(closer, index, ident)
        nearest = np.where(closer, dist, nearest)
    edge = np.full((n, n), 1e9)
    for index, (cy, cx) in enumerate(centres):
        # Distance to the bisector between the owner of the pixel and this centre: the true distance to that joint.
        owner = centres[ident]
        sep = np.maximum(np.hypot(np.minimum(np.abs(owner[..., 0] - cy), n - np.abs(owner[..., 0] - cy)),
                                  np.minimum(np.abs(owner[..., 1] - cx), n - np.abs(owner[..., 1] - cx))), 1e-3)
        reach = (_wrapped(n, yy, xx, cy, cx) ** 2 - nearest ** 2) / (2 * sep)
        edge = np.where(ident == index, edge, np.minimum(edge, reach))
    tones = 1 + 0.14 * (rng.random(points) - 0.5) * 2
    light = tones[ident] * (1 + 0.09 * _fbm(rng, ((8, 8, 0.5), (28, 28, 0.5)), n)) + _grain(rng, n, 0.04)
    light *= 0.9 + 0.1 * _smooth(0, 10, edge)
    colour = _paint(base, light)
    joint = _smooth(3.2, 0.8, edge)
    return colour * (1 - 0.7 * joint[..., None])


def _linoleum(rng, base, n, squares: int = 4):
    yy, xx = np.mgrid[:n, :n]
    size = n / squares
    ident = (yy // size).astype(int) * squares + (xx // size).astype(int)
    marble = _fbm(rng, ((3, 3, 0.5), (8, 8, 0.4), (24, 24, 0.3)), n)
    light = (1 + 0.04 * (rng.random(squares * squares) - 0.5) * 2)[ident] * (1 + 0.10 * marble) + _grain(rng, n, 0.05)
    flecks = _noise(rng, 110, 110, n)
    light += 0.10 * (flecks > 0.9) - 0.09 * (flecks < 0.08)
    light -= 0.09 * (_noise(rng, 2, 150, n) > 0.9)
    path = np.clip(_fbm(rng, ((2, 2, 1.0), (5, 5, 0.6)), n) - 0.1, 0, 1)
    seam = np.minimum(np.minimum(xx % size, size - xx % size), np.minimum(yy % size, size - yy % size))
    light -= 0.13 * _smooth(2.2, 0.4, seam)
    return _paint(base, light + 0.14 * path)


_BUILD = {"plaster": _plaster, "concrete": _concrete, "wood_planks": _wood_planks, "parquet": _parquet,
          "metal_panels": _metal_panels, "riveted_steel": _riveted_steel, "tile": _tile, "carpet": _carpet,
          "brick": _brick, "stone": _stone, "linoleum": _linoleum}


def _seeded(name: str, seed: int) -> np.random.Generator:
    return np.random.default_rng([int(seed) & 0x7FFFFFFF, sum(map(ord, name)) * 7919 + VERSION])


def make(name: str, seed: int = 0, color: tuple | list | None = None, size: int = SIZE) -> Image.Image:
    """One tileable picture of ``name``. ``color`` is the base colour (the material's own when omitted)."""
    if name not in MATERIALS:
        raise ValueError(f"unknown material {name}; use one of {', '.join(MATERIALS)}")
    base = tuple(int(v) for v in (color or MATERIALS[name][0]))
    colour = _BUILD[name](_seeded(name, seed), base, size)
    # Joints and plank gaps are drawn from the picture's own corner; moving them off the edge keeps a line from
    # starting exactly at the wrap and makes the periodic picture read as seamless to a naive edge comparison.
    colour = np.roll(colour, (size * 37 // 512, size * 77 // 512), axis=(0, 1))
    return Image.fromarray(np.clip(colour, 0, 255).astype(np.uint8))


def door_leaf(name: str, seed: int, color: tuple | list | None, width_m: float, height_m: float) -> Image.Image:
    """The material cut to a door leaf at its real scale, not stretched. Wood runs its grain up the leaf."""
    tile_m = MATERIALS[name][1]
    picture = np.asarray(make(name, seed, color))
    if name == "wood_planks":
        picture = np.rot90(picture)
    per_m = SIZE / tile_m
    wide, tall = max(8, round(width_m * per_m)), max(8, round(height_m * per_m))
    reps = (int(np.ceil(tall / SIZE)), int(np.ceil(wide / SIZE)), 1)
    return Image.fromarray(np.tile(picture, reps)[:tall, :wide])


# ---------------------------------------------------------------- choosing a material from words


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def material_of(text: str) -> str | None:
    """The material the words name, or None."""
    plain = _plain(text)
    return next((name for name, stems in _WORDS if any(_has(plain, stem) for stem in stems)), None)


def _has(plain: str, stem: str) -> bool:
    """``stem`` starts a word of the text; a stem of three letters or fewer is the whole word (``rug`` is not ``rugged``)."""
    return re.search(rf"\b{re.escape(stem)}" + (r"\b" if len(stem) <= 3 else ""), plain) is not None


def color_of(text: str) -> tuple[int, int, int] | None:
    """The base colour the words name (with ``dark`` or ``light``), or None."""
    plain = _plain(text)
    found = next((rgb for words, rgb in _COLORS if any(_has(plain, word) for word in words)), None)
    if found is None:
        return None
    if any(word in plain for word in _DARK):
        return tuple(round(v * 0.6) for v in found)
    if any(word in plain for word in _LIGHT):
        return tuple(round(v + (255 - v) * 0.35) for v in found)
    return found


def hex_of(rgb: tuple | list) -> str:
    return "#" + "".join(f"{int(v):02x}" for v in rgb)


def rgb_of(value: str) -> tuple[int, int, int]:
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def pick(surface: str, text: str, style: str = "") -> dict:
    """``{material, color, tile_m}`` for a surface from its words. The style only decides when the words name nothing."""
    material = material_of(text) or material_of(style) or _DEFAULT[surface]
    color = color_of(text) or MATERIALS[material][0]
    return {"material": material, "color": hex_of(color), "tile_m": MATERIALS[material][1]}


def defaults_for(spec: dict, style: str = "") -> dict:
    """What every surface of a box room wears when nobody painted it: from the words of its floor, walls and ceiling.

    The door is steel in a metal room and wood otherwise; the trim (skirting and frames) is dark steel or painted white."""
    floor = pick("floor", spec["floor"], style)
    walls = pick("walls", spec["walls"], style)
    ceiling = pick("ceiling", spec.get("ceiling") or "white plaster", style)
    metal = walls["material"] in _METAL
    door = pick("door", "painted steel door" if metal else "oak wooden door", "")
    trim = pick("trim", "dark steel" if metal else "white paint", "")
    return {"floor": floor, "walls": walls, "ceiling": ceiling, "door": door, "trim": trim}
