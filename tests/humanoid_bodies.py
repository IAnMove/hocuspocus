"""Deterministic test bodies: one closed, welded surface like a Hunyuan3D mesh.

Each body is a smooth union of tapered capsules and spheres sampled on a voxel
grid. The surface is the set of voxel faces between inside and outside cells,
smoothed a little. ``joints`` holds the construction joint positions, so a test
can measure landmark error against the body it built. Y is up, the body faces
+Z, and its left side is +X.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache

import numpy as np

_SMOOTH_PASSES = 6


@lru_cache(maxsize=None)
def body(kind: str, *, voxel: float = 0.016) -> dict:
    """Return ``{"positions", "indices", "joints", "height"}`` for a named body. Cached: do not mutate."""
    joints, parts = _BODIES[kind]()
    positions, indices = _surface(parts, voxel)
    floor = float(positions[:, 1].min())
    return {
        "positions": positions,
        "indices": indices,
        "joints": {name: np.asarray(value, dtype=np.float64) for name, value in joints.items()},
        "height": float(positions[:, 1].max()) - floor,
        "floor": floor,
    }


def as_glb(item: dict, node_matrix: np.ndarray | None = None, instances: int = 1, extensions: list[str] | None = None) -> bytes:
    """The body as a plain GLB: one indexed primitive, one material.

    ``node_matrix`` stores the vertices in the node's local space so the world
    shape stays the same. ``instances`` > 1 hangs the same mesh from that many
    nodes, side by side.
    """
    import struct

    matrix = np.eye(4) if node_matrix is None else np.asarray(node_matrix, dtype=np.float64)
    inverse = np.linalg.inv(matrix)
    local = np.asarray(item["positions"], dtype=np.float64) @ inverse[:3, :3].T + inverse[:3, 3]
    positions = local.astype("<f4")
    indices = np.asarray(item["indices"], dtype="<u4").reshape(-1)
    blob = positions.tobytes() + indices.tobytes()
    nodes = []
    for index in range(instances):
        placed = matrix.copy()
        placed[0, 3] += index * 3.0
        nodes.append({"name": f"Body{index}", "mesh": 0, "matrix": placed.T.reshape(-1).tolist()})
    document = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(instances))}], "nodes": nodes,
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.7, 0.6, 1.0]}}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": positions.nbytes, "target": 34962},
                        {"buffer": 0, "byteOffset": positions.nbytes, "byteLength": indices.nbytes, "target": 34963}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3",
                       "min": positions.min(axis=0).tolist(), "max": positions.max(axis=0).tolist()},
                      {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"}],
    }
    if extensions:
        document["extensionsUsed"] = list(extensions)
        document["extensionsRequired"] = list(extensions)
    text = json.dumps(document).encode("utf-8")
    text += b" " * (-len(text) % 4)
    blob += b"\0" * (-len(blob) % 4)
    chunks = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(blob), 0x004E4942) + blob
    return struct.pack("<III", 0x46546C67, 2, 12 + len(chunks)) + chunks


def transformed(item: dict, *, yaw_degrees: float = 0.0, offset=(0.0, 0.0, 0.0)) -> dict:
    """The same body turned about Y and moved. Joints follow."""
    angle = math.radians(yaw_degrees)
    rotation = np.array([[math.cos(angle), 0.0, math.sin(angle)], [0.0, 1.0, 0.0], [-math.sin(angle), 0.0, math.cos(angle)]])
    shift = np.asarray(offset, dtype=np.float64)
    moved = dict(item)
    moved["positions"] = item["positions"] @ rotation.T + shift
    moved["joints"] = {name: value @ rotation.T + shift for name, value in item["joints"].items()}
    moved["floor"] = item["floor"] + float(shift[1])
    return moved


def _human(arm_drop: float = 0.0, *, arms_down: bool = False, legs_together: bool = False, hat: bool = False,
           extra: tuple = ()) -> tuple[dict, list]:
    hip, knee, ankle = 0.10, 0.48, 0.08
    leg_x = 0.0 if legs_together else hip
    joints = {
        "pelvis": (0.0, 0.95, 0.0),
        "chest": (0.0, 1.30, 0.0),
        "neck": (0.0, 1.47, 0.0),
        "head": (0.0, 1.60, 0.02),
        "crown": (0.0, 1.75, 0.02),
    }
    parts = [
        ("capsule", joints["pelvis"], joints["chest"], 0.15, 0.17),
        ("capsule", (0.0, 1.30, 0.0), (0.0, 1.40, 0.0), 0.17, 0.12),
        ("capsule", (0.0, 1.38, 0.0), joints["neck"], 0.06, 0.055),
        ("sphere", joints["head"], 0.115),
    ]
    if hat:
        parts.append(("capsule", (0.0, 1.70, 0.02), (0.05, 1.98, -0.03), 0.10, 0.01))
        joints["crown"] = (0.05, 1.99, -0.03)
    for side in (1.0, -1.0):
        _human_leg(joints, parts, side, leg_x, knee, ankle)
        _human_arm(joints, parts, side, 90.0 - 8.0 if arms_down else arm_drop)
    return joints, parts + list(extra)


def _human_leg(joints, parts, side, leg_x, knee, ankle) -> None:
    name = "left" if side > 0 else "right"
    hip = (side * leg_x, 0.92, 0.0)
    knee_point = (side * leg_x * 0.95, knee, 0.01)
    ankle_point = (side * leg_x * 0.9, ankle, 0.0)
    toe = (side * leg_x * 0.9, 0.035, 0.17)
    joints.update({f"{name}_hip": hip, f"{name}_knee": knee_point, f"{name}_ankle": ankle_point, f"{name}_toe": toe})
    parts += [
        ("capsule", hip, knee_point, 0.085, 0.06),
        ("capsule", knee_point, ankle_point, 0.06, 0.045),
        ("capsule", (ankle_point[0], 0.05, -0.03), toe, 0.05, 0.035),
    ]


def _human_arm(joints, parts, side, drop) -> None:
    name = "left" if side > 0 else "right"
    shoulder = (side * 0.20, 1.39, 0.0)
    direction = np.array([side * math.cos(math.radians(drop)), -math.sin(math.radians(drop)), 0.0])
    elbow = np.asarray(shoulder) + direction * 0.29
    wrist = elbow + direction * 0.25
    tip = wrist + direction * 0.17
    joints.update({f"{name}_shoulder": shoulder, f"{name}_elbow": elbow, f"{name}_wrist": wrist, f"{name}_hand_tip": tip})
    parts += [
        ("capsule", (side * 0.10, 1.40, 0.0), shoulder, 0.07, 0.065),
        ("capsule", shoulder, elbow, 0.055, 0.045),
        ("capsule", elbow, wrist, 0.045, 0.035),
        ("capsule", wrist, tip, 0.045, 0.03),
    ]


def _pet() -> tuple[dict, list]:
    joints = {"pelvis": (0.0, 0.34, 0.0), "chest": (0.0, 0.52, 0.0), "neck": (0.0, 0.60, 0.0), "head": (0.0, 0.78, 0.0), "crown": (0.0, 1.08, 0.0)}
    parts = [("capsule", (0.0, 0.33, 0.0), (0.0, 0.55, 0.0), 0.15, 0.13), ("sphere", (0.0, 0.84, 0.0), 0.24)]
    for side in (1.0, -1.0):
        name = "left" if side > 0 else "right"
        hip, knee, ankle = (side * 0.075, 0.30, 0.0), (side * 0.08, 0.17, 0.01), (side * 0.08, 0.06, 0.0)
        shoulder, elbow, wrist, tip = (side * 0.14, 0.53, 0.0), (side * 0.27, 0.53, 0.0), (side * 0.38, 0.53, 0.0), (side * 0.46, 0.53, 0.0)
        joints.update({f"{name}_hip": hip, f"{name}_knee": knee, f"{name}_ankle": ankle, f"{name}_toe": (side * 0.08, 0.03, 0.11),
                       f"{name}_shoulder": shoulder, f"{name}_elbow": elbow, f"{name}_wrist": wrist, f"{name}_hand_tip": tip})
        parts += [
            ("capsule", hip, knee, 0.065, 0.055), ("capsule", knee, ankle, 0.055, 0.05),
            ("capsule", (side * 0.08, 0.04, -0.02), (side * 0.08, 0.035, 0.09), 0.05, 0.04),
            ("capsule", (side * 0.06, 0.53, 0.0), elbow, 0.05, 0.042), ("capsule", elbow, wrist, 0.042, 0.04),
            ("sphere", (side * 0.42, 0.53, 0.0), 0.05),
        ]
    return joints, parts


def _alien() -> tuple[dict, list]:
    joints, parts = _pet()
    for side in (1.0, -1.0):
        parts.append(("capsule", (side * 0.18, 0.86, 0.0), (side * 0.40, 0.92, 0.0), 0.06, 0.025))
    return joints, parts


def _penguin() -> tuple[dict, list]:
    joints = {"crown": (0.0, 0.92, 0.0)}
    parts = [("capsule", (0.0, 0.22, 0.0), (0.0, 0.62, 0.0), 0.24, 0.18), ("sphere", (0.0, 0.72, 0.0), 0.2)]
    for side in (1.0, -1.0):
        parts += [
            ("capsule", (side * 0.2, 0.55, 0.0), (side * 0.27, 0.30, 0.0), 0.05, 0.03),
            ("capsule", (side * 0.08, 0.04, 0.0), (side * 0.10, 0.03, 0.12), 0.04, 0.03),
        ]
    return joints, parts


_BODIES = {
    "human_t": lambda: _human(0.0),
    "human_a": lambda: _human(40.0),
    "human_a_steep": lambda: _human(62.0),
    "human_hat": lambda: _human(0.0, hat=True),
    "pet": _pet,
    "alien": _alien,
    "arms_down": lambda: _human(arms_down=True),
    "legs_together": lambda: _human(10.0, legs_together=True),
    "penguin": _penguin,
    "arms_raised": lambda: _human(-20.0),
    "arms_up": lambda: _human(-50.0),
    "with_orb": lambda: _human(0.0, extra=(("sphere", (1.12, 1.18, 0.3), 0.07),)),
    "on_base": lambda: _human(30.0, extra=tuple(("capsule", (-0.38, -0.04, z), (0.38, -0.04, z), 0.035, 0.035) for z in (-0.12, 0.0, 0.12, 0.24))),
}

BODY_KINDS = tuple(_BODIES)


def _surface(parts: list, voxel: float) -> tuple[np.ndarray, np.ndarray]:
    low, high = _bounds(parts, voxel)
    axes = [np.arange(low[i], high[i] + voxel, voxel) for i in range(3)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1)
    inside = _field(parts, grid.reshape(-1, 3)).reshape(grid.shape[:3]) < 0.0
    corners, quads = _faces(inside)
    positions = low + corners * voxel - voxel * 0.5
    positions = _relax(positions, quads)
    triangles = np.concatenate((quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]), axis=0)
    return positions, triangles.astype(np.int64)


def _bounds(parts: list, voxel: float) -> tuple[np.ndarray, np.ndarray]:
    points, radii = [], []
    for part in parts:
        if part[0] == "sphere":
            points.append(part[1])
            radii.append(part[2])
        else:
            points += [part[1], part[2]]
            radii += [part[3], part[4]]
    cloud = np.asarray(points, dtype=np.float64)
    pad = max(radii) + voxel * 3
    return cloud.min(axis=0) - pad, cloud.max(axis=0) + pad


def _field(parts: list, points: np.ndarray) -> np.ndarray:
    value = np.full(len(points), 10.0)
    for part in parts:
        value = _smooth_min(value, _distance(part, points), 0.03)
    return value


def _distance(part, points: np.ndarray) -> np.ndarray:
    if part[0] == "sphere":
        return np.linalg.norm(points - np.asarray(part[1]), axis=1) - part[2]
    start, end = np.asarray(part[1], dtype=np.float64), np.asarray(part[2], dtype=np.float64)
    segment = end - start
    factor = np.clip(((points - start) @ segment) / max(float(segment @ segment), 1e-12), 0.0, 1.0)
    radius = part[3] + (part[4] - part[3]) * factor
    return np.linalg.norm(points - (start + factor[:, None] * segment), axis=1) - radius


def _smooth_min(left: np.ndarray, right: np.ndarray, blend: float) -> np.ndarray:
    mix = np.clip(0.5 + 0.5 * (right - left) / blend, 0.0, 1.0)
    return right * (1.0 - mix) + left * mix - blend * mix * (1.0 - mix)


def _faces(inside: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Quads between inside and outside cells, wound outward, on shared corners."""
    shape = np.array(inside.shape) + 1
    quads = []
    for axis in range(3):
        quads.append(_axis_faces(inside, axis, shape))
    faces = np.concatenate(quads, axis=0)
    used, remap = np.unique(faces.reshape(-1), return_inverse=True)
    corners = np.stack(np.unravel_index(used, tuple(shape)), axis=1).astype(np.float64)
    return corners, remap.reshape(-1, 4)


def _axis_faces(inside: np.ndarray, axis: int, shape: np.ndarray) -> np.ndarray:
    padded = np.pad(inside, [(1, 1) if index == axis else (0, 0) for index in range(3)])
    lower = np.take(padded, range(0, padded.shape[axis] - 1), axis=axis)
    upper = np.take(padded, range(1, padded.shape[axis]), axis=axis)
    rows = []
    for mask, flip in ((lower & ~upper, False), (~lower & upper, True)):
        cells = np.argwhere(mask)
        rows.append(_quad_corners(cells, axis, shape, flip))
    return np.concatenate(rows, axis=0)


def _quad_corners(cells: np.ndarray, axis: int, shape: np.ndarray, flip: bool) -> np.ndarray:
    u, v = [index for index in range(3) if index != axis]
    base = cells.copy()
    offsets = []
    for du, dv in ((0, 0), (1, 0), (1, 1), (0, 1)):
        corner = base.copy()
        corner[:, u] += du
        corner[:, v] += dv
        offsets.append(np.ravel_multi_index(corner.T, tuple(shape)))
    quad = np.stack(offsets, axis=1)
    outward = (axis == 1) != flip
    return quad[:, ::-1] if outward else quad


def _relax(positions: np.ndarray, quads: np.ndarray) -> np.ndarray:
    edges = np.concatenate([quads[:, [0, 1]], quads[:, [1, 2]], quads[:, [2, 3]], quads[:, [3, 0]]], axis=0)
    edges = np.concatenate((edges, edges[:, ::-1]), axis=0)
    degree = np.bincount(edges[:, 0], minlength=len(positions)).astype(np.float64)[:, None]
    relaxed = positions.copy()
    for _index in range(_SMOOTH_PASSES):
        total = np.zeros_like(relaxed)
        np.add.at(total, edges[:, 0], relaxed[edges[:, 1]])
        relaxed = relaxed * 0.5 + 0.5 * total / np.maximum(degree, 1.0)
    return relaxed
