"""Seated at a table, on a bed: world3d.scene.patch places furniture and sitters from what the agent declares (height,
furniture, beside, rest), and inspect judges the held pose from the character's joints (layout.contacts)."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pygltflib")

import services.world3d_rest_place as rest_place
from services.humanoid_rig.animate import animate_humanoid
from services.humanoid_rig.rig import rig_humanoid
from services.procedural_3d.compose import compose_glb
from services.world3d_contact_poses import measure_scene
from services.world3d_scene_bounds import MODEL_HEIGHT
from services.world3d_scenes import World3DSceneError, inspect_scene, patch_scene
from services.world3d_slot_fields import clip_cues
from tests.test_world3d_scene_layout import SCENE, WORKSPACE, item, scene, workspace_dir
from tests.test_world3d_seats import one_mesh_chair

FIXTURES = Path(__file__).parent / "fixtures" / "humanoid_rig"
PET = "/api/v1/file/pet.glb?workspace=studio"
_RIGGED: list = []


def rigged_pet() -> bytes:
    """A small rigged humanoid (tests/fixtures/humanoid_rig/pet.json) with the library's Sit Down clip, made once."""
    if not _RIGGED:
        document = json.loads((FIXTURES / "pet.json").read_text())
        rigged, _sidecar = rig_humanoid(compose_glb(document["pieces"], document["id"]))
        _RIGGED.append(animate_humanoid(rigged, ["sit_down"], 120)[0])
    return _RIGGED[0]


def in_process(request: dict, output: Path) -> dict:
    """The worker's animate mode without the subprocess: the same sit_clip, baked here."""
    data, clips, warnings = animate_humanoid(Path(request["source"]).read_bytes(), request["animations"], request["animation_bpm"],
                                             interactions=request["interactions"])
    output.write_bytes(data)
    return {"clips": clips, "warnings": warnings}


@pytest.fixture
def stage(tmp_path, monkeypatch):
    monkeypatch.setattr(rest_place, "BAKER", in_process)
    folder = tmp_path / WORKSPACE
    folder.mkdir()
    (folder / "pet.glb").write_bytes(rigged_pet())
    (folder / "pet.humanoid.json").write_text('{"version": 5}')
    (folder / "chair-mesh.glb").write_bytes(compose_glb(one_mesh_chair(), "chair"))
    crate = [{"type": "box", "position": [0, 0.5, 0], "scale": [1.2, 1.0, 1.2], "color": "#777777"}]
    (folder / "crate.glb").write_bytes(compose_glb(crate, "crate"))
    scene(tmp_path, [])
    return tmp_path


def patch(tmp_path, bindings, revision=None, **changes):
    current = revision or inspect_scene(WORKSPACE, SCENE, workspace_dir(tmp_path))["revision"]
    return patch_scene(WORKSPACE, SCENE, workspace_dir(tmp_path), {"bindings": bindings, **changes}, current)


def slot_of(viewed, identifier):
    return next(slot for slot in viewed["document"]["slots"] if slot["id"] == identifier)


def contact(viewed, identifier):
    return next(row for row in viewed["layout"]["contacts"] if row["id"] == identifier)


def codes(viewed):
    return [line.split(":", 1)[0] for line in viewed["warnings"]]


def joints(tmp_path, viewed, identifier):
    people, _pieces, _drawn = measure_scene(viewed["document"], WORKSPACE, workspace_dir(tmp_path), viewed["document"]["duration"] / 2)
    return next(person for person in people if person.id == identifier)


def table_and_two(tall=1.75, short=1.5, seats=(0.40, 0.34), table=0.68):
    return [{"object_id": "table", "add": True, "furniture": {"kind": "table", "height": table}},
            {"object_id": "chair_a", "add": True, "furniture": {"kind": "chair", "seat": seats[0]}, "beside": {"object": "table", "side": "left"}},
            {"object_id": "chair_b", "add": True, "furniture": {"kind": "chair", "seat": seats[1]}, "beside": {"object": "table", "side": "right"}},
            {"object_id": "tall", "add": True, "source_url": PET, "height": tall, "rest": {"pose": "sit", "on": "chair_a", "at": "table"}},
            {"object_id": "short", "add": True, "source_url": PET, "height": short, "rest": {"pose": "sit", "on": "chair_b", "at": "table"}}]


# ------------------------------------------------------------------------------------------------------------- height

def test_height_is_fit_height_m_and_is_not_stored(stage):
    viewed = patch(stage, [{"object_id": "crate", "add": True, "source_url": "/api/v1/file/crate.glb?workspace=studio", "height": 0.75}])
    assert slot_of(viewed, "crate")["scale"] == pytest.approx(0.75 / MODEL_HEIGHT) and "height" not in slot_of(viewed, "crate")
    assert item(viewed, "crate")["boundsM"]["size"][1] == pytest.approx(0.75, abs=1e-3)
    for bad in ({"height": 0.75, "scale": 2}, {"height": 0.75, "fit": {"heightM": 1}}, {"height": -1}, {"height": None}):
        with pytest.raises(World3DSceneError):
            patch(stage, [{"object_id": "crate", **bad}])


# ------------------------------------------------------------------------------------------------------------- beside

def test_beside_puts_a_chair_against_a_side_of_the_table_by_their_boxes_facing_it(stage):
    viewed = patch(stage, [{"object_id": "table", "add": True, "furniture": "table"},
                           {"object_id": "chair", "add": True, "furniture": "chair", "beside": {"object": "table", "side": "right", "gap": 0.1}}])
    chair, table = item(viewed, "chair")["boundsM"], item(viewed, "table")["boundsM"]
    assert chair["min"][0] == pytest.approx(table["max"][0] + 0.1, abs=1e-3) and chair["center"][2] == pytest.approx(0, abs=1e-3)
    assert chair["bottomY"] == pytest.approx(0, abs=1e-3)
    assert slot_of(viewed, "chair")["rotationY"] == pytest.approx(-math.pi / 2), "its front (+z) turned toward the table (-x)"
    assert slot_of(viewed, "chair")["beside"] == {"object": "table", "side": 90.0, "gap": 0.1, "offset": 0.0, "facing": "object"}


def test_beside_follows_a_turned_and_moved_table_on_every_patch(stage):
    patch(stage, [{"object_id": "table", "add": True, "furniture": "table"},
                  {"object_id": "chair", "add": True, "furniture": "chair", "beside": {"object": "table", "side": "front"}}])
    viewed = patch(stage, [{"object_id": "table", "position": [3, 0, 1], "rotationY": math.pi / 2}])
    chair, table = item(viewed, "chair")["boundsM"], item(viewed, "table")["boundsM"]
    assert chair["min"][0] == pytest.approx(table["max"][0], abs=1e-3), "the table's front now faces +x"
    assert chair["center"][2] == pytest.approx(1, abs=1e-3) and slot_of(viewed, "chair")["rotationY"] == pytest.approx(-math.pi / 2)


def test_beside_refuses_cycles_unknown_objects_and_removing_what_it_names(stage):
    patch(stage, [{"object_id": "table", "add": True, "furniture": "table"},
                  {"object_id": "chair", "add": True, "furniture": "chair", "beside": {"object": "table"}}])
    with pytest.raises(World3DSceneError, match="beside_cycle|circle"):
        patch(stage, [{"object_id": "table", "beside": {"object": "chair"}}])
    with pytest.raises(World3DSceneError, match="is not an object of the scene"):
        patch(stage, [{"object_id": "chair", "beside": {"object": "sofa"}}])
    with pytest.raises(World3DSceneError, match="item_in_use|before removing"):
        patch(stage, [{"object_id": "table", "remove": True}])
    for bad in ({"object": "chair"}, {"object": "table", "side": "up"}, {"object": "table", "gap": 20}, {"object": "table", "facing": "north"}):
        with pytest.raises(World3DSceneError):
            patch(stage, [{"object_id": "chair", "beside": bad}])


def test_beside_null_or_a_position_drops_the_declaration(stage):
    patch(stage, [{"object_id": "table", "add": True, "furniture": "table"},
                  {"object_id": "chair", "add": True, "furniture": "chair", "beside": {"object": "table"}}])
    assert "beside" not in slot_of(patch(stage, [{"object_id": "chair", "beside": None}]), "chair")
    patch(stage, [{"object_id": "chair", "beside": {"object": "table"}}])
    viewed = patch(stage, [{"object_id": "chair", "position": [5, 0, 5]}])
    assert "beside" not in slot_of(viewed, "chair") and slot_of(viewed, "chair")["position"] == [5, 0, 5]


# --------------------------------------------------------------------------------------------------------------- rest

@pytest.mark.parametrize(("height", "seat", "turn"), [(1.2, 0.27, 0.0), (1.5, 0.34, 0.6), (1.9, 0.43, -2.2)])
def test_rest_puts_the_hips_on_the_seat_and_the_feet_on_the_floor_for_any_size_and_turn(stage, height, seat, turn):
    viewed = patch(stage, [{"object_id": "chair", "add": True, "furniture": {"kind": "chair", "seat": seat}, "position": [1, 0, -2],
                            "rotationY": turn},
                           {"object_id": "pet", "add": True, "source_url": PET, "height": height, "rest": {"pose": "sit", "on": "chair"}}])
    row = contact(viewed, "pet")
    assert row["pose"] == "seated" and row["seat"]["object"] == "chair" and row["seat"]["topM"] == pytest.approx(seat, abs=0.01)
    assert abs(row["seat"]["gapM"]) < 0.01 and not row.get("issues"), viewed["warnings"]
    person = joints(stage, viewed, "pet")
    rest_ankle = float(person.rest["LeftFoot"][1] - person.body.box_low) * person.frame.factor
    for side in ("Left", "Right"):
        assert person.joints[f"{side}Foot"][1] == pytest.approx(rest_ankle, abs=0.01), "the feet stay on the floor"
    assert person.forward == pytest.approx([math.sin(turn), math.cos(turn)], abs=1e-6), "away from the backrest"
    chair = item(viewed, "chair")["boundsM"]
    hips = person.joints["Hips"]
    assert chair["min"][0] - 0.01 <= hips[0] <= chair["max"][0] + 0.01 and chair["min"][2] - 0.01 <= hips[2] <= chair["max"][2] + 0.01


def test_rest_converts_the_seat_into_the_characters_own_units(stage):
    viewed = patch(stage, [{"object_id": "chair", "add": True, "furniture": {"kind": "chair", "seat": 0.34}},
                           {"object_id": "pet", "add": True, "source_url": PET, "height": 1.5, "rest": {"pose": "sit", "on": "chair"}}])
    slot = slot_of(viewed, "pet")
    person = joints(stage, viewed, "pet")
    native = person.frame.to_native([person.joints["Hips"]])[0]
    seat_native = (0.34 - person.frame.offset[1]) / person.frame.factor
    assert native[1] == pytest.approx(seat_native + rest_place.HIP_ABOVE_SEAT * person.size["leg"] / person.frame.factor, abs=2e-3)
    assert slot["grounded"] is False and slot["position"][1] == pytest.approx(-person.body.box_low * person.frame.factor, abs=1e-4)
    assert person.frame.factor == pytest.approx(1.5 / (person.body.document and _box_height(stage)), rel=1e-6)


def _box_height(stage) -> float:
    from services.procedural_3d.glb_bounds import glb_bounds
    return glb_bounds(stage / WORKSPACE / "pet.glb")["size"][1]


def test_rest_is_stored_reopens_and_null_gives_the_character_its_own_model_back(stage):
    original = hashlib.sha256((stage / WORKSPACE / "pet.glb").read_bytes()).hexdigest()
    viewed = patch(stage, [{"object_id": "chair", "add": True, "furniture": "chair"},
                           {"object_id": "pet", "add": True, "source_url": PET, "height": 1.9, "grounded": True,
                            "rest": {"pose": "sit", "on": "chair"}}])
    slot = slot_of(viewed, "pet")
    assert slot["rest"] == {"pose": "sit", "on": "chair"} and slot["restBase"]["sourceUrl"] == PET
    derived = slot["sourceUrl"].split("/api/v1/file/")[1].split("?")[0]
    assert derived.startswith("world3d-rest/pet-sit-") and (stage / WORKSPACE / derived).is_file()
    assert (stage / WORKSPACE / derived).with_suffix(".humanoid.json").read_text() == '{"version": 5}', "the rig sidecar travels along"
    assert slot["clip"]["name"] == "Rest Sit" and slot["grounded"] is False
    assert next(row for row in viewed["objects"] if row["id"] == "pet")["rest"] == {"pose": "sit", "on": "chair"}
    reopened = inspect_scene(WORKSPACE, SCENE, workspace_dir(stage))
    assert slot_of(reopened, "pet") == slot and contact(reopened, "pet")["pose"] == "seated"
    stood = slot_of(patch(stage, [{"object_id": "pet", "rest": None}]), "pet")
    assert stood["sourceUrl"] == PET and stood["clip"] is None and stood["grounded"] is True
    assert not {"rest", "restBase", "clips"} & set(stood)
    assert hashlib.sha256((stage / WORKSPACE / "pet.glb").read_bytes()).hexdigest() == original, "the shared character file is untouched"


def test_the_renderer_gets_plain_numbers_and_a_held_clip(stage):
    viewed = patch(stage, table_and_two())
    for slot in viewed["document"]["slots"]:
        assert len(slot["position"]) == 3 and all(type(value) is float or type(value) is int for value in slot["position"])
        assert type(slot["rotationY"]) in (int, float) and type(slot["scale"]) in (int, float)
    for name in ("tall", "short"):
        (cue,) = clip_cues(slot_of(viewed, name)["clips"])
        assert cue["loop"] is False and cue["duration"] > 0 and cue["offset"] == rest_place.HOLD_AT
    json.dumps(viewed["document"])


def test_rest_refuses_what_cannot_sit(stage):
    patch(stage, [{"object_id": "chair", "add": True, "furniture": "chair"}, {"object_id": "pet", "add": True, "source_url": PET}])
    for bad in ({"pose": "lie", "on": "chair"}, {"pose": "sit"}, {"pose": "sit", "on": "pet"}, {"pose": "sit", "on": "chair", "surface": {"point": [1, 2]}},
                {"pose": "sit", "on": "chair", "hands": "yes"}):
        with pytest.raises(World3DSceneError):
            patch(stage, [{"object_id": "pet", "rest": bad}])
    with pytest.raises(World3DSceneError, match="rest or motion"):
        patch(stage, [{"object_id": "pet", "rest": {"pose": "sit", "on": "chair"}, "motion": {"to": [1, 0, 1]}}])


def test_a_new_position_or_clip_stands_the_sitter_up(stage):
    patch(stage, [{"object_id": "chair", "add": True, "furniture": "chair"},
                  {"object_id": "pet", "add": True, "source_url": PET, "rest": {"pose": "sit", "on": "chair"}}])
    viewed = patch(stage, [{"object_id": "pet", "position": [2, 0, 0]}])
    assert "rest" not in slot_of(viewed, "pet") and slot_of(viewed, "pet")["sourceUrl"] == PET and slot_of(viewed, "pet")["position"] == [2, 0, 0]


def test_a_one_mesh_chair_seat_is_guessed_and_says_so(stage):
    viewed = patch(stage, [{"object_id": "chair", "add": True, "source_url": "/api/v1/file/chair-mesh.glb?workspace=studio", "height": 0.9},
                           {"object_id": "pet", "add": True, "source_url": PET, "height": 1.9, "rest": {"pose": "sit", "on": "chair"}}])
    guess = next(line for line in viewed["warnings"] if line.startswith("seat_surface_guessed"))
    assert "0.46 m" in guess and 'surface: {point: [x, y, z]}' in guess
    assert contact(viewed, "pet")["seat"]["topM"] == pytest.approx(0.46, abs=0.01)


def test_sitting_on_the_edge_of_a_bed_faces_the_camera_from_its_long_side(stage):
    viewed = patch(stage, [{"object_id": "bed", "add": True, "furniture": {"kind": "bed", "height": 0.45}},
                           {"object_id": "pet", "add": True, "source_url": PET, "height": 1.75, "rest": {"pose": "sit", "on": "bed"}}])
    row = contact(viewed, "pet")
    assert row["pose"] == "seated" and row["seat"]["part"] == 'part 1 "mattress"' and not row.get("issues"), viewed["warnings"]
    person = joints(stage, viewed, "pet")
    assert person.forward == pytest.approx([0, 1], abs=1e-6) and person.joints["Hips"][2] > 0.2, "near the front edge, facing the camera"


# ----------------------------------------------------------------------------------------------------------- warnings

def test_a_held_sit_down_with_no_chair_is_seated_without_seat_with_the_fix(stage):
    viewed = patch(stage, [{"object_id": "pet", "add": True, "source_url": PET, "grounded": True, "height": 1.7,
                            "clips": [{"clip": {"index": 1, "name": "Sit Down"}, "start": 0, "offset": 0.9, "duration": 0.05}]}])
    line = next(line for line in viewed["warnings"] if line.startswith("seated_without_seat"))
    assert 'rest {pose: "sit", on: "seat_pet"}' in line
    assert contact(viewed, "pet")["fix"] == [{"object_id": "seat_pet", "add": True, "furniture": {"kind": "chair"}},
                                             {"object_id": "pet", "rest": {"pose": "sit", "on": "seat_pet"}}]


def test_a_sitter_moved_off_its_seat_floats_or_sinks_by_the_number(stage):
    viewed = patch(stage, [{"object_id": "chair", "add": True, "furniture": {"kind": "chair", "seat": 0.4}},
                           {"object_id": "pet", "add": True, "source_url": PET, "height": 1.75, "rest": {"pose": "sit", "on": "chair"}}])
    seated = {key: slot_of(viewed, "pet")[key] for key in ("sourceUrl", "clip", "clips", "position", "rotationY", "scale", "grounded")}
    for lift, code in ((0.15, "floats_above_seat"), (-0.12, "sunk_into_seat")):
        placed = {**seated, "position": [seated["position"][0], seated["position"][1] + lift, seated["position"][2]]}
        moved = patch(stage, [{"object_id": "copy", "add": True, **{k: v for k, v in placed.items() if k not in ("grounded",)},
                               "grounded": False}, {"object_id": "pet", "rest": None, "position": [9, 0, 9]}])
        line = next(line for line in moved["warnings"] if line.startswith(code))
        assert f"{abs(lift):.2f} m" in line and 'rest {pose: "sit", on: "chair"}' in line
        patch(stage, [{"object_id": "copy", "remove": True}])
        patch(stage, [{"object_id": "pet", "rest": {"pose": "sit", "on": "chair"}}])


def test_a_seat_too_high_for_the_legs_says_the_seat_height_to_use(stage):
    viewed = patch(stage, [{"object_id": "chair", "add": True, "furniture": {"kind": "chair", "seat": 0.62}},
                           {"object_id": "pet", "add": True, "source_url": PET, "height": 1.2, "rest": {"pose": "sit", "on": "chair"}}])
    line = next(line for line in viewed["warnings"] if line.startswith("seat_height_unusual"))
    fix = next(item for item in contact(viewed, "pet")["fix"] if item.get("object_id") == "chair")
    assert "the feet leave the floor" in line and 0.2 < fix["furniture"]["seat"] < 0.32
    assert f"seat: {fix['furniture']['seat']:g}" in line
    assert "limb_through_object" not in codes(viewed), "the thighs on a too-high seat are the same problem"


def test_an_unsized_seat_is_furniture_size_unusual_with_the_height(stage):
    viewed = patch(stage, [{"object_id": "chair", "add": True, "source_url": "/api/v1/file/chair-mesh.glb?workspace=studio"},
                           {"object_id": "pet", "add": True, "source_url": PET, "rest": {"pose": "sit", "on": "chair"}}])
    line = next(line for line in viewed["warnings"] if line.startswith("furniture_size_unusual"))
    assert "chair is drawn 1.70 m tall" in line and "give chair height 0.9" in line


def test_a_table_too_high_too_far_or_behind_says_how_to_fix_it(stage):
    viewed = patch(stage, table_and_two(table=1.1))
    line = next(line for line in viewed["warnings"] if line.startswith("at_height_unusual"))
    fix = next(item for item in contact(viewed, "tall")["fix"] if item.get("object_id") == "table")
    assert "everyone at it" in line and 0.55 < fix["furniture"]["height"] < 0.8
    far = patch(stage, [{"object_id": "table", "furniture": {"kind": "table", "height": 0.68}},
                        {"object_id": "chair_a", "beside": {"object": "table", "side": "left", "gap": 0.7}}])
    line = next(line for line in far["warnings"] if line.startswith("at_out_of_reach"))
    gap = next(item for item in contact(far, "tall")["fix"] if item.get("object_id") == "chair_a")["beside"]["gap"]
    assert gap < 0.3 and f"gap: {gap:g}" in line
    behind = patch(stage, [{"object_id": "chair_a", "beside": {"object": "table", "side": "left", "facing": "away"}}])
    assert "at_not_in_front" in codes(behind)


def test_limbs_through_furniture_and_standing_inside_it_are_reported_unless_collide_false(stage):
    viewed = patch(stage, [{"object_id": "chair", "add": True, "furniture": {"kind": "chair", "seat": 0.4}},
                           {"object_id": "pet", "add": True, "source_url": PET, "height": 1.75, "rest": {"pose": "sit", "on": "chair"}}])
    shins = joints(stage, viewed, "pet").joints
    knee = (shins["LeftLeg"] + shins["LeftFoot"]) / 2
    crate = {"object_id": "box", "add": True, "source_url": "/api/v1/file/crate.glb?workspace=studio", "height": 0.1,
             "position": [float(knee[0]), float(knee[1]) - 0.05, float(knee[2])], "grounded": False}
    viewed = patch(stage, [crate])
    row = contact(viewed, "pet")
    assert any(hit["limb"].endswith("shin") and hit["object"] == "box" for hit in row["through"]) and "limb_through_object" in codes(viewed)
    moved = next(fix for fix in row["fix"] if fix["object_id"] == "box")
    assert moved.get("position", crate["position"]) != crate["position"] or moved.get("height"), "the fix moves or resizes the box, in numbers"
    assert "limb_through_object" not in codes(patch(stage, [{"object_id": "pet", "collide": False}]))
    inside = patch(stage, [{"object_id": "box", "remove": True},
                           {"object_id": "crate", "add": True, "source_url": "/api/v1/file/crate.glb?workspace=studio", "height": 1.6},
                           {"object_id": "walker", "add": True, "source_url": PET, "grounded": True, "height": 1.7}])
    line = next(line for line in inside["warnings"] if line.startswith("inside_object"))
    assert line.startswith("inside_object: walker stands inside crate") and "out of it: position [" in line
    step = next(fix for fix in contact(inside, "walker")["fix"] if fix["object_id"] == "walker")["position"]
    assert math.hypot(step[0], step[2]) > 0.9, "out past the crate's edge (0.6 m from its middle) and a body more"


# --------------------------------------------------------------------------------------------------------------- scene

def test_two_people_at_a_table_declared_only_by_intent_have_no_contact_warnings(stage):
    viewed = patch(stage, table_and_two())
    assert not [line for line in viewed["warnings"] if line.split(":", 1)[0] in _CONTACT_CODES], viewed["warnings"]
    for name in ("tall", "short"):
        row = contact(viewed, name)
        assert row["pose"] == "seated" and abs(row["seat"]["gapM"]) < 0.01 and row["at"]["object"] == "table"
        assert row["at"]["rangeM"][0] <= row["at"]["topM"] <= row["at"]["rangeM"][1]
    hands = joints(stage, viewed, "tall").joints
    top = item(viewed, "table")["boundsM"]["max"][1]
    assert hands["LeftHand"][1] == pytest.approx(top + rest_place.HAND_LIFT_M, abs=0.03), "the forearms rest on the table"


def test_the_same_scene_with_a_held_sit_down_and_no_chairs_is_seated_without_seat(stage):
    sit_down = [{"clip": {"index": 1, "name": "Sit Down"}, "start": 0, "offset": 0.9, "duration": 0.05}]
    viewed = patch(stage, [{"object_id": "table", "add": True, "furniture": {"kind": "table", "height": 0.68}},
                           {"object_id": "tall", "add": True, "source_url": PET, "height": 1.75, "grounded": True, "position": [-0.9, 0, 0],
                            "rotationY": math.pi / 2, "clips": sit_down},
                           {"object_id": "short", "add": True, "source_url": PET, "height": 1.5, "grounded": True, "position": [0.9, 0, 0],
                            "rotationY": -math.pi / 2, "clips": sit_down}])
    assert codes(viewed).count("seated_without_seat") == 2


_CONTACT_CODES = {"seated_without_seat", "floats_above_seat", "sunk_into_seat", "seat_height_unusual", "limb_through_object", "inside_object",
                  "at_height_unusual", "at_out_of_reach", "at_not_in_front", "furniture_size_unusual", "seat_surface_guessed", "rest_unresolved"}


def test_the_derived_clip_is_made_by_the_real_worker(stage, monkeypatch):
    from tests.test_humanoid_animate import _worker_python
    python = _worker_python()
    from routers.model3d_animate import execute_animate
    monkeypatch.setattr(rest_place, "BAKER", lambda request, output: execute_animate(request, output, python=python))
    viewed = patch(stage, [{"object_id": "chair", "add": True, "furniture": {"kind": "chair", "seat": 0.4}},
                           {"object_id": "pet", "add": True, "source_url": PET, "height": 1.75, "rest": {"pose": "sit", "on": "chair"}}])
    assert abs(contact(viewed, "pet")["seat"]["gapM"]) < 0.01 and not codes(viewed)
    assert np.isfinite(joints(stage, viewed, "pet").joints["Hips"]).all()


def test_the_editor_arranges_its_own_document_with_the_same_bindings(stage):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.world3d_templates import create_world3d_templates_router
    patched = patch(stage, table_and_two())
    document = inspect_scene(WORKSPACE, SCENE, workspace_dir(stage))["document"]
    editor = {**document, "slots": [{key: value for key, value in slot.items() if key not in ("rest", "restBase", "beside")}
                                     for slot in document["slots"]]}
    app = FastAPI()
    app.include_router(create_world3d_templates_router(workspace_dir(stage), thumbnails=object()))
    reply = TestClient(app).post("/api/v1/world3d/templates/arrange", json={"workspace": WORKSPACE, "document": editor, "bindings": [
        {"object_id": "chair_a", "beside": {"object": "table", "side": "left"}},
        {"object_id": "tall", "rest": {"pose": "sit", "on": "chair_a", "at": "table"}}]})
    assert reply.status_code == 200, reply.text
    arranged = reply.json()
    assert slot_of(arranged, "tall")["position"] == slot_of(patched, "tall")["position"]
    assert slot_of(arranged, "tall")["sourceUrl"] == slot_of(patched, "tall")["sourceUrl"], "the same derived file, made once"
    assert contact(arranged, "tall")["pose"] == "seated"
    assert inspect_scene(WORKSPACE, SCENE, workspace_dir(stage))["revision"] == patched["revision"], "the working scene is not touched"
    refused = TestClient(app).post("/api/v1/world3d/templates/arrange", json={"workspace": WORKSPACE, "document": editor,
                                                                              "bindings": [{"object_id": "tall", "rest": {"pose": "lie", "on": "x"}}]})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "invalid_rest"


def test_a_beat_that_acts_stands_the_sitter_up_and_says_so(stage):
    from services.world3d_beats import beat_scene
    viewed = patch(stage, [{"object_id": "chair", "add": True, "furniture": {"kind": "chair", "seat": 0.4}},
                           {"object_id": "pet", "add": True, "source_url": PET, "height": 1.75, "rest": {"pose": "sit", "on": "chair"}}])
    acted = beat_scene(WORKSPACE, SCENE, workspace_dir(stage), {"beats": [{"t": 1, "who": "pet", "verb": "do", "action": "Sit Down"}]},
                       viewed["revision"])
    assert any(line.startswith("rest_released: pet") for line in acted["warnings"])
    assert "rest" not in slot_of(acted, "pet") and slot_of(acted, "pet")["sourceUrl"] == PET
    assert "Sit Down" in [cue["clip"]["name"] for cue in slot_of(acted, "pet")["clips"]]


def test_without_a_table_the_hands_rest_on_the_thighs_or_beside_the_hips_on_a_wide_seat(stage):
    viewed = patch(stage, [{"object_id": "chair", "add": True, "furniture": {"kind": "chair", "seat": 0.4}},
                           {"object_id": "pet", "add": True, "source_url": PET, "height": 1.75, "rest": {"pose": "sit", "on": "chair"}}])
    lap = joints(stage, viewed, "pet").joints
    for side in ("Left", "Right"):
        thigh = (lap[f"{side}UpLeg"] + lap[f"{side}Leg"]) / 2
        assert lap[f"{side}Hand"][1] > thigh[1] and np.linalg.norm(lap[f"{side}Hand"][[0, 2]] - thigh[[0, 2]]) < 0.2, "a hand on its thigh"
    bed = patch(stage, [{"object_id": "bed", "add": True, "furniture": {"kind": "bed", "height": 0.4}, "position": [3, 0, 0]},
                        {"object_id": "pet", "rest": {"pose": "sit", "on": "bed"}}])
    hands = joints(stage, bed, "pet").joints
    top = item(bed, "bed")["boundsM"]["min"][1] + 0.4
    for side in ("Left", "Right"):
        assert hands[f"{side}Hand"][1] == pytest.approx(top + rest_place.HAND_LIFT_M, abs=0.04), "on the mattress beside the hips"
    assert abs(hands["LeftHand"][0] - hands["RightHand"][0]) > abs(hands["LeftUpLeg"][0] - hands["RightUpLeg"][0]) + 0.2
    arms = patch(stage, [{"object_id": "pet", "rest": {"pose": "sit", "on": "bed", "hands": False}}])
    assert slot_of(arms, "pet")["sourceUrl"] != slot_of(bed, "pet")["sourceUrl"], "hands: false bakes the clip's own arms"


def test_a_grown_body_that_would_need_a_childs_seat_is_told_its_legs_look_wrong(stage):
    viewed = patch(stage, [{"object_id": "chair", "add": True, "furniture": {"kind": "chair", "seat": 0.62}},
                           {"object_id": "pet", "add": True, "source_url": PET, "height": 1.5, "rest": {"pose": "sit", "on": "chair"}}])
    line = next(line for line in viewed["warnings"] if line.startswith("legs_unusually_short"))
    assert "pet is 1.50 m tall" in line and "a child's" in line and "Re-rig" in line
    assert "seat_height_unusual" not in codes(viewed) and not any(fix.get("object_id") == "chair" for fix in contact(viewed, "pet").get("fix", []))


def test_a_character_is_drawn_at_the_height_its_maker_recorded(stage):
    (stage / WORKSPACE / "pet.meta.json").write_text(json.dumps({"params": {"traits": {"height": 1.62}}}))
    viewed = patch(stage, [{"object_id": "pet", "add": True, "source_url": PET}])
    assert slot_of(viewed, "pet")["scale"] == pytest.approx(1.62 / MODEL_HEIGHT) and item(viewed, "pet")["recordedHeightM"] == 1.62
    chosen = patch(stage, [{"object_id": "other", "add": True, "source_url": PET, "height": 1.8}])
    assert slot_of(chosen, "other")["scale"] == pytest.approx(1.8 / MODEL_HEIGHT), "a height given wins"
    plain = patch(stage, [{"object_id": "crate", "add": True, "source_url": "/api/v1/file/crate.glb?workspace=studio"}])
    assert slot_of(plain, "crate")["scale"] == 1 and "recordedHeightM" not in item(plain, "crate")


def test_a_stage_rooms_bed_and_desk_are_named_like_objects(stage):
    room = {"mold": {"id": "dormitorio", "blocks": [{"id": "bed", "kind": "bed", "box": [0, 0, -1.3, 1.7, 0.45, 2.2]},
                                                    {"id": "desk", "kind": "desk", "box": [2.5, 0, -1.0, 1.2, 0.68, 0.7]},
                                                    {"id": "sofa", "kind": "sofa", "box": [-2.5, 0, -1.0, 2.0, 0.8, 0.8]}]}}
    path = stage / WORKSPACE / "world3d-edits" / f"{SCENE}.json"
    record = json.loads(path.read_text())
    record["document"]["room"] = room
    path.write_text(json.dumps(record))
    viewed = patch(stage, [{"object_id": "pet", "add": True, "source_url": PET, "height": 1.75, "rest": {"pose": "sit", "on": "bed"}}])
    row = contact(viewed, "pet")
    assert row["pose"] == "seated" and row["seat"]["object"] == "bed" and row["seat"]["topM"] == pytest.approx(0.45, abs=0.01)
    assert not row.get("issues"), viewed["warnings"]
    sofa = patch(stage, [{"object_id": "pet", "rest": {"pose": "sit", "on": "sofa"}}])
    assert any(line.startswith("seat_surface_guessed: sofa is a box of the stage's set") for line in sofa["warnings"])
    chair = patch(stage, [{"object_id": "chair", "add": True, "furniture": {"kind": "chair", "seat": 0.4},
                           "beside": {"object": "desk", "side": "front"}}, {"object_id": "pet", "rest": {"pose": "sit", "on": "chair", "at": "desk"}}])
    assert contact(chair, "pet")["at"]["object"] == "desk"
    with pytest.raises(World3DSceneError) as refused:
        patch(stage, [{"object_id": "marker", "add": True}, {"object_id": "pet", "rest": {"pose": "sit", "on": "wardrobe"}}])
    message = str(refused.value)
    assert "the stage's own furniture (part of the set, named as it is): bed, desk, sofa" in message
    assert "empty markers (bind a GLB first): marker" in message and "add: true, furniture" in message


def test_an_agent_starts_from_an_empty_stage_sets_the_frame_and_names_the_scene(tmp_path):
    from services.world3d_template_commands import command_catalog, execute_command
    folder = tmp_path / WORKSPACE
    folder.mkdir()
    made = execute_command("world3d.scene.instantiate", {"version": 1, "intent_id": "blank-1", "input": {
        "workspace": WORKSPACE, "template_id": "blank", "width": 1080, "height": 1920, "duration": 6}}, workspace_dir(tmp_path))
    scene = made["result"]["scene"]
    assert (scene["document"]["width"], scene["document"]["height"], scene["document"]["duration"], scene["document"]["slots"]) == (1080, 1920, 6, [])
    changed = execute_command("world3d.scene.patch", {"version": 1, "intent_id": "frame-1", "input": {
        "workspace": WORKSPACE, "scene_id": scene["sceneId"], "base_revision": 1, "width": 1920, "height": 1080, "fps": 24}}, workspace_dir(tmp_path))
    document = changed["result"]["scene"]["document"]
    assert (document["width"], document["height"], document["fps"]) == (1920, 1080, 24)
    with pytest.raises(Exception):
        execute_command("world3d.scene.patch", {"version": 1, "intent_id": "frame-2", "input": {
            "workspace": WORKSPACE, "scene_id": scene["sceneId"], "base_revision": 2, "width": 1081}}, workspace_dir(tmp_path))
    tools = {tool["name"]: tool for tool in command_catalog()}
    patch_schema = json.dumps(tools["world3d.scene.patch"]["inputSchema"])
    assert "fixed holds eye and look still" in patch_schema and "orbit" in patch_schema and "1080 x 1920" in patch_schema
    assert 'template_id "blank"' in tools["world3d.scene.instantiate"]["description"]
    assert "No card is needed" in tools["world3d.scene.patch"]["description"]
    assert "scenes.world3d.export.receipt" in tools["world3d.scene.publish"]["description"]


def test_exports_say_which_receipt_to_poll():
    from services.jobs_wait import command_catalog as jobs_catalog
    from services.world3d_export import command_catalog as export_catalog
    assert "scenes.world3d.export.receipt" in jobs_catalog()[0]["description"]
    assert "not jobs.wait" in next(tool for tool in export_catalog() if tool["name"] == "scenes.world3d.export")["description"]
