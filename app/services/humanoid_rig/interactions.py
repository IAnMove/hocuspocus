"""Clips that meet things in the scene: sit on a seat, reach a point, look at something.

Targets are points in the model's own space (the GLB's metres), so a client
turns a seat's top or a prop's handle into these coordinates once and bakes.
The feet stay planted where the character stands; the legs and arms reach their
goals with the same IK as every clip.
"""
from __future__ import annotations

import math

import numpy as np

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.contacts import foot_contacts
from services.humanoid_rig.errors import InvalidInput
from services.humanoid_rig.motion import Pose, Rig, bake_with_frames
from services.humanoid_rig.names import BONE_NAMES

FPS = 30
_HIP_ABOVE_SEAT = 0.16          # leg lengths from the seat surface up to the hips joint when seated
_SEAT_RANGE = (0.3, 0.9)        # seat heights a character sits on naturally, in leg lengths above the floor
_HEAD_YAW, _HEAD_PITCH = 70.0, (-35.0, 45.0)
_UNREACHABLE_LEAN = 0.5         # how far the body bends toward a target it cannot reach


def sit_clip(rig: Rig, seat, duration: float = 3.0, stand_up: bool = False, look=None, name: str = "Sit") -> dict:
    """Lower the hips onto ``seat`` (the middle of the seat's top surface) and stay; optionally stand again."""
    point = _point(seat, "seat")
    times, seconds = _times(duration)
    warnings: list[str] = []
    height = (point[1] - rig.floor) / rig.leg
    if not _SEAT_RANGE[0] <= height <= _SEAT_RANGE[1]:
        warnings.append("seat_height_unusual: the seat is too low or too high for a natural sit")
    seated = _seat_amount(times, seconds, stand_up)
    descending = _descent(times, seconds, stand_up)
    target = point + np.array([0.0, _HIP_ABOVE_SEAT * rig.leg, 0.0])
    shift = _in_facing(rig, target - rig.root) / rig.leg
    pose = Pose(rig, times / seconds)
    pose.grounded = False
    pose.move_root(side=shift[0] * seated, up=shift[1] * seated, forward=shift[2] * seated)
    pose.spine(pitch=8.0 * seated + 26.0 * descending)
    pose.head(pitch=-4.0 * seated - 10.0 * descending)
    for side in ("Left", "Right"):
        pose.plant(side, out=0.02 * seated)
        pose.arm(side, lift=-rig.limits["arm_down"] + 10.0 * descending, swing=6.0 + 30.0 * seated + 20.0 * descending)
        pose.elbow(side, 14.0 + 40.0 * seated)
    if _knee_overreach(rig, target):
        warnings.append("seat_out_of_reach: the seat is too far from the feet; they leave the floor")
    _aim_head(pose, rig, look, times, seconds)
    return _clip(pose, rig, times, seconds, name, warnings)


def reach_clip(rig: Rig, target, hand: str = "auto", duration: float = 2.0, hold: bool = True, look=True,
               name: str = "Reach") -> dict:
    """Bring one wrist to ``target`` and hold it there (or return at the end).

    The chest turns and bends toward the target only as much as the arm needs: the smallest lean
    that reaches is found by bisection, so a near target keeps the body upright.
    """
    point = _point(target, "target")
    times, seconds = _times(duration)
    side = _hand_side(hand, _in_facing(rig, point - rig.root))
    progress = _reach_amount(times, seconds, hold)
    peak = len(times) - 1 if hold else int(np.argmax(progress))

    def attempt(lean: float):
        pose = _reach_pose(rig, side, point, times, progress, lean)
        if look:
            _aim_head(pose, rig, point, times, seconds)
        clip, positions = _baked(pose, rig, times, seconds, name, [])
        return clip, float(np.linalg.norm(positions[peak, rig.index(f"{side}Hand")] - point))

    clip, error = attempt(0.0)
    tolerance = 0.01 * rig.arm
    if error > tolerance:
        full, full_error = attempt(1.0)
        if full_error <= tolerance:
            low, high, clip, error = 0.0, 1.0, full, full_error
            for _step in range(7):
                middle = (low + high) / 2.0
                trial, trial_error = attempt(middle)
                if trial_error <= tolerance:
                    high, clip, error = middle, trial, trial_error
                else:
                    low = middle
        else:
            # Out of reach even fully bent: a moderate lean reads as reaching, not as falling over.
            clip, error = attempt(_UNREACHABLE_LEAN)
            clip["warnings"].append("target_out_of_reach: the hand stops short of the target")
    clip["hand"] = side.lower()
    return clip


def _reach_pose(rig: Rig, side: str, point: np.ndarray, times: np.ndarray, progress: np.ndarray, lean: float) -> Pose:
    """Feet planted, the chest turned and bent by ``lean`` (0..1) toward the target, the wrist on its way to it."""
    pose = Pose(rig, times / times[-1])
    for each in ("Left", "Right"):
        pose.plant(each)
    shoulder = rig.rest_positions[rig.index(f"{side}Arm")]
    yaw, _pitch = _aim_angles(rig, rig.rest_positions[rig.index("Spine2")], point)
    _yaw, below = _aim_angles(rig, shoulder, point)
    bend = lean * progress
    # Turn the reaching shoulder toward the target: it sits 90 degrees to its side of the chest.
    twist = float(np.clip(yaw - 90.0 * (1.0 if side == "Left" else -1.0), -35.0, 35.0))
    # Bend as much as the target lies below the shoulder; a target ahead at shoulder height needs a slight lean.
    total = float(np.clip(15.0 + 0.9 * below, 10.0, 75.0))
    pose.spine(yaw=twist * bend, pitch=0.6 * total * bend)
    pose.hips(pitch=0.4 * total * bend)
    # Low targets also lower the body, as a person crouches to pick something up.
    low = float(np.clip((rig.root[1] - point[1]) / rig.leg, 0.0, 1.0))
    pose.move_root(up=-0.35 * low * bend, forward=-0.06 * bend)
    rest_wrist = _relaxed_wrist(rig, side, len(times))
    pose.reach_world(side, rest_wrist + (point - rest_wrist) * progress[:, None], pole=(0.3, -1.0, -0.5))
    return pose


def look_clip(rig: Rig, target, duration: float = 2.0, name: str = "Look") -> dict:
    """Turn the head and neck toward ``target`` and hold, within what a neck allows."""
    point = _point(target, "target")
    times, seconds = _times(duration)
    pose = Pose(rig, times / seconds)
    for side in ("Left", "Right"):
        pose.plant(side)
    _aim_head(pose, rig, point, times, seconds)
    return _clip(pose, rig, times, seconds, name, [])


def _point(value, label: str) -> np.ndarray:
    try:
        point = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise InvalidInput(f"{label} must be [x, y, z]") from exc
    if point.shape != (3,) or not np.all(np.isfinite(point)):
        raise InvalidInput(f"{label} must be [x, y, z]")
    return point


def _times(duration) -> tuple[np.ndarray, float]:
    seconds = float(duration)
    if not math.isfinite(seconds) or not 0.8 <= seconds <= 30.0:
        raise InvalidInput("interaction duration must be between 0.8 and 30 seconds")
    count = max(2, int(math.ceil(seconds * FPS))) + 1
    return np.linspace(0.0, seconds, count), seconds


def _in_facing(rig: Rig, vector: np.ndarray) -> np.ndarray:
    """A model-space vector in the character's frame: x left, y up, z forward."""
    return rot.rotate(rot.inverse(rig.facing), np.asarray(vector, dtype=np.float64))


def _window(times: np.ndarray, start: float, end: float) -> np.ndarray:
    s = np.clip((times - start) / max(end - start, 1e-9), 0.0, 1.0)
    return s * s * (3.0 - 2.0 * s)


def _seat_amount(times: np.ndarray, seconds: float, stand_up: bool) -> np.ndarray:
    down = min(1.2, seconds * 0.4)
    amount = _window(times, 0.2, 0.2 + down)
    if stand_up:
        amount = amount * (1.0 - _window(times, seconds - 0.2 - down, seconds - 0.2))
    return amount


def _descent(times: np.ndarray, seconds: float, stand_up: bool) -> np.ndarray:
    """The forward lean of sitting down and standing up: 0 standing or seated, 1 half way."""
    down = min(1.2, seconds * 0.4)
    lean = np.sin(np.pi * np.clip((times - 0.2) / down, 0.0, 1.0))
    if stand_up:
        lean = np.maximum(lean, np.sin(np.pi * np.clip((times - (seconds - 0.2 - down)) / down, 0.0, 1.0)))
    return lean


def _reach_amount(times: np.ndarray, seconds: float, hold: bool) -> np.ndarray:
    amount = _window(times, 0.15 * seconds, 0.55 * seconds)
    if not hold:
        amount = amount * (1.0 - _window(times, 0.7 * seconds, 0.95 * seconds))
    return amount


def _hand_side(hand: str, local_target: np.ndarray) -> str:
    if hand in ("left", "right"):
        return hand.capitalize()
    if hand != "auto":
        raise InvalidInput("hand must be left, right or auto")
    return "Left" if local_target[0] >= 0.0 else "Right"


def _aim_angles(rig: Rig, origin: np.ndarray, point: np.ndarray) -> tuple[float, float]:
    """Yaw (> 0 left) and pitch (> 0 down) in degrees from ``origin`` to ``point`` in the character's frame."""
    delta = _in_facing(rig, point - origin)
    yaw = math.degrees(math.atan2(delta[0], delta[2]))
    pitch = math.degrees(math.atan2(-delta[1], math.hypot(delta[0], delta[2])))
    return yaw, pitch


def _aim_head(pose: Pose, rig: Rig, target, times: np.ndarray, seconds: float) -> None:
    if target is None:
        return
    yaw, pitch = _aim_angles(rig, rig.rest_positions[rig.index("Head")], _point(target, "look target"))
    turn = _window(times, 0.1 * seconds, 0.45 * seconds)
    pose.head(yaw=float(np.clip(yaw, -_HEAD_YAW, _HEAD_YAW)) * turn, pitch=float(np.clip(pitch, *_HEAD_PITCH)) * turn)


def _relaxed_wrist(rig: Rig, side: str, count: int) -> np.ndarray:
    """Where the wrist hangs in the default stance, so the reach starts from the arm at rest."""
    relaxed = Pose(rig, np.zeros(1))
    for each in ("Left", "Right"):
        relaxed.plant(each)
    _local, _root, positions, _worlds = bake_with_frames(relaxed)
    return np.broadcast_to(positions[0, rig.index(f"{side}Hand")], (count, 3)).copy()


def _knee_overreach(rig: Rig, hips: np.ndarray) -> bool:
    """True when the seated hips are farther from an ankle than the leg can stretch."""
    for side in ("Left", "Right"):
        ankle = rig.rest_positions[rig.index(f"{side}Foot")]
        if float(np.linalg.norm(hips + _hip_offset(rig, side) - ankle)) > 0.98 * rig.leg:
            return True
    return False


def _hip_offset(rig: Rig, side: str) -> np.ndarray:
    return rig.rest_positions[rig.index(f"{side}UpLeg")] - rig.root


def _clip(pose: Pose, rig: Rig, times: np.ndarray, seconds: float, name: str, warnings: list[str]) -> dict:
    return _baked(pose, rig, times, seconds, name, warnings)[0]


def _baked(pose: Pose, rig: Rig, times: np.ndarray, seconds: float, name: str, warnings: list[str]) -> tuple[dict, np.ndarray]:
    """The clip and the canonical joint positions of every frame."""
    local, root, positions, worlds = bake_with_frames(pose)
    return {
        "id": name.lower().replace(" ", "_"),
        "name": name,
        "duration": seconds,
        "times": times,
        "rotations": {bone: local[:, index] for index, bone in enumerate(BONE_NAMES) if not bone.endswith("_End")},
        "hips_translation": root,
        "contacts": foot_contacts(rig, times, positions, worlds, loop=False),
        "warnings": warnings,
    }, positions


__all__ = ["look_clip", "reach_clip", "sit_clip"]
