"""world3d.scene.beats: who does what when, resolved into the object's own fields."""
import itertools
import json
import math

import jsonschema
import pytest

from services.mcp_profiles import SERIES_TOOLS
from services.world3d_beats import beat_scene
from services.world3d_blank_scene import editor_shape_problems
from services.world3d_scenes import World3DSceneError
from services.world3d_scene_motion import pose_at
from services.world3d_template_commands import command_catalog, execute_command
from tests.test_glb_bounds import accessor, mesh, write
from tests.test_world3d_scene_layout import SCENE, WORKSPACE, model_glb, scene, slot, workspace_dir

_INTENTS = itertools.count(1)
CLIPS = {"Idle": 2.0, "Walk": 1.0, "Run": 0.6, "Wave": 1.5, "Hit": 1.0, "Crouch": 2.0, "Wobble Dance": 2.0}


def person_glb(tmp_path, name="person.glb", clips=None, low=(-0.3, 0, -0.2), high=(0.3, 1.7, 0.2)):
    """A 1.7 m model with the given animations ({name: seconds}); the file has only its JSON, which is all the readers use."""
    folder = tmp_path / WORKSPACE
    folder.mkdir(exist_ok=True)
    clips = CLIPS if clips is None else clips
    accessors = [accessor(list(low), list(high))] + [{"componentType": 5126, "count": 2, "type": "SCALAR", "min": [0], "max": [length]} for length in clips.values()]
    animations = [{"name": label, "channels": [], "samplers": [{"input": index + 1, "output": index + 1, "interpolation": "LINEAR"}]} for index, label in enumerate(clips)]
    document = {"scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}], "meshes": [mesh(0)], "accessors": accessors}
    if animations:
        document["animations"] = animations
    return write(folder, document, name)


PERSON = "/api/v1/file/person.glb?workspace=studio"
PROP = "/api/v1/file/prop.glb?workspace=studio"


def sheet(tmp_path, beats, slots=None, revision=1, **document):
    return beat(tmp_path, beats, revision, slots=slots, **document)


def beat(tmp_path, beats, revision=1, slots=None, fresh=True, schema=True, **document):
    if fresh:
        person_glb(tmp_path)
        person_glb(tmp_path, "prop.glb", clips={})
        scene(tmp_path, slots if slots is not None else [slot("ana", PERSON, grounded=True, position=[0, 0, 5]), slot("rock", PROP, position=[0, 0, -5], grounded=True)], **document)
    arguments = {"version": 1, "intent_id": f"beats-{next(_INTENTS)}",
                 "input": {"workspace": WORKSPACE, "scene_id": SCENE, "base_revision": revision, "beats": beats}}
    if schema:
        jsonschema.validate(arguments, next(item for item in command_catalog() if item["name"] == "world3d.scene.beats")["inputSchema"])
    return execute_command("world3d.scene.beats", arguments, workspace_dir(tmp_path))["result"]["scene"]


def refused(tmp_path, beats, text, **document):
    with pytest.raises(Exception) as error:
        beat(tmp_path, beats, schema=False, **document)
    assert getattr(error.value, "status_code", None) == 422 or isinstance(error.value, World3DSceneError)
    detail = getattr(error.value, "detail", None) or {"code": getattr(error.value, "code", ""), "message": str(error.value)}
    assert detail["code"] == "invalid_beats" and text in detail["message"], detail
    assert json.loads((tmp_path / WORKSPACE / "world3d-edits" / f"{SCENE}.json").read_text())["revision"] == 1, "nothing is written"


def slot_of(viewed, identifier):
    return next(item for item in viewed["document"]["slots"] if item["id"] == identifier)


def test_the_command_is_registered_like_patch_and_the_reply_is_the_inspect_view_plus_resolved(tmp_path):
    entry = next(item for item in command_catalog() if item["name"] == "world3d.scene.beats")
    assert entry["mutation"] and entry["inputSchema"]["properties"]["intent_id"]["pattern"] and "world3d.scene.beats" in SERIES_TOOLS
    assert {"beats", "base_revision", "scene_id"} <= set(entry["inputSchema"]["properties"]["input"]["required"]) | {"beats"}
    viewed = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "appear"}])
    assert viewed["revision"] == 2 and viewed["layout"]["items"] and viewed["resolved"][0]["beat"] == 0 and viewed["document"]["slots"][0]["appearance"]["start"] == 0
    assert editor_shape_problems(viewed["document"]) == []


def test_appear_hides_the_object_until_t_and_can_place_it_and_a_second_appear_is_ignored(tmp_path):
    viewed = sheet(tmp_path, [{"t": 1.5, "who": "ana", "verb": "appear", "at": [3, 4], "duration": 0.5, "color": "#ffd36b"}, {"t": 3, "who": "ana", "verb": "appear"}])
    ana = slot_of(viewed, "ana")
    assert ana["appearance"] == {"start": 1.5, "duration": 0.5, "color": "#ffd36b"} and ana["position"] == [3, 0, 4]
    assert any(line.startswith("second_appear_ignored:") for line in viewed["warnings"]) and viewed["resolved"][1]["set"] == {}


def test_go_is_a_timed_move_with_the_walk_clip_over_the_same_seconds_and_idle_around_it(tmp_path):
    viewed = sheet(tmp_path, [{"t": 1, "who": "ana", "verb": "go", "to": [3, 2], "duration": 3, "face": True}])
    ana = slot_of(viewed, "ana")
    assert ana["motion"] == {"to": [3, 0, 2], "start": 1, "end": 4, "easing": "linear", "faceTravel": True}
    names = {index: label for index, label in enumerate(CLIPS)}
    assert [(cue["clip"]["name"], cue["start"]) for cue in ana["clips"]] == [("Idle", 0), ("Walk", 1), ("Idle", 4)]
    assert ana["clips"][1] == {"clip": {"index": 1, "name": "Walk"}, "start": 1, "duration": 3, "loop": True} and names[1] == "Walk"
    assert pose_at(ana, 0.5, 5)[0] == [0, 0, 5] and pose_at(ana, 4.5, 5)[0] == [3, 0, 2]
    assert viewed["resolved"][0]["set"]["motion"] == ana["motion"] and "impliedSpeedMps 1.41" in viewed["resolved"][0]["notes"][0]
    assert editor_shape_problems(viewed["document"]) == []


def test_a_fast_go_plays_the_run_clip_and_without_a_duration_a_walk_takes_its_pace(tmp_path):
    fast = slot_of(sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "go", "to": [0, -5], "duration": 2}]), "ana")
    assert [cue["clip"]["name"] for cue in fast["clips"]] == ["Run", "Idle"]                  # 10 m in 2 s: 5 m/s
    slow = sheet(tmp_path, [{"t": 0.5, "who": "ana", "verb": "go", "to": [0, 5 - 2.8]}])
    assert slot_of(slow, "ana")["motion"]["end"] == pytest.approx(2.5), "2.8 m at 1.4 m/s"
    paced = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "go", "to": [0, 5 - 6], "speed_mps": 2}])
    assert slot_of(paced, "ana")["motion"]["end"] == 3


def test_a_rigid_model_moves_without_clips_and_takes_until_its_next_beat_by_default(tmp_path):
    viewed = sheet(tmp_path, [{"t": 1, "who": "rock", "verb": "go", "to": [4, 0, -5]}, {"t": 3, "who": "rock", "verb": "do", "action": "bounce"}])
    rock = slot_of(viewed, "rock")
    assert rock["motion"]["start"] == 1 and rock["motion"]["end"] == 3 and "clips" not in rock
    assert any(line.startswith("no_clip_for_verb:") and "rock" in line for line in viewed["warnings"])
    assert not [line for line in viewed["warnings"] if line.startswith("implied_speed")]


def test_a_fast_move_warns_implied_speed_and_a_move_past_the_end_is_cut_with_a_warning(tmp_path):
    viewed = sheet(tmp_path, [{"t": 0, "who": "rock", "verb": "go", "to": [40, -5], "duration": 2}])
    assert any(line.startswith("implied_speed:") and "20.0 m/s" in line for line in viewed["warnings"])
    late = sheet(tmp_path, [{"t": 3, "who": "rock", "verb": "go", "to": [4, -5], "duration": 6}])
    assert slot_of(late, "rock")["motion"]["end"] == 5 and any(line.startswith("go_cut_short:") for line in late["warnings"])


def test_go_near_another_object_stops_short_of_where_it_is_when_it_arrives(tmp_path):
    viewed = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "go", "to": {"near": "rock", "distance_m": 2}, "duration": 3}])
    assert slot_of(viewed, "ana")["motion"]["to"] == pytest.approx([0, 0, -3])
    chased = sheet(tmp_path, [{"t": 0, "who": "rock", "verb": "go", "to": [10, -5], "duration": 4}, {"t": 0, "who": "ana", "verb": "go", "to": {"near": "rock", "distance_m": 1}, "duration": 4}])
    destination = slot_of(chased, "ana")["motion"]["to"]
    assert math.hypot(destination[0] - 10, destination[2] + 5) == pytest.approx(1, abs=0.05), "the rock is at 10, -5 when she arrives, whichever beat comes first"


def test_go_with_via_bends_the_path_and_easing_headings_and_a_second_go_are_handled(tmp_path):
    viewed = sheet(tmp_path, [{"t": 0, "who": "rock", "verb": "go", "to": [6, 0, -5], "via": [3, 4], "duration": 4, "easing": "smooth", "headingOffset": 1.5},
                              {"t": 2, "who": "rock", "verb": "go", "to": [9, -5], "duration": 1}])
    motion = slot_of(viewed, "rock")["motion"]
    assert motion["via"] == [3, 0, 4] and motion["easing"] == "smooth" and motion["headingOffset"] == 1.5 and motion["to"] == [6, 0, -5]
    assert any(line.startswith("second_go_ignored:") for line in viewed["warnings"])


def test_face_turns_before_the_move_or_in_place_the_short_way_and_after_the_move_it_is_ignored(tmp_path):
    before = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "face", "toward": "rock"}])
    assert slot_of(before, "ana")["rotationY"] == pytest.approx(math.pi, abs=1e-4) and "motion" not in slot_of(before, "ana")
    east = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "face", "toward": [5, 5]}])
    assert slot_of(east, "ana")["rotationY"] == pytest.approx(math.pi / 2, abs=1e-4)
    turning = sheet(tmp_path, [{"t": 2, "who": "ana", "verb": "face", "toward": [-5, 5]}], slots=[slot("ana", PERSON, grounded=True, position=[0, 0, 5], rotationY=6.0)])
    motion = slot_of(turning, "ana")["motion"]
    assert (motion["start"], motion["end"], motion["to"]) == (2, 2.5, [0, 0, 5]) and motion["turnTo"] == pytest.approx(-math.pi / 2 + 2 * math.pi, abs=1e-3), "from 6.0 rad the short way is up"
    after = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "go", "to": [0, 0], "duration": 2}, {"t": 3, "who": "ana", "verb": "face", "toward": "rock"}])
    assert any(line.startswith("face_after_go_ignored:") for line in after["warnings"])
    before_go = sheet(tmp_path, [{"t": 1, "who": "ana", "verb": "go", "to": [5, 5], "duration": 2}, {"t": 0.5, "who": "ana", "verb": "face", "toward": [5, 5]}])
    assert slot_of(before_go, "ana")["rotationY"] == pytest.approx(math.pi / 2, abs=1e-4)


def test_do_plays_the_clip_the_model_has_for_the_word_by_name_label_or_exact_name(tmp_path):
    viewed = sheet(tmp_path, [{"t": 0.5, "who": "ana", "verb": "do", "action": "wave"}, {"t": 2.5, "who": "ana", "verb": "do", "action": "wobble", "duration": 3},
                              {"t": 4, "who": "ana", "verb": "do", "action": "HIT"}])
    cues = [(cue["clip"]["name"], cue["start"], cue.get("duration"), cue.get("loop")) for cue in slot_of(viewed, "ana")["clips"]]
    assert cues == [("Idle", 0, None, True), ("Wave", 0.5, 1.5, False), ("Idle", 2.0, None, True), ("Wobble Dance", 2.5, 3, True), ("Hit", 4, 1, False)]
    assert viewed["resolved"][1]["set"]["clips"][0]["clip"] == {"index": 6, "name": "Wobble Dance"}


def test_a_word_the_model_has_no_clip_for_is_a_warning_with_the_clips_it_has_never_an_error(tmp_path):
    viewed = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "do", "action": "levitate"}])
    line = next(line for line in viewed["warnings"] if line.startswith("no_clip_for_verb:"))
    assert "'levitate'" in line and "Idle" in line and "clips" not in slot_of(viewed, "ana")
    marker = sheet(tmp_path, [{"t": 0, "who": "m", "verb": "do", "action": "wave"}], slots=[slot("m")])
    assert any(line.startswith("no_clip_for_verb:") for line in marker["warnings"])


def test_a_hold_plays_once_and_a_clip_longer_than_its_slot_loops(tmp_path):
    viewed = sheet(tmp_path, [{"t": 1, "who": "ana", "verb": "do", "action": "crouch", "duration": 4}, {"t": 0, "who": "ana", "verb": "do", "action": "walk", "duration": 0.5}])
    by_start = {cue["start"]: cue for cue in slot_of(viewed, "ana")["clips"]}
    assert by_start[1]["loop"] is False and by_start[0]["loop"] is False


def test_fx_at_an_object_a_point_or_where_the_object_passes_through_something(tmp_path):
    model_glb(tmp_path, "town.glb", low=(-2, 0, -2), high=(2, 1.7, 2))
    slots = [slot("town", "/api/v1/file/town.glb?workspace=studio", grounded=True, position=[0, 0, -3]), slot("ana", PERSON, grounded=True, position=[0, 0, 5])]
    viewed = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "go", "to": [0, -8], "duration": 4},
                              {"t": 2, "who": "ana", "verb": "fx", "kind": "explosion", "at": "collision", "intensity": 1.5},
                              {"t": 1, "who": "ana", "verb": "fx", "kind": "sparks", "at": [1, 2, 3]}, {"t": 3, "who": "ana", "verb": "fx", "kind": "smoke"}], slots=slots)
    cues = {cue["kind"]: cue for cue in viewed["document"]["worldSfx"]}
    assert cues["explosion"]["position"]["z"] == pytest.approx(viewed["layout"]["collisions"][0]["at"][2], abs=1e-3) and cues["explosion"]["intensity"] == 1.5
    assert cues["sparks"]["position"] == {"x": 1, "y": 2, "z": 3} and cues["smoke"]["anchor"]["slotId"] == "ana" and all(cue["label"] == "beat:ana" for cue in cues.values())
    assert any(line.startswith("collision: ana passes through town") for line in viewed["warnings"])


def test_an_fx_at_a_collision_with_none_is_a_warning_and_a_second_fx_call_replaces_the_first_and_keeps_the_rest(tmp_path):
    first = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "go", "to": [0, 2], "duration": 2}, {"t": 1, "who": "ana", "verb": "fx", "kind": "explosion", "at": "collision"},
                             {"t": 1, "who": "ana", "verb": "fx", "kind": "sparks"}], worldSfx=[{"id": "blast", "kind": "fire", "start": 0, "end": 1, "position": {"x": 0, "y": 0, "z": 0}}])
    assert any(line.startswith("no_collision_for_fx:") for line in first["warnings"])
    assert [cue["id"] for cue in first["document"]["worldSfx"]] == ["blast", "fx-beat-ana-sparks-2"]
    second = beat(tmp_path, [{"t": 2, "who": "ana", "verb": "fx", "kind": "shockwave"}], revision=2, fresh=False)
    assert [cue["kind"] for cue in second["document"]["worldSfx"]] == ["fire", "shockwave"] and slot_of(second, "ana")["motion"]["to"] == [0, 0, 2], "an fx-only call leaves the move"


def test_a_second_call_for_an_object_replaces_its_earlier_beats_and_leaves_the_others(tmp_path):
    first = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "go", "to": [0, 0], "duration": 2}, {"t": 0, "who": "rock", "verb": "go", "to": [3, -5], "duration": 2},
                             {"t": 1, "who": "ana", "verb": "appear"}])
    second = beat(tmp_path, [{"t": 1, "who": "ana", "verb": "do", "action": "wave"}], revision=2, fresh=False)
    ana = slot_of(second, "ana")
    assert "motion" not in ana and [cue["clip"]["name"] for cue in ana["clips"]] == ["Idle", "Wave", "Idle"] and "appearance" in ana, "go and do are one sheet; appear is another"
    assert slot_of(second, "rock")["motion"] == slot_of(first, "rock")["motion"], "an object the call does not name keeps its beats"


BAD = [
    ([{"t": 1, "who": "ghost", "verb": "go", "to": [0, 0]}], "not an object of the scene"),
    ([{"t": 5, "who": "ana", "verb": "appear"}], "outside the scene"), ([{"t": -1, "who": "ana", "verb": "appear"}], "outside the scene"),
    ([{"t": "soon", "who": "ana", "verb": "appear"}], "outside the scene"), (["x"], "must be an object"),
    ([{"t": 1, "who": "ana", "verb": "dance"}], "not one of appear, go, face, do, fx"), ([{"t": 1, "who": "ana", "verb": "fx"}], ".kind"),
    ([{"t": 1, "who": "ana", "verb": "fx", "kind": "teapot"}], "world effect"), ([{"t": 1, "who": "ana", "verb": "go"}], ".to must be"),
    ([{"t": 1, "who": "ana", "verb": "go", "to": [1]}], ".to must be"), ([{"t": 1, "who": "ana", "verb": "go", "to": {"near": "ana"}}], "another object"),
    ([{"t": 1, "who": "ana", "verb": "go", "to": [1, 1], "duration": 1, "speed_mps": 1}], "give one"), ([{"t": 1, "who": "ana", "verb": "go", "to": [1, 1], "duration": -1}], ".duration"),
    ([{"t": 1, "who": "ana", "verb": "face", "toward": "ghost"}], "another object"), ([{"t": 1, "who": "ana", "verb": "face", "toward": [0, 5]}], "no direction"),
    ([{"t": 1, "who": "ana", "verb": "do"}], ".action"), ([{"t": 1, "who": "ana", "verb": "appear", "color": "red"}], "appearance"),
    ([{"t": 1, "who": "ana", "verb": "fx", "kind": "fire", "at": [99, 0, 0]}], "farther than 50 m"),
]


@pytest.mark.parametrize("beats, text", BAD, ids=[text for _beats, text in BAD])
def test_a_bad_beat_is_refused_with_its_position_and_nothing_is_written(tmp_path, beats, text):
    refused(tmp_path, beats, text)


@pytest.mark.parametrize("beats", ["nope", [], [{"t": 0, "who": "ana", "verb": "appear"}] * 65])
def test_beats_must_be_a_list_of_one_to_sixty_four(tmp_path, beats):
    person_glb(tmp_path)
    scene(tmp_path, [slot("ana", PERSON)])
    with pytest.raises(World3DSceneError) as error:
        beat_scene(WORKSPACE, SCENE, workspace_dir(tmp_path), {"beats": beats}, 1)
    assert error.value.code == "invalid_beats" and "list of 1-64" in str(error.value)


def test_a_stale_revision_is_a_conflict_and_the_receipt_replays(tmp_path):
    sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "appear"}])
    with pytest.raises(Exception) as stale:
        beat(tmp_path, [{"t": 1, "who": "ana", "verb": "appear"}], revision=1, fresh=False)
    assert stale.value.status_code == 409 and stale.value.detail["code"] == "revision_conflict"
    arguments = {"version": 1, "intent_id": "same-1", "input": {"workspace": WORKSPACE, "scene_id": SCENE, "base_revision": 2, "beats": [{"t": 1, "who": "ana", "verb": "appear"}]}}
    first = execute_command("world3d.scene.beats", arguments, workspace_dir(tmp_path))
    again = execute_command("world3d.scene.beats", arguments, workspace_dir(tmp_path))
    assert again.get("replayed") is True and again["result"] == first["result"]


def test_a_fixed_camera_that_never_sees_the_object_warns_but_an_entrance_does_not(tmp_path):
    camera = {"family": "fixed", "eye": [0, 1.5, 12], "look": [0, 1, 5], "fov": 40}                           # looks toward -z; the person walks in from z=5
    off = sheet(tmp_path, [{"t": 1, "who": "rock", "verb": "do", "action": "wave"}], camera={**camera, "look": [0, 1, 30]})   # turned the other way: the rock is behind it
    walk_in = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "go", "to": [0, 8], "duration": 3}, {"t": 0, "who": "ana", "verb": "appear"}], camera=camera)
    assert any(line.startswith("actor_out_of_frame:") and "rock" in line for line in off["warnings"])
    assert not [line for line in walk_in["warnings"] if line.startswith("actor_out_of_frame")]
    lost = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "go", "to": [60, 5], "duration": 5}], camera=camera,
                 slots=[slot("ana", PERSON, grounded=True, position=[30, 0, 5])])                                 # far off to the side the whole time
    assert any(line.startswith("actor_out_of_frame:") and "never inside" in line for line in lost["warnings"])


def test_the_moves_a_sheet_makes_are_checked_for_collisions_in_the_same_reply(tmp_path):
    model_glb(tmp_path, "town.glb", low=(-2, 0, -2), high=(2, 1.7, 2))
    slots = [slot("town", "/api/v1/file/town.glb?workspace=studio", grounded=True, position=[0, 0, 0]), slot("ana", PERSON, grounded=True, position=[0, 0, 8])]
    viewed = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "go", "to": [0, -8], "duration": 4}], slots=slots)
    hit = viewed["layout"]["collisions"][0]
    assert (hit["a"], hit["b"]) == ("ana", "town") and 1.4 < hit["from_s"] < 2.2 and any(line.startswith("collision: ana passes through town") for line in viewed["warnings"])
    ghost = sheet(tmp_path, [{"t": 0, "who": "ana", "verb": "go", "to": [0, -8], "duration": 4}], slots=[slots[0], {**slots[1], "collide": False}])
    assert ghost["layout"]["collisions"] == []
