"""The pieces of a diorama set as GLBs: one house block per generated facade, and a tiled ground slab.

A house is a box: its front wears the whole facade picture, its sides and back repeat a thin strip of the facade's
edge and its roof the facade's top strip, so the block reads as one painted object. The ground is a thin slab whose
top tiles the ground picture every ``tile`` metres. Units are metres, y up. A house's origin is the middle of its
front's bottom edge, the front facing +z; the ground's origin is the middle of its top. A scene keeps those origins
(``fitGltf`` places the origin and scales the model to 1.7 m times the slot's scale), so the scene compiler lays the
pieces out around the cast (``ui/src/features/scene3d/dioramaSet.ts``).
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pygltflib
from PIL import Image

DEPTH = 3.0              # every house is this deep
STRIP = 0.04             # share of the facade picture the sides and roof repeat
TEXTURE_WIDTH = 768      # facades are embedded at most this wide
GROUND_TEXTURE = 1024
GROUND_SIZE = 80.0       # the slab's side
GROUND_TILE = 3.0        # metres the ground picture covers before it repeats
GROUND_THICKNESS = 0.2
GROUND_TONE = 0.8        # the ground a little darker than its picture: a pale floor glared and drowned the lyrics
MARGIN_CLOSE = 28        # a pixel this near the backdrop colour (on every channel) is backdrop
MARGIN_TINT = 24         # a backdrop is grey or white: its channels differ by less than this
MARGIN_SHARE = 0.6       # a line mostly of backdrop is margin
MAX_TRIM = 0.12          # never trim more than this share of a side
SKY_BLUE = 18            # a sky pixel is bluer than red by this much, and at least as blue as green
SKY_SHARE = 0.85         # a top row mostly of sky is sky
SKY_TRIM = 0.35          # sky above a small house is trimmed up to this share of the picture


def trim_border(picture: Image.Image) -> Image.Image:
    """Crop what is not the facade: a grey or white studio backdrop around it, then sky above it."""
    return _trim_sky(_trim_backdrop(picture))


def _trim_backdrop(picture: Image.Image) -> Image.Image:
    """The backdrop is the colour of both top corners when they agree and are grey or white. A side loses the lines
    that are mostly that colour, never more than MAX_TRIM of it; a facade that fills the picture keeps it all."""
    pixels = np.asarray(picture.convert("RGB"), dtype=np.float32)
    left_corner, right_corner = pixels[0, 0], pixels[0, -1]
    colour = (left_corner + right_corner) / 2
    if np.abs(left_corner - right_corner).max() > MARGIN_CLOSE or colour.max() - colour.min() > MARGIN_TINT:
        return picture
    backdrop = np.abs(pixels - colour).max(axis=2) < MARGIN_CLOSE
    rows, columns = backdrop.mean(axis=1), backdrop.mean(axis=0)
    height, width = backdrop.shape

    def depth(shares) -> int:
        limit = int(len(shares) * MAX_TRIM)
        return next((count for count, share in enumerate(shares[:limit]) if share < MARGIN_SHARE), limit)

    top, bottom, left, right = depth(rows), depth(rows[::-1]), depth(columns), depth(columns[::-1])
    if not (top or bottom or left or right):
        return picture
    return picture.crop((left, top, width - right, height - bottom))


def _trim_sky(picture: Image.Image) -> Image.Image:
    """A small house drawn whole leaves sky over its walls (a beach hut under a blue sky): the top rows that are
    mostly sky go, up to SKY_TRIM of the picture. A blue sky and a night sky are both bluer than they are red."""
    pixels = np.asarray(picture.convert("RGB"), dtype=np.float32)
    red, green, blue = pixels[..., 0], pixels[..., 1], pixels[..., 2]
    sky = ((blue - red >= SKY_BLUE) & (blue >= green)).mean(axis=1)
    limit = int(len(sky) * SKY_TRIM)
    top = next((count for count, share in enumerate(sky[:limit]) if share < SKY_SHARE), limit)
    return picture.crop((0, top, picture.width, picture.height)) if top else picture


def _png(picture: Image.Image, widest: int) -> bytes:
    picture = picture.convert("RGB")
    if picture.width > widest:
        picture = picture.resize((widest, round(widest * picture.height / picture.width)), Image.LANCZOS)
    out = io.BytesIO()
    picture.save(out, "PNG", optimize=True)
    return out.getvalue()


def _quad(corners, uvs):
    """A quad given counter-clockwise from its outside (bottom-left, bottom-right, top-right, top-left)."""
    a, b, c = (np.array(corner, dtype=np.float64) for corner in corners[:3])
    normal = np.cross(b - a, c - a)
    normal = (normal / (np.linalg.norm(normal) or 1.0)).tolist()
    return list(corners), [normal] * 4, list(uvs)


def _arrays(quads):
    positions, normals, uvs, indices = [], [], [], []
    for corners, quad_normals, quad_uvs in quads:
        base = len(positions)
        positions += corners
        normals += quad_normals
        # glTF puts v = 0 at the top of the picture; the quads count v from the bottom.
        uvs += [(u, 1 - v) for u, v in quad_uvs]
        indices += [base, base + 1, base + 2, base, base + 2, base + 3]
    return (np.array(positions, np.float32), np.array(normals, np.float32), np.array(uvs, np.float32),
            np.array(indices, np.uint16))


def house_arrays(width: float, height: float):
    """A box with its front on z = 0 facing +z, centred on x, standing on y = 0 and reaching back to z = -DEPTH."""
    w, h, d = width / 2, height, DEPTH
    edge = [(0, 0), (STRIP, 0), (STRIP, 1), (0, 1)]          # the facade's left edge, stretched over a side
    top = [(0, 1 - STRIP), (1, 1 - STRIP), (1, 1), (0, 1)]   # the facade's top strip, over the roof
    return _arrays([
        _quad([(-w, 0, 0), (w, 0, 0), (w, h, 0), (-w, h, 0)], [(0, 0), (1, 0), (1, 1), (0, 1)]),     # front
        _quad([(w, 0, 0), (w, 0, -d), (w, h, -d), (w, h, 0)], edge),                                 # right
        _quad([(-w, 0, -d), (-w, 0, 0), (-w, h, 0), (-w, h, -d)], edge),                             # left
        _quad([(w, 0, -d), (-w, 0, -d), (-w, h, -d), (w, h, -d)], edge),                             # back
        _quad([(-w, h, 0), (w, h, 0), (w, h, -d), (-w, h, -d)], top),                                # roof
    ])


def ground_arrays(size: float, tile: float, thickness: float):
    """A slab whose top is y = 0, centred on the origin; the top repeats the picture every ``tile`` metres."""
    s, t, r = size / 2, thickness, size / tile
    rim = [(0, 0), (r, 0), (r, 0.02), (0, 0.02)]
    return _arrays([
        _quad([(-s, 0, s), (s, 0, s), (s, 0, -s), (-s, 0, -s)], [(0, 0), (r, 0), (r, r), (0, r)]),   # top
        _quad([(-s, -t, s), (s, -t, s), (s, 0, s), (-s, 0, s)], rim),
        _quad([(s, -t, -s), (-s, -t, -s), (-s, 0, -s), (s, 0, -s)], rim),
        _quad([(s, -t, s), (s, -t, -s), (s, 0, -s), (s, 0, s)], rim),
        _quad([(-s, -t, -s), (-s, -t, s), (-s, 0, s), (-s, 0, -s)], rim),
    ])


def _write(target: str | Path, name: str, arrays, png: bytes, *, repeat: bool, tone: float = 1.0) -> None:
    positions, normals, uvs, indices = arrays
    blob = bytearray()
    gltf = pygltflib.GLTF2(asset=pygltflib.Asset(version="2.0", generator="hocuspocus diorama_set"),
                           scenes=[pygltflib.Scene(nodes=[0])], scene=0)

    def view(data: bytes, kind: int | None = None) -> int:
        while len(blob) % 4:
            blob.append(0)
        gltf.bufferViews.append(pygltflib.BufferView(buffer=0, byteOffset=len(blob), byteLength=len(data), target=kind))
        blob.extend(data)
        return len(gltf.bufferViews) - 1

    def accessor(array: np.ndarray, shape: str, component: int, kind: int) -> int:
        bounds = {"max": array.max(axis=0).tolist(), "min": array.min(axis=0).tolist()} if shape == "VEC3" else {}
        gltf.accessors.append(pygltflib.Accessor(bufferView=view(array.tobytes(), kind), componentType=component,
                                                 count=len(array), type=shape, **bounds))
        return len(gltf.accessors) - 1

    wrap = pygltflib.REPEAT if repeat else pygltflib.CLAMP_TO_EDGE
    gltf.samplers.append(pygltflib.Sampler(magFilter=pygltflib.LINEAR, minFilter=pygltflib.LINEAR_MIPMAP_LINEAR, wrapS=wrap, wrapT=wrap))
    gltf.images.append(pygltflib.Image(bufferView=view(png), mimeType="image/png", name=name))
    gltf.textures.append(pygltflib.Texture(source=0, sampler=0))
    gltf.materials.append(pygltflib.Material(name=name, pbrMetallicRoughness=pygltflib.PbrMetallicRoughness(
        baseColorTexture=pygltflib.TextureInfo(index=0), baseColorFactor=[tone, tone, tone, 1.0], metallicFactor=0.0, roughnessFactor=0.9)))
    attributes = pygltflib.Attributes(POSITION=accessor(positions, "VEC3", pygltflib.FLOAT, pygltflib.ARRAY_BUFFER),
                                      NORMAL=accessor(normals, "VEC3", pygltflib.FLOAT, pygltflib.ARRAY_BUFFER),
                                      TEXCOORD_0=accessor(uvs, "VEC2", pygltflib.FLOAT, pygltflib.ARRAY_BUFFER))
    indices_at = accessor(indices, "SCALAR", pygltflib.UNSIGNED_SHORT, pygltflib.ELEMENT_ARRAY_BUFFER)
    gltf.meshes.append(pygltflib.Mesh(name=name, primitives=[pygltflib.Primitive(attributes=attributes, indices=indices_at, material=0)]))
    gltf.nodes.append(pygltflib.Node(name=name, mesh=0))
    gltf.buffers.append(pygltflib.Buffer(byteLength=len(blob)))
    gltf.set_binary_blob(bytes(blob))
    gltf.save_binary(str(target))


def build_house(target: str | Path, facade: str | Path, height: float) -> dict:
    """A house block ``height`` metres tall, as wide as the trimmed facade's aspect makes it."""
    with Image.open(facade) as picture:
        picture = trim_border(picture.convert("RGB"))
        width = round(height * picture.width / picture.height, 3)
        _write(target, Path(target).stem, house_arrays(width, height), _png(picture, TEXTURE_WIDTH), repeat=False)
    return {"width": width, "height": round(float(height), 3)}


def build_ground(target: str | Path, texture: str | Path, *, size: float = GROUND_SIZE, tile: float = GROUND_TILE) -> dict:
    with Image.open(texture) as picture:
        _write(target, Path(target).stem, ground_arrays(size, tile, GROUND_THICKNESS), _png(picture, GROUND_TEXTURE), repeat=True,
               tone=GROUND_TONE)
    return {"size": size, "height": GROUND_THICKNESS}
