"""Landmarks of a T or A pose humanoid, from its front silhouette and depth.

The silhouette finds the legs (the gap up to the crotch), the neck (the
narrowest row under the head) and the arms (thin branches off the torso).
Mesh cross-sections then give each joint its depth. A mesh that is not an
upright biped with its arms clear of the body raises ``NotHumanoid``.
Thresholds are fractions of the mesh height, so proportions do not matter.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.body_parts import (
    arm_drop,
    arm_line,
    connect_pieces,
    find_arms,
    find_legs,
    find_neck,
    leg_center,
    leg_regions,
    require_arm_angle,
    torso_half,
)
from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.landmark_depth import Depth
from services.humanoid_rig.names import LANDMARK_NAMES
from services.humanoid_rig.silhouette import front_silhouette

_ASYMMETRY = 0.25
_SIDES = (("left", 1.0), ("right", -1.0))


def detect_landmarks(positions: np.ndarray, indices: np.ndarray | None = None) -> dict:
    """Return the construction landmarks for a humanoid mesh.

    ``positions`` is (N, 3) in metres, Y up. ``indices`` is (M, 3); without
    indices, every three positions are a triangle. A body facing -Z is turned
    for the analysis and the landmarks are turned back.
    """
    triangles = _triangles(positions, indices)
    y_min = float(triangles[:, :, 1].min())
    height = float(triangles[:, :, 1].max()) - y_min
    _require_height(height)
    _require_upright(triangles, height)
    vertices = np.unique(np.round(triangles.reshape(-1, 3), 5), axis=0)
    facing, pivot = _facing(vertices, y_min, height)
    if facing < 0:
        triangles, vertices = _turn(triangles, pivot), _turn(vertices, pivot)
    found = _analyse(triangles, vertices, y_min, height)
    if facing < 0:
        found["points"] = {name: _turn(np.asarray(point), pivot) for name, point in found["points"].items()}
        found["head"]["x"] = 2.0 * float(pivot[0]) - found["head"]["x"]
        found["warnings"].append("facing_back")
    return _payload(found, height, y_min, facing)


def _analyse(triangles: np.ndarray, vertices: np.ndarray, y_min: float, height: float) -> dict:
    silhouette = connect_pieces(front_silhouette(triangles, height))
    mask = silhouette.mask
    legs = find_legs(mask)
    neck = find_neck(mask, legs)
    half = torso_half(neck["widths"], legs, neck)
    arms = find_arms(mask, legs, neck, half)
    tall = legs["top"] - legs["floor"] + 1
    lines = {side: arm_line(mask, arms[side], tall) for side, _sign in _SIDES}
    drops = {side: arm_drop(lines[side], sign) for side, sign in _SIDES}
    for drop in drops.values():
        require_arm_angle(drop)
    base = _base_top(legs, mask, silhouette, tall)
    depth = Depth(vertices, silhouette, height, y_min, base)
    points = _assemble(depth, legs, neck, half, lines, leg_regions(mask, legs))
    _require_symmetry(points, height)
    _require_facing_front(points, height)
    head = {"y": float(points["neck"][1]), "x": float(points["neck"][0]), "half": neck["head_width"] * 0.5 * silhouette.pixel}
    warnings = _warnings(neck, drops, points, height) + ([] if base is None else ["on_a_base"])
    return {"points": points, "warnings": warnings, "arm_drop": float(np.mean(list(drops.values()))), "head": head, "base": base}


def _base_top(legs: dict, mask: np.ndarray, silhouette, tall: int) -> float | None:
    """The top of a pedestal: the feet separate well above the lowest point, over something wider than them."""
    if legs["feet_row"] - legs["floor"] <= tall * 0.03:
        return None
    if _row_span(mask[legs["floor"] + 1]) <= _row_span(mask[legs["feet_row"]]) * 1.25:
        return None
    return silhouette.origin[1] + legs["feet_row"] * silhouette.pixel


def _row_span(row: np.ndarray) -> int:
    filled = np.flatnonzero(row)
    return int(filled[-1] - filled[0] + 1) if len(filled) else 0


def _require_facing_front(points: dict, height: float) -> None:
    """A body turned away from the camera puts one shoulder and one hand far behind the other."""
    hands = abs(float(points["left_wrist"][2]) - float(points["right_wrist"][2]))
    shoulders = abs(float(points["left_shoulder"][2]) - float(points["right_shoulder"][2]))
    if hands > height * 0.12 or shoulders > height * 0.06:
        raise NotHumanoid("turned")


def _assemble(depth: Depth, legs: dict, neck: dict, half: float, lines: dict, regions: dict) -> dict:
    points = depth.spine(legs, neck, half)
    for side, _sign in _SIDES:
        points.update(depth.leg(side, regions[side], legs, points["crotch"], leg_center))
        points.update(depth.arm(side, lines[side]))
    _require_finite(points)
    return points


def _warnings(neck: dict, drops: dict, points: dict, height: float) -> list[str]:
    warnings = []
    if not neck["found"]:
        warnings.append("neck_not_found")
    if max(drops.values()) > 55.0:
        warnings.append("arms_steep")
    if float(points["crotch"][1] - points["left_ankle"][1]) < height * 0.2:
        warnings.append("short_legs")
    reach = np.linalg.norm(points["left_hand_tip"] - points["left_shoulder"])
    if float(reach) < height * 0.22:
        warnings.append("short_arms")
    return warnings


def _payload(found: dict, height: float, y_min: float, facing: float) -> dict:
    ordered = {name: [float(v) for v in found["points"][name]] for name in LANDMARK_NAMES}
    floor = y_min if found["base"] is None else float(found["base"])
    warnings = list(dict.fromkeys(found["warnings"]))
    drop = float(found["arm_drop"])
    return {
        "points": ordered,
        "height": float(height),
        "y_min": float(floor),
        "base": found["base"],
        "facing": int(facing),
        "arm_drop": round(drop, 2),
        "pose": "t" if drop < 20.0 else "a",
        "confidence": round(max(0.3, 1.0 - 0.15 * len([item for item in warnings if item not in ("facing_back", "on_a_base")])), 2),
        "warnings": warnings,
        "head_region": dict(found["head"]),
    }


def _require_height(height: float) -> None:
    if height < 1e-4:
        raise NotHumanoid("degenerate")


def _require_upright(triangles: np.ndarray, height: float) -> None:
    extent = triangles.reshape(-1, 3).max(axis=0) - triangles.reshape(-1, 3).min(axis=0)
    if float(extent[2]) > height * 1.0 or float(extent[0]) > height * 2.4:
        raise NotHumanoid("not_upright")


def _require_finite(points: dict) -> None:
    for point in points.values():
        if not np.all(np.isfinite(point)):
            raise NotHumanoid("degenerate")


def _facing(vertices: np.ndarray, y_min: float, height: float) -> tuple[float, np.ndarray]:
    """-1 when the feet clearly point to -Z. Turned bodies keep their place."""
    low = vertices[:, [0, 2]].min(axis=0)
    high = vertices[:, [0, 2]].max(axis=0)
    pivot = (low + high) * 0.5
    shins = vertices[(vertices[:, 1] > y_min + height * 0.08) & (vertices[:, 1] < y_min + height * 0.16)]
    feet = vertices[vertices[:, 1] < y_min + height * 0.035]
    if len(shins) < 8 or len(feet) < 8:
        return 1.0, pivot
    middle = float(np.median(shins[:, 2]))
    forward = float(np.percentile(feet[:, 2], 98)) - middle
    backward = middle - float(np.percentile(feet[:, 2], 2))
    if backward > forward * 1.35 and backward - forward > height * 0.02:
        return -1.0, pivot
    return 1.0, pivot


def _turn(points: np.ndarray, pivot: np.ndarray) -> np.ndarray:
    turned = np.array(points, dtype=np.float64, copy=True)
    turned[..., 0] = 2.0 * pivot[0] - turned[..., 0]
    turned[..., 2] = 2.0 * pivot[1] - turned[..., 2]
    return turned


def _triangles(positions: np.ndarray, indices: np.ndarray | None) -> np.ndarray:
    cloud = np.asarray(positions, dtype=np.float64)
    if cloud.ndim != 2 or cloud.shape[1] != 3 or len(cloud) < 9 or not np.all(np.isfinite(cloud)):
        raise NotHumanoid("degenerate")
    if indices is None:
        if len(cloud) % 3:
            raise NotHumanoid("degenerate")
        faces = cloud.reshape(-1, 3, 3)
    else:
        index = np.asarray(indices, dtype=np.int64)
        if index.ndim != 2 or index.shape[1] != 3 or not index.size or int(index.min()) < 0 or int(index.max()) >= len(cloud):
            raise NotHumanoid("degenerate")
        faces = cloud[index]
    if len(faces) < 4:
        raise NotHumanoid("degenerate")
    return faces


def _require_symmetry(points: dict, height: float) -> None:
    limit = height * _ASYMMETRY
    center = float(points["crotch"][0])
    for name in ("hip", "knee", "ankle", "shoulder", "elbow", "wrist"):
        left, right = points[f"left_{name}"], points[f"right_{name}"]
        if left[0] <= center or right[0] >= center:
            raise NotHumanoid("asymmetry")
        if abs((float(left[0]) - center) - (center - float(right[0]))) > limit or abs(float(left[1]) - float(right[1])) > limit:
            raise NotHumanoid("asymmetry")
