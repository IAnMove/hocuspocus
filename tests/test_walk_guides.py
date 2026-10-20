"""The walk computed in 3D that guides the poses of a walk sheet (services/walk_guides.py)."""
import numpy as np
import pytest
from PIL import Image

from services.walk_guides import (FEET_SHARE, TURN, WalkGuideError, curve, expected_spread, guide_image, leg_spread, parse_size, phase_of,
                                  project, to_picture, visible_face, walk_pose, HIP_KEYS)

SOLES = ("r_heel", "r_ball", "l_heel", "l_ball")


def test_a_curve_passes_through_its_keys_and_loops():
    for phase, value in HIP_KEYS:
        assert curve(HIP_KEYS, phase) == pytest.approx(value)
    assert curve(HIP_KEYS, 0.999999) == pytest.approx(curve(HIP_KEYS, 0.0), abs=1e-3)
    values = [curve(HIP_KEYS, k / 200) for k in range(200)]
    assert max(values) <= max(value for _, value in HIP_KEYS) + 1e-9, "no overshoot past the highest key"


@pytest.mark.parametrize("phase", [k / 12 for k in range(12)])
def test_the_body_stands_on_the_ground_with_one_foot_at_least_and_never_below_it(phase):
    pose = walk_pose(phase)
    lowest = min(pose[name][1] for name in SOLES)
    assert lowest == pytest.approx(0.0, abs=1e-9)
    assert all(pose[name][1] >= -1e-9 for name in pose), "nothing goes through the floor"
    assert 0.95 < pose["head_top"][1] < 1.03, "the figure is one height tall"


def test_the_second_half_of_the_cycle_is_the_first_with_the_legs_swapped():
    for k in range(6):
        first, second = walk_pose(k / 12), walk_pose(k / 12 + 0.5)
        for part in ("knee", "ankle", "heel", "toe", "elbow", "wrist"):
            mine, theirs = first[f"r_{part}"], second[f"l_{part}"]
            assert mine[:2] == pytest.approx(theirs[:2], abs=1e-6) and mine[2] == pytest.approx(-theirs[2], abs=1e-6)


def test_phase_zero_is_the_contact_of_the_right_leg_and_the_body_rises_to_the_passing_pose():
    contact, passing = walk_pose(0.0), walk_pose(0.25)
    assert contact["r_ankle"][0] > 0.15 > -0.15 > contact["l_ankle"][0], "the right foot ahead, the left behind"
    assert contact["r_heel"][1] < 0.01 and contact["l_ball"][1] < 0.01, "both feet on the ground at contact"
    assert abs(passing["l_ankle"][0] - passing["r_ankle"][0]) < 0.1 and passing["l_heel"][1] > 0.04, "the free foot passes under the body"
    assert passing["r_hip"][1] > contact["r_hip"][1] + 0.015, "the body is higher at the passing pose"
    assert contact["l_wrist"][0] > contact["r_wrist"][0], "the arm against the forward leg swings forward"


def test_each_direction_turns_the_body_toward_its_side_of_the_picture():
    pose = walk_pose(0.0)
    side, front, back = (to_picture(pose, direction) for direction in ("side", "front", "back"))
    assert side["nose"][0] > side["head"][0] and side["r_hip"][2] > side["l_hip"][2], "the profile looks right with its right side to us"
    assert front["nose"][2] > front["head"][2] and front["r_hip"][0] < front["l_hip"][0], "from the front its right is on our left"
    assert back["nose"][2] < back["head"][2] and back["r_hip"][0] > back["l_hip"][0]
    three = to_picture(pose, "front34")
    assert three["nose"][0] > three["head"][0] and three["nose"][2] > three["head"][2], "toward us and to our right"


def test_the_face_shows_only_from_the_front_and_one_eye_and_ear_in_profile():
    assert visible_face("front") == {"nose", "r_eye", "l_eye", "r_ear", "l_ear"}
    assert visible_face("side") == {"nose", "r_eye", "r_ear"}
    assert {"nose", "r_eye", "l_eye"}.isdisjoint(visible_face("back")) and {"r_ear", "l_ear"} <= visible_face("back")
    assert "nose" not in visible_face("back34") and "nose" in visible_face("front34")


def test_a_guide_is_the_size_asked_with_the_feet_on_the_line_and_differs_by_direction():
    size = (448, 576)
    pictures = {direction: guide_image(direction, 0.0, size, "skeleton") for direction in TURN}
    assert all(picture.size == size for picture in pictures.values())
    hashes = {np.asarray(picture.convert("L").resize((32, 40))).tobytes() for picture in pictures.values()}
    assert len(hashes) == 5
    mannequin = np.asarray(guide_image("side", 0.0, size, "mannequin").convert("L")) < 250
    bottom = int(np.nonzero(mannequin.any(axis=1))[0][-1])
    assert abs(bottom - size[1] * FEET_SHARE) < size[1] * 0.03
    placed = project(to_picture(walk_pose(0.0), "front"), size)
    assert placed["r_toe"][1] > placed["l_toe"][1], "the foot that steps toward the camera is lower in the picture"


def test_the_back_view_starts_with_the_leg_on_the_viewers_left_as_the_catalog_says():
    picture = np.asarray(guide_image("back", 0.0, (448, 576), "skeleton").convert("RGB")).astype(int)
    left_leg, right_leg = (0, 85, 255), (0, 255, 170)  # OpenPose: the left shin is blue, the right one green
    def lowest(colour):
        rows = np.nonzero((np.abs(picture - np.array(colour)).sum(axis=2) < 30).any(axis=1))[0]
        return rows.max()
    assert lowest(left_leg) > 0 and lowest(right_leg) > 0


def test_the_legs_are_wide_in_a_profile_stride_and_narrow_at_the_passing_pose_and_from_the_front():
    assert expected_spread("side", 0.0) > 0.55 > 0.4 > expected_spread("side", 0.25)
    assert all(expected_spread("front", k / 12) < 0.25 for k in range(12))
    assert expected_spread("front34", 0.0) != pytest.approx(expected_spread("front34", 0.5), abs=0.05), "the near leg ahead looks wider"
    figure = Image.new("RGBA", (100, 200), (0, 0, 0, 0))
    figure.paste((10, 10, 10, 255), (40, 0, 60, 200))
    figure.paste((10, 10, 10, 255), (10, 160, 90, 200))
    assert leg_spread(figure) == pytest.approx(80 / 200)
    assert leg_spread(Image.new("RGBA", (10, 10))) == 0.0


def test_a_sheet_splits_one_cycle_and_bad_input_is_refused():
    assert [phase_of(index, 4) for index in range(4)] == [0.0, 0.25, 0.5, 0.75]
    assert parse_size("896x1152") == (896, 1152)
    for bad in (lambda: phase_of(4, 4), lambda: parse_size("big"), lambda: parse_size("10x10"), lambda: guide_image("left", 0.0),
                lambda: guide_image("side", 0.0, style="sketch")):
        with pytest.raises(WalkGuideError):
            bad()
