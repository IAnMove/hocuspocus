"""How far this body can lower or raise its arms, and how far its chest sticks out.

A mascot with a round belly cannot drop its arms as far as a slim adult, and
its big head blocks arms raised overhead. Arms sweep in the front plane, so the
test runs on the front silhouette of everything but the arms. The chest depth
places hands in front of the body in clips such as the clap.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from services.humanoid_rig.names import BONE_BY_NAME
from services.humanoid_rig.silhouette import front_silhouette

_ARM_PARTS = ("Arm", "ForeArm", "Hand")
_DOWN = (80.0, 30.0)
_UP = (150.0, 30.0)
_SWING = (150.0, 50.0)
_RESOLUTION = 200


def comfort_limits(vertices: np.ndarray, indices: np.ndarray, joints: np.ndarray, weights: np.ndarray, skeleton: dict) -> dict:
    """Arm sweep limits in degrees from the T pose, and the chest depth in metres."""
    points = np.asarray(vertices, dtype=np.float64)
    dominant = joints[np.arange(len(joints)), np.argmax(weights, axis=1)]
    arms = np.isin(dominant, [BONE_BY_NAME[f"{side}{part}"] for side in ("Left", "Right") for part in _ARM_PARTS])
    faces = np.asarray(indices, dtype=np.int64)
    body_faces = faces[~arms[faces].any(axis=1)]
    found = {"arm_down": _DOWN[0], "arm_up": _UP[0], "swing_up": _SWING[0], "chest_front": _chest_front(points[~arms], skeleton)}
    if len(body_faces) < 4:
        return _rounded(found)
    silhouette = front_silhouette(points[body_faces], float(skeleton["height"]), _RESOLUTION)
    clearance = ndimage.distance_transform_edt(~silhouette.mask) * silhouette.pixel
    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        arm = _arm(points, dominant, skeleton, side)
        found["arm_down"] = min(found["arm_down"], _sweep(clearance, silhouette, arm, sign * float(skeleton.get("facing", 1)), -1.0, _DOWN))
        found["arm_up"] = min(found["arm_up"], _sweep(clearance, silhouette, arm, sign * float(skeleton.get("facing", 1)), 1.0, _UP))
        found["swing_up"] = min(found["swing_up"], _forward_swing(_head(points, dominant), arm, sign, found["arm_down"], skeleton))
    return _rounded(found)


def _head(points: np.ndarray, dominant: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Center and half extents of the head, as an ellipsoid."""
    head = points[dominant == BONE_BY_NAME["Head"]]
    if len(head) < 8:
        return None
    low, high = np.percentile(head, 1, axis=0), np.percentile(head, 99, axis=0)
    return (low + high) * 0.5, np.maximum((high - low) * 0.5, 1e-4)


def _forward_swing(head, arm: dict, sign: float, arm_down: float, skeleton: dict) -> float:
    """Largest forward swing of a lowered arm that stays out of the head."""
    if head is None:
        return _SWING[0]
    facing = float(skeleton.get("facing", 1))
    lift = math.radians(-(arm_down - 15.0))
    for degrees in np.arange(_SWING[0], _SWING[1] - 1e-6, -5.0):
        swing = math.radians(degrees)
        local = np.array([sign * math.cos(lift), math.sin(lift) * math.cos(swing), -math.sin(lift) * math.sin(swing)])
        heading = np.array([local[0] * facing, local[1], local[2] * facing])
        samples = arm["shoulder"] + np.outer(np.linspace(0.35, 1.0, 12) * arm["length"], heading)
        inside = np.sum(((samples - head[0]) / (head[1] + arm["radius"])) ** 2, axis=1) < 1.0
        if not np.any(inside):
            return float(degrees)
    return _SWING[1]


def _rounded(found: dict) -> dict:
    return {name: round(float(value), 4 if name == "chest_front" else 1) for name, value in found.items()}


def _chest_front(points: np.ndarray, skeleton: dict) -> float:
    chest = np.asarray(skeleton["world"]["Spine2"], dtype=np.float64)
    height = float(skeleton["height"])
    facing = float(skeleton.get("facing", 1))
    band = points[np.abs(points[:, 1] - chest[1]) < height * 0.04]
    band = band[np.abs(band[:, 0] - chest[0]) < height * 0.12]
    if len(band) < 4:
        return height * 0.1
    return max(float(np.percentile((band[:, 2] - chest[2]) * facing, 98)), height * 0.03)


def _arm(points: np.ndarray, dominant: np.ndarray, skeleton: dict, side: str) -> dict:
    world = skeleton["world"]
    shoulder = np.asarray(world[f"{side}Arm"], dtype=np.float64)
    elbow, wrist = np.asarray(world[f"{side}ForeArm"]), np.asarray(world[f"{side}Hand"])
    tip = np.asarray(skeleton["tips"][f"{side}Hand"], dtype=np.float64)
    length = float(np.linalg.norm(elbow - shoulder) + np.linalg.norm(wrist - elbow) + np.linalg.norm(tip - wrist))
    fore = points[dominant == BONE_BY_NAME[f"{side}ForeArm"]]
    radius = float(skeleton["height"]) * 0.025
    if len(fore):
        radius = float(np.median(_segment_distance(fore, elbow, wrist)))
    return {"shoulder": shoulder, "length": length, "radius": radius}


def _sweep(clearance: np.ndarray, silhouette, arm: dict, lateral: float, direction: float, span: tuple[float, float]) -> float:
    for degrees in np.arange(span[0], span[1] - 1e-6, -2.5):
        angle = math.radians(direction * degrees)
        heading = np.array([lateral * math.cos(angle), math.sin(angle)])
        if _clear(clearance, silhouette, arm, heading):
            return float(degrees)
    return float(span[1])


def _clear(clearance: np.ndarray, silhouette, arm: dict, heading: np.ndarray) -> bool:
    start = arm["shoulder"][:2]
    samples = start + np.outer(np.linspace(0.35, 1.0, 16) * arm["length"], heading)
    rows = np.array([silhouette.row_of(float(y)) for y in samples[:, 1]])
    cols = np.array([silhouette.col_of(float(x)) for x in samples[:, 0]])
    inside = (rows >= 0) & (rows < clearance.shape[0]) & (cols >= 0) & (cols < clearance.shape[1])
    gaps = np.full(len(samples), np.inf)
    gaps[inside] = clearance[rows[inside], cols[inside]]
    return bool(np.all(gaps >= arm["radius"] * 0.9))


def _segment_distance(points: np.ndarray, start: np.ndarray, end: np.ndarray) -> np.ndarray:
    segment = end - start
    factor = np.clip(((points - start) @ segment) / max(float(segment @ segment), 1e-12), 0.0, 1.0)
    return np.linalg.norm(points - (start + factor[:, None] * segment), axis=1)
