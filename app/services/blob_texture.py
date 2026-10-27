"""A texture for a lofted body: the atlas its UVs point into, a guide to repaint, and the texture written into a GLB.

The atlas is an orthographic front view on the left half and the back view (mirrored, as seen from behind) on the right half of
a 2:1 picture, in the body's T-pose. A body made with ``atlas`` gets UVs by that projection, so a picture painted over the
guide (the same two views, shaded grey) lands on the body where it was painted, and follows it when it moves. The body itself
never changes: to dress it differently, paint another picture over the same guide and write it in again.
"""
from __future__ import annotations

import json
import math
import struct

ATLAS = (2048, 1024)


def atlas_frame(meshes) -> tuple[float, float, float]:
    """``(centre x, centre y, span)`` of the T-pose: the same for the guide and the UVs, from the vertices of ``meshes``."""
    xs, ys = [], []
    for mesh in meshes:
        xs.extend(v[0] for v in mesh.vertices)
        ys.extend(v[1] for v in mesh.vertices)
    span = max(max(xs) - min(xs), max(ys) - min(ys)) * 1.06
    return (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, span


def atlas_uv(point, back: bool, frame) -> tuple[float, float]:
    cx, cy, span = frame
    u = 0.5 + (point[0] - cx) / span
    if back:
        u = 1.0 - u
    return (u * 0.5 + (0.5 if back else 0.0), 0.5 - (point[1] - cy) / span)


def atlas_uvs(mesh, frame) -> list[tuple[float, float]]:
    """One UV per vertex. A triangle takes the view it faces (front when its normal looks toward +Z), whole, so no triangle
    smears across the two halves; the edge between the views is a seam on the sides, like an old game's."""
    uvs: list[tuple[float, float]] = []
    for i in range(0, len(mesh.vertices), 3):
        a, b, c = mesh.vertices[i:i + 3]
        back = sum(mesh.normals[i + k][2] for k in range(3)) < 0   # the stored normals point outward
        uvs.extend(atlas_uv(p, back, frame) for p in (a, b, c))
    return uvs


def guide_png(parts, size=ATLAS) -> bytes:
    """The two views of the body, face and hair in flat grey on a dark ground: what Qwen repaints into a texture. ``parts`` are
    ``loft_parts``; the frame is the body's, as for the UVs."""
    import io

    from PIL import Image, ImageDraw

    meshes = [mesh for mesh, _name, _uvs in parts]
    frame = atlas_frame(meshes[:1])
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
            triangles.append((pts, nrm))
    for back in (False, True):
        facing = [t for t in triangles if (t[1][2] < 0) == back or abs(t[1][2]) < 0.15]
        facing.sort(key=lambda t: sum(p[2] for p in t[0]) * (-1 if back else 1))
        for pts, nrm in facing:
            seen = (-nrm[0], nrm[1], -nrm[2]) if back else nrm
            shade = 0.45 + 0.55 * max(0.0, sum(seen[j] * light[j] for j in range(3)))
            colour = (int(205 * shade), int(205 * shade), int(210 * shade))
            draw.polygon([(atlas_uv(p, back, frame)[0] * size[0], atlas_uv(p, back, frame)[1] * size[1]) for p in pts], fill=colour)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def attach_texture(glb: bytes, png: bytes, materials: tuple[str, ...] = ("body", "face")) -> bytes:
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
    document.setdefault("samplers", []).append({"magFilter": 9729, "minFilter": 9729, "wrapS": 33071, "wrapT": 33071})
    document.setdefault("textures", []).append({"sampler": len(document["samplers"]) - 1, "source": len(document["images"]) - 1})
    for index in found:
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
