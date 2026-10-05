"""Landmarks from the front silhouette: accuracy on built bodies, and honest refusals."""
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.landmarks import detect_landmarks
from services.humanoid_rig.names import LANDMARK_NAMES
from services.procedural_3d.compose import compose_glb
from services.procedural_3d.glb_container import parse_glb_container
from tests.humanoid_bodies import body, transformed

ROOT = Path(__file__).parents[1] / "tests" / "fixtures" / "humanoid_rig"
ARM_JOINTS = ("shoulder", "elbow", "wrist", "hand_tip")
LEG_JOINTS = ("knee", "ankle")
# Mascot legs are short and their feet are balls, so the knee and ankle have less to go on.
LEG_LIMIT = {"pet": 0.045, "alien": 0.045}


def _found(item):
    return detect_landmarks(item["positions"], item["indices"])


def _error(found, item, name):
    return float(np.linalg.norm(np.asarray(found["points"][name]) - item["joints"][name])) / found["height"]


@pytest.mark.parametrize("kind", ["human_t", "human_a", "human_hat", "pet", "alien"])
def test_limb_joints_match_the_built_body(kind):
    item = body(kind)
    found = _found(item)
    assert list(found["points"]) == list(LANDMARK_NAMES)
    for side in ("left", "right"):
        for joint in ARM_JOINTS:
            assert _error(found, item, f"{side}_{joint}") < 0.03, (side, joint)
        for joint in LEG_JOINTS:
            assert _error(found, item, f"{side}_{joint}") < LEG_LIMIT.get(kind, 0.03), (side, joint)
        assert _error(found, item, f"{side}_hip") < 0.08
    assert _error(found, item, "crown") < 0.03


def test_pose_and_arm_angle_are_measured():
    assert _found(body("human_t"))["pose"] == "t"
    a_pose = _found(body("human_a"))
    assert a_pose["pose"] == "a" and abs(a_pose["arm_drop"] - 40.0) < 3.0
    steep = _found(body("human_a_steep"))
    assert abs(steep["arm_drop"] - 62.0) < 4.0
    assert "arms_steep" in steep["warnings"] and steep["confidence"] < 1.0


def test_big_ears_belong_to_the_head_and_not_to_the_arms():
    item = body("alien")
    found = _found(item)
    assert _error(found, item, "left_hand_tip") < 0.03
    region = found["head_region"]
    assert region["half"] > 0.35
    assert region["y"] < found["points"]["head"][1] < found["points"]["crown"][1]
    assert found["points"]["left_shoulder"][1] < region["y"]


def test_long_hair_and_a_skirt_do_not_put_the_neck_at_the_waist():
    item = body("long_hair_skirt")
    found = _found(item)
    for side in ("left", "right"):
        for joint in ARM_JOINTS:
            # The torso width is measured at the skirt, which pushes the shoulder out a little.
            assert _error(found, item, f"{side}_{joint}") < (0.04 if joint == "shoulder" else 0.03), (side, joint)
    assert found["pose"] == "t"
    assert found["points"]["neck"][1] > item["joints"]["left_shoulder"][1], "the neck is above the arms, not at the waist"


def test_a_cape_over_the_shoulders_does_not_hide_the_arms():
    item = body("cape")
    found = _found(item)
    assert "covered_arms" in found["warnings"] and found["confidence"] == 1.0
    for side in ("left", "right"):
        for joint in ARM_JOINTS:
            # Without looking under the cape, the shoulder sat at the cape's edge, 0.12 of the height out.
            assert _error(found, item, f"{side}_{joint}") < (0.04 if joint == "shoulder" else 0.03), (side, joint)
    cloth, points = found["cloth"], item["positions"]
    assert cloth.sum() > 500, "the sheets hanging beside the torso are cloth"
    assert not cloth[np.abs(points[:, 0]) > 0.45].any(), "the forearms and hands are not"
    assert not cloth[points[:, 1] < 1.1].any(), "nor is anything below the cape"


def test_a_cape_behind_the_legs_is_looked_behind():
    item = body("back_cape")
    found = _found(item)
    assert {"covered_legs", "covered_arms"} <= set(found["warnings"]) and found["confidence"] == 1.0
    for side in ("left", "right"):
        for joint in ARM_JOINTS + LEG_JOINTS:
            assert _error(found, item, f"{side}_{joint}") < 0.03, (side, joint)
        assert _error(found, item, f"{side}_hip") < 0.08
    assert abs(found["points"]["crotch"][2]) < 0.02, "the cape behind does not pull the hips back"
    cloth, points = found["cloth"], item["positions"]
    cape = (points[:, 2] < -0.2) & (points[:, 1] < 1.0)
    assert cloth[cape].mean() > 0.95 and cloth[points[:, 2] > -0.15].mean() < 0.01


def test_legs_hidden_by_a_robe_are_placed_from_the_feet():
    item = body("robe")
    found = _found(item)
    assert "legs_hidden" in found["warnings"] and found["confidence"] < 1.0
    for side in ("left", "right"):
        for joint in ARM_JOINTS + LEG_JOINTS:
            assert _error(found, item, f"{side}_{joint}") < 0.03, (side, joint)
        assert _error(found, item, f"{side}_hip") < 0.08
    hem = found["robe"]["hem"]
    assert found["points"]["left_ankle"][1] < hem < found["points"]["left_knee"][1]
    assert _found(body("human_a"))["robe"] is None


@pytest.mark.parametrize("kind", ["human_t", "human_a", "long_hair_skirt"])
def test_a_body_without_cloth_has_none(kind):
    found = _found(body(kind))
    assert not found["cloth"].any()
    assert not {"covered_arms", "covered_legs", "legs_hidden"} & set(found["warnings"])


@pytest.mark.parametrize("kind,reason", [("arms_down", "hands_stuck"), ("legs_together", "single_leg"), ("penguin", "single_leg"),
                                         ("robe_to_floor", "single_leg")])
def test_bodies_that_cannot_be_rigged_are_refused(kind, reason):
    with pytest.raises(NotHumanoid) as caught:
        _found(body(kind))
    assert caught.value.reason == reason
    assert str(caught.value).startswith("not_humanoid:")


def test_a_body_facing_back_is_turned_and_reported():
    item = transformed(body("human_t"), yaw_degrees=180.0)
    found = _found(item)
    assert found["facing"] == -1 and "facing_back" in found["warnings"]
    assert found["points"]["left_hand_tip"][0] < found["points"]["crotch"][0]
    for joint in ("left_shoulder", "right_wrist", "left_knee"):
        assert _error(found, item, joint) < 0.03


def test_a_body_away_from_the_origin_is_found_where_it_stands():
    item = transformed(body("human_a"), offset=(2.0, 0.5, -1.0))
    found = _found(item)
    for joint in ("left_shoulder", "right_elbow", "left_ankle"):
        assert _error(found, item, joint) < 0.03


def test_a_lying_body_is_not_upright():
    item = body("human_t")
    lying = item["positions"][:, [0, 2, 1]] * np.array([1.0, 1.0, -1.0])
    with pytest.raises(NotHumanoid) as caught:
        detect_landmarks(lying, item["indices"])
    assert caught.value.reason == "not_upright"


def test_detection_is_deterministic_and_a_soup_matches_indexed():
    item = body("human_a")
    first = _found(item)
    assert _found(item)["points"] == first["points"]
    soup = item["positions"][item["indices"]].reshape(-1, 3)
    assert detect_landmarks(soup)["points"] == first["points"]


def test_degenerate_mesh_is_rejected():
    with pytest.raises(NotHumanoid) as caught:
        detect_landmarks(np.zeros((3, 3)))
    assert caught.value.reason == "degenerate"


def _compose(name):
    fixture = json.loads((ROOT / f"{name}.json").read_text())
    container = parse_glb_container(compose_glb(fixture["pieces"], name), max_chunks=2, max_json_bytes=200_000)
    document = json.loads(container.json_bytes)
    count = document["accessors"][0]["count"]
    offset = document["bufferViews"][0].get("byteOffset", 0)
    cloud = np.asarray(struct.unpack_from(f"<{count * 3}f", container.bin_bytes, offset)).reshape(-1, 3)
    return fixture, cloud


@pytest.mark.parametrize("name", ("robot", "pet", "a_pose"))
def test_box_built_figures_rig_even_with_gaps_between_pieces(name):
    fixture, cloud = _compose(name)
    found = detect_landmarks(cloud)
    built = fixture["landmarks"]
    height = found["height"]
    pairs = (("left_hand_tip", "left_hand", 0.03), ("right_hand_tip", "right_hand", 0.03), ("left_knee", "left_knee", 0.04),
             ("crown", "crown", 0.01), ("left_elbow", "left_elbow", 0.07), ("left_shoulder", "left_shoulder", 0.07))
    for ours, theirs, limit in pairs:
        error = np.linalg.norm(np.asarray(found["points"][ours]) - np.asarray(built[theirs])) / height
        assert error < limit, ours


@pytest.mark.parametrize("name", ("hands_stuck", "one_leg"))
def test_box_figures_that_cannot_be_rigged_keep_their_reason(name):
    fixture, cloud = _compose(name)
    with pytest.raises(NotHumanoid) as caught:
        detect_landmarks(cloud)
    assert caught.value.reason == fixture["reason"]


def test_arms_a_little_above_horizontal_are_found_and_far_above_are_refused():
    item = body("arms_raised")
    found = _found(item)
    assert found["arm_drop"] < -10.0
    for joint in ("left_elbow", "right_wrist", "left_hand_tip"):
        assert _error(found, item, joint) < 0.03
    with pytest.raises(NotHumanoid) as caught:
        _found(body("arms_up"))
    assert caught.value.reason == "arms_raised"


def test_a_loose_prop_does_not_close_the_gap_between_the_feet():
    item = body("with_orb")
    found = _found(item)
    assert _error(found, item, "left_hand_tip") < 0.03 and _error(found, item, "right_ankle") < 0.03


def test_a_figure_on_a_base_stands_on_its_top():
    item = body("on_base")
    found = _found(item)
    assert "on_a_base" in found["warnings"] and found["confidence"] == 1.0
    assert found["base"] is not None and abs(found["y_min"] - found["base"]) < 1e-9
    assert found["base"] > float(item["positions"][:, 1].min()) + 0.04
    for joint in ("left_ankle", "right_knee"):
        assert _error(found, item, joint) < 0.03


def test_a_body_turned_away_from_the_camera_is_refused():
    with pytest.raises(NotHumanoid) as caught:
        _found(transformed(body("human_t"), yaw_degrees=45.0))
    assert caught.value.reason == "turned"


def test_an_empty_face_list_is_degenerate():
    item = body("human_t")
    with pytest.raises(NotHumanoid) as caught:
        detect_landmarks(item["positions"], np.zeros((0, 3), dtype=np.int64))
    assert caught.value.reason == "degenerate"
