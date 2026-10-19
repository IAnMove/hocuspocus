"""The GLB parts of a plate room (see ``room_plate``): the card, the floor, the walls, the ceiling and the cut-out props.

Every picture is unlit (``KHR_materials_unlit``): the plate already carries its own light, so the scene's lamps and tone
mapping must not touch it. The card and the floor in front of it share one image, the plate: the card shows rows
``0 .. floorTop`` and the floor, a trapezoid, rows ``floorTop .. 1``. A vertex of the trapezoid is at the world point the plate's
camera sees at its own picture coordinates, so there is no resampling and no seam between wall and floor.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from services import room_plate, room_plate_extend
from services.room_plate_extend import Plate

ROWS = 48
COLUMNS = 64        # u and v are not affine in x and z together (u goes with x / z): thin, narrow cells keep the error under a tenth of a pixel
BAKE = 512            # the extension is blurred by construction: half a thousand pixels across say all it has to say
FLOOR_BAKE = 768
PROP_ALPHA = 24


def build_parts(spec: dict, textures: dict) -> list[dict]:
    """Every part of the room: unlit pictures, and the props that were given a cut-out as masked cards in front of the plate."""
    plate = spec["plate"]
    pictures = textures.get("plate") or {}
    back = _rgb(pictures.get("back"))
    extension = Plate(back)
    size, geo = spec["size"], room_plate.geometry(plate)
    png = _png(back)
    parts = [_card(size, geo, png), _floor_strip(size, geo, png), _floor(size, geo, extension),
             _wall(size, geo, "left", pictures.get("left"), extension), _wall(size, geo, "right", pictures.get("right"), extension),
             _ceiling(size, geo, extension)]
    pictures_of_props = list(textures.get("props") or [])
    for index, prop in enumerate(spec["props"]):
        source = pictures_of_props[index] if index < len(pictures_of_props) else None
        parts.append(prop_part(spec, prop, source, index))
    return parts


def prop_part(spec: dict, prop: dict, source: Any, index: int, *, unlit: bool = True) -> dict:
    """A cut-out standing at the prop's place, facing the camera, as tall as ``height_m``. Its alpha is a mask, so it writes depth
    like a solid and a person who walks behind it is hidden by it."""
    if source is None:
        raise ValueError(f"props[{index}] needs its cut-out picture (image: {{file}}, a PNG with alpha)")
    picture, ratio = _cut(source)
    from services.room_box import prop_point
    x, _y, z = prop_point(spec["size"], prop)
    base, height = float(prop.get("y", 0.0)), float(prop["height_m"])
    half = height * ratio / 2
    quad = _arrays([(x + half, base, z), (x - half, base, z), (x - half, base + height, z), (x + half, base + height, z)],
                   [(0, 1), (1, 1), (1, 0), (0, 0)])
    return {"name": f"prop-{index + 1}", "arrays": quad, "png": _png(picture), "repeat": False, "alpha": False, "mask": True,
            "glow": False, "tint": 1.0, "unlit": unlit}


# ---------------------------------------------------------------- the parts


def _card(size: dict, geo: dict, png: bytes) -> dict:
    half, top, back = size["w"] / 2, size["h"], size["d"] / 2
    row = geo["base_row"]
    corners = [(half, 0, back), (-half, 0, back), (-half, top, back), (half, top, back)]
    return _part("plate", _arrays(corners, [(0, row), (1, row), (1, 0), (0, 0)]), png)


def _floor_strip(size: dict, geo: dict, png: bytes) -> dict:
    """The plate's floor rows on the floor: a grid whose every vertex is the world point the plate's camera sees at its (u, v)."""
    width, depth, hz, row = size["w"], size["d"], geo["horizon"], geo["base_row"]
    v = np.linspace(row, 1.0, ROWS + 1)[:, None] * np.ones((1, COLUMNS + 1))
    u = np.ones((ROWS + 1, 1)) * np.linspace(0.0, 1.0, COLUMNS + 1)[None, :]
    s = depth * (row - hz) / (v - hz)
    x = (0.5 - u) * width * s / depth
    positions = np.stack([x, np.zeros_like(x), -depth / 2 + s], axis=-1).reshape(-1, 3).astype(np.float32)
    uvs = np.stack([u, v], axis=-1).reshape(-1, 2).astype(np.float32)
    k = np.arange((ROWS + 1) * (COLUMNS + 1)).reshape(ROWS + 1, COLUMNS + 1)
    a, b, c, d = k[:-1, :-1].ravel(), k[:-1, 1:].ravel(), k[1:, 1:].ravel(), k[1:, :-1].ravel()
    indices = np.stack([a, d, c, a, c, b], axis=1).ravel().astype(np.uint16)
    normals = np.tile(np.array([0, 1, 0], np.float32), (len(positions), 1))
    return _part("floor-plate", (positions, normals, uvs, indices), png)


def _floor(size: dict, geo: dict, extension: Plate) -> dict:
    """The floor the strip does not cover (two wedges beside it and the part in front of it), baked from the plate's edges. The
    strip and this floor never overlap, so no two surfaces fight for a pixel and the strip can stand exactly on y = 0."""
    width, depth, hz, row = size["w"], size["d"], geo["horizon"], geo["base_row"]

    def mapping(i: np.ndarray, j: np.ndarray):
        near = np.maximum(1 - j, 0.02)
        return 0.5 - (0.5 - i) / near, hz + (row - hz) / near

    picture = room_plate_extend.bake(extension, FLOOR_BAKE, _short(FLOOR_BAKE * depth / width), mapping)
    half, edge = width / 2, geo["near_s"]
    cuts = _cuts(depth, edge)
    below, above = cuts[cuts <= edge], cuts[cuts >= edge]
    z = lambda s: s - depth / 2                                                 # noqa: E731
    reach = lambda s: half * s / depth                                          # noqa: E731
    pieces = [[[(half, 0, z(s)), (-half, 0, z(s))] for s in below],             # the floor in front of the strip
              [[(half, 0, z(s)), (reach(s), 0, z(s))] for s in above],          # the wedge left of it
              [[(-reach(s), 0, z(s)), (-half, 0, z(s))] for s in above]]        # and the one on the right
    return _part("floor", _ribbons(pieces, lambda p: np.stack([0.5 - p[:, 0] / width, 0.5 - p[:, 2] / depth], axis=1), (0, 1, 0)), _png(picture))


def _ceiling(size: dict, geo: dict, extension: Plate) -> dict:
    width, depth, hz, hp, eye = size["w"], size["d"], geo["horizon"], geo["plate_h"], geo["eye_height"]
    top = size["h"]

    def mapping(i: np.ndarray, j: np.ndarray):
        near = np.maximum(1 - j, 0.02)
        return 0.5 - (0.5 - i) / near, hz - (top - eye) / (hp * near)

    picture = room_plate_extend.bake(extension, BAKE, _short(BAKE * depth / width), mapping)
    half = width / 2
    rows = [[(half, top, s - depth / 2), (-half, top, s - depth / 2)] for s in _cuts(depth)]
    uv = lambda p: np.stack([0.5 - p[:, 0] / width, 0.5 - p[:, 2] / depth], axis=1)   # noqa: E731
    return _part("ceiling", _ribbons([rows], uv, (0, -1, 0)), _png(picture))


def _wall(size: dict, geo: dict, side: str, given: Any, extension: Plate) -> dict:
    """A side wall. ``left`` is the wall on the left of the frame (world +x), ``right`` the other. Its picture, when the room was
    given one, runs from the viewer's left to his right as he faces it; with none it is the plate's edge, mirrored."""
    width, depth, hz, hp, eye = size["w"], size["d"], geo["horizon"], geo["plate_h"], geo["eye_height"]
    top = size["h"]
    x = width / 2 if side == "left" else -width / 2
    # Seen from inside, the back corner is on the right of the left wall and on the left of the right wall.
    along = (lambda z: (z + depth / 2) / depth) if side == "left" else (lambda z: 1 - (z + depth / 2) / depth)
    rows = [[(x, 0, s - depth / 2), (x, top, s - depth / 2)] for s in _cuts(depth)]
    uv = lambda p: np.stack([along(p[:, 2]), 1 - p[:, 1] / top], axis=1)                # noqa: E731
    normal = (-1, 0, 0) if side == "left" else (1, 0, 0)
    if given is not None:
        return _part(f"wall-{side}", _ribbons([rows], uv, normal), _png(_rgb(given)))

    def mapping(i: np.ndarray, j: np.ndarray):
        reach = np.maximum(i if side == "left" else 1 - i, 0.02)      # camera distance as a share of the plate's
        across = 0.5 / reach
        return (0.5 - across if side == "left" else 0.5 + across), hz + (eye - top * (1 - j)) / (hp * reach)

    picture = room_plate_extend.bake(extension, BAKE, _short(BAKE * top / depth), mapping)
    return _part(f"wall-{side}", _ribbons([rows], uv, normal), _png(picture))


def _cuts(depth: float, extra: float | None = None) -> np.ndarray:
    """Camera distances where a surface that reaches the camera is cut: each cell is at most twice as far at one end as at the other, so
    a perspective-correct rasteriser never interpolates across a huge range of depths (the cell at the camera is the only exception)."""
    cuts = {0.0, *(depth * 2.0 ** -k for k in range(7, -1, -1))}
    return np.array(sorted(cuts | ({float(extra)} if extra is not None else set())))


def _ribbons(pieces: list, uv_of, normal: tuple) -> tuple:
    """Positions, normals, uvs and triangles of ribbons: each piece is a list of rows of equal length, and a quad joins two
    neighbouring rows at two neighbouring points. ``uv_of`` gives the picture coordinates of an (n, 3) array of positions."""
    points, indices, base = [], [], 0
    for rows in pieces:
        grid = np.asarray(rows, np.float64)
        height, across = grid.shape[:2]
        points.append(grid.reshape(-1, 3))
        k = base + np.arange(height * across).reshape(height, across)
        a, b, c, d = k[:-1, :-1].ravel(), k[:-1, 1:].ravel(), k[1:, 1:].ravel(), k[1:, :-1].ravel()
        indices.append(np.stack([a, d, c, a, c, b], axis=1).ravel())
        base += height * across
    positions = np.concatenate(points)
    normals = np.tile(np.array(normal, np.float32), (len(positions), 1))
    return (positions.astype(np.float32), normals, uv_of(positions).astype(np.float32), np.concatenate(indices).astype(np.uint16))


# ---------------------------------------------------------------- helpers


def _part(name: str, arrays: tuple, png: bytes) -> dict:
    return {"name": name, "arrays": arrays, "png": png, "repeat": False, "alpha": False, "glow": False, "tint": 1.0, "unlit": True}


def _arrays(corners: list, uvs: list) -> tuple:
    """One quad: positions, normals (from its winding), glTF uvs (v from the top of the picture) and its two triangles."""
    points = np.array(corners, np.float32)
    normal = np.cross(points[1] - points[0], points[2] - points[0])
    normal = normal / (np.linalg.norm(normal) or 1.0)
    return (points, np.tile(normal.astype(np.float32), (4, 1)), np.array(uvs, np.float32), np.array([0, 1, 2, 0, 2, 3], np.uint16))


def _short(value: float) -> int:
    return int(max(128, min(FLOOR_BAKE, round(value))))


def _rgb(source: Any) -> Image.Image:
    if isinstance(source, Image.Image):
        return source.convert("RGB")
    if source is None:
        raise ValueError("the plate's back picture is missing")
    with Image.open(source) as opened:
        return opened.convert("RGB")


def _png(picture: Image.Image) -> bytes:
    out = io.BytesIO()
    picture.save(out, "PNG", compress_level=6)
    return out.getvalue()


def _cut(source: Any) -> tuple[Image.Image, float]:
    """The cut-out cropped to what it draws (alpha above ``PROP_ALPHA``), and its width over its height: so ``height_m`` is the
    height of the object and the bottom of the card is its foot."""
    if isinstance(source, Image.Image):
        picture = source.convert("RGBA")
    else:
        with Image.open(Path(source)) as opened:
            picture = opened.convert("RGBA")
    box = picture.getchannel("A").point(lambda value: 255 if value > PROP_ALPHA else 0).getbbox()
    if box is None:
        raise ValueError("a prop's cut-out is empty: its alpha channel draws nothing")
    picture = picture.crop(box)
    return picture, picture.width / picture.height
