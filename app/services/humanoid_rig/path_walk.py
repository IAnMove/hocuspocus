"""A walk along a path with the feet planted in the world.

The in-place walk moves the feet under a still body; Video 3D used to slide the
model along the path, so the soles skated. Here the hips follow the path and each
foot lands on a footprint that stays put until the foot lifts again. The legs
reach their footprints with the same two-bone IK as every clip.

Points are the ground under the hips, in the model's own space (the GLB's
metres): the first point is where the walk starts. Steps get longer and quicker
with speed, within what a walk allows; the walk starts and ends standing.
"""
from __future__ import annotations

import math

import numpy as np

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.clip_recipes import TAU, keys
from services.humanoid_rig.contacts import foot_contacts
from services.humanoid_rig.errors import InvalidInput
from services.humanoid_rig.motion import Pose, Rig, bake_with_frames
from services.humanoid_rig.names import BONE_NAMES

FPS = 30
MAX_POINTS = 64
MAX_DURATION = 120.0
_STEP_MIN, _STEP_MAX = 0.35, 0.85          # leg lengths between opposite footprints
_SWING_SHARE, _SWING_MAX = 0.8, 0.55       # share of the time between landings; seconds
_LIFT = 0.075                              # swing apex, leg lengths
_HEEL_RISE = 0.15                          # seconds the heel rises before a foot lifts
_FAST_WALK = 2.6                           # legs per second; faster reads as a run


def path_clip(rig: Rig, points, duration: float, name: str = "Path Walk") -> dict:
    """Bake one clip that walks through ``points`` (``(N, 2)`` x/z metres) in ``duration`` seconds."""
    route = _Route(rig, _points(points))
    seconds = _duration(duration)
    count = max(2, int(math.ceil(seconds * FPS))) + 1
    times = np.linspace(0.0, seconds, count)
    travel = route.length * _eased_progress(times, seconds)
    steps = _Steps(route, travel, times)
    pose = Pose(rig, times / seconds)
    pose.grounded = True
    _place_body(pose, route, travel, steps)
    _place_feet(pose, route, steps)
    _swing_arms(pose, steps)
    local, root, positions, worlds = bake_with_frames(pose)
    return {
        "id": "path_walk",
        "name": name,
        "duration": seconds,
        "times": times,
        "rotations": {bone: local[:, index] for index, bone in enumerate(BONE_NAMES) if not bone.endswith("_End")},
        "hips_translation": root,
        "contacts": foot_contacts(rig, times, positions, worlds, loop=False),
        "warnings": steps.warnings,
    }


def _points(points) -> np.ndarray:
    try:
        array = np.asarray(points, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise InvalidInput("path points must be [x, z] pairs") from exc
    if array.ndim != 2 or array.shape[1] != 2 or not 2 <= len(array) <= MAX_POINTS or not np.all(np.isfinite(array)):
        raise InvalidInput(f"a path needs 2 to {MAX_POINTS} finite [x, z] points")
    keep = np.concatenate(([True], np.linalg.norm(np.diff(array, axis=0), axis=1) > 1e-6))
    if keep.sum() < 2:
        raise InvalidInput("the path points are all the same place")
    return array[keep]


def _duration(value) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or not 0.5 <= seconds <= MAX_DURATION:
        raise InvalidInput(f"path duration must be between 0.5 and {MAX_DURATION:g} seconds")
    return seconds


def _eased_progress(times: np.ndarray, duration: float) -> np.ndarray:
    """0..1 travelled: speed ramps up over the first and down over the last ``ramp`` seconds."""
    ramp = min(0.6, duration / 4.0)
    cruise = duration - 2.0 * ramp
    t = np.clip(times, 0.0, duration)
    late = np.maximum(t - (duration - ramp), 0.0)
    distance = np.where(t <= ramp, t * t / (2.0 * ramp), ramp / 2.0 + (t - ramp))
    distance = np.where(late > 0.0, ramp / 2.0 + cruise + late - late * late / (2.0 * ramp), distance)
    return np.clip(distance / (cruise + ramp), 0.0, 1.0)


class _Route:
    """The path in the character's facing frame and in leg lengths (x = left, z = forward)."""

    def __init__(self, rig: Rig, points: np.ndarray) -> None:
        self.rig = rig
        hips = rig.root
        flat = np.column_stack((points[:, 0] - hips[0], np.zeros(len(points)), points[:, 1] - hips[2]))
        local = rot.rotate(np.broadcast_to(rot.inverse(rig.facing), (len(points), 4)), flat) / rig.leg
        dense = _catmull_rom(local[:, [0, 2]], 24)
        segments = np.linalg.norm(np.diff(dense, axis=0), axis=1)
        self.samples = dense
        self.arc = np.concatenate(([0.0], np.cumsum(segments)))
        self.length = float(self.arc[-1])
        ankle = rig.rest_positions[rig.index("LeftFoot")] - hips
        self.half_width = abs(float(rot.rotate(rot.inverse(rig.facing), ankle)[0])) / rig.leg

    def at(self, distance: np.ndarray) -> np.ndarray:
        d = np.clip(distance, 0.0, self.length)
        return np.column_stack([np.interp(d, self.arc, self.samples[:, axis]) for axis in (0, 1)])

    def heading(self, distance: np.ndarray) -> np.ndarray:
        """Degrees about up, > 0 toward the left, continuous along the path."""
        eps = max(1e-4, self.length * 1e-3)
        d = np.clip(distance, 0.0, self.length)
        ahead, behind = self.at(np.minimum(d + eps, self.length)), self.at(np.maximum(d - eps, 0.0))
        delta = ahead - behind
        return np.degrees(np.unwrap(np.arctan2(delta[:, 0], delta[:, 1])))

    def left(self, distance: np.ndarray) -> np.ndarray:
        angle = np.radians(self.heading(distance))
        return np.column_stack((np.cos(angle), -np.sin(angle)))


def _catmull_rom(points: np.ndarray, per_segment: int) -> np.ndarray:
    """Centripetal Catmull-Rom through every point; two points give a straight line."""
    if len(points) == 2:
        return np.linspace(points[0], points[1], per_segment + 1)
    padded = np.vstack((2 * points[0] - points[1], points, 2 * points[-1] - points[-2]))
    out = [points[:1]]
    for i in range(1, len(padded) - 2):
        p0, p1, p2, p3 = padded[i - 1:i + 3]
        t0 = 0.0
        t1 = t0 + max(np.linalg.norm(p1 - p0) ** 0.5, 1e-6)
        t2 = t1 + max(np.linalg.norm(p2 - p1) ** 0.5, 1e-6)
        t3 = t2 + max(np.linalg.norm(p3 - p2) ** 0.5, 1e-6)
        t = np.linspace(t1, t2, per_segment + 1)[1:, None]
        a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
        a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
        a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
        b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
        b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
        out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    return np.vstack(out)


class _Steps:
    """Footprints along the path and when each foot lifts and lands.

    Both feet start side by side at the first point. Step k (alternating, right
    first) lands at k step lengths along the path when the hips are half a step
    behind it; the last step brings the trailing foot beside the other.
    """

    def __init__(self, route: _Route, travel: np.ndarray, times: np.ndarray) -> None:
        self.times = times
        self.warnings: list[str] = []
        duration = float(times[-1])
        speed = route.length / max(duration - min(0.6, duration / 4.0), 1e-6)
        step = min(_STEP_MAX, max(_STEP_MIN, 0.35 + 0.3 * speed))
        if speed > _FAST_WALK:
            self.warnings.append("path_too_fast: the walk is faster than a natural walk")
        count = max(1, int(math.ceil(route.length / step - 1e-9))) if route.length > 0.05 else 0
        spacing = route.length / count if count else 0.0
        reach = [k * spacing for k in range(1, count + 1)] + ([route.length] if count else [])
        when = [float(np.interp(min(max(d - spacing / 2.0, 0.0), route.length * 0.999), travel, times))
                for d in reach[:-1]] + ([float(times[-1]) if travel[-1] < route.length * 0.999
                                         else float(np.interp(route.length * 0.999, travel, times))] if count else [])
        when = list(np.maximum.accumulate(when)) if when else []
        self.events = [{"side": "Right" if k % 2 == 0 else "Left", "distance": d, "land": t}
                       for k, (d, t) in enumerate(zip(reach, when))]
        previous = 0.0
        for event in self.events:
            gap = max(event["land"] - previous, 1.0 / FPS)
            event["lift"] = max(previous, event["land"] - min(_SWING_SHARE * gap, _SWING_MAX))
            previous = event["land"]


def _place_body(pose: Pose, route: _Route, travel: np.ndarray, steps: _Steps) -> None:
    where = route.at(travel)
    heading = route.heading(travel)
    phase, energy = _gait_phase(steps)
    stance = _stance_side(steps)
    left = route.left(travel)
    sway = 0.015 * energy * np.sin(np.pi * phase["step"]) * stance
    pose.move_root(side=where[:, 0] + left[:, 0] * sway, forward=where[:, 1] + left[:, 1] * sway,
                   up=-0.02 - energy * (0.015 + 0.016 * np.cos(TAU * phase["step"])))
    cycle = phase["cycle"]
    pose.hips(yaw=heading - 5.0 * energy * np.cos(TAU * cycle), roll=-2.5 * energy * np.sin(TAU * cycle))
    pose.spine(pitch=3.0 * energy, yaw=4.5 * energy * np.cos(TAU * cycle), roll=1.5 * energy * np.sin(TAU * cycle))
    pose.head(pitch=-2.0 * energy, yaw=-0.5 * energy * np.cos(TAU * cycle))


def _gait_phase(steps: _Steps) -> tuple[dict, np.ndarray]:
    """``step``: 0 at each landing, 0.5 half way; ``cycle``: 0 at left landings, 0.5 at right ones.

    ``energy`` (0..1) scales bob and swing: 0 while standing before the first and after the last step.
    """
    times = steps.times
    lands = [0.0] + [event["land"] for event in steps.events]
    cycle_marks = [0.5] + [(index + 1) * 0.5 for index in range(len(steps.events))]
    if len(lands) < 2:
        zeros = np.zeros_like(times)
        return {"step": zeros, "cycle": zeros}, zeros
    step = np.zeros_like(times)
    for start, end in zip(lands[:-1], lands[1:]):
        inside = (times >= start) & (times < end)
        step[inside] = (times[inside] - start) / max(end - start, 1e-9)
    cycle = np.interp(times, lands, cycle_marks) % 1.0
    first_lift = steps.events[0]["lift"]
    energy = np.clip(np.minimum((times - first_lift) / 0.3, (lands[-1] - times) / 0.3), 0.0, 1.0)
    return {"step": step, "cycle": cycle}, energy


def _stance_side(steps: _Steps) -> np.ndarray:
    """+1 while the left foot carries the body, -1 for the right, 0 standing."""
    side = np.zeros_like(steps.times)
    for event in steps.events:
        swinging = (steps.times >= event["lift"]) & (steps.times < event["land"])
        side[swinging] = -1.0 if event["side"] == "Left" else 1.0
    return side


def _place_feet(pose: Pose, route: _Route, steps: _Steps) -> None:
    times = steps.times
    rig = pose.rig
    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        prints = [0.0] + [event["distance"] for event in steps.events if event["side"] == side]
        moves = [event for event in steps.events if event["side"] == side]
        ground = np.full(len(times), prints[0])
        up = np.zeros(len(times))
        pitch = np.zeros(len(times))
        for start, event in zip(prints, moves):
            # The heel rises before the toe leaves, as in the in-place walk.
            heel = (times >= event["lift"] - _HEEL_RISE) & (times < event["lift"])
            pitch[heel] = -22.0 * (times[heel] - (event["lift"] - _HEEL_RISE)) / _HEEL_RISE
            swing = (times >= event["lift"]) & (times < event["land"])
            s = (times[swing] - event["lift"]) / max(event["land"] - event["lift"], 1e-9)
            eased = s * s * (3.0 - 2.0 * s)
            ground[swing] = start + (event["distance"] - start) * eased
            up[swing] = _LIFT * np.sin(np.pi * s) ** 1.4
            pitch[swing] = keys(s, [(0.0, -22.0), (0.35, -8.0), (0.8, 6.0), (1.0, 12.0)])
            ground[times >= event["land"]] = event["distance"]
            landed = (times >= event["land"]) & (times < event["land"] + 0.12)
            pitch[landed] = 12.0 * (1.0 - (times[landed] - event["land"]) / 0.12)
        spot = route.at(ground) + route.left(ground) * (sign * route.half_width)
        rest = rot.rotate(rot.inverse(rig.facing), rig.rest_positions[rig.index(f"{side}Foot")] - rig.root) / rig.leg
        pose.plant(side, forward=spot[:, 1] - rest[2], up=up, out=sign * (spot[:, 0] - rest[0]), pitch=pitch,
                   yaw=route.heading(ground))


def _swing_arms(pose: Pose, steps: _Steps) -> None:
    phase, energy = _gait_phase(steps)
    lift = -pose.rig.limits["arm_down"] + 3.0
    for side, sign in (("Left", -1.0), ("Right", 1.0)):
        swing = sign * 18.0 * energy * np.cos(TAU * phase["cycle"])
        pose.arm(side, lift=lift, swing=6.0 + swing)
        pose.elbow(side, 20.0 + 0.45 * np.maximum(swing, 0.0))


__all__ = ["FPS", "MAX_DURATION", "MAX_POINTS", "path_clip"]
