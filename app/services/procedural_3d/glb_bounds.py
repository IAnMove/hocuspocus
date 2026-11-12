"""Rest-pose bounding box of a GLB, read from its JSON chunk alone.

glTF requires ``min`` and ``max`` on every POSITION accessor, so the box of each mesh primitive is known without
touching a buffer. The box is carried through the node tree of the default scene (``matrix`` or translation, rotation
and scale of each node) and merged. Only the 12-byte header, the 8-byte chunk header and the JSON chunk are read, so a
100 MB model costs a few kilobytes.

Skinned meshes: the box is the accessor box under the mesh node's world transform, which is the model in its bind
pose. Joint transforms, morph targets and animation clips are not applied. This matches what the Video 3D renderer
measures when it fits a model (``Box3().setFromObject`` of the loaded scene, before any clip plays) for every model
whose bind pose is its rest pose. A model whose armature carries a uniform unit conversion (centimetres under a 0.01
armature) is off by that factor on every axis, which cancels where only proportions matter.

``glb_bounds`` never raises: every failure is ``{"ok": False, "reason": <code>}``.
"""
from __future__ import annotations

import json
import math
import struct
from itertools import product
from pathlib import Path

from services.procedural_3d.glb_inspector import GlbInspectorLimits

_GLB_MAGIC = 0x46546C67
_JSON_CHUNK = 0x4E4F534A
_HEADER = 20           # 12-byte file header + 8-byte header of the first chunk
_MAX_DEPTH = 64
_MAX_VISITS = 20_000
MAX_JSON_BYTES = GlbInspectorLimits().max_json_bytes
_DIGITS = 6


class _Refused(Exception):
    """A GLB the box cannot be measured from; the message is the reason code."""


def glb_bounds(path, *, max_json_bytes: int = MAX_JSON_BYTES) -> dict:
    """``{ok, min, max, size, center, bottomY, reason}``: the box in glTF units (metres), y up, or ``ok: False`` and why.

    Reasons: ``missing_file``, ``not_glb``, ``unsupported_version``, ``truncated``, ``json_too_large``,
    ``invalid_json``, ``missing_min_max``, ``no_meshes``, ``bad_reference``, ``bad_transform``, ``cyclic_nodes``,
    ``too_many_nodes``, ``non_finite``, ``unreadable``."""
    try:
        low, high = _measure(_read_document(Path(path), max_json_bytes))
        return _result(low, high)
    except _Refused as refusal:
        return _refused(str(refusal))
    except FileNotFoundError:
        return _refused("missing_file")
    except Exception:  # noqa: BLE001 - the contract is that a bad file never raises
        return _refused("unreadable")


def _refused(reason: str) -> dict:
    return {"ok": False, "min": None, "max": None, "size": None, "center": None, "bottomY": None, "reason": reason}


def _result(low: list[float], high: list[float]) -> dict:
    if not all(math.isfinite(value) for value in (*low, *high)):
        raise _Refused("non_finite")
    size = [high[axis] - low[axis] for axis in range(3)]
    center = [(high[axis] + low[axis]) / 2 for axis in range(3)]
    cut = lambda values: [round(value, _DIGITS) for value in values]  # noqa: E731
    return {"ok": True, "min": cut(low), "max": cut(high), "size": cut(size), "center": cut(center),
            "bottomY": round(low[1], _DIGITS), "reason": None}


def _read_document(path: Path, max_json_bytes: int) -> dict:
    with path.open("rb") as handle:
        head = handle.read(_HEADER)
        if len(head) < 12 or struct.unpack_from("<I", head, 0)[0] != _GLB_MAGIC:
            raise _Refused("not_glb")
        version, declared = struct.unpack_from("<II", head, 4)
        if version != 2:
            raise _Refused("unsupported_version")
        if len(head) < _HEADER or declared < _HEADER or declared > path.stat().st_size:
            raise _Refused("truncated")
        length, kind = struct.unpack_from("<II", head, 12)
        if kind != _JSON_CHUNK:
            raise _Refused("not_glb")
        if length > max_json_bytes:
            raise _Refused("json_too_large")
        if _HEADER + length > declared:
            raise _Refused("truncated")
        payload = handle.read(length)
    if len(payload) != length:
        raise _Refused("truncated")
    try:
        document = json.loads(payload.decode("utf-8"))
    except ValueError as error:
        raise _Refused("invalid_json") from error
    if not isinstance(document, dict):
        raise _Refused("invalid_json")
    return document


def _measure(document: dict) -> tuple[list[float], list[float]]:
    low, high = [math.inf] * 3, [-math.inf] * 3
    for world, mesh in _meshes(document):
        for box_low, box_high in _primitive_boxes(document, mesh):
            for corner in product(*zip(box_low, box_high)):
                point = _apply(world, corner)
                low = [min(a, b) for a, b in zip(low, point)]
                high = [max(a, b) for a, b in zip(high, point)]
    if low[0] == math.inf:
        raise _Refused("no_meshes")
    return low, high


def _meshes(document: dict):
    """Each ``(world matrix, mesh index)`` of the default scene, parents before children."""
    for _index, _node, world, mesh in _mesh_nodes(document):
        yield world, mesh


def _mesh_nodes(document: dict):
    """Each ``(node index, node, world matrix, mesh index)`` of the default scene's mesh nodes, parents before children."""
    nodes = _list(document.get("nodes"))
    stack = [(index, _IDENTITY, ()) for index in reversed(_roots(document, nodes))]
    visits = 0
    while stack:
        index, parent, ancestors = stack.pop()
        visits += 1
        if visits > _MAX_VISITS:
            raise _Refused("too_many_nodes")
        if index in ancestors or len(ancestors) > _MAX_DEPTH:
            raise _Refused("cyclic_nodes")
        node = _item(nodes, index)
        world = _multiply(parent, _local(node))
        if "mesh" in node:
            yield index, node, world, node["mesh"]
        for child in reversed(_list(node.get("children"))):
            stack.append((child, world, (*ancestors, index)))


def _roots(document: dict, nodes: list) -> list:
    scenes = _list(document.get("scenes"))
    if scenes:
        scene = _item(scenes, document.get("scene", 0))
        return _list(scene.get("nodes"))
    children = {child for node in nodes if isinstance(node, dict) for child in _list(node.get("children"))}
    return [index for index in range(len(nodes)) if index not in children]


def _primitive_boxes(document: dict, mesh_index):
    mesh = _item(_list(document.get("meshes")), mesh_index)
    accessors = _list(document.get("accessors"))
    for primitive in _list(mesh.get("primitives")):
        position = (primitive.get("attributes") or {}).get("POSITION") if isinstance(primitive, dict) else None
        if position is None:
            continue
        accessor = _item(accessors, position)
        yield _vector(accessor.get("min"), 3, "missing_min_max"), _vector(accessor.get("max"), 3, "missing_min_max")


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _item(items: list, index) -> dict:
    if type(index) is not int or not 0 <= index < len(items) or not isinstance(items[index], dict):
        raise _Refused("bad_reference")
    return items[index]


def _vector(value, length: int, reason: str) -> list[float]:
    if not isinstance(value, list) or len(value) != length or not all(type(item) in (int, float) and math.isfinite(item) for item in value):
        raise _Refused(reason)
    return [float(item) for item in value]


_IDENTITY = tuple(tuple(1.0 if row == column else 0.0 for column in range(4)) for row in range(4))


def _multiply(a, b):
    return tuple(tuple(sum(a[row][k] * b[k][column] for k in range(4)) for column in range(4)) for row in range(4))


def _apply(matrix, point) -> list[float]:
    return [sum(matrix[row][axis] * point[axis] for axis in range(3)) + matrix[row][3] for row in range(3)]


def _local(node: dict):
    """The node's own transform as a row-major 4x4: its ``matrix`` (column-major in glTF) or T * R * S."""
    if "matrix" in node:
        flat = _vector(node["matrix"], 16, "bad_transform")
        return tuple(tuple(flat[column * 4 + row] for column in range(4)) for row in range(4))
    translation = _vector(node.get("translation", [0, 0, 0]), 3, "bad_transform")
    x, y, z, w = _vector(node.get("rotation", [0, 0, 0, 1]), 4, "bad_transform")
    scale = _vector(node.get("scale", [1, 1, 1]), 3, "bad_transform")
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0:
        raise _Refused("bad_transform")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    rotation = ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
                (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
                (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))
    rows = [tuple(rotation[row][column] * scale[column] for column in range(3)) + (translation[row],) for row in range(3)]
    return (*rows, (0.0, 0.0, 0.0, 1.0))
