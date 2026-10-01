"""Capsule skin weights for the standard humanoid, at most four influences.

Arm vertices cannot weight a leg, and a vertex cannot weight the arm on the
other side of the torso. Split compose vertices are welded by position before
the adjacency smooth, then the side mask is applied again.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.names import (
    BONE_BY_NAME,
    BONE_NAMES,
    BONE_PARENTS,
    LEFT_ARM_BONES,
    LEFT_LEG_BONES,
    RIGHT_ARM_BONES,
    RIGHT_LEG_BONES,
)

_SMOOTH = 4
_INFLUENCES = 4


def compute_weights(vertices: np.ndarray, indices: np.ndarray | None, skeleton: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(joints, weights)`` with shapes (N, 4). Weights sum to 1."""
    points = np.asarray(vertices, dtype=np.float64)
    distances = _distances(points, skeleton["world"])
    allowed = _allowed(points, distances, skeleton)
    score = _masked_score(distances, allowed, skeleton["height"])
    joints, weights = _top_influences(score)
    joints, weights = _smooth(points, indices, joints, weights, allowed, distances, skeleton["height"])
    return joints, weights


def dominant_distance(vertices: np.ndarray, joints: np.ndarray, weights: np.ndarray, skeleton: dict) -> np.ndarray:
    """Distance from each vertex to the capsule of its strongest bone."""
    distances = _distances(np.asarray(vertices, dtype=np.float64), skeleton["world"])
    dominant = joints[np.arange(len(joints)), np.argmax(weights, axis=1)]
    return distances[np.arange(len(distances)), dominant]


def _distances(points: np.ndarray, world: dict) -> np.ndarray:
    """Each bone owns the segment that runs out to its chain child, not back to its parent."""
    columns = [_capsule(points, start, end) for start, end in _chain_segments(world)]
    return np.stack(columns, axis=1)


def _chain_segments(world: dict):
    child = {}
    for name, parent in BONE_PARENTS:
        if parent is not None and parent not in child:
            child[parent] = name
    segments = []
    for name in BONE_NAMES:
        start = world[name]
        segments.append((start, world[child[name]] if name in child else start))
    return segments


def _capsule(points: np.ndarray, start: np.ndarray, end: np.ndarray) -> np.ndarray:
    segment = end - start
    length_sq = float(segment @ segment)
    if length_sq < 1e-12:
        return np.linalg.norm(points - start, axis=1)
    factor = np.clip(((points - start) @ segment) / length_sq, 0.0, 1.0)
    closest = start + factor[:, None] * segment
    return np.linalg.norm(points - closest, axis=1)


def _allowed(points: np.ndarray, distances: np.ndarray, skeleton: dict) -> np.ndarray:
    height = skeleton["height"]
    allowed = np.ones(distances.shape, dtype=bool)
    center = float(skeleton["world"]["Hips"][0])
    side = points[:, 0] - center
    band = height * 0.02
    _forbid(allowed, side > band, RIGHT_ARM_BONES)
    _forbid(allowed, side < -band, LEFT_ARM_BONES)
    _forbid(allowed, np.abs(side) <= band, LEFT_ARM_BONES + RIGHT_ARM_BONES)
    _forbid(allowed, side > band, RIGHT_LEG_BONES)
    _forbid(allowed, side < -band, LEFT_LEG_BONES)
    _separate_limbs(allowed, distances, height)
    _keep_legs_below_hips(allowed, points, skeleton)
    _keep_arms_outside_chest(allowed, points, skeleton)
    return allowed


def _keep_legs_below_hips(allowed: np.ndarray, points: np.ndarray, skeleton: dict) -> None:
    """The pelvis sits above the hip joint. A knee bend must not carry it."""
    hip_y = float(skeleton["world"]["Hips"][1])
    above = points[:, 1] > hip_y + skeleton["height"] * 0.015
    _forbid(allowed, above, LEFT_LEG_BONES + RIGHT_LEG_BONES)


def _keep_arms_outside_chest(allowed: np.ndarray, points: np.ndarray, skeleton: dict) -> None:
    """Clavicles run across the chest. Only vertices outboard of the shoulder may use an arm."""
    center = float(skeleton["world"]["Hips"][0])
    reach = min(
        abs(float(skeleton["world"]["LeftArm"][0]) - center),
        abs(float(skeleton["world"]["RightArm"][0]) - center),
    )
    inside = np.abs(points[:, 0] - center) < reach * 0.82
    _forbid(allowed, inside, LEFT_ARM_BONES + RIGHT_ARM_BONES)


def _forbid(allowed: np.ndarray, mask: np.ndarray, names: tuple) -> None:
    if not np.any(mask):
        return
    columns = [BONE_BY_NAME[name] for name in names]
    allowed[np.ix_(mask, columns)] = False


def _separate_limbs(allowed: np.ndarray, distances: np.ndarray, height: float) -> None:
    arms = [BONE_BY_NAME[name] for name in LEFT_ARM_BONES + RIGHT_ARM_BONES]
    legs = [BONE_BY_NAME[name] for name in LEFT_LEG_BONES + RIGHT_LEG_BONES]
    arm_distance = distances[:, arms].min(axis=1)
    leg_distance = distances[:, legs].min(axis=1)
    margin = height * 0.01
    _forbid(allowed, arm_distance + margin < leg_distance, LEFT_LEG_BONES + RIGHT_LEG_BONES)
    _forbid(allowed, leg_distance + margin < arm_distance, LEFT_ARM_BONES + RIGHT_ARM_BONES)


def _masked_score(distances: np.ndarray, allowed: np.ndarray, height: float) -> np.ndarray:
    score = 1.0 / (distances * distances + (height * 0.02) ** 2)
    score = np.where(allowed, score, 0.0)
    empty = score.sum(axis=1) <= 0
    if np.any(empty):
        nearest = np.argmin(np.where(allowed, distances, 1e6), axis=1)
        score[empty, nearest[empty]] = 1.0
    return score


def _top_influences(score: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(-score, axis=1)[:, :_INFLUENCES]
    picked = np.take_along_axis(score, order, axis=1)
    total = picked.sum(axis=1, keepdims=True)
    total[total <= 0] = 1.0
    weights = np.zeros(score.shape[0:1] + (_INFLUENCES,), dtype=np.float64)
    weights[:] = picked / total
    return order.astype(np.uint16), weights


def _smooth(points, indices, joints, weights, allowed, distances, height):
    welded, inverse = _weld(points)
    table = np.zeros((len(welded), len(BONE_NAMES)))
    _scatter_mean(table, inverse, joints, weights)
    edges = _edges(inverse, indices, len(points))
    for _iteration in range(_SMOOTH):
        table = _average(table, edges)
    _apply_allowed(table, inverse, allowed)
    scores = _cut_far(table[inverse], distances, height)
    return _top_influences(np.maximum(scores, 0.0))


def _cut_far(scores: np.ndarray, distances: np.ndarray, height: float) -> np.ndarray:
    """Smoothing walks a whole box in four hops. Drop bones far from the nearest one."""
    nearest = np.min(np.where(scores > 0, distances, 1e6), axis=1)
    keep = distances <= (nearest + height * 0.08)[:, None]
    return np.where(keep, scores, 0.0)


def _weld(points: np.ndarray):
    rounded = np.round(points, 4)
    _unique, inverse = np.unique(rounded, axis=0, return_inverse=True)
    return _unique, inverse


def _scatter_mean(table, inverse, joints, weights) -> None:
    flat_joint = joints.reshape(-1)
    flat_weight = weights.reshape(-1)
    flat_inverse = np.repeat(inverse, _INFLUENCES)
    np.add.at(table, (flat_inverse, flat_joint), flat_weight)
    counts = np.bincount(inverse, minlength=len(table))
    counts[counts == 0] = 1
    table /= counts[:, None]


def _edges(inverse: np.ndarray, indices: np.ndarray | None, count: int) -> np.ndarray:
    welded = inverse[_faces(indices, count)]
    pairs = np.stack((welded[:, [0, 1]], welded[:, [1, 2]], welded[:, [2, 0]]), axis=1).reshape(-1, 2)
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    if len(pairs) == 0:
        return pairs
    return np.unique(np.concatenate((pairs, pairs[:, ::-1]), axis=0), axis=0)


def _faces(indices: np.ndarray | None, count: int) -> np.ndarray:
    if indices is None:
        return np.arange(count, dtype=np.int64).reshape(-1, 3)
    return np.asarray(indices, dtype=np.int64)


def _average(table: np.ndarray, edges: np.ndarray) -> np.ndarray:
    if len(edges) == 0:
        return table
    accumulated = np.zeros_like(table)
    np.add.at(accumulated, edges[:, 1], table[edges[:, 0]])
    degree = np.bincount(edges[:, 1], minlength=len(table)).astype(np.float64)
    touched = degree > 0
    updated = table.copy()
    updated[touched] = (table[touched] + accumulated[touched]) / (degree[touched, None] + 1.0)
    return updated


def _apply_allowed(table: np.ndarray, inverse: np.ndarray, allowed: np.ndarray) -> None:
    collapsed = np.ones((len(table), allowed.shape[1]), dtype=np.uint8)
    np.minimum.at(collapsed, inverse, allowed.astype(np.uint8))
    table *= collapsed.astype(bool)
