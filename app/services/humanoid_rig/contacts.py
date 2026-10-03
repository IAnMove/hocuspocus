"""When each foot lands in a clip, so footsteps can follow the animation.

A foot is down when the lowest of its contact points (heel or toe tip, see
``Rig.contacts``) is within ``LANDED`` leg lengths of the floor, and in the air
once it rises above ``SWING``. A contact is the first frame a foot is down after
being in the air, so a foot that stays planted (idle, wave) never lands.
Heights are measured against the floor, not the hips, so in-place walks, where
the planted foot slides back under the body, count like real steps.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.motion import Rig
from services.humanoid_rig.names import BONE_NAMES

SWING = 0.035
LANDED = 0.012
# Downward speed, in leg lengths per second, that counts as a full-strength landing.
FULL_STRENGTH_SPEED = 2.0


def foot_heights(rig: Rig, positions: np.ndarray, worlds: np.ndarray) -> dict[str, np.ndarray]:
    """Per side, the height of its lowest contact point above the floor, in leg lengths."""
    heights: dict[str, np.ndarray] = {}
    for bone, offset in rig.contacts:
        side = "left" if BONE_NAMES[bone].startswith("Left") else "right"
        points = positions[:, bone] + rot.rotate(worlds[:, bone], np.broadcast_to(offset, positions[:, bone].shape))
        height = (points[:, 1] - rig.floor) / rig.leg
        heights[side] = height if side not in heights else np.minimum(heights[side], height)
    return heights


def foot_contacts(rig: Rig, times, positions: np.ndarray, worlds: np.ndarray, loop: bool) -> list[dict]:
    """``[{t, foot, strength}]`` sorted by time. ``loop`` clips repeat their first frame at the end."""
    times = np.asarray(times, dtype=np.float64)
    found = []
    for side, height in foot_heights(rig, positions, worlds).items():
        count = len(height) - 1 if loop and len(height) > 2 else len(height)
        for index in _landings(height[:count], loop):
            found.append({"t": round(float(times[index] - times[0]), 4), "foot": side,
                          "strength": _strength(height, times, index)})
    return sorted(found, key=lambda item: (item["t"], item["foot"]))


def _landings(height: np.ndarray, loop: bool) -> list[int]:
    """Frames where a foot comes down after a swing. A loop is scanned from its highest frame, once around."""
    if not len(height) or float(height.max()) < SWING:
        return []
    count = len(height)
    start = int(np.argmax(height)) if loop else 0
    airborne = bool(height[start] >= SWING)
    found = []
    for step in range(1, count + 1 if loop else count):
        index = (start + step) % count
        if airborne and height[index] <= LANDED:
            found.append(index)
            airborne = False
        elif not airborne and height[index] >= SWING:
            airborne = True
    return sorted(found)


def _strength(height: np.ndarray, times: np.ndarray, index: int) -> float:
    """Downward speed over the two frames before landing, scaled to 0..1."""
    before = max(0, index - 2)
    if before == index:
        return 0.5
    speed = (float(height[before]) - float(height[index])) / max(float(times[index] - times[before]), 1e-6)
    return round(float(np.clip(speed / FULL_STRENGTH_SPEED, 0.05, 1.0)), 3)
