"""Looping local-rotation clips for the standard humanoid.

Apply X, then Y, then Z as local intrinsic: q = qx * qy * qz with xyzw Hamilton product.
Each authored bone uses one axis, so a single quaternion is enough. No translation keys.
"""

from __future__ import annotations

import math

import numpy as np

from services.humanoid_rig.names import BONE_NAMES, CLIP_IDS, CLIP_LABELS

_SAMPLES = 25
_AXES = (0, 1, 2)
_Track = tuple[str, int, str, float, float]

# Axes these clips can produce. Degrees, inclusive.
JOINT_LIMITS: dict[str, list[tuple[int, float, float]]] = {
    "Spine": [(0, -25.0, 35.0), (2, -20.0, 20.0)],
    "Spine1": [(0, -25.0, 35.0)],
    "Spine2": [(0, -25.0, 35.0), (2, -20.0, 20.0)],
    "Head": [(0, -60.0, 60.0), (1, -60.0, 60.0), (2, -60.0, 60.0)],
    "LeftUpLeg": [(0, -50.0, 60.0), (2, -30.0, 30.0)],
    "RightUpLeg": [(0, -50.0, 60.0), (2, -30.0, 30.0)],
    "LeftLeg": [(0, 0.0, 140.0)],
    "RightLeg": [(0, 0.0, 140.0)],
    "LeftArm": [(1, -90.0, 90.0), (2, -30.0, 170.0)],
    "RightArm": [(1, -90.0, 90.0), (2, -170.0, 30.0)],
    "LeftForeArm": [(1, -150.0, 0.0)],
    "RightForeArm": [(1, 0.0, 150.0)],
}

__all__ = ["JOINT_LIMITS", "axis_quat", "clip_library", "degrees_of"]


def _pulse(u: np.ndarray) -> np.ndarray:
    # 0 at the ends, 1 in the middle.
    return 0.5 - 0.5 * np.cos(2 * np.pi * u)


def _swing(u: np.ndarray) -> np.ndarray:
    # 0 at both ends.
    return np.sin(2 * np.pi * u)


def _double(u: np.ndarray) -> np.ndarray:
    return np.sin(4 * np.pi * u)


def _two(u: np.ndarray) -> np.ndarray:
    return 0.5 - 0.5 * np.cos(4 * np.pi * u)


def _swing_sq(u: np.ndarray) -> np.ndarray:
    return _swing(u) ** 2


def _sin_pi(u: np.ndarray) -> np.ndarray:
    return np.sin(np.pi * u)


def _const(u: np.ndarray) -> np.ndarray:
    return np.ones_like(u, dtype=np.float64)


_CURVES = {
    "swing": _swing,
    "pulse": _pulse,
    "double": _double,
    "two": _two,
    "swing_sq": _swing_sq,
    "sin_pi": _sin_pi,
    "const": _const,
}

_BEATS: dict[str, int] = {
    "idle": 4,
    "breathe": 4,
    "walk": 2,
    "run": 2,
    "jump": 2,
    "wave": 2,
    "cheer": 2,
    "dance_bounce": 2,
    "dance_side": 2,
    "dance_arms": 2,
    "clap": 2,
    "punch": 2,
    "sit_down": 4,
    "victory": 2,
}

# angle = offset + scale * curve(u). One axis per bone.
_RECIPES: dict[str, tuple[_Track, ...]] = {
    "idle": (
        ("Spine", 0, "swing", 4.0, 0.0),
        ("Head", 0, "swing", 3.0, 0.0),
    ),
    "breathe": (
        ("Spine", 0, "pulse", 6.0, 0.0),
        ("Spine1", 0, "pulse", 4.0, 0.0),
    ),
    "walk": (
        ("LeftUpLeg", 0, "swing", -25.0, 0.0),
        ("RightUpLeg", 0, "swing", 25.0, 0.0),
        ("LeftLeg", 0, "swing_sq", 22.0, 18.0),
        ("RightLeg", 0, "swing_sq", 22.0, 18.0),
        ("LeftArm", 1, "swing", 18.0, 0.0),
        ("RightArm", 1, "swing", -18.0, 0.0),
    ),
    "run": (
        ("LeftUpLeg", 0, "swing", -40.0, 0.0),
        ("RightUpLeg", 0, "swing", 40.0, 0.0),
        ("LeftLeg", 0, "swing_sq", 35.0, 25.0),
        ("RightLeg", 0, "swing_sq", 35.0, 25.0),
        ("LeftArm", 1, "swing", 32.0, 0.0),
        ("RightArm", 1, "swing", -32.0, 0.0),
        ("Spine", 0, "double", 6.0, 0.0),
    ),
    "jump": (
        ("LeftUpLeg", 0, "two", 28.0, 0.0),
        ("RightUpLeg", 0, "two", 28.0, 0.0),
        ("LeftLeg", 0, "two", 75.0, 0.0),
        ("RightLeg", 0, "two", 75.0, 0.0),
        ("LeftArm", 2, "pulse", 100.0, 0.0),
        ("RightArm", 2, "pulse", -100.0, 0.0),
    ),
    "wave": (
        ("LeftArm", 2, "swing", 25.0, 70.0),
        ("LeftForeArm", 1, "const", 0.0, -20.0),
    ),
    "cheer": (
        ("LeftArm", 2, "double", 20.0, 110.0),
        ("RightArm", 2, "double", -20.0, -110.0),
    ),
    "dance_bounce": (
        ("LeftLeg", 0, "two", 20.0, 15.0),
        ("RightLeg", 0, "two", 20.0, 15.0),
        ("Spine", 0, "double", 8.0, 0.0),
        ("LeftArm", 2, "swing", 18.0, 0.0),
        ("RightArm", 2, "swing", -18.0, 0.0),
    ),
    "dance_side": (
        ("LeftUpLeg", 2, "swing", 16.0, 0.0),
        ("RightUpLeg", 2, "swing", 16.0, 0.0),
        ("Spine", 2, "swing", -10.0, 0.0),
        ("LeftArm", 2, "swing", 24.0, 0.0),
        ("RightArm", 2, "swing", 24.0, 0.0),
    ),
    "dance_arms": (
        ("LeftArm", 2, "swing", 50.0, 40.0),
        ("RightArm", 2, "swing", 50.0, -40.0),
        ("LeftForeArm", 1, "double", -20.0, -30.0),
        ("RightForeArm", 1, "double", 20.0, 30.0),
    ),
    "clap": (
        ("LeftArm", 1, "two", -55.0, 0.0),
        ("RightArm", 1, "two", 55.0, 0.0),
        ("LeftForeArm", 1, "two", -45.0, 0.0),
        ("RightForeArm", 1, "two", 45.0, 0.0),
    ),
    "punch": (
        ("RightArm", 1, "sin_pi", 80.0, 0.0),
        ("RightForeArm", 1, "const", 0.0, 12.0),
        ("LeftArm", 1, "const", 0.0, -20.0),
        ("LeftForeArm", 1, "const", 0.0, -50.0),
    ),
    "sit_down": (
        ("LeftUpLeg", 0, "pulse", 45.0, 0.0),
        ("RightUpLeg", 0, "pulse", 45.0, 0.0),
        ("LeftLeg", 0, "pulse", 95.0, 0.0),
        ("RightLeg", 0, "pulse", 95.0, 0.0),
        ("Spine", 0, "pulse", 12.0, 0.0),
    ),
    "victory": (
        ("LeftArm", 2, "double", 8.0, 130.0),
        ("RightArm", 2, "double", -8.0, -130.0),
        ("Head", 0, "swing", 6.0, -10.0),
    ),
}


def _check_tracks(tracks: tuple[_Track, ...], bones: set[str]) -> None:
    seen: set[str] = set()
    for bone, axis, curve, _scale, _offset in tracks:
        if bone not in bones or bone in seen:
            raise RuntimeError(bone)
        if axis not in _AXES or curve not in _CURVES:
            raise RuntimeError(curve)
        seen.add(bone)


def _check_recipes() -> None:
    bones = set(BONE_NAMES)
    if set(_BEATS) != set(CLIP_IDS) or set(_RECIPES) != set(CLIP_IDS):
        raise RuntimeError("clip table does not match CLIP_IDS")
    for clip_id, beats in _BEATS.items():
        if beats <= 0:
            raise RuntimeError(clip_id)
    for tracks in _RECIPES.values():
        _check_tracks(tracks, bones)


_check_recipes()


def axis_quat(axis: np.ndarray, degrees: float) -> np.ndarray:
    """Right-handed xyzw quaternion. q = (unit(axis) * sin(θ/2), cos(θ/2))."""
    direction = np.asarray(axis, dtype=np.float64)
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)
    half = math.radians(float(degrees)) * 0.5
    xyz = (direction / norm) * math.sin(half)
    return np.array([xyz[0], xyz[1], xyz[2], math.cos(half)], dtype=np.float64)


def degrees_of(quat: np.ndarray) -> tuple[int, float]:
    """Dominant axis index and signed degrees. Identity is near axis 0 at 0."""
    xyzw = np.asarray(quat, dtype=np.float64).reshape(4)
    xyz = xyzw[:3]
    length = float(np.linalg.norm(xyz))
    radians = 2.0 * math.atan2(length, float(xyzw[3]))
    axis = int(np.argmax(np.abs(xyz)))
    sign = 1.0 if float(xyz[axis]) >= 0.0 else -1.0
    return axis, float(math.degrees(sign * radians))


def _angles(scale: float, offset: float, curve: str, u: np.ndarray) -> np.ndarray:
    return offset + scale * _CURVES[curve](u)


def _track_quats(axis: int, degrees: np.ndarray) -> np.ndarray:
    half = np.deg2rad(np.asarray(degrees, dtype=np.float64)) * 0.5
    quats = np.zeros((half.shape[0], 4), dtype=np.float64)
    quats[:, axis] = np.sin(half)
    quats[:, 3] = np.cos(half)
    return quats


def _rotations(clip_id: str, u: np.ndarray) -> dict[str, np.ndarray]:
    rotations: dict[str, np.ndarray] = {}
    for bone, axis, curve, scale, offset in _RECIPES[clip_id]:
        rotations[bone] = _track_quats(axis, _angles(scale, offset, curve, u))
    return rotations


def _build_clip(clip_id: str, bpm: float) -> dict:
    beats = _BEATS[clip_id]
    duration = beats * 60.0 / bpm
    times = np.linspace(0.0, duration, _SAMPLES, dtype=np.float64)
    return {
        "id": clip_id,
        "name": CLIP_LABELS[clip_id],
        "bpm": bpm,
        "beats": beats,
        "duration": duration,
        "times": times,
        "rotations": _rotations(clip_id, times / duration),
    }


def _require_bpm(bpm: float) -> float:
    value = float(bpm)
    if not math.isfinite(value) or value < 60.0 or value > 180.0:
        raise ValueError("bpm must be finite and in [60, 180]")
    return value


def _select_ids(ids: list[str] | None) -> tuple[str, ...]:
    chosen = CLIP_IDS if ids is None else tuple(ids)
    unknown = [item for item in chosen if item not in CLIP_LABELS]
    if unknown:
        raise ValueError(f"unknown clip id: {unknown[0]}")
    return chosen


def clip_library(bpm: float, ids: list[str] | None = None) -> list[dict]:
    """Return looping in-place clips at ``bpm`` for ``ids`` or every clip id."""
    tempo = _require_bpm(bpm)
    return [_build_clip(clip_id, tempo) for clip_id in _select_ids(ids)]
