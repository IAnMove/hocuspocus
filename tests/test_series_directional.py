"""Directional 2D figures in a Series 3D shot: the script fields, the kit's sheets, the scene binding and the checks."""
import copy
import json
import math
from pathlib import Path

import pytest

from services import series_directional as directional
from services import series_shot3d
from services.series_native_render import NativeRenderError

SPEC = json.loads((Path(__file__).resolve().parents[1] / "app" / "shared" / "directional_sprites.json").read_text(encoding="utf-8"))


def sheet_record(count=12, **extra):
    return {"sheet": {"source": "/api/v1/file/sheet.png?workspace=w", "width": 800, "height": 1920, "count": count, "columns": 4, "rows": 3,
                      "cell": {"width": 200, "height": 640}}, "frames": [], "fps": 8, "loop": "loop", "facing": "right",
            "reviewState": "approved", **extra}


def kit(**animations):
    return {"id": "kit-ana", "name": "Ana", "base": {"source": "ana.png", "reviewState": "approved"}, "animations": animations}


FIVE = ("front", "front34", "side", "back34", "back")


def full_kit():
    animations = {}
    for dir_name in FIVE:
        animations[f"walk-{dir_name}"] = sheet_record(motion="walk", dir=dir_name, view="front" if dir_name == "front" else "side")
        animations[f"idle-{dir_name}"] = sheet_record(2, motion="idle", dir=dir_name, loop="pingpong")
    return kit(**animations)


def test_a_heading_is_a_number_or_one_of_four_names():
    assert directional.heading_degrees("toward") == 0 and directional.heading_degrees("right") == 90
    assert directional.heading_degrees("away") == 180 and directional.heading_degrees("left") == -90
    assert directional.heading_degrees(270) == -90 and directional.heading_degrees(-180) == 180
    for bad in ("sideways", None, True, math.nan, math.inf, 5000, [], {}):
        assert directional.heading_degrees(bad) is None


def test_the_cast_fields_are_kept_when_valid_and_dropped_when_not():
    assert directional.cast_fields({"characterId": "ana"}) == {}
    kept = directional.cast_fields({"heading": "left", "walkTo": {"x": 1, "z": -2.5}, "walkSpeed": 0.8, "walkAt": 1.5})
    assert kept == {"heading": -90, "walkTo": {"x": 1, "z": -2.5}, "walkSpeed": 0.8, "walkAt": 1.5}
    assert directional.cast_fields({"walkTo": {"x": 1, "z": 2}}) == {"walkTo": {"x": 1, "z": 2}}
    assert directional.cast_fields({"walkTo": {"x": 1}}) == {} and directional.cast_fields({"walkTo": [1, 2]}) == {}
    assert directional.cast_fields({"walkSpeed": 2, "walkAt": 1}) == {}, "a speed with nowhere to go is nothing"
    assert directional.cast_fields({"walkTo": {"x": 1, "z": 2}, "walkSpeed": 99}) == {"walkTo": {"x": 1, "z": 2}}
    assert directional.cast_fields({"heading": "up"}) == {}
    assert directional.uses_direction({"heading": 0}) and directional.uses_direction({"walkTo": {"x": 0, "z": 0}})
    assert not directional.uses_direction({"characterId": "ana", "at": "near"})


def test_the_scene_keeps_the_fields_for_a_template_a_box_room_and_a_mold_room():
    entry = {"characterId": "ana", "objectId": "ana", "heading": "right", "walkTo": {"x": 2, "z": 1}, "walkSpeed": 1.0, "walkAt": 0.5}
    stored = series_shot3d.normalize_scene3d({"template": "two-shot", "cast": [entry]})
    assert stored["cast"][0]["heading"] == 90 and stored["cast"][0]["walkTo"] == {"x": 2, "z": 1}
    assert stored["cast"][0]["walkSpeed"] == 1.0 and stored["cast"][0]["walkAt"] == 0.5
    plain = {"template": "two-shot", "cast": [{"characterId": "ana", "objectId": "ana"}]}
    assert series_shot3d.normalize_scene3d(plain) == {"template": "two-shot", "cast": [{"characterId": "ana", "objectId": "ana"}], "quality": "draft"}
    from services.series_sets import script_scene3d
    series = {"rooms": {"kitchen": {"kind": "room", "prompt": "kitchen", "size": {"w": 4, "d": 5}}}}
    boxed = script_scene3d({"kind": "3d", "set": "kitchen", "cast": [{"characterId": "ana", "at": {"x": 1, "z": 0}, "heading": "away", "walkTo": {"x": -1, "z": 0}}]}, {}, series=series)
    assert boxed["cast"][0]["heading"] == "away" or boxed["cast"][0]["heading"] == 180
    assert series_shot3d.normalize_scene3d(boxed)["cast"][0]["walkTo"] == {"x": -1, "z": 0}
    mold = script_scene3d({"kind": "3d", "cast": [{"characterId": "ana", "mark": "behind_desk", "walkTo": {"x": 1, "z": 1}}]}, {"set3d": {"mold": "despacho"}})
    assert mold["cast"][0]["walkTo"] == {"x": 1, "z": 1}


def test_the_kit_offers_its_approved_sheets_with_the_motion_and_direction_they_say_or_the_ones_the_contract_infers():
    animations = {
        "walk": sheet_record(4, group="cycle", view="side"),                      # the old four-pose walk: side
        "walk-12": sheet_record(12, motion="walk", dir="side"),
        "walk-front": sheet_record(12, motion="walk", dir="front"),
        "idle": sheet_record(2, group="cycle", view="front", loop="pingpong"),    # the breathing idle: front
        "idle-back": sheet_record(2, motion="idle", dir="back"),
        "wave": sheet_record(4, group="gesture", view="front"),
        "walk-pending": {**sheet_record(12, motion="walk", dir="back"), "reviewState": "pending"},
        "run": sheet_record(4, group="cycle", view="side"),
        "walk-bust": sheet_record(4, group="cycle", view="bust"),
        "broken": {"reviewState": "approved"},
    }
    sheets = {item["id"]: item for item in directional.kit_sheets(kit(**animations))}
    assert set(sheets) == {"walk", "walk-12", "walk-front", "idle", "idle-back"}
    assert (sheets["walk"]["motion"], sheets["walk"]["dir"]) == ("walk", "side")
    assert (sheets["idle"]["motion"], sheets["idle"]["dir"]) == ("idle", "front")
    assert sheets["walk-12"]["count"] == 12 and sheets["walk-12"]["cell"] == {"width": 200, "height": 640}
    assert sheets["walk-12"]["columns"] == 4 and sheets["walk-12"]["rows"] == 3 and sheets["walk-12"]["fps"] == 8 and sheets["walk-12"]["loop"] == "loop"
    assert sheets["walk-12"]["source"] == "/api/v1/file/sheet.png?workspace=w"
    assert "facing" not in sheets["walk-12"], "right is the contract"
    left = directional.kit_sheets(kit(**{"walk-left": sheet_record(motion="walk", dir="side", facing="left")}))
    assert left[0]["facing"] == "left"
    assert directional.kit_sheets({"animations": None}) == [] and directional.kit_sheets({}) == []


def test_a_block_carries_what_the_painter_needs_and_a_figure_with_no_sheet_still_walks():
    entry = {"characterId": "ana", "heading": 90, "walkTo": {"x": 2, "z": 1}, "walkSpeed": 1.0, "walkAt": 0.5}
    block = directional.block(entry, full_kit(), [[1.0, 2.0]], "w")
    assert len(block["sheets"]) == 10 and block["heading"] == 90
    assert block["walk"] == {"to": [2, 1], "speed": 1.0, "start": 0.5} and block["speech"] == [[1.0, 2.0]]
    plain = directional.block({"characterId": "ana", "walkTo": {"x": 2, "z": 1}}, kit(), [], "w")
    assert plain == {"sheets": [], "walk": {"to": [2, 1], "speed": SPEC["walkSpeed"], "start": 0}}
    assert directional.block({"characterId": "ana", "at": "near"}, full_kit(), [], "w") is None
    relative = directional.kit_sheets(kit(**{"walk": sheet_record(group="cycle", view="side")}), "ws a")
    assert relative[0]["source"] == "/api/v1/file/sheet.png?workspace=w"
    outputs = sheet_record()
    outputs["sheet"]["source"] = "outputs/walk sheet.png"
    assert directional.kit_sheets(kit(walk=outputs | {"group": "cycle", "view": "side"}), "ws a")[0]["source"] == "/api/v1/file/walk%20sheet.png?workspace=ws%20a"


def test_the_nearest_direction_is_the_one_the_picture_would_take():
    assert directional.nearest_direction("front34", {"side", "back"}) == "side"
    assert directional.nearest_direction("side", {"front34", "back34"}) == "front34", "a tie goes toward the front"
    assert directional.nearest_direction("back", {"front"}) == "front"
    assert directional.nearest_direction("side", set()) is None


def test_the_server_sectors_are_the_renderers_table():
    """ui/tests/directionalSprite.test.ts walks the same table: 22.5, 67.5, 112.5 and 157.5 degrees are the edges, ties toward the front."""
    def expected(theta):
        reach = abs(directional._wrap(theta))
        return "front" if reach <= 22.5 else "front34" if reach <= 67.5 else "side" if reach <= 112.5 else "back34" if reach <= 157.5 else "back"
    for step in range(-720, 1441):
        assert directional._sector(step / 4) == expected(step / 4), step / 4
    assert [directional._sector(angle) for angle in (22.5, 22.6, 67.5, 67.6, 112.5, 112.6, 157.5, 157.6, -180)] == [
        "front", "front34", "front34", "side", "side", "back34", "back34", "back", "back"]


def test_a_still_figure_in_a_fixed_camera_needs_one_direction_and_a_walker_the_ones_of_its_path():
    spec = {"size": {"w": 4, "d": 5, "h": 2.6}}
    assert directional.needed_directions({"heading": 0, "at": {"x": 0, "z": 0}}, (0, 0), spec) == {"front"}
    assert directional.needed_directions({"heading": 90}, (0, 0), spec) == {"side"}
    assert directional.needed_directions({"heading": -90}, (0, 0), spec) == {"side"}
    assert directional.needed_directions({"heading": 180}, (0, 0), spec) == {"back"}
    across = directional.needed_directions({"walkTo": {"x": -1.5, "z": 0}}, (1.5, 0), spec)
    assert "side" in across and across <= {"side", "front34", "back34"}
    assert directional.needed_directions({"heading": 0}, (0, 0), None) == set(FIVE)


def test_the_window_of_each_speaker_comes_from_the_timing_of_the_shot():
    beats = [{"characterId": "ana", "text": "hi"}, {"characterId": "luis", "text": "yo"}, {"characterId": "ana", "text": "again"}, {"characterId": "ana", "text": " "}]
    windows = directional.speech_windows(beats, [(0.5, 1.5), (2.0, 3.0), (3.5, 4.0), (5.0, 6.0)])
    assert windows == {"ana": [[0.5, 1.5], [3.5, 4.0]], "luis": [[2.0, 3.0]]}
    assert directional.speech_windows([], []) == {}


def test_the_bindings_give_each_directional_cast_member_its_block_and_nobody_else_anything():
    config = {"template": "two-shot", "cast": [
        {"characterId": "ana", "objectId": "subject_1", "heading": 0, "walkTo": {"x": 1, "z": 1}},
        {"characterId": "luis", "objectId": "subject_2"},
        {"characterId": "eva", "objectId": "extra", "heading": 90}]}
    kits = {"kit-ana": full_kit(), "kit-eva": kit()}
    characters = {"ana": "kit-ana", "luis": "kit-luis", "eva": "kit-eva"}
    found = directional.directional_bindings(config, kits, characters, {"ana": [[1, 2]]}, "w")
    assert [item["object_id"] for item in found] == ["subject_1", "extra"]
    assert found[0]["directional"]["speech"] == [[1, 2]] and len(found[0]["directional"]["sheets"]) == 10
    assert found[1]["directional"] == {"sheets": [], "heading": 90}
    assert directional.directional_bindings({"template": "two-shot", "cast": [{"characterId": "luis", "objectId": "subject_2"}]}, kits, characters, {}, "w") == []


class World3D:
    def __init__(self):
        self.calls = []

    def __call__(self, tool, arguments):
        self.calls.append((tool, arguments))
        data = arguments.get("input") or {}
        if tool == "world3d.templates.user.put":
            return {"result": {"template": {"id": data["id"]}}}
        if tool == "world3d.scene.instantiate":
            return {"result": {"scene": {"sceneId": "w3d-1", "revision": 1}}}
        if tool in ("world3d.scene.patch", "world3d.scene.talk"):
            return {"result": {"scene": {"sceneId": "w3d-1", "revision": data["base_revision"] + 1}}}
        if tool == "world3d.scene.publish":
            return {"result": {"scene": {"sceneId": "w3d-1", "revision": 9, "file": "w3d-1.world3d.scene.json", "document": {"v": 1}}}}
        raise AssertionError(tool)


def test_a_directional_shot_binds_the_sheets_after_the_voice_and_a_plain_shot_asks_for_the_same_as_before():
    shot = {"id": "s1", "scene3d": {"template": "user-mars", "cast": [{"characterId": "ana", "objectId": "ana", "heading": "toward", "walkTo": {"x": 1, "z": 1}}]}}
    lines = [{"characterId": "ana", "start": 0.8, "filename": "ln1.wav", "cues": []}]
    tools = World3D()
    series_shot3d.build_scene(tools, "w", "job", shot, lines, 4.5, {"kit-ana": full_kit()}, {"ana": "kit-ana"}, NativeRenderError, speech={"ana": [[0.8, 2.0]]})
    names = [tool for tool, _ in tools.calls]
    assert names[-3:] == ["world3d.scene.talk", "world3d.scene.patch", "world3d.scene.publish"]
    patch = tools.calls[-2][1]["input"]
    assert patch["base_revision"] == 4 and patch["bindings"][0]["object_id"] == "ana"
    block = patch["bindings"][0]["directional"]
    assert block["speech"] == [[0.8, 2.0]] and block["heading"] == 0 and block["walk"]["to"] == [1, 1]
    # A shot that names no direction makes exactly the calls and the digest it made before this existed.
    plain = {"id": "s1", "scene3d": {"template": "user-mars", "cast": [{"characterId": "ana", "objectId": "ana"}]}}
    before, after = World3D(), World3D()
    one = series_shot3d.build_scene(before, "w", "job", plain, lines, 4.5, {"kit-ana": full_kit()}, {"ana": "kit-ana"}, NativeRenderError)
    two = series_shot3d.build_scene(after, "w", "job", plain, lines, 4.5, {"kit-ana": full_kit()}, {"ana": "kit-ana"}, NativeRenderError, speech={"ana": [[0.8, 2.0]]})
    assert before.calls == after.calls and one["renderDigest"] == two["renderDigest"]
    assert not any("directional" in json.dumps(args) for _tool, args in before.calls)


def test_a_silent_directional_figure_in_a_plain_template_is_bound_to_its_pose_first():
    from services.series_sets import bind_silent_cast
    calls = []

    def call(name, args):
        calls.append(args["input"])
        return {"result": {"scene": {"sceneId": "scene", "revision": 2}}}
    config = {"template": "two-shot", "cast": [{"characterId": "ana", "objectId": "subject_1", "heading": 90}, {"characterId": "luis", "objectId": "subject_2"}]}
    kits = {"kit-ana": kit(), "kit-luis": kit()}
    result = bind_silent_cast(call, "w", "stem", {"sceneId": "scene", "revision": 1}, config, [], kits, {"ana": "kit-ana", "luis": "kit-luis"})
    assert result["revision"] == 2 and [row["object_id"] for row in calls[0]["bindings"]] == ["subject_1"]
    assert calls[0]["bindings"][0]["media"] == "image" and calls[0]["bindings"][0]["imageLook"] == {"grounded": True}
    untouched = bind_silent_cast(call, "w", "stem", {"sceneId": "scene", "revision": 1}, {"template": "two-shot", "cast": config["cast"][1:]}, [], kits, {"luis": "kit-luis"})
    assert untouched["revision"] == 1


# The script check ---------------------------------------------------------------------------

class Checker:
    def __init__(self, kits, characters=("ana",)):
        self.kits = kits
        self.problems = []
        self.characters = {name: {"id": name, "voiceProfile": {"characterKitRef": {"id": f"kit-{name}"}}} for name in characters}


def run_check(shot, kits=None, series=None):
    checker, warnings = Checker(kits if kits is not None else {"kit-ana": full_kit()}), []
    directional.check_shot(checker, shot, "shot 1", "s1", warnings, series or {})
    return checker.problems, warnings


BOX = {"kind": "room", "prompt": "a small kitchen", "size": {"w": 4, "d": 5}, "floor": "oak boards", "walls": "warm plaster"}


def test_a_shot_that_names_no_direction_says_nothing():
    problems, warnings = run_check({"kind": "3d", "cast": [{"characterId": "ana", "at": "near"}]})
    assert problems == [] and warnings == []


def test_direction_fields_belong_to_a_3d_shot_and_must_be_well_formed():
    problems, _ = run_check({"kind": "2d", "cast": [{"characterId": "ana", "heading": 0}]})
    assert any("only for a 3d shot" in item for item in problems)
    problems, _ = run_check({"kind": "3d", "cast": [{"characterId": "ana", "heading": "sideways"}]})
    assert any("heading" in item for item in problems)
    problems, _ = run_check({"kind": "3d", "cast": [{"characterId": "ana", "walkTo": {"x": 1}}]})
    assert any("walkTo" in item for item in problems)
    problems, _ = run_check({"kind": "3d", "cast": [{"characterId": "ana", "walkTo": {"x": 1, "z": 1}, "walkSpeed": 40}]})
    assert any("walkSpeed" in item for item in problems)
    problems, _ = run_check({"kind": "3d", "cast": [{"characterId": "ana", "walkSpeed": 1.0}]})
    assert any("walkTo" in item for item in problems)
    problems, _ = run_check({"kind": "3d", "cast": [{"characterId": "ana", "heading": "left", "walkTo": {"x": 1, "z": 1}, "walkSpeed": 1, "walkAt": 0.5}]})
    assert problems == []


def test_a_kit_without_the_direction_a_fixed_camera_needs_warns_and_names_the_nearest():
    partial = kit(**{"walk-12": sheet_record(12, motion="walk", dir="side"), "idle-front": sheet_record(2, motion="idle", dir="front")})
    series = {"rooms": {"kitchen": BOX}}
    shot = {"kind": "3d", "set": "kitchen", "cast": [{"characterId": "ana", "at": {"x": 1.5, "z": 0}, "walkTo": {"x": -1.5, "z": 0}}]}
    problems, warnings = run_check(shot, {"kit-ana": partial}, series)
    assert problems == []
    missing = [item for item in warnings if item["code"] == "direction_sheet_missing"]
    assert len(missing) == 1 and missing[0]["subject"] == "ana" and missing[0]["shots"] == ["s1"]
    assert "walk" in missing[0]["message"] and "nearest" in missing[0]["message"]
    complete, none = run_check(shot, {"kit-ana": full_kit()}, series)
    assert complete == [] and not [item for item in none if item["code"] == "direction_sheet_missing"]
    nothing, said = run_check({"kind": "3d", "cast": [{"characterId": "ana", "heading": 0}]}, {"kit-ana": kit()})
    assert nothing == [] and "base pose" in next(item for item in said if item["code"] == "direction_sheet_missing")["message"]


def test_a_destination_outside_the_room_warns_and_does_not_stop_the_script():
    series = {"rooms": {"kitchen": BOX}}
    inside = {"kind": "3d", "set": "kitchen", "cast": [{"characterId": "ana", "at": {"x": 1, "z": 0}, "walkTo": {"x": -1, "z": 1}}]}
    assert not [item for item in run_check(inside, series=series)[1] if item["code"] == "walk_path_outside_room"]
    out = {"kind": "3d", "set": "kitchen", "cast": [{"characterId": "ana", "at": {"x": 1, "z": 0}, "walkTo": {"x": 5, "z": 0}}]}
    problems, warnings = run_check(out, series=series)
    assert problems == [] and [item["code"] for item in warnings if item["code"] == "walk_path_outside_room"] == ["walk_path_outside_room"]
    zone = {"kind": "3d", "set": "kitchen", "cast": [{"characterId": "ana", "at": "near", "walkTo": {"x": 0, "z": 9}}]}
    assert any(item["code"] == "walk_path_outside_room" for item in run_check(zone, series=series)[1])


def test_a_walker_who_speaks_is_told_that_the_walk_stops_while_the_voice_runs():
    shot = {"kind": "3d", "lines": [{"who": "ana", "es": "hola"}], "cast": [{"characterId": "ana", "walkTo": {"x": 1, "z": 1}}]}
    _, warnings = run_check(shot)
    blocked = [item for item in warnings if item["code"] == "walk_blocked_by_speech"]
    assert len(blocked) == 1 and "stops" in blocked[0]["message"]
    silent = {"kind": "3d", "lines": [{"who": "luis", "es": "hola"}], "cast": [{"characterId": "ana", "walkTo": {"x": 1, "z": 1}}]}
    assert not [item for item in run_check(silent)[1] if item["code"] == "walk_blocked_by_speech"]


def test_the_render_measures_how_long_the_walk_waited_for_the_voice():
    cast = {"characterId": "ana", "objectId": "ana", "walkTo": {"x": 3, "z": 0}, "walkSpeed": 1.0, "walkAt": 0.5}
    shot = {"id": "s1", "scene3d": {"template": "user-mars", "cast": [cast]}}
    warnings = directional.render_warnings(shot, {"ana": [[1.0, 2.0], [9.0, 10.0]]}, (0.0, 0.0), "s1")
    assert len(warnings) == 1 and warnings[0]["code"] == "walk_blocked_by_speech" and "1 s" in warnings[0]["message"]
    assert directional.render_warnings(shot, {"ana": [[8.0, 9.0]]}, (0.0, 0.0), "s1") == [], "after the walk ended nothing waits"
    assert directional.render_warnings(shot, {}, (0.0, 0.0), "s1") == []
    plain = {"id": "s1", "scene3d": {"template": "user-mars", "cast": [{"characterId": "ana", "objectId": "ana"}]}}
    assert directional.render_warnings(plain, {"ana": [[1.0, 2.0]]}, (0.0, 0.0), "s1") == []


# The scene binding ----------------------------------------------------------------------------

def scene_slot(media="image"):
    return {"id": "ana", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0, "scale": 1, "sourceUrl": "/api/v1/file/ana.png?workspace=w", "media": media, "clip": None}


def block_of(**extra):
    return {"sheets": [{"motion": "walk", "dir": "side", "source": "/api/v1/file/w.png?workspace=w", "columns": 4, "rows": 3, "count": 12,
                        "cell": {"width": 200, "height": 640}, "fps": 8, "loop": "loop"}], **extra}


def test_the_patch_stores_the_block_on_the_screen_of_an_image_object_and_refuses_what_the_editor_would_not_read():
    from services import world3d_slot_fields as fields
    from services.world3d_scenes import World3DSceneError, _bind
    document = {"slots": [scene_slot()]}
    _bind(document, {"object_id": "ana", "directional": block_of(heading=90, walk={"to": [2, 1], "speed": 1.2, "start": 0.5})}, set())
    stored = document["slots"][0]["screen"]
    assert stored["media"] == "image" and stored["sourceUrl"] == "/api/v1/file/ana.png?workspace=w"
    assert stored["directional"]["heading"] == 90 and stored["directional"]["walk"]["to"] == [2, 1]
    _bind(document, {"object_id": "ana", "directional": None}, set())
    assert "directional" not in document["slots"][0]["screen"]
    for bad in ({"sheets": "x"}, block_of(heading="sideways"), block_of(walk={"to": [1], "speed": 1, "start": 0}), block_of(walk={"to": [1, 2], "speed": 0, "start": 0}),
                block_of(speech=[[2, 1]]), {"sheets": [{**block_of()["sheets"][0], "dir": "up"}]}, {"sheets": [{**block_of()["sheets"][0], "count": 0}]}, {"sheets": []}, 5):
        with pytest.raises(World3DSceneError) as error:
            _bind({"slots": [scene_slot()]}, {"object_id": "ana", "directional": bad}, set())
        assert error.value.code == "invalid_directional"
    with pytest.raises(World3DSceneError):
        _bind({"slots": [scene_slot("model3d")]}, {"object_id": "ana", "directional": block_of()}, set())
    assert fields.directional(block_of(heading="left"))["heading"] == -90
    assert fields.directional({"sheets": [], "heading": 0}) == {"sheets": [], "heading": 0}


def test_the_stored_block_is_exactly_what_the_editor_parses():
    from services import world3d_slot_fields as fields
    given = block_of(heading="away", walk={"to": [2, 1], "speed": 1.2, "start": 0.5}, speech=[[3, 4], [0, 1]])
    kept = fields.directional(copy.deepcopy(given))
    assert kept["heading"] == 180 and kept["speech"] == [[0, 1], [3, 4]]
    assert fields.directional(copy.deepcopy(kept)) == kept


def test_the_tools_say_the_new_fields():
    from services.series_commands import OPERATIONS
    from services.world3d_template_commands import command_catalog
    text = json.dumps(OPERATIONS["series.episode.from_script"]) + json.dumps(OPERATIONS["series.shot.update"])
    for word in ("heading", "walkTo", "walkSpeed", "walkAt"):
        assert word in text, word
    patch = next(item for item in command_catalog() if item["name"] == "world3d.scene.patch")
    assert "directional" in json.dumps(patch)
