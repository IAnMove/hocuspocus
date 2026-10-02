"""Pose math for the humanoid compatibility path.

Quaternions are xyzw. q and -q are the same orientation. FK is
parent_world × local_TRS, including wrapper scale. CUBICSPLINE is reported;
it is not treated as LINEAR.
"""

from __future__ import annotations

import math

import numpy as np

from services.humanoid_rig.body_roles import (
    CHILD_TRANSLATION_REST_M,
    CONSTANT_SCALE_EPSILON,
    HEIGHT_RATIO_MAX,
    HEIGHT_RATIO_MIN,
)

IDENTITY_QUAT = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)


class PoseMathError(ValueError):
    """A pose the new path will not invent a stand-in for."""

    def __init__(self, reason: str, *, clip: str | None = None, channel: str | None = None) -> None:
        self.reason = reason
        self.clip = clip
        self.channel = channel
        super().__init__(reason)


def as_quat(value) -> np.ndarray:
    quat = np.asarray(value, dtype=np.float64).reshape(4)
    return normalize_quat(quat)


def normalize_quat(quat: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(quat))
    if length == 0.0 or not math.isfinite(length):
        raise PoseMathError("invalid_quaternion")
    return quat / length


def quat_mul(left, right) -> np.ndarray:
    """Hamilton product. Applies ``right`` first, then ``left``."""
    ax, ay, az, aw = as_quat(left)
    bx, by, bz, bw = as_quat(right)
    return np.array([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ], dtype=np.float64)


def quat_inv(quat) -> np.ndarray:
    x, y, z, w = as_quat(quat)
    return np.array([-x, -y, -z, w], dtype=np.float64)


def quats_equivalent(left, right, *, atol: float = 1e-5) -> bool:
    """True when the orientations match, including the q / -q pair."""
    a = as_quat(left)
    b = as_quat(right)
    return abs(float(np.dot(a, b))) >= 1.0 - atol


def axis_angle_quat(axis, radians: float) -> np.ndarray:
    direction = np.asarray(axis, dtype=np.float64)
    direction = direction / np.linalg.norm(direction)
    half = float(radians) * 0.5
    scale = math.sin(half)
    return np.array([
        direction[0] * scale,
        direction[1] * scale,
        direction[2] * scale,
        math.cos(half),
    ], dtype=np.float64)


def quat_rotate(quat, vector) -> np.ndarray:
    """Rotate a vector by a unit quaternion. Length is preserved, including zero.

    Orientation products stay in ``quat_mul``, which normalizes. A vector is
    not an orientation, so it is applied with the rotation matrix.
    """
    direction = np.asarray(vector, dtype=np.float64).reshape(3)
    return trs_matrix([0.0, 0.0, 0.0], quat, [1.0, 1.0, 1.0])[:3, :3] @ direction


def lerp(left, right, t: float) -> np.ndarray:
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    return (1.0 - t) * a + t * b


def slerp(left, right, t: float) -> np.ndarray:
    a = as_quat(left)
    b = as_quat(right)
    dot = float(np.dot(a, b))
    if dot < 0.0:
        b = -b
        dot = -dot
    if dot > 0.9995:
        return normalize_quat(lerp(a, b, t))
    theta = math.acos(min(1.0, dot))
    scale = math.sin(theta)
    wa = math.sin((1.0 - t) * theta) / scale
    wb = math.sin(t * theta) / scale
    return wa * a + wb * b


def trs_matrix(translation, rotation, scale) -> np.ndarray:
    """Column-vector TRS. Scale is applied before rotation."""
    x, y, z, w = as_quat(rotation)
    sx, sy, sz = (float(v) for v in scale)
    rotation_m = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = rotation_m * np.array([sx, sy, sz], dtype=np.float64)
    matrix[:3, 3] = np.asarray(translation, dtype=np.float64)
    return matrix


def world_matrices(locals_m: list[np.ndarray], parents: list[int | None]) -> list[np.ndarray]:
    """FK. ``parents[i]`` is None at a root. Raises when the graph cycles."""
    worlds: list[np.ndarray | None] = [None] * len(locals_m)
    for index in range(len(locals_m)):
        _world_at(index, locals_m, parents, worlds, set())
    return [np.asarray(item) for item in worlds]


def _world_at(index, locals_m, parents, worlds, stack: set[int]) -> np.ndarray:
    cached = worlds[index]
    if cached is not None:
        return cached
    if index in stack:
        raise PoseMathError("skeleton_cycle")
    stack.add(index)
    parent = parents[index]
    local = locals_m[index]
    if parent is None:
        worlds[index] = local
    else:
        worlds[index] = _world_at(parent, locals_m, parents, worlds, stack) @ local
    stack.remove(index)
    return worlds[index]


def sample_channel(times, values, t: float, interpolation: str, *, clip: str = "", channel: str = ""):
    """Sample one channel. STEP holds the previous key. CUBICSPLINE is an error."""
    kind = interpolation or "LINEAR"
    if kind == "CUBICSPLINE":
        raise PoseMathError("unsupported_interpolation", clip=clip or None, channel=channel or None)
    if kind not in ("LINEAR", "STEP"):
        raise PoseMathError("unsupported_interpolation", clip=clip or None, channel=channel or None)
    clocks = np.asarray(times, dtype=np.float64).reshape(-1)
    samples = np.asarray(values, dtype=np.float64)
    if len(clocks) == 0:
        raise PoseMathError("empty_channel", clip=clip or None, channel=channel or None)
    if kind == "STEP":
        return _hold_step(clocks, samples, t)
    return _lerp_keys(clocks, samples, t, channel)


def _hold_step(clocks, samples, t: float):
    index = int(np.searchsorted(clocks, t, side="right") - 1)
    index = min(max(index, 0), len(clocks) - 1)
    return np.array(samples[index], dtype=np.float64, copy=True)


def _lerp_keys(clocks, samples, t: float, channel: str):
    if t <= float(clocks[0]):
        return np.array(samples[0], dtype=np.float64, copy=True)
    if t >= float(clocks[-1]):
        return np.array(samples[-1], dtype=np.float64, copy=True)
    index = int(np.searchsorted(clocks, t, side="right") - 1)
    span = float(clocks[index + 1] - clocks[index])
    u = 0.0 if span == 0.0 else (t - float(clocks[index])) / span
    if samples.shape[-1] == 4 and channel.endswith("rotation"):
        return slerp(samples[index], samples[index + 1], u)
    return lerp(samples[index], samples[index + 1], u)


def target_world_quat(source_t, source_ref, target_ref) -> np.ndarray:
    """Carry the source world delta onto the target rest.

    ``R_t(t) = R_s(t) inv(R_s_ref) R_t_ref``. The two rest quaternions are the
    calibrated frames. At the reference, the target stays on its own rest.
    Child offsets are not inferred: if those frames were not calibrated, the
    result stays unverified.
    """
    delta = quat_mul(source_t, quat_inv(source_ref))
    return quat_mul(delta, target_ref)


def rest_axes_agree(source_ref, target_ref, source_axis, target_axis, *, tol: float = 1e-3) -> bool:
    """True when the two local axes point the same way in the calibrated rest."""
    source = quat_rotate(source_ref, source_axis)
    target = quat_rotate(target_ref, target_axis)
    return float(np.linalg.norm(source - target)) <= tol


def local_from_parent(parent_world, child_world) -> np.ndarray:
    return quat_mul(quat_inv(parent_world), child_world)


def height_ratio(source_m: float, target_m: float) -> float:
    """Scale factor between two measured metre heights. Refuses a ×100 factor."""
    source = float(source_m)
    target = float(target_m)
    if source <= 0.0 or target <= 0.0 or not math.isfinite(source) or not math.isfinite(target):
        raise PoseMathError("invalid_height")
    ratio = target / source
    if ratio < HEIGHT_RATIO_MIN or ratio > HEIGHT_RATIO_MAX:
        raise PoseMathError("height_ratio_refused")
    return ratio


def in_place_translations(samples, source_m: float, target_m: float) -> tuple[np.ndarray, dict]:
    """Drop horizontal XZ travel from the first frame. Keep vertical action.

    Trajectory yaw is recorded as not removed. This does not guess which hip
    turns are locomotion.
    """
    points = np.asarray(samples, dtype=np.float64)
    ratio = height_ratio(source_m, target_m)
    origin = points[0]
    delta = points - origin
    out = np.repeat(origin.reshape(1, 3), len(points), axis=0)
    out[:, 1] = origin[1] + delta[:, 1] * ratio
    return out, _root_meta("in_place", ratio)


def preserve_translations(samples, source_m: float, target_m: float) -> tuple[np.ndarray, dict]:
    points = np.asarray(samples, dtype=np.float64)
    ratio = height_ratio(source_m, target_m)
    origin = points[0]
    out = origin + (points - origin) * ratio
    return out, _root_meta("preserve", ratio)


def _root_meta(policy: str, ratio: float) -> dict:
    yaw = "not_removed" if policy == "in_place" else "kept"
    return {
        "policy": policy,
        "trajectory_yaw": yaw,
        "height_ratio": ratio,
        "horizontal": "first_frame_xz" if policy == "in_place" else "scaled_delta",
    }


def resolve_height(*, position_min_y, position_max_y, node_translation_span, wrapper_scale) -> dict:
    """Record geometric height. A node-translation span is not that height.

    Wrapper scale is stored and is not applied a second time to bounds that
    are already in metres.
    """
    rejected = []
    if node_translation_span is not None:
        rejected.append({
            "method": "node_translation_span",
            "value": float(node_translation_span),
            "reason": "not_skinned_geometric_height",
        })
    height = None
    method = None
    if position_min_y is not None and position_max_y is not None:
        height = float(position_max_y) - float(position_min_y)
        method = "position_bounds_m"
    return {
        "height_m": height,
        "height_method": method,
        "wrapper_scale": None if wrapper_scale is None else [float(v) for v in wrapper_scale],
        "wrapper_scale_applied_again": False,
        "rejected": rejected,
    }


def constant_child_translation(samples, rest, tolerance: float = CHILD_TRANSLATION_REST_M) -> dict:
    """Collapse a child translation to rest only inside the recorded tolerance."""
    values = np.asarray(samples, dtype=np.float64)
    origin = np.asarray(rest, dtype=np.float64)
    peak = float(np.max(np.abs(values - origin))) if len(values) else 0.0
    if peak <= tolerance:
        return {
            "collapsed": True,
            "policy": "constant_child_translation_to_rest",
            "tolerance_m": tolerance,
            "values": np.repeat(origin.reshape(1, 3), len(values), axis=0),
        }
    return {
        "collapsed": False,
        "reason": "variable_translation",
        "peak_m": peak,
        "values": values,
    }


def scale_channel_policy(samples, epsilon: float = CONSTANT_SCALE_EPSILON) -> dict:
    """Nearly constant unit scale is recorded. Variable scale is not dropped."""
    values = np.asarray(samples, dtype=np.float64)
    peak = float(np.max(np.abs(values - 1.0))) if values.size else 0.0
    if peak <= epsilon:
        return {"ignored": True, "policy": "constant_unit_scale", "epsilon": epsilon, "peak": peak}
    return {"ignored": False, "reason": "variable_scale", "peak": peak}
