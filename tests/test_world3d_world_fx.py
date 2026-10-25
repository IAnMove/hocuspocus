"""worldFx in a world3d.scene.patch: 3D effects placed by point, by object (they follow it) or at a collision."""
import json
import math

import jsonschema
import pytest

from services.world3d_blank_scene import editor_shape_problems
from services.world3d_scenes import World3DSceneError, patch_scene
from services.world3d_template_commands import command_catalog, execute_command
from services.world3d_world_fx import world_fx_problems
from tests.test_world3d_scene_collisions import passer, world
from tests.test_world3d_scene_layout import SCENE, WORKSPACE, model_glb, scene, slot, workspace_dir


def patch(tmp_path, revision=1, **changes):
    return patch_scene(WORKSPACE, SCENE, workspace_dir(tmp_path), {"bindings": changes.pop("bindings", []), **changes}, revision)


def own(viewed):
    return [cue for cue in viewed["document"]["worldSfx"] if cue["id"].startswith("fx-")]


def test_an_explosion_at_a_point_is_a_cue_the_editor_parses_and_the_inspect_echoes(tmp_path):
    scene(tmp_path, [slot("a")])
    viewed = patch(tmp_path, worldFx=[{"kind": "explosion", "start": 1.5, "at": [2, 0.5, -3], "scale": 2, "color": "#ff6a32", "intensity": 1.4, "sound": True, "volume": 0.4}])
    (cue,) = own(viewed)
    assert cue["kind"] == "explosion" and (cue["start"], cue["end"]) == (1.5, 3.9) and cue["position"] == {"x": 2, "y": 0.5, "z": -3}
    assert (cue["scale"], cue["intensity"], cue["color"], cue["sound"], cue["volume"]) == (2, 1.4, "#ff6a32", True, 0.4)
    assert cue["id"] == "fx-explosion-1" and 1 <= cue["seed"] <= 1_000_000 and "anchor" not in cue
    assert viewed["worldFx"] == [{"id": "fx-explosion-1", "kind": "explosion", "start": 1.5, "end": 3.9, "at": [2, 0.5, -3], "own": True}]
    assert "worldFx" in viewed["editable"] and editor_shape_problems(viewed["document"]) == []


def test_a_patch_replaces_its_own_fx_cues_and_keeps_the_templates(tmp_path):
    scene(tmp_path, [slot("a")], worldSfx=[{"id": "blast", "kind": "explosion", "start": 0.5, "end": 2, "position": {"x": 0, "y": 0.4, "z": 0}}])
    first = patch(tmp_path, worldFx=[{"id": "fx-one", "kind": "sparks", "start": 0, "at": [0, 1, 0]}, {"kind": "smoke", "start": 1, "end": 2, "at": [1, 0, 1]}])
    assert [cue["id"] for cue in first["document"]["worldSfx"]] == ["blast", "fx-one", "fx-smoke-2"]
    again = patch(tmp_path, revision=2, worldFx=[{"id": "fx-two", "kind": "fire", "start": 0, "at": [0, 0, 0]}])
    assert [cue["id"] for cue in again["document"]["worldSfx"]] == ["blast", "fx-two"]
    cleared = patch(tmp_path, revision=3, worldFx=[])
    assert [cue["id"] for cue in cleared["document"]["worldSfx"]] == ["blast"] and [row["own"] for row in cleared["worldFx"]] == [False]
    untouched = patch(tmp_path, revision=4, bindings=[])
    assert [cue["id"] for cue in untouched["document"]["worldSfx"]] == ["blast"]


def test_the_end_defaults_to_a_length_that_suits_the_kind_and_never_passes_the_scene(tmp_path):
    scene(tmp_path, [slot("a")], duration=3)
    cues = {cue["kind"]: cue for cue in own(patch(tmp_path, worldFx=[
        {"kind": "explosion", "start": 0.5, "at": [0, 0, 0]}, {"kind": "smoke", "start": 1, "at": [0, 0, 0]}, {"kind": "shockwave", "start": 0, "end": 7, "at": [0, 0, 0]}]))}
    assert cues["explosion"]["end"] == 2.9 and cues["smoke"]["end"] == 3 and cues["shockwave"]["end"] == 7


def test_an_effect_on_an_object_is_an_anchor_in_the_models_own_units_that_follows_it(tmp_path):
    model_glb(tmp_path, "walker.glb", low=(-0.5, -0.85, -0.5), high=(0.5, 0.85, 0.5))                  # 1.7 m tall, origin in the middle
    scene(tmp_path, [slot("hero", "/api/v1/file/walker.glb?workspace=studio", position=[4, 0, -2], grounded=True, rotationY=math.pi / 2,
                          motion={"to": [4, 0, -12], "easing": "linear"})], duration=4)
    viewed = patch(tmp_path, worldFx=[{"kind": "sparks", "start": 2, "at": {"object_id": "hero", "offset": [0, 1.0, 0.5]}}])
    (cue,) = own(viewed)
    # 1.7 m model, factor 1: 1.0 m up from the feet is 1.0 + (-0.85) in local units, 0.5 m ahead is 0.5
    assert cue["anchor"] == {"slotId": "hero", "offset": {"x": 0, "y": pytest.approx(0.15), "z": 0.5}}
    # fallback place at start 2 s: halfway along the walk, 0.5 m ahead of a model turned a quarter (its front is +x)
    assert cue["position"] == {"x": pytest.approx(4.5), "y": 1.0, "z": pytest.approx(-7)}
    assert viewed["worldFx"][0]["anchoredTo"] == "hero"


def test_an_anchor_scales_with_the_model_and_a_scaled_model_keeps_the_offset_in_metres(tmp_path):
    model_glb(tmp_path, "big.glb", low=(-1, 0, -1), high=(1, 4, 1))                                    # 4 units tall: factor 1.7 / 4 x scale 2
    scene(tmp_path, [slot("big", "/api/v1/file/big.glb?workspace=studio", scale=2, grounded=True)])
    (cue,) = own(patch(tmp_path, worldFx=[{"kind": "fire", "start": 0, "at": {"object_id": "big", "offset": [0.85, 1.7, 0]}}]))
    assert cue["anchor"]["offset"] == {"x": pytest.approx(1.0), "y": pytest.approx(2.0), "z": 0}       # metres / (0.85) in the model's units; grounded: min y is 0


def test_an_effect_at_a_collision_takes_the_middle_of_that_passage(tmp_path):
    world(tmp_path, passer())
    viewed = patch(tmp_path, worldFx=[{"kind": "explosion", "start": 2, "at": {"collision": 0}}])
    first = viewed["layout"]["collisions"][0]
    (cue,) = own(viewed)
    assert [cue["position"][axis] for axis in "xyz"] == pytest.approx(first["at"], abs=1e-3)


@pytest.mark.parametrize("bad, text", [
    ({"kind": "teapot", "start": 0, "at": [0, 0, 0]}, "world effect"),
    ({"kind": "fire", "start": 0}, "must be [x, y, z]"),
    ({"kind": "fire", "start": 0, "at": [60, 0, 0]}, "farther than 50 m"),
    ({"kind": "fire", "start": 0, "at": [0, 0]}, "three numbers"),
    ({"kind": "fire", "start": 9, "at": [0, 0, 0]}, "never show"),
    ({"kind": "fire", "start": 1, "end": 1, "at": [0, 0, 0]}, "after .start"),
    ({"kind": "fire", "start": 0, "at": [0, 0, 0], "id": "boom"}, "start with fx-"),
    ({"kind": "fire", "start": 0, "at": [0, 0, 0], "scale": 99}, "scale"),
    ({"kind": "fire", "start": 0, "at": [0, 0, 0], "color": "red"}, "#rrggbb"),
    ({"kind": "fire", "start": 0, "at": [0, 0, 0], "sound": "yes"}, "true or false"),
    ({"kind": "fire", "start": 0, "at": [0, 0, 0], "bonus": 1}, "unknown"),
    ({"kind": "fire", "start": 0, "at": {"object_id": "nobody"}}, "not an object"),
    ({"kind": "fire", "start": 0, "at": {"object_id": "a", "offset": [1]}}, "offset"),
    ({"kind": "fire", "start": 0, "at": {"collision": 3}}, "layout.collisions"),
    ({"kind": "fire", "start": 0, "at": [0, 0, 0], "to": [1, 1, 1]}, "beam ends"),
    ({"kind": "laser", "start": 0, "at": [0, 0, 0], "to": {"collision": 0}}, "must be [x, y, z], {object_id"),
])
def test_a_bad_effect_is_refused_with_a_code_and_writes_nothing(tmp_path, bad, text):
    scene(tmp_path, [slot("a")], duration=5)
    with pytest.raises(World3DSceneError) as refused:
        patch(tmp_path, worldFx=[bad])
    assert refused.value.code == "invalid_world_fx" and text in str(refused.value)
    assert json.loads((tmp_path / WORKSPACE / "world3d-edits" / f"{SCENE}.json").read_text())["revision"] == 1


def test_a_beam_says_where_it_ends_and_without_it_a_warning_says_so(tmp_path):
    model_glb(tmp_path, "m.glb")
    here = "/api/v1/file/m.glb?workspace=studio"
    scene(tmp_path, [slot("a", here, position=[1, 0, 0]), slot("b", here, position=[5, 0, 0])])
    viewed = patch(tmp_path, worldFx=[{"kind": "laser", "start": 0, "at": [0, 1, 0], "to": [3, 1, 0]},
                                      {"id": "fx-bolt", "kind": "lightning", "start": 1, "at": {"object_id": "a"}, "to": {"object_id": "b"}}, {"id": "fx-lone", "kind": "energy_beam", "start": 2, "at": [0, 0, 0]}])
    laser, bolt, lone = own(viewed)
    assert laser["targetPosition"] == {"x": 3, "y": 1, "z": 0} and "target" not in laser
    assert bolt["target"]["slotId"] == "b" and bolt["anchor"]["slotId"] == "a" and "targetPosition" in bolt
    assert any(line.startswith("fx_beam_without_target:") and "worldFx[2]" in line for line in viewed["warnings"]) and "target" not in lone


def test_an_object_that_cannot_be_measured_gets_a_fixed_effect_and_a_warning(tmp_path):
    scene(tmp_path, [slot("marker", position=[2, 0, 2])])
    viewed = patch(tmp_path, worldFx=[{"kind": "smoke", "start": 0, "at": {"object_id": "marker", "offset": [0, 1, 0]}}])
    (cue,) = own(viewed)
    assert "anchor" not in cue and cue["position"] == {"x": 2, "y": 1, "z": 2}
    assert any(line.startswith("fx_anchor_fixed:") and "marker" in line for line in viewed["warnings"])


def test_the_editor_mirror_names_a_cue_the_editor_would_drop(tmp_path):
    document = {"version": 1, "units": "meters", "up": "y", "width": 1280, "height": 720, "fps": 30, "duration": 5,
                "camera": {"family": "fixed", "eye": [0, 1, 5], "look": [0, 1, 0], "fov": 45},
                "light": {"kind": "directional", "direction": [0, -1, 0], "intensity": 1, "color": "#ffffff"}, "slots": [slot("a")],
                "worldSfx": [{"id": "ok", "kind": "explosion", "start": 0, "end": 1}, {"id": "ok", "kind": "explosion", "start": 0, "end": 1},
                             {"id": "back", "kind": "fire", "start": 2, "end": 1}, {"id": "fx-odd", "kind": "teapot", "start": 0, "end": 1}, "junk"]}
    problems = world_fx_problems(document)
    assert len(problems) == 4 and "repeats the id 'ok'" in problems[0] and "ends before it starts" in problems[1] and "unknown kind" in problems[2] and "not an object" in problems[3]
    assert set(world_fx_problems(document)) <= set(editor_shape_problems(document))
    assert world_fx_problems({"worldSfx": [{"id": "packed", "kind": "phoenix", "start": 0, "end": 1}]}) == [], "a template's own kind (packed ones) is not judged"


def test_the_command_schema_takes_worldfx_and_the_reply_carries_it(tmp_path):
    schema = next(item for item in command_catalog() if item["name"] == "world3d.scene.patch")["inputSchema"]
    assert "worldFx" in schema["properties"]["input"]["properties"] and "collision" in schema["properties"]["input"]["properties"]["worldFx"]["description"]
    scene(tmp_path, [slot("a")])
    arguments = {"version": 1, "intent_id": "fx-1", "input": {"workspace": WORKSPACE, "scene_id": SCENE, "base_revision": 1,
                                                                "worldFx": [{"kind": "explosion", "start": 1, "at": [0, 0.5, 0]}]}}
    jsonschema.validate(arguments, schema)
    body = execute_command("world3d.scene.patch", arguments, workspace_dir(tmp_path))
    assert body["result"]["scene"]["worldFx"][0]["kind"] == "explosion"
