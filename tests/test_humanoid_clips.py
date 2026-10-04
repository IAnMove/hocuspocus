"""Clip library: loops, tempo, ground contact, joint sanity and pose independence."""
import math

import numpy as np
import pytest

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.clips import FPS, clip_catalog, clip_library, default_rig, rig_for_skeleton
from services.humanoid_rig.landmarks import detect_landmarks
from services.humanoid_rig.motion import lowest_contact
from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES, CLIP_IDS, CLIP_LABELS
from services.humanoid_rig.skeleton import build_skeleton
from tests.humanoid_bodies import body

PLANTED = ("idle", "breathe", "wave", "cheer", "dance_bounce", "clap", "punch", "victory", "talk", "nod",
           "look_around", "bow", "point", "shrug", "dance_arms")


def _rig(kind):
    item = body(kind)
    found = detect_landmarks(item["positions"], item["indices"])
    skeleton = build_skeleton(found["points"], found["height"], found["y_min"], found["facing"], found["head_region"])
    return rig_for_skeleton(skeleton)


def _locals(rig, clip):
    """Every bone's track. A freshly built rig stores canonical frames, so these are canonical locals."""
    assert np.allclose(rig.correction, rot.IDENTITY)
    count = len(clip["times"])
    return np.stack([clip["rotations"].get(name, np.tile(rig.rest_local[index], (count, 1))) for index, name in enumerate(BONE_NAMES)], axis=1)


def test_catalog_lists_every_clip_with_a_category():
    catalog = clip_catalog()
    assert [item["id"] for item in catalog] == list(CLIP_IDS)
    assert all(item["category"] and item["description"] and item["beats"] in (2, 4) for item in catalog)
    assert CLIP_LABELS["walk"] == "Walk" and CLIP_LABELS["dance_side"] == "Dance Side"


def test_every_clip_loops_and_lasts_whole_beats():
    for clip in clip_library(96.0):
        duration = clip["beats"] * 60.0 / 96.0
        assert clip["duration"] == pytest.approx(duration)
        assert clip["times"][0] == 0.0 and clip["times"][-1] == pytest.approx(duration)
        assert len(clip["times"]) == math.ceil(duration * FPS) + 1
        for name, track in clip["rotations"].items():
            assert abs(abs(float(track[0] @ track[-1])) - 1.0) < 1e-9, (clip["id"], name)
            assert np.allclose(np.linalg.norm(track, axis=1), 1.0, atol=1e-6)
        assert np.allclose(clip["hips_translation"][0], clip["hips_translation"][-1])


def test_library_is_deterministic_and_validates_its_inputs():
    first = clip_library(120.0, ["walk", "jump"])
    second = clip_library(120.0, ["walk", "jump"])
    for one, two in zip(first, second):
        assert all(np.array_equal(one["rotations"][name], two["rotations"][name]) for name in one["rotations"])
    for bad in (59.0, 181.0, float("nan")):
        with pytest.raises(ValueError):
            clip_library(bad, ["walk"])
    with pytest.raises(ValueError, match="unknown clip id"):
        clip_library(120.0, ["moonwalk"])


@pytest.mark.parametrize("kind", ("human_t", "pet"))
def test_feet_stay_on_the_floor_and_never_sink(kind):
    rig = _rig(kind)
    for clip in clip_library(120.0, rig=rig):
        positions, worlds = rig.forward(_locals(rig, clip), clip["hips_translation"])
        lowest = lowest_contact(rig, positions, worlds) - rig.floor
        assert float(lowest.min()) > -rig.leg * 0.01, clip["id"]
        if clip["id"] in PLANTED:
            assert float(np.abs(lowest).max()) < rig.leg * 0.01, clip["id"]
    walk = clip_library(120.0, ["walk"], rig)[0]
    positions, worlds = rig.forward(_locals(rig, walk), walk["hips_translation"])
    assert float(np.abs(lowest_contact(rig, positions, worlds) - rig.floor).max()) < rig.leg * 0.03


def test_jumps_and_runs_leave_the_ground():
    rig = default_rig()
    for clip_id, height in (("jump", 0.15), ("run", 0.02)):
        clip = clip_library(120.0, [clip_id], rig)[0]
        positions, worlds = rig.forward(_locals(rig, clip), clip["hips_translation"])
        assert float((lowest_contact(rig, positions, worlds) - rig.floor).max()) > rig.leg * height, clip_id


def test_knees_and_elbows_never_bend_backwards():
    for clip in clip_library(120.0):
        for side in ("Left", "Right"):
            knee = clip["rotations"][f"{side}Leg"]
            assert float((np.sign(knee[:, 3]) * knee[:, 0]).min()) > -0.01, clip["id"]
            elbow = clip["rotations"][f"{side}ForeArm"]
            sign = 1.0 if side == "Left" else -1.0
            assert float((np.sign(elbow[:, 3]) * elbow[:, 1] * -sign).min()) > -0.01, clip["id"]


def test_an_a_pose_body_moves_its_arms_like_a_t_pose_body():
    t_rig, a_rig = _rig("human_t"), _rig("human_a")
    for clip_id in ("wave", "walk", "clap"):
        t_clip, a_clip = clip_library(120.0, [clip_id], t_rig)[0], clip_library(120.0, [clip_id], a_rig)[0]
        _positions, t_worlds = t_rig.forward(_locals(t_rig, t_clip), t_clip["hips_translation"])
        _positions, a_worlds = a_rig.forward(_locals(a_rig, a_clip), a_clip["hips_translation"])
        for bone in ("LeftArm", "RightForeArm", "LeftUpLeg"):
            index = BONE_BY_NAME[bone]
            axis = np.array([1.0, 0.0, 0.0]) if "Arm" in bone else np.array([0.0, -1.0, 0.0])
            t_dir, a_dir = rot.rotate(t_worlds[:, index], axis), rot.rotate(a_worlds[:, index], axis)
            assert float(np.sum(t_dir * a_dir, axis=1).min()) > math.cos(math.radians(6.0)), (clip_id, bone)


@pytest.mark.parametrize("kind", ("human_t", "pet"))
def test_planted_feet_do_not_slide(kind):
    rig = _rig(kind)
    for clip_id in ("idle", "dance_bounce", "clap", "wave", "bow"):
        clip = clip_library(120.0, [clip_id], rig)[0]
        positions, _worlds = rig.forward(_locals(rig, clip), clip["hips_translation"])
        for side in ("Left", "Right"):
            ankle = positions[:, BONE_BY_NAME[f"{side}Foot"]]
            drift = np.ptp(ankle, axis=0)
            assert float(max(drift[0], drift[2])) < rig.leg * 0.002, (clip_id, side, drift)
    walk = clip_library(120.0, ["walk"], rig)[0]
    positions, _worlds = rig.forward(_locals(rig, walk), walk["hips_translation"])
    assert float(np.ptp(positions[:, BONE_BY_NAME["LeftFoot"], 0])) < rig.leg * 0.002


@pytest.mark.parametrize("kind", ("human_t", "human_a", "pet"))
def test_clapping_hands_meet_palm_to_palm(kind):
    rig = _rig(kind)
    clip = clip_library(120.0, ["clap"], rig)[0]
    positions, worlds = rig.forward(_locals(rig, clip), clip["hips_translation"])
    left, right = BONE_BY_NAME["LeftHand"], BONE_BY_NAME["RightHand"]
    gap = np.linalg.norm(positions[:, left] - positions[:, right], axis=1)
    frame = int(np.argmin(gap))
    toward = (positions[frame, right] - positions[frame, left]) / gap[frame]
    palm = np.array([0.0, -1.0, 0.0])
    assert gap[frame] < rig.arm * 0.2
    assert float(rot.rotate(worlds[frame, left], palm) @ toward) > 0.85
    assert float(-(rot.rotate(worlds[frame, right], palm) @ toward)) > 0.85


@pytest.mark.parametrize("clip_id,side,at,facing", (("shrug", "Left", 0.45, (0.0, 1.0, 0.0)), ("wave", "Right", 0.0, (0.0, 0.0, 1.0)),
                                                    ("talk", "Left", 0.2, (0.0, 1.0, 0.0))))
def test_palms_face_the_way_the_gesture_reads(clip_id, side, at, facing):
    """A shrug and a talking hand open upward; a wave shows the palm to the front."""
    for kind in ("human_t", "pet"):
        rig = _rig(kind)
        clip = clip_library(120.0, [clip_id], rig)[0]
        _positions, worlds = rig.forward(_locals(rig, clip), clip["hips_translation"])
        frame = int(len(clip["times"]) * at)
        palm = rot.rotate(worlds[frame, BONE_BY_NAME[f"{side}Hand"]], np.array([0.0, -1.0, 0.0]))
        assert float(palm @ np.asarray(facing)) > 0.55, (kind, clip_id, palm)
