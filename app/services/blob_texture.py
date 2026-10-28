"""A texture for a lofted body: the atlas its UVs point into, a guide to repaint, and the texture written into a GLB.

The atlas is a square picture made of two 2:1 pictures, one above the other. The top one holds an orthographic front view on the
left half and the back view (mirrored, as seen from behind) on the right half, in the body's T-pose. The bottom one holds the head at
three times that scale in three portrait tiles, the front, the right side (the left side is its mirror) and the back, so a face has the pixels a face needs. Each is painted
on its own guide (``body`` and ``head``) and the two are stacked. A body made with ``atlas`` gets UVs by that projection, so a picture painted over the
guide (the same two views, shaded grey) lands on the body where it was painted, and follows it when it moves. The body itself
never changes: to dress it differently, paint another picture over the same guide and write it in again.
"""
from __future__ import annotations

import json
import math
import struct

ATLAS = (2048, 2048)
HALF_SIZE = (2048, 1024)   # the size of each of the two pictures
BODY_ROWS = 1024   # the body views take the top 1024 rows, the head tiles the 1024 below
HEAD_TILES = 3   # front, side, back


def atlas_frame(meshes, layout=None) -> dict:
    """The T-pose frame for the body views (centre x, centre y, span) from the vertices of ``meshes``, and for the head tiles
    (centre y, span, chin height) from ``layout``. The guide and the UVs share it."""
    xs, ys = [], []
    for mesh in meshes:
        xs.extend(v[0] for v in mesh.vertices)
        ys.extend(v[1] for v in mesh.vertices)
    span = max(max(xs) - min(xs), max(ys) - min(ys)) * 1.06
    frame = {"body": ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, span)}
    if layout is not None:
        from services.blob_loft import shoulder_top

        # the head tile holds the head and its neck down to the shoulders, so the neck is skin from a face picture, not a few
        # pixels of collar from the body view
        cut = shoulder_top(layout) + 0.001 * layout["h"]
        top, bottom = layout["head_y"] + layout["sy"] * 0.62, cut - 0.03 * layout["h"]
        frame["head"] = ((top + bottom) / 2, (top - bottom) * 1.08, cut)   # cy, the tile's height in metres, the cut
    return frame


def head_tile(normal) -> int:
    """0 front, 1 side (both sides, the left one is the mirror of the right), 2 back: the way the triangle faces."""
    if normal[2] >= 0.7 or abs(normal[1]) > 0.6:   # the underside of the jaw and the crown take the front tile, skin and hair, not the dark ground
        return 0
    return 2 if normal[2] <= -0.45 else 1


def atlas_uv(point, back: bool, frame: dict, head: bool = False, tile: int = 0) -> tuple[float, float]:
    width, height = ATLAS
    if head and "head" in frame:
        cy, span_y, _cut = frame["head"]
        span_x = span_y / 1.5                      # a tile is 2:3, wider than a head and taller
        if tile == 0:
            u = 0.5 + point[0] / span_x
        elif tile == 2:
            u = 0.5 - point[0] / span_x            # seen from behind
        else:
            u = 0.5 - point[2] / span_x            # the face looks to the left of the side tile
        return ((tile + u) / HEAD_TILES, 0.5 + (0.5 - (point[1] - cy) / span_y) * 0.5)
    cx, cy, span = frame["body"]
    u = 0.5 + (point[0] - cx) / span
    if back:
        u = 1.0 - u
    return ((u * 0.5 + (0.5 if back else 0.0)), (0.5 - (point[1] - cy) / span) * BODY_ROWS / height)


def _is_head(points, frame: dict) -> bool:
    """At or above the shoulders and inside the head tile's width (a sleeve or a shoulder's slope stays in the body view)."""
    if "head" not in frame:
        return False
    _cy, span, cut = frame["head"]
    return sum(p[1] for p in points) / 3 >= cut and max(max(abs(p[0]), abs(p[2])) for p in points) <= span / 1.5 * 0.49


def atlas_uvs(mesh, frame: dict) -> list[tuple[float, float]]:
    """One UV per vertex. A triangle takes the view it faces (front when its normals look toward +Z), whole, so no triangle smears
    across the halves; a triangle at or above the shoulders and inside the head tile's width takes a head tile instead (front, side
    or back by where it faces). The edges between views are seams, like an old game's."""
    uvs: list[tuple[float, float]] = []
    for i in range(0, len(mesh.vertices), 3):
        points = mesh.vertices[i:i + 3]
        normal = tuple(sum(mesh.normals[i + k][j] for k in range(3)) / 3 for j in range(3))   # the stored normals point outward
        head = _is_head(points, frame)
        uvs.extend(atlas_uv(p, normal[2] < 0, frame, head, head_tile(normal)) for p in points)
    return uvs


def guide_png(parts, layout, part: str = "body", size=ATLAS) -> bytes:
    """``part`` ``body`` (the two body views) or ``head`` (the three head tiles) in flat grey on a dark ground, 2048 x 1024: what Qwen
    repaints. ``parts`` are ``loft_parts`` and ``layout`` the body's; the frame is the same as for the UVs."""
    import io

    from PIL import Image, ImageDraw

    meshes = [mesh for mesh, _name, _uvs in parts]
    frame = atlas_frame(meshes[:1], layout)
    image = Image.new("RGB", size, (40, 40, 44))
    draw = ImageDraw.Draw(image)
    light = (-0.4, 0.6, 0.7)
    norm = math.sqrt(sum(c * c for c in light))
    light = tuple(c / norm for c in light)
    triangles = []
    for mesh in meshes:
        for i in range(0, len(mesh.vertices), 3):
            pts = mesh.vertices[i:i + 3]
            nrm = tuple(sum(mesh.normals[i + k][j] for k in range(3)) / 3 for j in range(3))
            triangles.append((pts, nrm, _is_head(pts, frame)))

    def paint(pts, seen, uv):
        shade = 0.6 + 0.4 * max(0.0, sum(seen[j] * light[j] for j in range(3)))
        colour = (int(205 * shade), int(205 * shade), int(210 * shade))
        draw.polygon([(uv(p)[0] * size[0], uv(p)[1] * size[1]) for p in pts], fill=colour)

    if part == "body":
        for back in (False, True):
            facing = [t for t in triangles if (t[1][2] < 0) == back or abs(t[1][2]) < 0.15]
            facing.sort(key=lambda t: sum(p[2] for p in t[0]) * (-1 if back else 1))
            for pts, nrm, _head in facing:
                paint(pts, (-nrm[0], nrm[1], -nrm[2]) if back else nrm, lambda p, back=back: atlas_uv(p, back, frame))
    else:
        heads = [t for t in triangles if t[2]]
        for tile in range(HEAD_TILES):
            # the view's near side last: front by z, back by -z, the side by x (its far half is hidden anyway)
            axis, sign = ((2, 1), (0, 1), (2, -1))[tile]
            facing = [t for t in heads if t[1][axis] * sign > -0.15]
            facing.sort(key=lambda t: sum(p[axis] for p in t[0]) * sign)
            for pts, nrm, _head in facing:
                paint(pts, nrm if tile != 2 else (-nrm[0], nrm[1], -nrm[2]), lambda p, tile=tile: atlas_uv(p, False, frame, True, tile))
    image = image.crop((0, 0, size[0], BODY_ROWS)) if part == "body" else image.crop((0, BODY_ROWS, size[0], size[1]))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def bleed(picture, guide: bytes, radius: int = 28, band: int = 14):
    """The painted figure's colours pushed outward over the ground around it. The mould is never exactly the painted figure: a hand a
    little wider, a neck a little longer, and without this its pixels would sample the dark ground and show as black slivers.
    A pixel is trusted when it is painted (not ground-coloured) or well inside the mould's own silhouette (the ``guide``), where a
    dark jacket is a jacket; the rest, the ring along the silhouette and beyond, takes the colour of the nearest trusted pixels."""
    import io

    import numpy as np
    from PIL import Image

    pixels = np.asarray(picture.convert("RGB")).astype(np.float32)
    corners = np.concatenate([pixels[:12, :12].reshape(-1, 3), pixels[:12, -12:].reshape(-1, 3), pixels[-12:, :12].reshape(-1, 3), pixels[-12:, -12:].reshape(-1, 3)])
    ground = np.median(corners, axis=0)
    painted = np.abs(pixels - ground).max(axis=2) > 26
    shape = np.asarray(Image.open(io.BytesIO(guide)).convert("L").resize(picture.size)) > 80
    inner = shape.copy()
    for _ in range(band):
        inner = inner & np.roll(inner, 1, 0) & np.roll(inner, -1, 0) & np.roll(inner, 1, 1) & np.roll(inner, -1, 1)
    trusted = inner | (painted & shape)
    out = pixels.copy()
    filled = trusted.copy()
    for _ in range(radius):
        total = np.zeros_like(out)
        count = np.zeros(filled.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            near = np.roll(filled, (dy, dx), (0, 1))
            total += np.roll(out, (dy, dx), (0, 1)) * near[..., None]
            count += near
        grow = (~filled) & (count > 0)
        out[grow] = total[grow] / count[grow][:, None]
        filled |= grow
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def match_tiles(head):
    """The side and back tiles of a head picture moved to the front tile's tones (a Reinhard transfer in Lab on each tile's head pixels, the
    background left out): the three portraits are lit differently, and where the shader goes from the front picture to the side one that
    difference was a band across the cheek."""
    import cv2
    import numpy as np
    from PIL import Image

    rgb = np.asarray(head.convert("RGB"))
    h, w = rgb.shape[:2]
    third = w // 3
    tiles = [rgb[:, i * third:(i + 1) * third].copy() for i in range(3)]
    lab = [cv2.cvtColor(t, cv2.COLOR_RGB2LAB).astype(np.float32) for t in tiles]
    corner = np.median(np.concatenate([tiles[0][:12, :12].reshape(-1, 3), tiles[0][:12, -12:].reshape(-1, 3)]).astype(np.float32), axis=0)
    masks = [(np.abs(t.astype(np.float32) - corner).max(axis=2) > 24) for t in tiles]
    keep = [m & (np.arange(h)[:, None] < int(h * 0.78)) for m in masks]        # the head and neck's top, not the shoulders
    ref_mean = lab[0][keep[0]].mean(axis=0)
    ref_std = lab[0][keep[0]].std(axis=0) + 1e-3
    out = [tiles[0]]
    for i in (1, 2):
        pixels = lab[i][keep[i]]
        mean, std = pixels.mean(axis=0), pixels.std(axis=0) + 1e-3
        shifted = (lab[i] - mean) / std * ref_std + ref_mean
        # only part of the way for the lightness (a profile is lit from its own side) and fully for the colour
        shifted[..., 0] = lab[i][..., 0] * 0.4 + shifted[..., 0] * 0.6
        out.append(cv2.cvtColor(np.clip(shifted, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB))
    return Image.fromarray(np.concatenate(out + [rgb[:, 3 * third:]] if rgb.shape[1] > 3 * third else out, axis=1))


def stack_atlas(body, head=None, guides=None, match: bool = False) -> bytes:
    """The atlas picture (PNG bytes) from the painted ``body`` picture (2:1) and, when there is one, the painted ``head`` picture
    (2:1). Without a head picture the head tiles are cut from the body picture and enlarged, softer but the same man."""
    import io

    from PIL import Image

    top = body.convert("RGB").resize(HALF_SIZE, Image.LANCZOS)
    top = bleed(top, guides[0]) if guides else top
    if head is not None:
        bottom = head.convert("RGB").resize(HALF_SIZE, Image.LANCZOS)
        if match:
            bottom = match_tiles(bottom)
        bottom = bleed(bottom, guides[1]) if guides else bottom
    else:
        bottom = Image.new("RGB", HALF_SIZE, (90, 70, 60))
    atlas = Image.new("RGB", ATLAS)
    atlas.paste(top, (0, 0))
    atlas.paste(bottom, (0, BODY_ROWS))
    out = io.BytesIO()
    atlas.save(out, format="PNG")
    return out.getvalue()


def neck_skin(head) -> list[float]:
    """The skin colour of a head picture (0..1 sRGB): the median of the front tile just under the beard, where the neck is. What the
    underside of the jaw and the chin take, instead of the beard's row smeared down by a front projection."""
    import numpy as np

    width, height = head.size
    tile = np.asarray(head.convert("RGB").crop((0, 0, width // 3, height))).astype(np.float32)
    h, w = tile.shape[:2]
    patch = tile[int(h * 0.76):int(h * 0.84), int(w * 0.42):int(w * 0.58)].reshape(-1, 3)
    return [round(float(v) / 255.0, 4) for v in np.median(patch, axis=0)]


def hair_of(head) -> str:
    """The hair colour of a head picture (#RRGGBB): the median of the top of the front tile's crown, where the hair is, darker
    than the median of the scalp pixels so a highlight does not lighten the whole cap."""
    import numpy as np

    width, height = head.size
    tile = np.asarray(head.convert("RGB").crop((0, 0, width // 3, height))).astype(np.float32)
    h, w = tile.shape[:2]
    patch = tile[int(h * 0.13):int(h * 0.19), int(w * 0.40):int(w * 0.60)].reshape(-1, 3)
    r, g, b = (int(v) for v in np.percentile(patch, 35, axis=0))
    return "#%02X%02X%02X" % (r, g, b)


def frame_extras(frame: dict, skin: list[float] | None = None, hold: float = 0.0, face: tuple[float, float] | None = None, split: bool = True) -> dict:
    """The atlas frame as numbers a viewer can read from the material's ``extras``: the body views ``[centre x, centre y, span]``,
    the head tiles ``[centre y, tile height in metres, the cut]``."""
    out = {"body": [round(v, 6) for v in frame["body"]]}
    if "head" in frame:
        out["head"] = [round(v, 6) for v in frame["head"]]
    if skin:
        out["skin"] = list(skin)
    if hold:
        out["hold"] = round(float(hold), 3)
    if not split:
        out["noUpperSplit"] = True   # one blend height for the whole head: a fitted skull needs no longer hold of the front picture above the brows
    if face:
        out["faceYaw"] = round(float(face[0]), 2)       # degrees each way the face patch reaches
        out["faceFeather"] = round(float(face[1]), 2)   # degrees over which the patch fades into the skull at its border
    return out


def attach_texture(glb: bytes, png: bytes, materials: tuple[str, ...] = ("body", "face"), frame: dict | None = None, nearest: bool = False, skin: list[float] | None = None, hold: float = 0.0, face: tuple[float, float] | None = None, unlit: bool = False, split: bool = True) -> bytes:
    """The GLB with ``png`` as the base colour texture of the materials named in ``materials`` (one shared image), and no vertex
    colours on the primitives that use them (they would tint the picture). Everything else, skin and animations included, is kept
    byte for byte."""
    magic, version, _length = struct.unpack_from("<III", glb, 0)
    if magic != 0x46546C67 or version != 2:
        raise ValueError("not a binary glTF 2.0 file")
    json_length, json_type = struct.unpack_from("<II", glb, 12)
    document = json.loads(glb[20:20 + json_length])
    at = 20 + json_length
    binary = b""
    if at < len(glb):
        bin_length, _kind = struct.unpack_from("<II", glb, at)
        binary = glb[at + 8:at + 8 + bin_length]
    names = [m.get("name") for m in document.get("materials", [])]
    found = [names.index(name) for name in materials if name in names]
    if not found:
        raise ValueError(f"the model has none of the materials {', '.join(materials)}")
    binary += b"\x00" * (-len(binary) % 4)
    offset = len(binary)
    binary += png + b"\x00" * (-len(png) % 4)
    document.setdefault("bufferViews", []).append({"buffer": 0, "byteOffset": offset, "byteLength": len(png)})
    document.setdefault("images", []).append({"bufferView": len(document["bufferViews"]) - 1, "mimeType": "image/png"})
    document.setdefault("samplers", []).append({"magFilter": 9728 if nearest else 9729, "minFilter": 9728 if nearest else 9729, "wrapS": 33071, "wrapT": 33071})
    document.setdefault("textures", []).append({"sampler": len(document["samplers"]) - 1, "source": len(document["images"]) - 1})
    if unlit:
        # the photographs carry their own light: shown unlit, the geometry adds no shading of its own, so no step of the lighting can cut across the face
        used = document.setdefault("extensionsUsed", [])
        if "KHR_materials_unlit" not in used:
            used.append("KHR_materials_unlit")
        for index in found:
            document["materials"][index].setdefault("extensions", {})["KHR_materials_unlit"] = {}
    for index in found:
        if frame is not None:
            document["materials"][index].setdefault("extras", {})["atlas"] = frame_extras(frame, skin, hold, face, split)
        document["materials"][index].setdefault("pbrMetallicRoughness", {})["baseColorTexture"] = {"index": len(document["textures"]) - 1}
        document["materials"][index]["pbrMetallicRoughness"]["baseColorFactor"] = [1, 1, 1, 1]
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            if primitive.get("material") in found:
                primitive.get("attributes", {}).pop("COLOR_0", None)
    document["buffers"][0]["byteLength"] = len(binary)
    encoded = json.dumps(document, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    encoded += b" " * (-len(encoded) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(encoded) + len(binary)) + struct.pack("<II", len(encoded), json_type) + encoded
            + struct.pack("<II", len(binary), 0x004E4942) + binary)
