"""Where a moving Video 3D object is at a given second: the Python twin of the renderer's ``slotPoseAtTime``.

``ui/src/features/scene3d/performance.ts`` places an object with ``motion`` on the path from its slot position to
``motion.to`` (a straight line, a quadratic curve through ``via`` or a Catmull-Rom curve through ``points``), eased
``linear`` or ``smooth`` (smoothstep). ``motion.start`` and ``motion.end`` (scene seconds, default 0 and the end of the
scene) are the window the move runs over: before ``start`` the object sits at its slot position, after ``end`` it stays
at ``to``. A document without them moves over the whole shot, as it always did.

This module has the same formulas so a service can ask where something will be (collisions, beats, effects anchored in
space) without a browser. ``tests/fixtures/world3d_motion_samples.json`` holds poses sampled from the TypeScript runtime
(``ui/tests/scene3dMotionWindow.test.ts`` writes and checks it, ``tests/test_world3d_scene_motion.py`` checks this port
against it), so a change of either side that is not matched on the other fails a test.

``check_motion`` is the gate of a ``world3d.scene.patch`` binding's ``motion``: the editor drops a move whose ``to`` is
not three finite numbers, so the patch says so instead of storing it.
"""
from __future__ import annotations

import math
from typing import Any

MAX_SECONDS = 600
MAX_POINTS = 62                     # walkPath.ts MAX_PATH_POINTS
_PER_SEGMENT = 24                   # walkPath.ts catmullRomPath
_EPSILON = 0.001                    # slotPoseAtTime: the window never shorter than a millisecond


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _triple(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(_finite(item) for item in value)


def window(motion: dict, duration: float) -> tuple[float, float]:
    """``(start, end)`` in scene seconds: ``motion.start`` (0) to ``motion.end`` (the end of the scene)."""
    start, end = motion.get("start"), motion.get("end")
    return (float(start) if _finite(start) else 0.0, float(end) if _finite(end) else float(duration))


def is_timed(motion: Any) -> bool:
    return isinstance(motion, dict) and (motion.get("start") is not None or motion.get("end") is not None)


def check_motion(value: Any, duration: float) -> dict:
    """The ``motion`` of a binding as it is stored (a copy), or ``ValueError`` saying what the editor would not take.

    ``to`` (and ``via``, ``points`` when given) are [x, y, z]; ``start`` is 0-600 s and ``end`` 0-600 s, ``start`` before
    ``end`` and before the end of the scene; a timed move cannot also carry a baked ``walk`` (its feet are planted along
    the whole shot)."""
    if not isinstance(value, dict):
        raise ValueError("motion must be an object {to: [x, y, z], via?, points?, faceTravel?, easing?, start?, end?}")
    if not _triple(value.get("to")):
        raise ValueError("motion.to must be [x, y, z], three finite numbers in metres")
    if value.get("via") is not None and not _triple(value["via"]):
        raise ValueError("motion.via must be [x, y, z]")
    _check_points(value.get("points"))
    _check_window(value, duration)
    return dict(value)


def _check_points(points: Any) -> None:
    if points is None:
        return
    if not isinstance(points, list) or not 0 < len(points) <= MAX_POINTS or not all(_triple(point) for point in points):
        raise ValueError(f"motion.points must be a list of 1-{MAX_POINTS} [x, y, z] waypoints")


def _check_window(motion: dict, duration: float) -> None:
    for key in ("start", "end"):
        item = motion.get(key)
        if item is not None and (not _finite(item) or not 0 <= item <= MAX_SECONDS):
            raise ValueError(f"motion.{key} must be a time in the scene, 0-{MAX_SECONDS} seconds")
    if not is_timed(motion):
        return
    if motion.get("walk"):
        raise ValueError("motion_window_with_walk: a move with start or end cannot also carry a baked walk; "
                         "clear the walk or the window (the baked walk plants the feet along the whole shot)")
    start, end = window(motion, duration)
    if start >= end:
        raise ValueError(f"motion.start ({start:g} s) must come before motion.end ({end:g} s, the end of the scene unless given)")
    if start >= duration:
        raise ValueError(f"motion.start ({start:g} s) is at or after the end of the scene ({duration:g} s): the object would never move")


def bind_motion(slot: dict, binding: dict, duration: float) -> None:
    """The ``motion`` and ``collide`` of a patch binding, checked once the binding has put them on the slot.

    ``motion: null`` and ``collide: null`` or ``true`` take them off (an object collides unless it says ``collide: false``)."""
    from services.world3d_scenes import World3DSceneError
    name = slot.get("id")
    if "motion" in binding and slot.get("motion") is not None:
        try:
            slot["motion"] = check_motion(slot["motion"], duration)
        except ValueError as error:
            raise World3DSceneError("invalid_motion", f"{name}: {error}") from error
    if "collide" in binding:
        if type(binding["collide"]) not in (bool, type(None)):
            raise World3DSceneError("invalid_collide", f"{name}: collide is false (a ghost, a spirit: no collision warnings), or true / null for the default")
        slot.pop("collide", None)
        if binding["collide"] is False:
            slot["collide"] = False


def retime(motion: Any, factor: float) -> None:
    """Stretch a move's window with the scene (``retime``): the beat stays where it belongs in the new length."""
    if isinstance(motion, dict):
        for key in ("start", "end"):
            if _finite(motion.get(key)):
                motion[key] = round(motion[key] * factor, 3)


def pose_at(slot: dict, seconds: float, duration: float) -> tuple[list[float], float]:
    """``(position, rotationY)`` of a slot at ``seconds`` of the scene, as ``slotPoseAtTime`` places it.

    A slot with no ``motion`` stays where it is. A baked walk is not modelled: the path is the path."""
    position = [float(item) for item in slot.get("position") or [0, 0, 0]]
    rotation = float(slot.get("rotationY") or 0)
    motion = slot.get("motion")
    if not isinstance(motion, dict) or not _triple(motion.get("to")):
        return position, rotation
    return _moved(position, rotation, motion, seconds, duration)


def _moved(position: list[float], rotation: float, motion: dict, seconds: float, duration: float) -> tuple[list[float], float]:
    start, end = window(motion, duration)
    progress = max(0.0, min(1.0, (seconds - start) / max(_EPSILON, end - start)))
    t = progress * progress * (3 - 2 * progress) if motion.get("easing") == "smooth" else progress
    if motion.get("points"):
        return _waypoint_pose(position, rotation, motion, t)
    via = motion.get("via") if _triple(motion.get("via")) else None
    target = [float(item) for item in motion["to"]]
    here = [_quadratic(a, via[i], target[i], t) if via else a + (target[i] - a) * t for i, a in enumerate(position)]
    heading = _heading(position, target, via, t)
    if motion.get("faceTravel") and heading is not None:
        return here, heading + _heading_offset(motion)
    turn = motion.get("turnTo")
    return here, rotation + ((float(turn) if _finite(turn) else rotation) - rotation) * t


def _heading_offset(motion: dict) -> float:
    """Radians added to the travel heading; the editor keeps only a number within a full turn (``parseHeadingOffset``)."""
    offset = motion.get("headingOffset")
    return float(offset) if _finite(offset) and abs(offset) <= 2 * math.pi else 0.0


def _quadratic(a: float, via: float, b: float, t: float) -> float:
    return (1 - t) ** 2 * a + 2 * (1 - t) * t * via + t * t * b


def _heading(start: list[float], target: list[float], via: list[float] | None, t: float) -> float | None:
    """The direction of travel on the curve, or None while it is too short to tell (the runtime keeps the slot's own turn)."""
    if via:
        tangent = [2 * (1 - t) * (via[i] - start[i]) + 2 * t * (target[i] - via[i]) for i in range(3)]
    else:
        tangent = [target[i] - start[i] for i in range(3)]
    return math.atan2(tangent[0], tangent[2]) if math.hypot(tangent[0], tangent[2]) > 0.0001 else None


def _waypoint_pose(position: list[float], rotation: float, motion: dict, t: float) -> tuple[list[float], float]:
    target = [float(item) for item in motion["to"]]
    stops = [position, *([float(item) for item in point] for point in motion["points"]), target]
    x, z, heading = path_at(catmull_rom_path(stops), t)
    height = position[1] + (target[1] - position[1]) * t
    if motion.get("faceTravel"):
        return [x, height, z], heading + _heading_offset(motion)
    turn = motion.get("turnTo")
    return [x, height, z], rotation + ((float(turn) if _finite(turn) else rotation) - rotation) * t


def _mix(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _centripetal(p: list[tuple[float, float]], knots: tuple[float, float, float], t: float) -> tuple[float, float]:
    t1, t2, t3 = knots
    a1, a2, a3 = _mix(p[0], p[1], t / t1), _mix(p[1], p[2], (t - t1) / (t2 - t1)), _mix(p[2], p[3], (t - t2) / (t3 - t2))
    b1, b2 = _mix(a1, a2, t / t2), _mix(a2, a3, (t - t1) / (t3 - t1))
    return _mix(b1, b2, (t - t1) / (t2 - t1))


def _segment(p: list[tuple[float, float]]) -> list[tuple[float, float]]:
    t1 = max(math.sqrt(_distance(p[0], p[1])), 1e-6)
    t2 = t1 + max(math.sqrt(_distance(p[1], p[2])), 1e-6)
    t3 = t2 + max(math.sqrt(_distance(p[2], p[3])), 1e-6)
    return [_centripetal(p, (t1, t2, t3), t1 + (t2 - t1) * k / _PER_SEGMENT) for k in range(1, _PER_SEGMENT + 1)]


def catmull_rom_path(points: list[list[float]]) -> dict:
    """The ground curve (x, z) through the points, sampled densely, with arc lengths: ``walkPath.ts catmullRomPath``."""
    flat = [(float(point[0]), float(point[2])) for point in points]
    samples = [flat[0]]
    if len(flat) == 2:
        samples += [_mix(flat[0], flat[1], i / _PER_SEGMENT) for i in range(1, _PER_SEGMENT + 1)]
    else:
        padded = [(2 * flat[0][0] - flat[1][0], 2 * flat[0][1] - flat[1][1]), *flat,
                  (2 * flat[-1][0] - flat[-2][0], 2 * flat[-1][1] - flat[-2][1])]
        for i in range(1, len(padded) - 2):
            samples += _segment(padded[i - 1:i + 3])
    arc = [0.0]
    for i in range(1, len(samples)):
        arc.append(arc[i - 1] + _distance(samples[i - 1], samples[i]))
    return {"samples": samples, "arc": arc, "length": arc[-1]}


def path_at(path: dict, fraction: float) -> tuple[float, float, float]:
    """``(x, z, heading)`` at a fraction 0-1 of the path's length: ``walkPath.ts pathAt``."""
    samples, arc = path["samples"], path["arc"]
    target = max(0.0, min(1.0, fraction)) * path["length"]
    index = 1
    while index < len(arc) - 1 and arc[index] < target:
        index += 1
    span = max(1e-9, arc[index] - arc[index - 1])
    x, z = _mix(samples[index - 1], samples[index], (target - arc[index - 1]) / span)
    return x, z, math.atan2(samples[index][0] - samples[index - 1][0], samples[index][1] - samples[index - 1][1])
