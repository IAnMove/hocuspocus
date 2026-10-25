"""A timed move (motion.start, motion.end) and the Python twin of the renderer's slotPoseAtTime."""
import json
from pathlib import Path

import pytest

from services.series_shot3d import _motion as series_motion
from services.world3d_blank_scene import editor_shape_problems
from services.world3d_scene_motion import check_motion, pose_at, window
from services.world3d_scenes import World3DSceneError, patch_scene
from tests.test_world3d_scene_layout import SCENE, WORKSPACE, scene, slot, workspace_dir

SAMPLES = json.loads((Path(__file__).parent / "fixtures" / "world3d_motion_samples.json").read_text(encoding="utf-8"))


def patch(tmp_path, bindings, revision=1, **changes):
    return patch_scene(WORKSPACE, SCENE, workspace_dir(tmp_path), {"bindings": bindings, **changes}, revision)


@pytest.mark.parametrize("case", SAMPLES["cases"], ids=lambda case: case["name"])
def test_the_python_pose_is_what_the_typescript_runtime_samples(case):
    mover = {"position": case["position"], "rotationY": case["rotationY"], "motion": case["motion"]}
    for sample in case["samples"]:
        position, rotation = pose_at(mover, sample["t"], SAMPLES["duration"])
        assert position == pytest.approx(sample["position"], abs=1e-6), (case["name"], sample["t"])
        assert rotation == pytest.approx(sample["rotationY"], abs=1e-6), (case["name"], sample["t"])


def test_a_slot_without_a_usable_move_stays_where_it_is():
    assert pose_at({"position": [1, 2, 3], "rotationY": 0.5}, 2, 4) == ([1.0, 2.0, 3.0], 0.5)
    assert pose_at({"position": [1, 2, 3], "rotationY": 0.5, "motion": {"to": [1, 2]}}, 2, 4) == ([1.0, 2.0, 3.0], 0.5)
    assert window({}, 4) == (0.0, 4.0) and window({"start": 1}, 4) == (1.0, 4.0) and window({"end": 2}, 4) == (0.0, 2.0)


def test_before_start_the_object_waits_and_after_end_it_stays_at_the_destination():
    mover = {"position": [0, 0, 8], "rotationY": 0, "motion": {"to": [0, 0, -4], "start": 1, "end": 3}}
    assert [pose_at(mover, t, 4)[0][2] for t in (0, 1, 2, 3, 4)] == [8, 8, 2, -4, -4]


def test_check_motion_names_what_the_editor_would_drop_or_the_runtime_cannot_do():
    assert check_motion({"to": [1, 0, 0], "start": 1, "end": 2, "extra": "kept"}, 4) == {"to": [1, 0, 0], "start": 1, "end": 2, "extra": "kept"}
    for bad, text in (("walk", "object"), ({"to": [1, 0]}, "motion.to"), ({"to": [1, 0, 0], "via": [1]}, "motion.via"),
                      ({"to": [1, 0, 0], "points": []}, "motion.points"), ({"to": [1, 0, 0], "start": -1}, "motion.start"),
                      ({"to": [1, 0, 0], "end": "soon"}, "motion.end"), ({"to": [1, 0, 0], "start": 3, "end": 2}, "come before"),
                      ({"to": [1, 0, 0], "start": 4.5, "end": 6}, "never move"), ({"to": [1, 0, 0], "end": 0}, "come before"),
                      ({"to": [1, 0, 0], "start": 4}, "come before"),
                      ({"to": [1, 0, 0], "start": 1, "walk": {"key": "x"}}, "motion_window_with_walk")):
        with pytest.raises(ValueError, match=text):
            check_motion(bad, 4)


def test_a_binding_stores_a_window_and_the_inspect_echoes_it(tmp_path):
    scene(tmp_path, [slot("plane")])
    viewed = patch(tmp_path, [{"object_id": "plane", "motion": {"to": [10, 2, 0], "start": 1, "end": 3, "faceTravel": True}}])
    assert viewed["document"]["slots"][0]["motion"] == {"to": [10, 2, 0], "start": 1, "end": 3, "faceTravel": True}
    assert viewed["objects"][0]["motion"]["start"] == 1 and "invalid" not in str(viewed["warnings"])


def test_a_bad_move_is_refused_with_a_code_and_writes_nothing(tmp_path):
    scene(tmp_path, [slot("plane")])
    for motion, text in (({"to": [1, 0, 0], "start": 5.5, "end": 7}, "never move"), ({"to": [1, 0, 0], "start": 2, "end": 1}, "come before"),
                         ({"to": [1, 0, 0], "start": 1, "walk": {"sourceUrl": "a", "clip": {"index": 0, "name": "w"}, "key": "k"}}, "motion_window_with_walk"),
                         ({"to": "far"}, "motion.to")):
        with pytest.raises(World3DSceneError) as refused:
            patch(tmp_path, [{"object_id": "plane", "motion": motion}])
        assert refused.value.code == "invalid_motion" and text in str(refused.value) and "plane" in str(refused.value)
    assert json.loads((tmp_path / WORKSPACE / "world3d-edits" / f"{SCENE}.json").read_text())["revision"] == 1


def test_a_move_can_be_cleared_with_null(tmp_path):
    scene(tmp_path, [slot("plane", motion={"to": [1, 0, 0], "start": 1, "end": 3})])
    assert patch(tmp_path, [{"object_id": "plane", "motion": None}])["document"]["slots"][0]["motion"] is None


def test_retime_stretches_the_window_with_the_scene(tmp_path):
    scene(tmp_path, [slot("plane", motion={"to": [1, 0, 0], "start": 1, "end": 2.5}), slot("still")])
    viewed = patch(tmp_path, [], duration=10, retime=True)
    assert viewed["document"]["slots"][0]["motion"] == {"to": [1, 0, 0], "start": 2, "end": 5}
    assert viewed["document"]["slots"][1].get("motion") is None
    scene(tmp_path, [slot("plane", motion={"to": [1, 0, 0], "start": 1, "end": 2.5})])
    assert patch(tmp_path, [], duration=10)["document"]["slots"][0]["motion"] == {"to": [1, 0, 0], "start": 1, "end": 2.5}


def test_collide_false_is_stored_true_and_null_take_it_off_and_anything_else_is_refused(tmp_path):
    scene(tmp_path, [slot("ghost")])
    assert patch(tmp_path, [{"object_id": "ghost", "collide": False}])["document"]["slots"][0]["collide"] is False
    viewed = patch(tmp_path, [{"object_id": "ghost", "position": [1, 0, 0]}], revision=2)
    assert viewed["document"]["slots"][0]["collide"] is False and viewed["objects"][0]["collide"] is False
    for off in (True, None):
        scene(tmp_path, [slot("ghost", collide=False)])
        viewed = patch(tmp_path, [{"object_id": "ghost", "collide": off}])
        assert "collide" not in viewed["document"]["slots"][0] and "collide" not in viewed["objects"][0]
    scene(tmp_path, [slot("ghost")])
    with pytest.raises(World3DSceneError) as refused:
        patch(tmp_path, [{"object_id": "ghost", "collide": "no"}])
    assert refused.value.code == "invalid_collide"


def test_the_series_path_keeps_a_window_and_drops_one_that_cannot_run():
    kept = series_motion({"to": [1, 0, 0], "start": 1, "end": 3})
    assert kept["start"] == 1 and kept["end"] == 3
    assert series_motion({"to": [1, 0, 0], "start": 1})["start"] == 1
    assert "start" not in series_motion({"to": [1, 0, 0], "start": 3, "end": 1}) and "start" not in series_motion({"to": [1, 0, 0], "start": 700})
    assert "start" not in series_motion({"to": [1, 0, 0]})


def test_the_editor_gate_mirror_reports_a_move_the_editor_would_drop():
    document = {"version": 1, "units": "meters", "up": "y", "width": 1280, "height": 720, "fps": 30, "duration": 5,
                "camera": {"family": "fixed", "eye": [0, 1, 5], "look": [0, 1, 0], "fov": 45},
                "light": {"kind": "directional", "direction": [0, -1, 0], "intensity": 1, "color": "#ffffff"},
                "slots": [slot("ok", motion={"to": [1, 0, 0], "start": 1, "end": 2}), slot("lost", motion={"to": [1, 0]})]}
    problems = editor_shape_problems(document)
    assert problems == ["slots[1]: motion needs to [x, y, z]; the editor drops a move without it"]
