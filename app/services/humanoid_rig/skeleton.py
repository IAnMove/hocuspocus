"""Mixamo-named skeleton with canonical frames.

Every bone's local axes are the character's axes in a perfect T pose: +X is
the character's left, +Y is up, +Z is forward. The rest (bind) rotations bend
those frames onto the modeled pose: an A pose keeps its arms down at rest, and
a clip that sets a local rotation to identity puts that bone in the T pose.
So one clip fits every character, whatever its pose or proportions.

Hips keeps the original-metre translation and a scale of ``height / 1.7``;
joint translations under it are in that normalized space.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.names import BONE_PARENTS, NORMAL_HEIGHT

_IDENTITY = rot.IDENTITY
_UP_FRAMES = ("Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "HeadTop_End", "LeftShoulder", "RightShoulder")


def build_skeleton(points: dict, height: float, y_min: float, facing: int = 1, head_region: dict | None = None,
                   base: float | None = None, robe: dict | None = None) -> dict:
    """Place the standard hierarchy on landmark positions, in original metres.

    ``robe`` (``{"hem": y}``) marks legs hidden in a robe, whose surface the weights hang from the hips.
    """
    located = {name: np.asarray(value, dtype=np.float64) for name, value in points.items()}
    world = _world_positions(located, height)
    facing_quat = _IDENTITY.copy() if facing >= 0 else rot.axis_angle([0.0, 1.0, 0.0], 180.0)
    frames = _rest_frames(world, facing_quat)
    scale = float(height) / NORMAL_HEIGHT
    bones = [_bone(name, parent, world, frames, scale) for name, parent in BONE_PARENTS]
    return {
        "bones": bones,
        "world": world,
        "frames": frames,
        "scale": scale,
        "height": float(height),
        "y_min": float(y_min),
        "facing": 1 if facing >= 0 else -1,
        "tips": {"LeftHand": located["left_hand_tip"], "RightHand": located["right_hand_tip"]},
        "head_region": dict(head_region) if head_region else None,
        "base": None if base is None else float(base),
        "robe": dict(robe) if robe else None,
    }


def world_matrices(bones: list[dict], rotations: dict | None = None) -> list[np.ndarray]:
    """World matrix of every bone. ``rotations`` overrides local xyzw quaternions."""
    overrides = rotations or {}
    worlds: list[np.ndarray] = []
    by_name = {}
    for bone in bones:
        parent = np.eye(4) if bone["parent"] is None else by_name[bone["parent"]]
        rotation = overrides.get(bone["name"], bone["rotation"])
        world = parent @ _trs(bone["translation"], rotation, bone["scale"])
        by_name[bone["name"]] = world
        worlds.append(world)
    return worlds


def canonical_frames(world: dict, facing: int = 1) -> dict:
    """Canonical world frame of every bone for joint positions ``world``."""
    facing_quat = _IDENTITY.copy() if facing >= 0 else rot.axis_angle([0.0, 1.0, 0.0], 180.0)
    return _rest_frames(world, facing_quat)


def joint_positions(bones: list[dict]) -> dict:
    """World position of every joint at rest."""
    return {bone["name"]: matrix[:3, 3].copy() for bone, matrix in zip(bones, world_matrices(bones))}


def _bone(name: str, parent: str | None, world: dict, frames: dict, scale: float) -> dict:
    if parent is None:
        return {"name": name, "parent": None, "translation": world[name].copy(), "rotation": frames[name], "scale": np.full(3, scale)}
    to_parent = rot.inverse(frames[parent])  # world to the parent's frame
    return {
        "name": name,
        "parent": parent,
        "translation": rot.rotate(to_parent, world[name] - world[parent]) / scale,
        "rotation": rot.normalize(rot.multiply(to_parent, frames[name])),
        "scale": np.ones(3),
    }


def _rest_frames(world: dict, facing: np.ndarray) -> dict:
    frames = {name: facing.copy() for name in _UP_FRAMES}
    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        axis = np.array([sign, 0.0, 0.0])
        frames[f"{side}Arm"] = _aligned(facing, axis, world[f"{side}ForeArm"] - world[f"{side}Arm"])
        frames[f"{side}ForeArm"] = _aligned(facing, axis, world[f"{side}Hand"] - world[f"{side}ForeArm"])
        frames[f"{side}Hand"] = frames[f"{side}ForeArm"]
        thigh = rot.rotate(rot.inverse(facing), world[f"{side}Leg"] - world[f"{side}UpLeg"])
        straight = np.array([thigh[0], thigh[1], 0.0])
        frames[f"{side}UpLeg"] = _aligned(facing, straight, world[f"{side}Leg"] - world[f"{side}UpLeg"])
        frames[f"{side}Leg"] = _aligned(facing, straight, world[f"{side}Foot"] - world[f"{side}Leg"])
        for part in ("Foot", "ToeBase", "Toe_End"):
            frames[f"{side}{part}"] = frames[f"{side}Leg"]
    return frames


def _aligned(facing: np.ndarray, canonical: np.ndarray, measured: np.ndarray) -> np.ndarray:
    local = rot.rotate(rot.inverse(facing), measured)
    return rot.normalize(rot.multiply(facing, rot.align(canonical, local)))


def _world_positions(points: dict, height: float) -> dict[str, np.ndarray]:
    hips = (points["left_hip"] + points["right_hip"]) * 0.5 + np.array([0.0, height * 0.02, 0.0])
    hips[2] = points["crotch"][2]
    head = points["head"]
    neck = _neck(points, hips, head, height)
    located = {
        "Hips": hips,
        "Spine": _mix(hips, neck, 0.25),
        "Spine1": _mix(hips, neck, 0.5),
        "Spine2": _mix(hips, neck, 0.75),
        "Neck": neck,
        "Head": head.copy(),
        "HeadTop_End": points["crown"].copy(),
    }
    _limbs(located, points, neck)
    return located


def _neck(points: dict, hips: np.ndarray, head: np.ndarray, height: float) -> np.ndarray:
    shoulders = (points["left_shoulder"] + points["right_shoulder"]) * 0.5
    valley = points["neck"]
    y = float(shoulders[1]) + (float(valley[1]) - float(shoulders[1])) * 0.4
    y = min(y, float(head[1]) - height * 0.012)
    y = max(y, float(hips[1]) + (float(head[1]) - float(hips[1])) * 0.55)
    return np.array([float(valley[0]), y, (float(valley[2]) + float(shoulders[2])) * 0.5])


def _limbs(located: dict, points: dict, neck: np.ndarray) -> None:
    for side, prefix in (("left", "Left"), ("right", "Right")):
        joint = points[f"{side}_shoulder"]
        clavicle = _mix(neck, joint, 0.3)
        clavicle[1] = max(float(joint[1]), float(located["Spine2"][1])) + (float(neck[1]) - float(joint[1])) * 0.15
        located[f"{prefix}Shoulder"] = clavicle
        located[f"{prefix}Arm"] = joint.copy()
        located[f"{prefix}ForeArm"] = points[f"{side}_elbow"].copy()
        located[f"{prefix}Hand"] = points[f"{side}_wrist"].copy()
        located[f"{prefix}UpLeg"] = points[f"{side}_hip"].copy()
        located[f"{prefix}Leg"] = points[f"{side}_knee"].copy()
        located[f"{prefix}Foot"] = points[f"{side}_ankle"].copy()
        located[f"{prefix}ToeBase"] = points[f"{side}_ball"].copy()
        located[f"{prefix}Toe_End"] = points[f"{side}_toe"].copy()


def _mix(start: np.ndarray, end: np.ndarray, factor: float) -> np.ndarray:
    return start * (1.0 - factor) + end * factor


def _trs(translation: np.ndarray, rotation: np.ndarray, scale: np.ndarray) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, :3] = rot.to_matrix(rotation) @ np.diag(np.asarray(scale, dtype=np.float64))
    matrix[:3, 3] = np.asarray(translation, dtype=np.float64)
    return matrix
