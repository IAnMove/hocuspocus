"""Action clips: rifle aim and recoil, claw slashes, a hit reaction, a hover, and the kneel and crouch holds."""
import math

import numpy as np
import pytest

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.clip_recipes import HOLDS
from services.humanoid_rig.clips import FPS, clip_catalog, clip_library, rig_for_skeleton
from services.humanoid_rig.landmarks import detect_landmarks
from services.humanoid_rig.motion import lowest_contact
from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES, CLIP_LABELS
from services.humanoid_rig.skeleton import build_skeleton
from tests.humanoid_bodies import as_glb, body

ACTION = ("aim", "shoot", "claw", "hit", "hover", "kneel_pray", "crouch")
_SKELETONS = {}


def _rig(kind, limits=None):
    if kind not in _SKELETONS:
        item = body(kind)
        found = detect_landmarks(item["positions"], item["indices"])
        _SKELETONS[kind] = build_skeleton(found["points"], found["height"], found["y_min"], found["facing"], found["head_region"])
    return rig_for_skeleton(_SKELETONS[kind], limits)


def _play(rig, clip_id, bpm=120.0):
    clip = clip_library(bpm, [clip_id], rig)[0]
    count = len(clip["times"])
    local = np.stack([clip["rotations"].get(name, np.tile(rig.rest_local[index], (count, 1))) for index, name in enumerate(BONE_NAMES)], axis=1)
    positions, worlds = rig.forward(local, clip["hips_translation"])
    return clip, positions, worlds


def _at(rig, positions, bone):
    """A joint's track in the character's frame (x left, y up, z forward), metres from the rest root."""
    return rot.rotate(rot.inverse(rig.facing), positions[:, BONE_BY_NAME[bone]] - rig.root)


def _axis(rig, worlds, bone, axis):
    return rot.rotate(rot.inverse(rig.facing), rot.rotate(worlds[:, BONE_BY_NAME[bone]], np.asarray(axis, dtype=np.float64)))


def _unit(vectors):
    return vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)


def _steps(clip):
    """Largest bone rotation, in degrees, from each key to the next."""
    tracks = np.stack(list(clip["rotations"].values()), axis=1)
    dots = np.clip(np.abs(np.sum(tracks[1:] * tracks[:-1], axis=-1)), 0.0, 1.0)
    return np.degrees(2.0 * np.arccos(dots)).max(axis=1)


@pytest.mark.parametrize("bpm", (60.0, 120.0, 180.0))
def test_action_clips_are_finite_and_last_whole_beats(bpm):
    for kind in ("human_t", "pet"):
        for clip in clip_library(bpm, list(ACTION), _rig(kind)):
            tracks = np.stack(list(clip["rotations"].values()))
            assert np.all(np.isfinite(tracks)) and np.all(np.isfinite(clip["hips_translation"])), (kind, clip["id"])
            assert np.allclose(np.linalg.norm(tracks, axis=-1), 1.0, atol=1e-6)
            assert clip["duration"] == pytest.approx(clip["beats"] * 60.0 / bpm)
            assert len(clip["times"]) == math.ceil(clip["duration"] * FPS) + 1


def test_loops_have_no_seam_and_holds_come_to_rest():
    rig = _rig("human_t")
    catalog = {item["id"]: item for item in clip_catalog()}
    stance = clip_library(120.0, ["bow"], rig)[0]["rotations"]  # the bow starts from the plain standing stance
    for clip_id in ACTION:
        clip = clip_library(120.0, [clip_id], rig)[0]
        steps = _steps(clip)
        assert catalog[clip_id]["loop"] is clip["loop"] is (clip_id not in HOLDS)
        if clip["loop"]:
            # The pinned last key repeats the first: the step into it is no bigger than the motion elsewhere.
            assert steps[-1] <= 1.5 * steps[:-1].max() + 0.5, clip_id
        else:
            # A hold starts from the standing stance, so it crossfades from Idle, and ends still, in the pose it keeps.
            start = max(math.degrees(2.0 * math.acos(min(1.0, abs(float(track[0] @ stance[name][0]))))) for name, track in clip["rotations"].items())
            assert start < 8.0, clip_id
            assert float(steps[-3:].max()) < 0.2, clip_id
            first, last = (np.stack([track[index] for track in clip["rotations"].values()]) for index in (0, -1))
            assert float(np.abs(np.sum(first * last, axis=-1)).min()) < 0.95, clip_id
            assert float(np.linalg.norm(clip["hips_translation"][-1] - clip["hips_translation"][0])) > rig.leg * 0.2


@pytest.mark.parametrize("kind", ("human_t", "human_a", "pet"))
def test_kneel_pray_rests_both_knees_on_the_floor_with_the_hands_joined(kind):
    rig = _rig(kind)
    clip, positions, worlds = _play(rig, "kneel_pray")
    hold = slice(int(0.3 * len(clip["times"])), None)
    floor = rig.floor - rig.root[1]
    knees = [(_at(rig, positions, f"{side}Leg")[hold] - [0.0, floor, 0.0]) / rig.leg for side in ("Left", "Right")]
    for knee, side in zip(knees, ("Left", "Right")):
        # The knee joint sits about as high over the floor as the standing ankle: on the knee, neither through nor above.
        ankle_height = float(_at(rig, positions, f"{side}Foot")[0, 1] - floor) / rig.leg
        assert 0.5 * ankle_height < float(knee[:, 1].min()) and float(knee[:, 1].max()) < ankle_height + 0.01, (side, knee[:, 1].min())
        ankle = _at(rig, positions, f"{side}Foot")[hold]
        assert float((ankle[:, 2] - knee[:, 2] * rig.leg).max()) < -0.2 * rig.leg  # the shins reach back along the floor
    assert float(np.abs(knees[0][:, 1] - knees[1][:, 1]).max()) < 0.02
    hips = abs(float(_at(rig, positions, "LeftUpLeg")[0, 0] - _at(rig, positions, "RightUpLeg")[0, 0]))
    assert abs(float(knees[0][-1, 0] - knees[1][-1, 0])) * rig.leg < 1.6 * hips  # knees together, not splayed
    left, right = _at(rig, positions, "LeftHand")[-1], _at(rig, positions, "RightHand")[-1]
    assert float(np.linalg.norm(left - right)) < 0.15 * rig.arm
    assert float(left[2] - _at(rig, positions, "Spine2")[-1, 2]) > rig.limits["chest_front"]
    toward = _unit(right - left)
    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        fingers = _axis(rig, worlds, f"{side}Hand", (sign, 0.0, 0.0))[-1]
        palm = _axis(rig, worlds, f"{side}Hand", (0.0, -1.0, 0.0))[-1]
        assert fingers[1] > 0.8, (side, fingers)
        assert float(palm @ toward) * sign > 0.8, (side, palm)
    assert float(_axis(rig, worlds, "Head", (0.0, 0.0, 1.0))[-1, 1]) < -0.25  # head bowed
    assert [item["foot"] for item in clip["contacts"]] == ["right", "left"]


@pytest.mark.parametrize("kind,aside", (("human_t", 12.0), ("human_a", 12.0), ("pet", 20.0)))
def test_aim_holds_the_rifle_line_forward_at_shoulder_height(kind, aside):
    """``aside``: how far the line may turn from straight ahead; a short-armed mascot's support hand stops a little short."""
    rig = _rig(kind)
    _clip, positions, _worlds = _play(rig, "aim")
    grip, support = _at(rig, positions, "RightHand"), _at(rig, positions, "LeftHand")
    barrel = _unit(support - grip)
    assert float(np.degrees(np.arccos(barrel[:, 2])).max()) < aside
    assert float(np.degrees(np.arccos(np.clip(barrel @ barrel.mean(axis=0) / np.linalg.norm(barrel.mean(axis=0)), -1, 1))).max()) < 2.0
    assert float(np.linalg.norm(support - grip, axis=1).min()) > 0.3 * rig.arm
    shoulder = _at(rig, positions, "RightArm")
    assert float(np.abs(grip[:, 1] - shoulder[:, 1]).max()) < 0.25 * rig.arm
    assert float(grip[:, 2].min() - shoulder[:, 2].max()) > 0.0  # the hands are out in front
    left_foot, right_foot = _at(rig, positions, "LeftFoot"), _at(rig, positions, "RightFoot")
    assert float(left_foot[0, 2] - right_foot[0, 2]) > 0.15 * rig.leg  # left foot forward in the stance


@pytest.mark.parametrize("kind", ("human_t", "pet"))
def test_the_rifle_arms_stay_smooth_on_short_arms(kind):
    """The support hand stays just within reach, so a kick never snaps a straight elbow."""
    rig = _rig(kind)
    for clip_id, largest in (("aim", 2.0), ("shoot", 25.0)):
        clip, positions, _worlds = _play(rig, clip_id)
        assert float(_steps(clip).max()) < largest, clip_id
        reach = np.linalg.norm(_at(rig, positions, "LeftHand") - _at(rig, positions, "LeftArm"), axis=1)
        assert float(reach.max()) < 0.93 * rig.arm, clip_id


def test_shoot_kicks_the_muzzle_up_on_every_beat_and_recovers():
    rig = _rig("human_t")
    clip, positions, _worlds = _play(rig, "shoot", 120.0)
    _aim, aim_positions, _aim_worlds = _play(rig, "aim", 120.0)
    frames = len(clip["times"]) - 1
    per_beat = frames // clip["beats"]

    def climb(points):
        barrel = _unit(_at(rig, points, "LeftHand") - _at(rig, points, "RightHand"))
        return np.degrees(np.arcsin(barrel[:, 1]))

    kick = climb(positions) - climb(aim_positions)[: len(positions)]
    for beat in range(clip["beats"]):
        start = beat * per_beat
        assert float(kick[start + 1:start + 3].max()) > 3.0, beat
        assert float(abs(kick[start + per_beat // 2])) < 0.3 * float(kick[start + 1:start + 3].max()), beat
    grip, shoulder = _at(rig, positions, "RightHand"), _at(rig, positions, "RightArm")
    assert float(shoulder[1, 2]) < float(shoulder[per_beat // 2, 2])  # the shoulder is pushed back by the kick


def test_claw_swipes_across_the_body_with_alternating_arms():
    rig = _rig("human_t")
    clip, positions, _worlds = _play(rig, "claw")
    frames = len(clip["times"]) - 1
    for side, sign, shift in (("Right", -1.0, 0.0), ("Left", 1.0, 0.5)):
        wrist, shoulder = _at(rig, positions, f"{side}Hand"), _at(rig, positions, f"{side}Arm")
        start, end = int(round((0.2 + shift) * frames)), int(round((0.29 + shift) * frames))
        assert sign * (wrist[start, 0] - shoulder[start, 0]) > 0.15 * rig.arm, side  # wound up out to its side
        assert wrist[start, 1] > shoulder[start, 1], side  # and high
        assert sign * wrist[end, 0] < -0.02 * rig.arm, side  # swiped past the middle of the body
        assert wrist[end, 1] < shoulder[end, 1] - 0.2 * rig.arm, side  # and low
        assert wrist[end, 2] > rig.limits["chest_front"], side  # in front of the chest
        middle = (start + end) // 2
        assert wrist[middle, 2] - shoulder[middle, 2] > 0.4 * rig.arm, side  # the arc reaches out in front


def test_hit_throws_the_chest_back_steps_back_and_recovers():
    rig = _rig("human_t")
    clip, positions, _worlds = _play(rig, "hit")
    frames = len(clip["times"]) - 1
    lean = _at(rig, positions, "Neck")[:, 2] - _at(rig, positions, "Hips")[:, 2]
    early = int(0.12 * frames)
    assert float(lean[:early].min()) < float(lean[0]) - 0.1 * rig.leg  # snapped back within the first frames
    assert int(np.argmin(lean)) <= early
    right = _at(rig, positions, "RightFoot")[:, 2]
    assert float(right.min()) < float(right[0]) - 0.25 * rig.leg
    assert [item["foot"] for item in clip["contacts"]] == ["right", "right"]


def test_hover_stays_airborne_bobs_on_the_beat_and_trails_its_legs():
    rig = _rig("human_t")
    clip, positions, worlds = _play(rig, "hover")
    clearance = (lowest_contact(rig, positions, worlds) - rig.floor) / rig.leg
    assert float(clearance.min()) > 0.15 and clip["contacts"] == []
    height = clip["hips_translation"][:-1, 1]
    peaks = [index for index in range(len(height)) if height[index] > height[index - 1] and height[index] >= height[(index + 1) % len(height)]]
    assert len(peaks) == clip["beats"]
    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        assert float((_at(rig, positions, f"{side}Foot")[:, 2] - _at(rig, positions, f"{side}UpLeg")[:, 2]).max()) < 0.0
        out = sign * (_at(rig, positions, f"{side}Hand")[:, 0] - _at(rig, positions, f"{side}Arm")[:, 0])
        assert float(out.min()) > 0.2 * rig.arm  # arms held out from the body


def test_crouch_drops_into_cover_peeks_and_stays_down():
    rig = _rig("human_t")
    clip, positions, _worlds = _play(rig, "crouch")
    frames = len(clip["times"]) - 1
    hips, head = _at(rig, positions, "Hips")[:, 1], _at(rig, positions, "Head")[:, 1]
    down, peek = int(0.2 * frames), int(0.44 * frames)
    assert float(hips[0] - hips[down]) > 0.3 * rig.leg
    assert float(head[peek] - head[down]) > 0.1 * rig.leg
    assert float(hips[-1]) == pytest.approx(float(hips[down]), abs=0.02 * rig.leg)


@pytest.mark.parametrize("kind", ("human_t", "pet"))
def test_action_clips_keep_the_arms_under_a_tight_overhead_limit(kind):
    rig = _rig(kind, {"arm_up": 50.0})
    for clip_id in ACTION:
        _clip, positions, worlds = _play(rig, clip_id)
        up = _axis(rig, worlds, "Spine2", (0.0, 1.0, 0.0))
        for side in ("Left", "Right"):
            arm = _unit(_at(rig, positions, f"{side}ForeArm") - _at(rig, positions, f"{side}Arm"))
            assert float(np.degrees(np.arcsin(np.clip(np.sum(arm * up, axis=1), -1, 1))).max()) <= 50.0, (clip_id, side)
            for upper, lower, limit in ((f"{side}UpLeg", f"{side}Leg", 170.0), (f"{side}Arm", f"{side}ForeArm", 165.0)):
                end = {"Leg": "Foot", "ForeArm": "Hand"}[lower.replace(side, "")]
                one = _unit(_at(rig, positions, lower) - _at(rig, positions, upper))
                two = _unit(_at(rig, positions, f"{side}{end}") - _at(rig, positions, lower))
                assert float(np.degrees(np.arccos(np.clip(np.sum(one * two, axis=1), -1, 1))).max()) < limit, (clip_id, lower)


def test_rigged_and_animated_glbs_carry_the_action_clips_by_name():
    pytest.importorskip("pygltflib")
    from pygltflib import GLTF2

    from services.humanoid_rig.animate import animate_humanoid
    from services.humanoid_rig.rig import rig_humanoid

    rigged, sidecar = rig_humanoid(as_glb(body("human_t")), list(ACTION), 120.0)
    gltf = GLTF2.load_from_bytes(rigged)
    assert [item.name for item in gltf.animations] == [CLIP_LABELS[clip_id] for clip_id in ACTION]
    for animation, clip_id in zip(gltf.animations, ACTION):
        assert (animation.extras or {}).get("hocuspocus_loop", True) is (clip_id not in HOLDS)
    assert {row["id"]: row["loop"] for row in sidecar["clips"]} == {clip_id: clip_id not in HOLDS for clip_id in ACTION}
    _data, listed, warnings = animate_humanoid(rigged, ["kneel_pray", "aim"], 96.0)
    assert warnings == []
    assert [(row["index"], row["name"], row["loop"]) for row in listed] == [(7, "Kneel Pray", False), (8, "Aim", True)]
    assert listed[0]["duration"] == pytest.approx(16 * 60.0 / 96.0)


def test_rig_and_animate_requests_accept_the_action_ids():
    from routers.model3d_animate import _clip_ids
    from services.rig_service import _humanoid_animation_catalog, _humanoid_animations

    assert _humanoid_animations(list(ACTION)) == list(ACTION)
    assert _clip_ids(["hover", "claw"]) == ["hover", "claw"]
    listed = {item["id"]: item for item in _humanoid_animation_catalog()}
    assert {listed[clip_id]["category"] for clip_id in ACTION} <= {"Action", "Move", "Gesture"}
    assert [clip_id for clip_id in ACTION if not listed[clip_id]["loop"]] == ["kneel_pray", "crouch"]
