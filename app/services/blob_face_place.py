"""Where a 2D face sits on a rigged model: the head box, in model metres.

``faceAnchor.size`` is a diameter. Vertices skinned to the Head bone win over the bone's own origin,
which on a humanoid is often the neck. ``extras.faceAnchor`` on the glTF wins over both.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from services.blob_face import BlobFaceError
from services.humanoid_rig.gltf_accessors import (
    read_accessor,
    split_glb,
    _node_matrix,
    _position_primitives,
    _selected_meshes,
)
from services.humanoid_rig.pose_math import trs_matrix, world_matrices

# Half of the brief's head size when a Head bone has no skinned vertices.
_FALLBACK_RADII = (0.31, 0.29, 0.275)


def _is_head(name: str) -> bool:
    tail = "head"
    if name.lower() == tail:
        return True
    if len(name) <= len(tail) or not name.lower().endswith(tail):
        return False
    before, first = name[-len(tail) - 1], name[-len(tail)]
    return before in ":_" or (before.islower() and first.isupper())


def _head_index(nodes: list[dict]) -> int | None:
    hits = [index for index, node in enumerate(nodes) if _is_head(str(node.get("name") or ""))]
    for index in hits:
        if nodes[index].get("name") == "Head":
            return index
    return hits[0] if hits else None


def _family(nodes: list[dict], root: int) -> set[int]:
    children: dict[int, list[int]] = {}
    for index, node in enumerate(nodes):
        for child in node.get("children") or []:
            if isinstance(child, int):
                children.setdefault(index, []).append(child)
    found, stack = set(), [root]
    while stack:
        current = stack.pop()
        if current in found or not 0 <= current < len(nodes):
            continue
        found.add(current)
        stack.extend(children.get(current, []))
    return found


def _parents(nodes: list[dict]) -> list[int | None]:
    parents: list[int | None] = [None] * len(nodes)
    for index, node in enumerate(nodes):
        for child in node.get("children") or []:
            if isinstance(child, int) and 0 <= child < len(nodes):
                parents[child] = index
    return parents


def anchor_radii(anchor: dict[str, Any]) -> dict[str, list[float]] | None:
    """``center`` plus ``radii``, or ``size`` as a diameter (each axis halved)."""
    center = anchor.get("center") if isinstance(anchor, dict) else None
    if not isinstance(center, (list, tuple)) or len(center) != 3:
        return None
    try:
        origin = [float(value) for value in center]
    except (TypeError, ValueError):
        return None
    radii = anchor.get("radii")
    if not (isinstance(radii, (list, tuple)) and len(radii) == 3):
        size = anchor.get("size")
        if not (isinstance(size, (list, tuple)) and len(size) == 3):
            return None
        radii = [float(value) / 2 for value in size]
    try:
        halves = [float(value) for value in radii]
    except (TypeError, ValueError):
        return None
    if any(value <= 0 or value > 5 for value in halves) or any(abs(value) > 50 for value in origin):
        return None
    return {"center": [round(value, 4) for value in origin], "radii": [round(value, 4) for value in halves]}


def _declared_anchor(document: dict) -> dict[str, Any] | None:
    pools = [*(document.get("nodes") or []), *(document.get("scenes") or []), document.get("asset") or {}]
    for item in pools:
        if not isinstance(item, dict):
            continue
        found = anchor_radii((item.get("extras") or {}).get("faceAnchor") or {})
        if found:
            return {**found, "method": "faceAnchor"}
    return None


def _skin_cloud(points, joint_index, weights, joints, worlds, ibms, heads: set[int]) -> list[list[float]]:
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim == 1:
        pts = pts.reshape(1, -1)
    homo = np.concatenate((pts[:, :3], np.ones((len(pts), 1))), axis=1)
    indexes = np.asarray(joint_index, dtype=np.int64).reshape(len(pts), -1)
    influence = np.asarray(weights, dtype=np.float64).reshape(len(pts), -1)
    out = np.zeros((len(pts), 4), dtype=np.float64)
    for slot in range(indexes.shape[1]):
        for joint in np.unique(indexes[:, slot]):
            mask = indexes[:, slot] == joint
            joint = int(joint)
            if joint < 0 or joint >= len(joints) or joint >= len(ibms):
                continue
            node = joints[joint]
            if not isinstance(node, int) or isinstance(node, bool) or node not in heads or node >= len(worlds):
                continue
            out[mask] += influence[mask, slot][:, None] * (homo[mask] @ (worlds[node] @ ibms[joint]).T)
    keep = out[:, 3] > 0.5
    return out[keep, :3].tolist()


def _head_points(document: dict, buffers: list[bytes], worlds, heads: set[int]) -> list[list[float]]:
    cloud: list[list[float]] = []
    for skin in document.get("skins") or []:
        joints = skin.get("joints") or []
        if not isinstance(skin.get("inverseBindMatrices"), int) or not joints:
            continue
        inverse = read_accessor(document, skin["inverseBindMatrices"], buffers)
        ibms = [np.asarray(row, dtype=np.float64).reshape((4, 4), order="F") for row in np.atleast_2d(inverse)]
        for _mesh, primitive in _position_primitives(document, _selected_meshes(document)):
            attrs = primitive.get("attributes") or {}
            if not all(isinstance(attrs.get(key), int) for key in ("POSITION", "JOINTS_0", "WEIGHTS_0")):
                continue
            cloud.extend(_skin_cloud(read_accessor(document, attrs["POSITION"], buffers),
                                     read_accessor(document, attrs["JOINTS_0"], buffers),
                                     read_accessor(document, attrs["WEIGHTS_0"], buffers), joints, worlds, ibms, heads))
    return cloud


def _measure(document: dict, buffers: list[bytes]) -> dict[str, Any]:
    nodes = document.get("nodes") or []
    head = _head_index(nodes)
    if head is None:
        raise BlobFaceError("head_not_found", "The model has no Head bone")
    worlds = world_matrices([_node_matrix(node, trs_matrix) for node in nodes], _parents(nodes))
    cloud = _head_points(document, buffers, worlds, _family(nodes, head))
    if len(cloud) < 8:
        center = worlds[head][:3, 3]
        return {"center": [round(float(value), 4) for value in center], "radii": list(_FALLBACK_RADII), "method": "bone"}
    array = np.asarray(cloud, dtype=np.float64)
    low, high = array.min(axis=0), array.max(axis=0)
    center, radii = (low + high) / 2, np.maximum((high - low) / 2, 0.02)
    return {"center": [round(float(value), 4) for value in center], "radii": [round(float(value), 4) for value in radii],
            "method": "vertices"}


def head_placement(path: str) -> dict[str, Any]:
    """``center`` and ``radii`` (metres) for the face cap. ``faceAnchor`` in the glTF wins."""
    with open(path, "rb") as handle:
        document, buffers = split_glb(handle.read())
    declared = _declared_anchor(document)
    if declared:
        return declared
    try:
        return _measure(document, buffers)
    except BlobFaceError:
        raise
    except (OSError, ValueError) as error:
        raise BlobFaceError("head_not_found", "The model's head could not be measured") from error
