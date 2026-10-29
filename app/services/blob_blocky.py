"""Blocky people: our own boxes for a Roblox-like and a Minecraft-like (``voxel``) character on the one humanoid rig.

Both are built from boxes in a T-pose (arms out, a gap between the legs) with one 64 x 64 picture whose layout is the common
voxel-skin one (head, torso, arm and leg tiles, each box unwrapped as top, bottom, right, front, left, back). The picture is
made here from colours (skin, hair, shirt, trousers, shoes), or a picture of the workspace takes its place. The face is a
separate quad in front of the head that the face kit paints (expressions and mouths), like the lofted heads' face patch.
Nothing here uses anyone else's meshes, templates or pictures."""
from __future__ import annotations

import io
import math
import random

from services.blob_loft import Mesh

# unit sizes (width, height, depth) of each box, whether a limb is two segments, and the total height they add up to
SHAPES = {
    "voxel": {"head": (8, 8, 8), "torso": (8, 12, 4), "arm": (3.5, 12, 3.5), "leg": (4, 12, 4), "split": False, "total": 32.0},
    "roblox": {"head": (1.6, 1.3, 1.3), "torso": (2.0, 2.0, 1.0), "arm": (1.0, 2.0, 1.0), "leg": (1.0, 2.0, 1.0), "split": True, "total": 5.3},
}
# where each box is unwrapped in the 64 x 64 picture: (x, y) of its top-left corner, and its size in picture pixels (w, h, d)
TILES = {
    "head": ((0, 0), (8, 8, 8)), "torso": ((16, 16), (8, 12, 4)),
    "arm_r": ((40, 16), (4, 12, 4)), "leg_r": ((0, 16), (4, 12, 4)),
    "arm_l": ((32, 48), (4, 12, 4)), "leg_l": ((16, 48), (4, 12, 4)),
}
SIZE = 64
SHARES = {"upper": (0.0, 0.52), "lower": (0.52, 1.0)}   # the rows of a limb tile each segment of a two-part limb uses


def blocky_layout(spec: dict) -> dict:
    """Dimensions in metres for the layout dict the rest of the pipeline reads (``h``, the head box and its centre)."""
    shape = SHAPES[spec["blocky"]]
    unit = spec["height"] / shape["total"]
    hw, hh, hd = (v * unit for v in shape["head"])
    return {"h": spec["height"], "unit": unit, "sx": hw, "sy": hh, "sz": hd, "head_y": spec["height"] - hh / 2, "blocky": spec["blocky"], "real": False, "head_kind": "man"}


def _faces(centre, size):
    cx, cy, cz = centre
    w, h, d = size
    x0, x1, y0, y1, z0, z1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2, cz - d / 2, cz + d / 2
    # every face lists its corners bottom-left, bottom-right, top-right, top-left as seen from outside
    return {
        "right": ((-1, 0, 0), [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)]),
        "front": ((0, 0, 1), [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]),
        "left": ((1, 0, 0), [(x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)]),
        "back": ((0, 0, -1), [(x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)]),
        "top": ((0, 1, 0), [(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)]),
        "bottom": ((0, -1, 0), [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]),
    }


def _rects(tile, rows=None):
    (ox, oy), (tw, th, td) = tile
    lo, hi = rows or (0.0, 1.0)
    spans = {"right": (ox, oy + td, td, th), "front": (ox + td, oy + td, tw, th), "left": (ox + td + tw, oy + td, td, th),
             "back": (ox + 2 * td + tw, oy + td, tw, th), "top": (ox + td, oy, tw, td), "bottom": (ox + td + tw, oy, tw, td)}
    out = {}
    for name, (px, py, pw, ph) in spans.items():
        if rows and name in ("right", "front", "left", "back"):
            py, ph = py + ph * lo, ph * (hi - lo)
        out[name] = (px / SIZE, py / SIZE, (px + pw) / SIZE, (py + ph) / SIZE)
    return out


def _add_box(mesh: Mesh, uvs: list, centre, size, tile, rows=None, turn=None, pivot=(0.0, 0.0)) -> None:
    """A box with the tile's UVs. ``turn`` (degrees about Z, around ``pivot``) lays a hanging limb into the T-pose."""
    rects = _rects(tile, rows)
    c, s = (math.cos(math.radians(turn)), math.sin(math.radians(turn))) if turn else (1.0, 0.0)

    def move(p):
        x, y = p[0] - pivot[0], p[1] - pivot[1]
        return (pivot[0] + x * c - y * s, pivot[1] + x * s + y * c, p[2])

    def spin(n):
        return (n[0] * c - n[1] * s, n[0] * s + n[1] * c, n[2])

    for name, (normal, corners) in _faces(centre, size).items():
        u0, v0, u1, v1 = rects[name]
        quad = [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]
        for tri in ((0, 1, 2), (0, 2, 3)):
            mesh.triangle([move(corners[i]) for i in tri], [spin(normal)] * 3, [(1.0, 1.0, 1.0)] * 3)
            uvs.extend(quad[i] for i in tri)


def _face_board(top: float, head_h: float, head_w: float, head_d: float, height: float):
    face, face_uvs = Mesh(), []
    z = head_d / 2 + 0.0015 * height
    y0, y1, x0, x1 = top, top + head_h, -head_w / 2, head_w / 2
    quad = [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
    uv_quad = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]   # the kit painter's pictures are v-up, unlike the body picture's
    for tri in ((0, 1, 2), (0, 2, 3)):
        face.triangle([quad[i] for i in tri], [(0, 0, 1)] * 3, [(1.0, 1.0, 1.0)] * 3)
        face_uvs.extend(uv_quad[i] for i in tri)
    return face, face_uvs


def blocky_parts(spec: dict) -> list:
    """``[(mesh, material, uvs)]``: the body (one picture) and the face quad."""
    shape = SHAPES[spec["blocky"]]
    unit = blocky_layout(spec)["unit"]
    u = lambda value: value * unit
    leg_w, leg_h, leg_d = (u(v) for v in shape["leg"])
    torso_w, torso_h, torso_d = (u(v) for v in shape["torso"])
    arm_w, arm_h, arm_d = (u(v) for v in shape["arm"])
    head_w, head_h, head_d = (u(v) for v in shape["head"])
    gap = spec.get("leg_gap", 0.06) * torso_w
    body, uvs = Mesh(), []
    # legs, standing: the feet at y = 0
    for side, tile in ((-1, "leg_r"), (1, "leg_l")):
        x = side * (leg_w / 2 + gap / 2)
        if shape["split"]:
            for part in ("lower", "upper"):
                rows = SHARES[part]
                a, b = leg_h * (1 - rows[1]), leg_h * (1 - rows[0])
                _add_box(body, uvs, (x, (a + b) / 2, 0.0), (leg_w, b - a, leg_d), TILES[tile], rows)
        else:
            _add_box(body, uvs, (x, leg_h / 2, 0.0), (leg_w, leg_h, leg_d), TILES[tile])
    torso_y = leg_h + torso_h / 2
    _add_box(body, uvs, (0.0, torso_y, 0.0), (torso_w, torso_h, torso_d), TILES["torso"])
    top = leg_h + torso_h
    # arms: built hanging from the shoulder, then laid out into the pose (``spec["arm_turn"]`` degrees from hanging, 90 is a T)
    shoulder_y = top - arm_w / 2
    shares = (SHARES["upper"], SHARES["lower"]) if shape["split"] else (None,)
    for side, tile in ((-1, "arm_r"), (1, "arm_l")):
        pivot = (side * torso_w / 2, shoulder_y)
        turn = spec.get("arm_turn", 90.0) * side
        for share in shares:
            if share is None:
                _add_box(body, uvs, (pivot[0], shoulder_y - arm_h / 2, 0.0), (arm_w, arm_h, arm_d), TILES[tile], None, turn, pivot)
                continue
            a, b = shoulder_y - arm_h * share[1], shoulder_y - arm_h * share[0]
            _add_box(body, uvs, (pivot[0], (a + b) / 2, 0.0), (arm_w, b - a, arm_d), TILES[tile], share, turn, pivot)
    _add_box(body, uvs, (0.0, top + head_h / 2, 0.0), (head_w, head_h, head_d), TILES["head"])
    face, face_uvs = _face_board(top, head_h, head_w, head_d, spec["height"])
    return [(body, "body", uvs), (face, "face", face_uvs)]


def blocky_glb(spec: dict, name: str = "blob") -> bytes:
    from services.procedural_3d.compose import pack_parts

    return pack_parts(name, [(mesh.vertices, mesh.normals, mesh.colors, material, uvs) for mesh, material, uvs in blocky_parts(spec)])


def _rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _paint_named_part(paint, part, name, rect, skin, hair, shirt, pants, shoes, sleeves) -> None:
    if part == "head":
        paint(rect, skin)
        if name == "top":
            paint(rect, hair)
        elif name == "back":
            paint(rect, hair, (0.0, 0.8))
        elif name in ("right", "left", "front"):
            paint(rect, hair, (0.0, 0.3 if name != "front" else 0.2))
    elif part == "torso":
        paint(rect, shirt)
    elif part.startswith("arm"):
        paint(rect, shirt if name in ("top",) else skin)
        if name not in ("top", "bottom"):
            paint(rect, shirt, (0.0, 0.42 if sleeves == "short" else 1.0))
    else:
        paint(rect, pants)
        if name not in ("top", "bottom"):
            paint(rect, shoes, (0.82, 1.0))
        if name == "bottom":
            paint(rect, shoes)


def blocky_picture(spec: dict) -> bytes:
    """The 64 x 64 picture from the colours: a voxel one with pixel noise, a roblox one with flat plastic and a soft gradient."""
    from PIL import Image

    colours = spec["blocky_colors"]
    skin, hair, shirt, pants, shoes = (_rgb(colours[key]) for key in ("skin", "hair", "top", "bottom", "shoes"))
    voxel = spec["blocky"] == "voxel"
    rand = random.Random(7)
    image = Image.new("RGB", (SIZE, SIZE), skin)
    pixels = image.load()

    def paint(rect, colour, rows=None):
        u0, v0, u1, v1 = (round(c * SIZE) for c in rect)
        for y in range(v0, v1):
            if rows and not rows[0] <= (y - v0) / max(1, v1 - v0) < rows[1]:
                continue
            for x in range(u0, u1):
                k = 1.0 + (rand.uniform(-0.07, 0.07) if voxel else 0.0) - (0 if voxel else 0.08 * (y - v0) / max(1, v1 - v0))
                pixels[x, y] = tuple(max(0, min(255, int(c * k))) for c in colour)

    for part, (tile, _) in TILES.items():
        rects = _rects(TILES[part])
        for name, rect in rects.items():
            _paint_named_part(paint, part, name, rect, skin, hair, shirt, pants, shoes, spec.get("sleeves", "short"))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
