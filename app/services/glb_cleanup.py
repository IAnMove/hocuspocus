"""Clean a GLB brought in from elsewhere before a production rigs it.

Game exports often carry vertex normals in the vertex-colour channel: on the N64 a lit model stores its normals
where an unlit one stores colours, and a ripper that writes both as COLOR_0 gives every lit model rainbow tints
(red, green and purple gradients that follow the surface). Such a channel is recognised by how closely it follows
the NORMAL attribute and how saturated it is, and dropped; real vertex colours are kept.

Rips also carry textures decoded with the wrong format: confetti where every texel is a random vivid colour (an
old ape's beard, a fish's fins). A material painted with one loses that texture and shows its vertex colours.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np

NORMAL_LIKE = 0.3       # |median cosine| between the colour read as a direction and the normal
SATURATED = 0.4         # mean (max - min) of the colour channels: encoded directions are vivid, paint mostly is not
NOISY = 0.45            # median colour jump between neighbouring texels (summed over RGB, 0..3): garbage ~0.55-1.3, art < 0.35
VIVID = 0.35            # mean texel saturation: the garbage is confetti, while grain, static and stripes are mostly grey
SAMPLE = 256            # texels on a side of the corner of a texture that is measured
CLEANUP = 2             # version of this cleanup, part of a model's fingerprint

_TYPES = {5126: np.float32, 5121: np.uint8, 5123: np.uint16}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _read(gltf, index: int) -> np.ndarray:
    accessor = gltf.accessors[index]
    view = gltf.bufferViews[accessor.bufferView]
    kind, width = _TYPES[accessor.componentType], _WIDTH[accessor.type]
    item = np.dtype(kind).itemsize * width
    stride = view.byteStride or item
    start = view.byteOffset + (accessor.byteOffset or 0)
    raw = np.frombuffer(gltf.binary_blob()[start:start + stride * accessor.count], dtype=np.uint8)
    values = raw.reshape(accessor.count, stride)[:, :item].copy().view(kind).reshape(accessor.count, width).astype(np.float64)
    if kind is not np.float32 and accessor.normalized is not False:
        values /= np.iinfo(kind).max
    return values


def colours_are_normals(gltf) -> bool:
    """True when the vertex colours of the model's primitives read as its normals."""
    cosines, spreads = [], []
    for mesh in gltf.meshes:
        for primitive in mesh.primitives:
            attributes = primitive.attributes
            if attributes.COLOR_0 is None or attributes.NORMAL is None:
                continue
            colour = _read(gltf, attributes.COLOR_0)[:, :3]
            normal = _read(gltf, attributes.NORMAL)
            direction = 2 * colour - 1
            length = np.linalg.norm(direction, axis=1) * np.linalg.norm(normal, axis=1) + 1e-9
            cosines.append((direction * normal).sum(axis=1) / length)
            spreads.append(colour.max(axis=1) - colour.min(axis=1))
    if not cosines:
        return False
    return abs(float(np.median(np.concatenate(cosines)))) > NORMAL_LIKE and float(np.concatenate(spreads).mean()) > SATURATED


def noisy_images(gltf) -> set[int]:
    """Indices of the embedded images that are decoding garbage: every texel a random vivid colour."""
    found = set()
    for index, image in enumerate(gltf.images or []):
        texels = _texels(gltf, image)
        if texels is not None and _is_noise(texels):
            found.add(index)
    return found


def _texels(gltf, image) -> np.ndarray | None:
    from PIL import Image

    if image.bufferView is None:
        return None
    view = gltf.bufferViews[image.bufferView]
    start = view.byteOffset or 0
    try:
        with Image.open(io.BytesIO(gltf.binary_blob()[start:start + view.byteLength])) as picture:
            corner = picture.crop((0, 0, min(picture.width, SAMPLE), min(picture.height, SAMPLE)))   # a big texture is not read whole
            return np.asarray(corner.convert("RGB"), dtype=np.float32) / 255
    except (OSError, ValueError):
        return None


def _is_noise(rgb: np.ndarray) -> bool:
    if min(rgb.shape[:2]) < 2:
        return False
    jump = (np.median(np.abs(np.diff(rgb, axis=0)).sum(axis=2)) + np.median(np.abs(np.diff(rgb, axis=1)).sum(axis=2))) / 2
    top = rgb.max(axis=2)
    saturation = float(np.mean((top - rgb.min(axis=2)) / np.maximum(top, 1e-6)))
    return float(jump) > NOISY and saturation > VIVID


def _drop_noisy_textures(gltf) -> int:
    """Materials painted with a garbage image lose it; the count of materials changed."""
    noisy = noisy_images(gltf)
    if not noisy:
        return 0
    changed = 0
    for material in gltf.materials or []:
        paint = material.pbrMetallicRoughness
        texture = paint.baseColorTexture if paint else None
        if texture is not None and gltf.textures[texture.index].source in noisy:
            paint.baseColorTexture = None
            changed += 1
    return changed


def clean_glb(source: str | Path, target: str | Path) -> list[str]:
    """Write ``target`` without vertex colours that are really normals and without garbage textures, and say what
    was fixed. Empty (and nothing written) when the model is fine or unreadable."""
    import struct

    import pygltflib

    fixes = []
    try:
        gltf = pygltflib.GLTF2().load(str(source))
        if gltf is None:
            return []
        if colours_are_normals(gltf):
            for mesh in gltf.meshes:
                for primitive in mesh.primitives:
                    primitive.attributes.COLOR_0 = None
            fixes.append("its vertex colours were normals (rainbow tints)")
        if painted := _drop_noisy_textures(gltf):
            fixes.append(f"{painted} of its materials were painted with decoding noise, now dropped")
    except (OSError, ValueError, KeyError, IndexError, TypeError, struct.error):
        return []            # not a GLB this can read: the rig service says what is wrong with it
    if fixes:
        gltf.save_binary(str(target))
    return fixes
