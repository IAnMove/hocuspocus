"""Clean a GLB brought in from elsewhere before a production rigs it.

Game exports often carry vertex normals in the vertex-colour channel: on the N64 a lit model stores its normals
where an unlit one stores colours, and a ripper that writes both as COLOR_0 gives every lit model rainbow tints
(red, green and purple gradients that follow the surface). Such a channel is recognised by how closely it follows
the NORMAL attribute and how saturated it is, and dropped; real vertex colours are kept.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

NORMAL_LIKE = 0.3       # |median cosine| between the colour read as a direction and the normal
SATURATED = 0.4         # mean (max - min) of the colour channels: encoded directions are vivid, paint mostly is not
CLEANUP = 1             # version of this cleanup, part of a model's fingerprint

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


def clean_glb(source: str | Path, target: str | Path) -> bool:
    """Write ``target`` without vertex colours that are really normals. False (and nothing written) when the
    model's colours are real."""
    import struct

    import pygltflib

    try:
        gltf = pygltflib.GLTF2().load(str(source))
        if gltf is None or not colours_are_normals(gltf):
            return False
    except (OSError, ValueError, KeyError, IndexError, TypeError, struct.error):
        return False         # not a GLB this can read: the rig service says what is wrong with it
    for mesh in gltf.meshes:
        for primitive in mesh.primitives:
            primitive.attributes.COLOR_0 = None
    gltf.save_binary(str(target))
    return True
