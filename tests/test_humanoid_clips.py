"""Standard humanoid clip library: loops, tempo, and joint limits."""

from __future__ import annotations

import math

import numpy as np
import pytest

from services.humanoid_rig.clips import JOINT_LIMITS, axis_quat, clip_library, degrees_of
from services.humanoid_rig.names import BONE_NAMES, CLIP_IDS, CLIP_LABELS

_CLIP_KEYS = {"id", "name", "bpm", "beats", "duration", "times", "rotations"}


def _assert_times(times: np.ndarray, duration: float) -> None:
    assert isinstance(times, np.ndarray)
    assert times.dtype == np.float64
    assert times.ndim == 1
    assert times.shape[0] >= 17
    assert times[0] == 0.0
    assert times[-1] == duration
    assert bool(np.all(np.diff(times) > 0.0))
    expected = np.linspace(0.0, duration, times.shape[0], dtype=np.float64)
    np.testing.assert_array_equal(times, expected)


def _assert_rotations(rotations: dict[str, np.ndarray], frames: int) -> None:
    assert isinstance(rotations, dict)
    assert "Hips" not in rotations
    for bone, values in rotations.items():
        assert bone in BONE_NAMES
        assert isinstance(values, np.ndarray)
        assert values.dtype == np.float64
        assert values.shape == (frames, 4)
        norms = np.linalg.norm(values, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-8)
        np.testing.assert_allclose(values[0], values[-1], atol=1e-8)


def _assert_clip_shape(clip: dict, bpm: float) -> None:
    assert set(clip) == _CLIP_KEYS
    assert clip["name"] == CLIP_LABELS[clip["id"]]
    assert clip["bpm"] == bpm
    assert isinstance(clip["beats"], int)
    assert clip["beats"] > 0
    assert clip["duration"] == clip["beats"] * 60.0 / bpm
    assert clip["duration"] * bpm / 60.0 == clip["beats"]
    _assert_times(clip["times"], clip["duration"])
    _assert_rotations(clip["rotations"], clip["times"].shape[0])


def _assert_angle(bone: str, quat: np.ndarray) -> None:
    axis, angle = degrees_of(quat)
    if abs(angle) < 1e-6:
        return
    bounds = [item for item in JOINT_LIMITS[bone] if item[0] == axis]
    assert bounds
    _index, lo, hi = bounds[0]
    assert lo <= angle <= hi


def _angle_at(clip_id: str, bone: str, index: int) -> float:
    clip = clip_library(120.0, [clip_id])[0]
    return degrees_of(clip["rotations"][bone][index])[1]


@pytest.mark.parametrize("bpm", [60, 120, 180])
def test_library_covers_every_clip_and_loops(bpm: float) -> None:
    clips = clip_library(bpm)
    assert [item["id"] for item in clips] == list(CLIP_IDS)
    for clip in clips:
        _assert_clip_shape(clip, float(bpm))


@pytest.mark.parametrize("bpm", [59, 181, math.nan, math.inf])
def test_bpm_out_of_range_is_rejected(bpm: float) -> None:
    with pytest.raises(ValueError):
        clip_library(bpm)


def test_unknown_id_is_rejected() -> None:
    with pytest.raises(ValueError):
        clip_library(120, ["wave", "not_a_clip"])


def test_two_calls_are_identical() -> None:
    first = clip_library(96)
    second = clip_library(96)
    assert len(first) == len(second)
    for left, right in zip(first, second):
        assert left["id"] == right["id"]
        assert left["name"] == right["name"]
        assert left["bpm"] == right["bpm"]
        assert left["beats"] == right["beats"]
        assert left["duration"] == right["duration"]
        np.testing.assert_array_equal(left["times"], right["times"])
        assert list(left["rotations"]) == list(right["rotations"])
        for bone in left["rotations"]:
            np.testing.assert_array_equal(left["rotations"][bone], right["rotations"][bone])


def test_sampled_angles_stay_inside_joint_limits() -> None:
    for clip in clip_library(120):
        for bone, values in clip["rotations"].items():
            for quat in values:
                _assert_angle(bone, quat)


@pytest.mark.parametrize("clip_id", ["walk", "run"])
def test_walk_and_run_stay_in_place_and_stride(clip_id: str) -> None:
    clip = clip_library(120, [clip_id])[0]
    assert "translation" not in clip
    assert "translations" not in clip
    assert "Hips" not in clip["rotations"]
    thigh = clip["rotations"]["LeftUpLeg"]
    assert not np.allclose(thigh, thigh[:1])


def test_wave_request_returns_one_clip() -> None:
    clips = clip_library(90, ["wave"])
    assert len(clips) == 1
    assert clips[0]["id"] == "wave"
    assert clips[0]["name"] == "Wave"
    assert clips[0]["beats"] == 2


def test_signed_peaks_follow_the_authoring() -> None:
    # Sample 6 is u=0.25 (swing +1). Sample 12 is u=0.5. Sample 3 is double +1.
    assert _angle_at("walk", "LeftUpLeg", 6) == pytest.approx(-25.0)
    assert _angle_at("walk", "RightUpLeg", 6) == pytest.approx(25.0)
    assert _angle_at("walk", "LeftArm", 6) == pytest.approx(18.0)
    assert _angle_at("walk", "RightArm", 6) == pytest.approx(-18.0)
    assert _angle_at("run", "LeftUpLeg", 6) == pytest.approx(-40.0)
    assert _angle_at("wave", "LeftArm", 6) == pytest.approx(95.0)
    assert _angle_at("wave", "LeftForeArm", 0) == pytest.approx(-20.0)
    assert _angle_at("cheer", "RightArm", 3) == pytest.approx(-130.0)
    assert _angle_at("punch", "RightArm", 12) == pytest.approx(80.0)
    assert _angle_at("sit_down", "LeftLeg", 12) == pytest.approx(95.0)
    assert _angle_at("dance_side", "LeftArm", 6) == pytest.approx(24.0)
    assert _angle_at("dance_side", "RightArm", 6) == pytest.approx(24.0)


def test_axis_quat_roundtrip_keeps_axis_and_sign() -> None:
    positive = axis_quat(np.array([0.0, 1.0, 0.0]), 90.0)
    negative = axis_quat(np.array([0.0, 0.0, 1.0]), -30.0)
    identity = axis_quat(np.array([1.0, 0.0, 0.0]), 0.0)
    np.testing.assert_allclose(np.linalg.norm(positive), 1.0)
    np.testing.assert_allclose(np.linalg.norm(negative), 1.0)
    assert degrees_of(positive)[0] == 1
    assert degrees_of(positive)[1] == pytest.approx(90.0)
    assert degrees_of(negative) == pytest.approx((2, -30.0))
    np.testing.assert_allclose(identity, [0.0, 0.0, 0.0, 1.0])
