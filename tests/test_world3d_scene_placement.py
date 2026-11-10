"""The static placement check: the numbers of two real defects (a sleeper on a bed, a patient on a couch) and the cabin seats it must not flag."""
from services.world3d_scene_placement import scene_placement


def item(id_, lo, hi, position, clip="Idle", role="subject_1", **extra):
    centre = [(a + b) / 2 for a, b in zip(lo, hi)]
    return {"id": id_, "role": role, "media": "model3d", "position": position, "clip": clip,
            "boundsM": {"min": lo, "max": hi, "center": centre, "bottomY": lo[1]}, **extra}


def room(blocks, dims=(6, 6, 3)):
    return {"room": {"mold": {"dimensions": list(dims), "blocks": blocks}}, "duration": 3, "width": 1920, "height": 1080, "slots": [],
            "camera": {"family": "fixed", "eye": [0, 1.5, 3], "look": [0, 0.7, -1], "fov": 50}}


BED = {"id": "bed", "kind": "bed", "box": [0, 0, -1.3, 1.7, 0.55, 2.2], "surfaces": ["bed_front", "bed_top"]}


def test_a_sleeper_sunk_into_the_bed_and_hanging_off_its_head_is_told_where_to_go():
    lying = item("subject_1", [-0.83, 0.41, -2.96], [0.83, 0.86, -1.29], [0, 0.58, -1.3])
    result = scene_placement(room([BED]), [lying])
    codes = {i["code"]: i for i in result["issues"]}
    assert set(codes) >= {"sinks_into_support", "overhangs_support"}
    assert codes["sinks_into_support"]["fix"]["position"][1] == 0.72           # up by 0.14: the lowest point meets the top of the bed
    assert codes["overhangs_support"]["support"] == "bed"
    assert codes["overhangs_support"]["fix"]["position"][2] > -1.3             # slid toward the bed's centre
    assert any(w.startswith("placement_sinks_into_support: subject_1") and "fix: position" in w for w in result["warnings"])
    assert any(w.startswith("placement_fix_all: subject_1 position") for w in result["warnings"])       # both fixes applied at once


def test_a_body_that_rests_on_the_couch_inside_its_footprint_is_clean():
    couch = item("x_divan", [0.15, 0.0, -0.28], [1.05, 0.4, 1.68], [0.6, 0, 0.7], clip=None, role=None)
    sitter = item("subject_1", [0.2, 0.4, -0.2], [1.0, 0.75, 1.6], [0.6, 0.53, 0.7])
    assert scene_placement(room([]), [couch, sitter])["issues"] == []


def test_the_patient_who_hangs_past_the_end_of_the_couch_is_found_by_its_prop_support():
    couch = item("x_divan", [0.15, 0.0, -0.28], [1.05, 0.4, 1.68], [0.6, 0, 0.7], clip=None, role=None)
    sitter = item("subject_1", [-0.33, 0.34, -1.11], [1.53, 0.73, 0.71], [0.6, 0.47, 0.7])
    codes = [i["code"] for i in scene_placement(room([]), [couch, sitter])["issues"]]
    assert "overhangs_support" in codes


def test_people_lowered_into_seat_blocks_are_not_below_the_floor():
    seat = {"id": "seat_driver", "kind": "seat", "box": [-0.5, 0.0, -0.22, 0.52, 0.36, 0.56], "surfaces": ["seat_front", "seat_top"]}
    driver = item("subject_1", [-0.7, -0.51, -0.4], [-0.3, 1.2, -0.1], [-0.5, -0.51, -0.27])
    assert scene_placement(room([seat], (2.1, 3.0, 1.45)), [driver])["issues"] == []


def test_a_walker_below_the_floor_and_a_floating_character_are_told_apart():
    under = item("a", [0, -0.3, 0], [0.5, 1.4, 0.5], [0, -0.3, 0])
    float_ = item("b", [1, 0.5, 0], [1.5, 2.2, 0.5], [1, 0.5, 0], role="subject_2")
    codes = {i["id"]: i["code"] for i in scene_placement(room([]), [under, float_])["issues"]}
    assert codes == {"a": "below_floor", "b": "floating"}


def test_a_subject_outside_the_frame_is_cropped_and_a_far_one_is_tiny():
    out = item("subject_1", [5, 0, -1], [5.6, 1.8, -0.6], [5, 0, -1])
    far = item("subject_2", [-0.2, 0, -60], [0.2, 1.8, -59.8], [0, 0, -60], role="subject_2")
    codes = {i["id"]: i["code"] for i in scene_placement(room([], (200, 200, 50)), [out, far])["issues"]}
    assert codes == {"subject_1": "cropped", "subject_2": "tiny"}


def test_a_following_camera_is_judged_at_its_start_middle_and_end():
    doc = room([], (60, 60, 30))
    doc["camera"] = {"family": "fixed", "eye": [0, 1.5, 3], "look": [0, 1, 0], "fov": 40,
                     "framing": {"targetSlot": "subject_1", "from": [0, 0.2, 4], "to": [0, 0.2, 3.2], "lookFrom": [0, 0, 0], "lookTo": [0, 0, 0], "relativeToFacing": False}}
    walker = item("subject_1", [-0.3, 0, -0.2], [0.3, 1.8, 0.2], [0, 0, 0])
    assert scene_placement(doc, [walker])["issues"] == []


def test_a_mover_is_not_this_checks_business_and_a_broken_scene_reports_nothing():
    doc = room([])
    doc["slots"] = [{"id": "subject_1", "motion": {"to": [1, 0, 1]}}]
    under = item("subject_1", [0, -0.3, 0], [0.5, 1.4, 0.5], [0, -0.3, 0])
    assert scene_placement(doc, [under])["issues"] == []
    assert scene_placement({}, [{"id": "x", "boundsM": {"min": "bad"}}]) == {"issues": [], "warnings": []}


def test_a_humanoid_bind_pose_is_not_a_t_a_sleeper_is_judged_by_her_idle_body():
    """boundsM is the bind pose: arms out, 1.67 m wide. The idle body is a shoulder width wide, so the bed's width is not overhung."""
    bed = {"id": "bed", "kind": "bed", "box": [0, 0, -1.3, 1.7, 0.55, 2.2], "surfaces": ["bed_front", "bed_top"]}
    lying = item("subject_1", [-0.833, 0.55, -2.2], [0.833, 0.9, -0.4], [0, 0.6, -0.9], clip={"index": 0, "name": "Idle"}, rotationX=-1.5, rotationY=0.0)
    lying["boundsM"]["size"] = [1.666, 1.65, 0.337]
    codes = [i["code"] for i in scene_placement(room([bed]), [lying])["issues"]]
    assert "overhangs_support" not in codes and "outside_room" not in codes


def test_a_seated_person_is_judged_from_the_cushion_up():
    seat = {"id": "seat_driver", "kind": "seat", "box": [0, 0, -1, 0.52, 0.36, 0.56], "surfaces": ["seat_front", "seat_top"]}
    doc = room([seat], (2.1, 3.0, 1.45))
    doc["camera"] = {"family": "fixed", "eye": [0, 1.15, 1.2], "look": [0, 0.95, -1], "fov": 50}
    driver = item("subject_1", [-0.2, -0.5, -1.1], [0.2, 1.2, -0.9], [0, -0.5, -1])
    assert [i["code"] for i in scene_placement(doc, [driver])["issues"] if i["code"] == "cropped"] == []
