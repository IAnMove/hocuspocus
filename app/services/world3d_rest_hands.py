"""Where a seated character's wrists rest (``rest.hands``, on by default): on the table of ``rest.at``, else on the seat
beside the hips when it is wide (a bed, a bench, a sofa), else on the thighs. All in the character's own units, for
``sit_clip``'s ``hands``; ``None`` keeps the clip's own arms (``hands: false``, or nothing within reach).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

HAND_LIFT_M = 0.04           # a wrist rests this far over a table top or a seat, metres
TABLE_IN_M = 0.12            # ... this far in from the table's edge
BESIDE_HIPS_M = 0.13         # ... this far out from the hip joint, on a wide seat
SEAT_ROOM_M = 0.16           # a seat this much wider than the hips on each side holds the hands beside them
THIGH_TOP = 0.08             # leg lengths from the thigh's line up to where a hand rests on it
REACH = 0.97                 # arm lengths a wrist may be from its shoulder


@dataclass
class Sitter:
    joints: dict             # rest pose, model units
    shift: np.ndarray        # the hips' move from standing to seated, model units
    knees_z: float           # seated knees' forward coordinate (model z), the shins upright
    seat_y: float            # the seat's top, model y
    size: dict               # model units: thigh, leg, arm...
    facing: np.ndarray       # scene floor direction faced
    position: np.ndarray     # slot position (scene)
    turned: np.ndarray       # slot yaw as a matrix
    factor: float            # model units -> metres

    def to_model(self, points) -> np.ndarray:
        return ((np.asarray(points, dtype=np.float64) - self.position) @ self.turned) / self.factor

    def to_world(self, point) -> np.ndarray:
        return self.turned @ (np.asarray(point, dtype=np.float64) * self.factor) + self.position

    def shoulder(self, side: str) -> np.ndarray:
        return self.joints[f"{side}Arm"] + self.shift

    def reachable(self, side: str, wrist: np.ndarray) -> bool:
        return float(np.linalg.norm(wrist - self.shoulder(side))) <= REACH * self.size["arm"]


def resting_hands(rest: dict, sitter: Sitter, seat_rect: np.ndarray, table_corners: np.ndarray | None) -> list | None:
    """``[left wrist, right wrist]`` (model units) or None."""
    if rest.get("hands") is False:
        return None
    for place in (lambda: _on_table(sitter, table_corners), lambda: _beside_hips(sitter, seat_rect), lambda: _on_thighs(sitter)):
        found = place()
        if found is not None:
            return found
    return None


def _on_table(sitter: Sitter, corners: np.ndarray | None) -> list | None:
    if corners is None:
        return None
    wrists = []
    for side in ("Left", "Right"):
        shoulder = sitter.to_world(sitter.shoulder(side))
        edge = edge_distance(corners, shoulder, sitter.facing)
        if edge is None:
            return None
        goal = shoulder.copy()
        goal[[0, 2]] += sitter.facing * (edge + TABLE_IN_M)
        goal[1] = corners[:, 1].mean() + HAND_LIFT_M
        wrist = sitter.to_model([goal])[0]
        if not sitter.reachable(side, wrist):
            return None
        wrists.append(wrist.tolist())
    return wrists


def _beside_hips(sitter: Sitter, seat_rect: np.ndarray) -> list | None:
    """On the seat itself, either side of the hips, when it is wide enough there (model x is the sitter's left)."""
    rect = sitter.to_model(seat_rect)
    hips = sitter.joints["Hips"] + sitter.shift
    wrists = []
    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        out = abs(float(sitter.joints[f"{side}UpLeg"][0] - sitter.joints["Hips"][0])) + SEAT_ROOM_M / sitter.factor
        room = (rect[:, 0].max() - hips[0]) if sign > 0 else (hips[0] - rect[:, 0].min())
        if room < out:
            return None
        wrist = np.array([hips[0] + sign * (out - SEAT_ROOM_M / sitter.factor + BESIDE_HIPS_M / sitter.factor),
                          sitter.seat_y + HAND_LIFT_M / sitter.factor, hips[2] + 0.04 / sitter.factor])
        if not sitter.reachable(side, wrist):
            return None
        wrists.append(wrist.tolist())
    return wrists


def _on_thighs(sitter: Sitter) -> list | None:
    """On the top of each thigh, nearer the knee than the hip."""
    wrists = []
    for side in ("Left", "Right"):
        hip = sitter.joints[f"{side}UpLeg"] + sitter.shift
        knee = np.array([sitter.joints[f"{side}Leg"][0], sitter.joints[f"{side}Leg"][1], sitter.knees_z])
        wrist = hip * 0.4 + knee * 0.6 + np.array([0.0, THIGH_TOP * sitter.size["leg"], 0.0])
        if not sitter.reachable(side, wrist):
            return None
        wrists.append(wrist.tolist())
    return wrists


def edge_distance(corners: np.ndarray, origin: np.ndarray, facing: np.ndarray) -> float | None:
    """How far along ``facing`` the ray from ``origin`` enters the table top (a convex quad on the floor plane), or None."""
    flat = corners[:, [0, 2]]
    start = origin[[0, 2]]
    entry, leave = 0.0, 3.0
    for index in range(4):
        a, b = flat[index], flat[(index + 1) % 4]
        normal = np.array([b[1] - a[1], a[0] - b[0]])
        if normal @ (flat.mean(axis=0) - a) > 0:
            normal = -normal                                          # outward
        denominator, distance = normal @ facing, normal @ (start - a)
        if abs(denominator) < 1e-9:
            if distance > 0:
                return None
            continue
        t = -distance / denominator
        if denominator < 0:
            entry = max(entry, t)
        else:
            leave = min(leave, t)
    return entry if entry <= leave else None
