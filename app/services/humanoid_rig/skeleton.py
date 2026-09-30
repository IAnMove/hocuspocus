"""Mixamo-named skeleton in a normalized 1.7 m space.

Joint translations under Hips are in that space. Hips itself keeps the
original-metre translation and a scale of ``height / 1.7``, so one clip fits
every character. Rest rotations are identity and local axes stay world-aligned:
left is +X, the character faces +Z, Y is up.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.names import BONE_PARENTS, NORMAL_HEIGHT

_IDENTITY = np.array([0.0, 0.0, 0.0, 1.0])


def build_skeleton(points: dict, height: float, y_min: float) -> dict:
    """Place the standard hierarchy on landmark positions, in original metres."""
    located = {name: np.asarray(value, dtype=np.float64) for name, value in points.items()}
    world = _world_positions(located, height)
    scale = float(height) / NORMAL_HEIGHT
    bones = [_bone(name, parent, world, scale) for name, parent in BONE_PARENTS]
    return {
        "bones": bones,
        "world": world,
        "scale": scale,
        "height": float(height),
        "y_min": float(y_min),
    }


def world_matrices(bones: list[dict], rotations: dict | None = None) -> list[np.ndarray]:
    """World matrix of every bone. ``rotations`` overrides local xyzw quaternions."""
    overrides = rotations or {}
    worlds: list[np.ndarray] = []
    by_name = {}
    for bone in bones:
        parent = np.eye(4) if bone["parent"] is None else by_name[bone["parent"]]
        rotation = overrides.get(bone["name"], bone["rotation"])
        local = _trs(bone["translation"], rotation, bone["scale"])
        world = parent @ local
        by_name[bone["name"]] = world
        worlds.append(world)
    return worlds


def skin_vertices(
    vertices: np.ndarray,
    joints: np.ndarray,
    weights: np.ndarray,
    bind_worlds: list[np.ndarray],
    anim_worlds: list[np.ndarray],
) -> np.ndarray:
    """Linear blend skinning with bindMatrix = identity, matching Video 3D.

    ``inverseBind = inverse(bind world)``. At rest the mesh is unchanged.
    """
    points = np.asarray(vertices, dtype=np.float64)
    inverse = [np.linalg.inv(matrix) for matrix in bind_worlds]
    skinned = np.zeros_like(points)
    for influence in range(4):
        weight = weights[:, influence].astype(np.float64)
        active = weight > 0
        if not np.any(active):
            continue
        chosen = joints[active, influence]
        for joint in np.unique(chosen):
            mask = np.zeros(len(points), dtype=bool)
            mask[np.flatnonzero(active)[chosen == joint]] = True
            transformed = _apply(anim_worlds[int(joint)] @ inverse[int(joint)], points[mask])
            skinned[mask] += weight[mask, None] * transformed
    return skinned


def axis_quaternion(axis: np.ndarray, degrees: float) -> np.ndarray:
    """Right-handed xyzw quaternion."""
    theta = np.radians(float(degrees)) * 0.5
    direction = np.asarray(axis, dtype=np.float64)
    direction = direction / np.linalg.norm(direction)
    return np.array([*(direction * np.sin(theta)), np.cos(theta)])


def _bone(name: str, parent: str | None, world: dict, scale: float) -> dict:
    if parent is None:
        translation = world[name]
        bone_scale = np.array([scale, scale, scale])
    else:
        translation = (world[name] - world[parent]) / scale
        bone_scale = np.ones(3)
    return {
        "name": name,
        "parent": parent,
        "translation": translation.astype(np.float64),
        "rotation": _IDENTITY.copy(),
        "scale": bone_scale,
    }


def _world_positions(points: dict, height: float) -> dict[str, np.ndarray]:
    hips = points["crotch"]
    shoulder = (points["left_shoulder"] + points["right_shoulder"]) * 0.5
    crown = points["crown"]
    located = {
        "Hips": hips,
        "Spine": _mix(hips, shoulder, 0.33),
        "Spine1": _mix(hips, shoulder, 0.66),
        "Spine2": shoulder.copy(),
        "Neck": _mix(shoulder, crown, 0.35),
        "Head": _mix(shoulder, crown, 0.68),
        "HeadTop_End": crown.copy(),
    }
    _limbs(located, points, shoulder, height)
    return located


def _limbs(located: dict, points: dict, shoulder: np.ndarray, height: float) -> None:
    step = np.array([0.0, 0.0, height * 0.045])
    for side, prefix in (("left", "Left"), ("right", "Right")):
        joint = points[f"{side}_shoulder"]
        located[f"{prefix}Shoulder"] = _mix(shoulder, joint, 0.2)
        located[f"{prefix}Arm"] = joint.copy()
        located[f"{prefix}ForeArm"] = points[f"{side}_elbow"].copy()
        located[f"{prefix}Hand"] = points[f"{side}_hand"].copy()
        located[f"{prefix}UpLeg"] = points[f"{side}_hip"].copy()
        located[f"{prefix}Leg"] = points[f"{side}_knee"].copy()
        foot = points[f"{side}_foot"]
        located[f"{prefix}Foot"] = foot.copy()
        located[f"{prefix}ToeBase"] = foot + step
        located[f"{prefix}Toe_End"] = foot + step * 2


def _mix(start: np.ndarray, end: np.ndarray, factor: float) -> np.ndarray:
    return start * (1.0 - factor) + end * factor


def _trs(translation: np.ndarray, rotation: np.ndarray, scale: np.ndarray) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, :3] = _quat_matrix(rotation) @ np.diag(np.asarray(scale, dtype=np.float64))
    matrix[:3, 3] = np.asarray(translation, dtype=np.float64)
    return matrix


def _quat_matrix(quaternion: np.ndarray) -> np.ndarray:
    x, y, z, w = (float(value) for value in quaternion)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def _apply(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    return points @ matrix[:3, :3].T + matrix[:3, 3]
