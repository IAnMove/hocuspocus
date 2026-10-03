"""Sit on a seat, reach a point and look at something, with the feet planted."""
import numpy as np
import pytest

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.clips import default_rig
from services.humanoid_rig.errors import InvalidInput
from services.humanoid_rig.interactions import look_clip, reach_clip, sit_clip
from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES


def _motion(rig, clip):
    count = len(clip["times"])
    local = np.stack([clip["rotations"].get(name, np.tile(rig.rest_local[index], (count, 1)))
                      for index, name in enumerate(BONE_NAMES)], axis=1)
    return rig.forward(local, clip["hips_translation"])


def _feet_drift(rig, positions):
    return max(float(np.max(np.ptp(positions[:, BONE_BY_NAME[f"{side}Foot"]][:, [0, 2]], axis=0))) for side in ("Left", "Right"))


@pytest.mark.parametrize("seat", ([0.0, 0.45, -0.35], [0.05, 0.6, -0.3], [-0.05, 0.4, -0.4]))
def test_the_hips_settle_on_the_seat_and_the_feet_stay_on_the_floor(seat):
    rig = default_rig()
    clip = sit_clip(rig, seat, 3.0)
    positions, _worlds = _motion(rig, clip)
    hips = positions[-1, BONE_BY_NAME["Hips"]]
    tolerance = 0.02  # metres for this 1.7 m rig: the roadmap's 2 cm, scaled to the character's height
    assert abs(float(hips[1] - (seat[1] + 0.16 * rig.leg))) < tolerance
    assert np.allclose(hips[[0, 2]], [seat[0], seat[2]], atol=tolerance)
    assert _feet_drift(rig, positions) < 0.025 * rig.leg, "only the small outward shuffle"
    ankles = positions[:, [BONE_BY_NAME["LeftFoot"], BONE_BY_NAME["RightFoot"]], 1]
    assert float(np.ptp(ankles)) < 0.005, "the ankles stay at floor height"
    assert clip["warnings"] == []


def test_standing_up_returns_to_the_start():
    rig = default_rig()
    clip = sit_clip(rig, [0.0, 0.45, -0.35], 4.0, stand_up=True)
    positions, _worlds = _motion(rig, clip)
    assert np.allclose(positions[-1, BONE_BY_NAME["Hips"]], positions[0, BONE_BY_NAME["Hips"]], atol=0.01)


def test_unusual_or_far_seats_are_flagged():
    rig = default_rig()
    assert any(item.startswith("seat_height_unusual") for item in sit_clip(rig, [0.0, 0.05, -0.3], 3.0)["warnings"])
    assert any(item.startswith("seat_out_of_reach") for item in sit_clip(rig, [0.0, 0.45, -1.2], 3.0)["warnings"])


@pytest.mark.parametrize("target,hand", [([0.35, 1.2, 0.25], "left"), ([-0.5, 1.4, 0.3], "right"), ([0.2, 0.6, 0.5], "left")])
def test_a_reachable_target_is_reached_within_one_percent_of_the_arm(target, hand):
    rig = default_rig()
    clip = reach_clip(rig, target, duration=2.0)
    positions, _worlds = _motion(rig, clip)
    assert clip["hand"] == hand
    wrist = positions[-1, BONE_BY_NAME[f"{hand.capitalize()}Hand"]]
    assert float(np.linalg.norm(wrist - np.asarray(target))) < 0.01 * rig.arm
    assert _feet_drift(rig, positions) < 0.002 * rig.leg
    assert clip["warnings"] == []


def test_a_near_target_keeps_the_body_upright_and_a_far_one_is_flagged():
    rig = default_rig()
    near = reach_clip(rig, [0.35, 1.2, 0.25])
    assert np.allclose(near["rotations"]["Spine"][-1], near["rotations"]["Spine"][0], atol=1e-6), "no lean needed"
    far = reach_clip(rig, [0.4, 1.0, 1.8])
    assert any(item.startswith("target_out_of_reach") for item in far["warnings"])


def test_a_reach_without_hold_returns_the_hand():
    rig = default_rig()
    clip = reach_clip(rig, [0.35, 1.2, 0.25], duration=2.0, hold=False)
    positions, _worlds = _motion(rig, clip)
    hand = positions[:, BONE_BY_NAME["LeftHand"]]
    assert np.allclose(hand[-1], hand[0], atol=0.01)


def test_the_head_turns_toward_what_it_looks_at():
    rig = default_rig()
    target = np.array([1.5, 1.6, 1.0])
    clip = look_clip(rig, target, 2.0)
    _positions, worlds = _motion(rig, clip)
    forward = rot.rotate(worlds[-1, BONE_BY_NAME["Head"]], np.array([0.0, 0.0, 1.0]))
    toward = target - _positions[-1, BONE_BY_NAME["Head"]]
    yaw_gap = np.degrees(np.arctan2(forward[0], forward[2]) - np.arctan2(toward[0], toward[2]))
    assert abs(float(yaw_gap)) < 3.0


@pytest.mark.parametrize("call", [
    lambda rig: sit_clip(rig, [0, 0.4], 3.0), lambda rig: sit_clip(rig, [0, 0.4, 0], 0.2),
    lambda rig: reach_clip(rig, [0, 1, float("nan")]), lambda rig: reach_clip(rig, [0, 1, 1], hand="both"),
])
def test_bad_requests_are_refused(call):
    with pytest.raises(InvalidInput):
        call(default_rig())


def test_a_rigged_glb_gets_interaction_clips_with_named_warnings():
    from services.humanoid_rig.animate import animate_humanoid
    from services.humanoid_rig.rig import rig_humanoid
    from tests.humanoid_bodies import as_glb, body

    rigged, _sidecar = rig_humanoid(as_glb(body("human_t")), ["idle"], 120)
    _data, clips, warnings = animate_humanoid(rigged, [], 120, interactions=[
        {"kind": "sit", "seat": [0.0, 0.45, -0.35]}, {"kind": "reach", "target": [0.0, 1.0, 3.0]}, {"kind": "look", "target": [1, 1.5, 1]}])
    assert [clip["name"] for clip in clips] == ["Sit", "Reach", "Look"]
    assert any(item.startswith("Reach: target_out_of_reach") for item in warnings)
