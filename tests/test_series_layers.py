"""A 2D set in layers: images and looping videos at a depth, behind or in front of the cast, pushed in by depth."""
import hashlib
import json

import pytest

from services.series_guide import build_bible
from services.series_layers import CAST_DEPTH, MAX_LAYERS, digest_location, layer_entry, layout_layers, normalize_location, shot_layers
from services.series_library import normalize_series_project
from services.series_script import ScriptError, apply_script
from services.series_shot_plan import BACKGROUND_ZOOM, background_point, build_shot_spec, normalize_layout2d, plan_layers
from services.series_take_inputs import render_inputs, stale_shot_ids
from tests.test_series_script_produce import FILES, KITS as SCRIPT_KITS, SCRIPT, Series

COLUMNS = {"assetId": "asset_columns", "depth": 0.25}
PILLAR = {"file": "fg-pillar.png", "depth": 0.95, "front": True, "x": 10, "y": 60, "scale": 0.9}
FOG = {"file": "fog.webm", "depth": 0.85, "front": True, "opacity": 0.5, "scale": 1.2, "drift": 14}


def series(**garage):
    character = lambda cid: {"id": cid, "voiceProfile": {"characterKitRef": {"id": f"kit-{cid}", "workspace": "cast"}}}
    return {"id": "uv", "title": "Valle", "spokenLanguage": "Español de España", "characters": [character("kevin"), character("gary")],
            "locations": [{"id": "garage", "referenceAssetIds": ["asset_day"], "layout2d": {"homes": {"kevin": 30, "gary": 70}, **garage}},
                          {"id": "street", "referenceAssetIds": ["asset_day"]}],
            "assets": {"asset_day": {"kind": "image", "uri": "outputs/day.png"}, "asset_columns": {"kind": "image", "uri": "columns.png"},
                       "asset_smoke": {"kind": "video", "uri": "outputs/smoke.mp4"}}}


TWO = {"id": "s1", "productionMethod": "animation_2d", "locationId": "garage", "camera": "push", "visibleCharacterIds": ["kevin", "gary"],
       "dialogueBeats": [{"id": "b1", "characterId": "kevin", "text": "Hola."}], "layout2d": {"framing": "two", "camera": "push"}}
THREE = {"id": "s2", "productionMethod": "animation_3d", "locationId": "garage", "visibleCharacterIds": ["kevin"],
         "dialogueBeats": [{"id": "b2", "characterId": "kevin", "text": "Adiós."}],
         "scene3d": {"template": "t", "cast": [{"characterId": "kevin", "objectId": "k"}]}}
STREET = {"id": "s3", "productionMethod": "animation_2d", "locationId": "street", "visibleCharacterIds": ["gary"], "dialogueBeats": []}
OWN = {**TWO, "id": "s4", "layout2d": {"framing": "two", "layers": [PILLAR]}}
KITS = {"kit-kevin": {"id": "kit-kevin", "name": "Kevin"}, "kit-gary": {"id": "kit-gary", "name": "Gary"}}
RECORDED = {"b1": {"filename": "l1.wav", "duration": 1.0}}


def spec(value, shot=TWO):
    return build_shot_spec(value, {"id": "ep1"}, shot, workspace="cast", recorded=RECORDED)


# Validation -------------------------------------------------------------------

def test_a_layer_gets_its_defaults_and_drops_unknown_keys():
    assert layer_entry({"file": "wall.png", "junk": 1}, "l") == {"file": "wall.png", "depth": 0.3, "front": False, "opacity": 1.0,
                                                                  "x": 50.0, "y": 50.0, "scale": 1.0}
    assert layer_entry({"assetId": "a", "front": True}, "l")["depth"] == 0.9, "an unplaced front layer sits near the lens"
    assert layer_entry({**FOG}, "l") == {"file": "fog.webm", "depth": 0.85, "front": True, "opacity": 0.5, "x": 50.0, "y": 50.0,
                                         "scale": 1.2, "drift": 14.0}
    assert "drift" not in layer_entry({"file": "fog.png", "drift": 0}, "l")


@pytest.mark.parametrize("bad, message", [
    ({"depth": 0.5}, "exactly one of assetId"), ({"assetId": "a", "file": "b.png"}, "exactly one of assetId"),
    ({"file": "  "}, "exactly one of assetId"), ({"file": 3}, "exactly one of assetId"),
    ({"file": "../outside.png"}, "workspace path"), ({"file": "/etc/x.png"}, "workspace path"),
    ({"file": "a.png", "depth": 1.5}, r"depth must be a number from 0 to 1"), ({"file": "a.png", "depth": True}, "depth"),
    ({"file": "a.png", "opacity": -0.1}, "opacity"), ({"file": "a.png", "scale": 0}, "scale"), ({"file": "a.png", "x": 200}, r"\.x"),
    ({"file": "a.png", "drift": 900}, "drift"), ({"file": "a.png", "front": "yes"}, "front must be true or false"), ("wall.png", "must be an object"),
])
def test_a_malformed_layer_is_refused_with_where_it_is(bad, message):
    with pytest.raises(ValueError, match=message):
        layout_layers({"layers": [{"file": "ok.png"}, bad]}, "locations[0].layout2d")
    with pytest.raises(ValueError, match=r"locations\[0\]\.layout2d\.layers\[1\]"):
        layout_layers({"layers": [{"file": "ok.png"}, bad]}, "locations[0].layout2d")


def test_layer_lists_and_the_cast_depth_are_bounded():
    with pytest.raises(ValueError, match=f"more than {MAX_LAYERS} layers"):
        layout_layers({"layers": [{"file": "a.png"}] * (MAX_LAYERS + 1)}, "layout2d")
    with pytest.raises(ValueError, match="must be a list"):
        layout_layers({"layers": {"file": "a.png"}}, "layout2d")
    for bad in (0, 1.2, "0.5", True):
        with pytest.raises(ValueError, match="layout2d.castDepth must be a number from 0.1 to 1"):
            layout_layers({"castDepth": bad}, "layout2d")
    assert layout_layers({"layers": None, "castDepth": None}, "layout2d") == {}, "null leaves them to the location"


def test_a_shot_layout_keeps_its_layers_and_an_empty_list_that_turns_them_off():
    assert normalize_layout2d({"framing": "two", "layers": [COLUMNS], "castDepth": 0.7}) == {
        "framing": "two", "layers": [layer_entry(COLUMNS, "l")], "castDepth": 0.7}
    assert normalize_layout2d({"layers": []}) == {"layers": []}
    with pytest.raises(ValueError, match=r"layout2d\.layers\[0\]"):
        normalize_layout2d({"layers": [{"depth": 2}]})


def test_the_series_checks_location_layers_and_keeps_the_rest_of_the_layout():
    project = {"id": "show", "locations": [{"id": "crypt", "layout2d": {"homes": {"a": 20}, "layers": [PILLAR], "anchors": {}}},
                                           {"id": "bare", "layout2d": {"homes": {"a": 40}, "layers": []}}]}
    saved = normalize_series_project(project, "show", "default")
    crypt, bare = saved["locations"]
    assert list(crypt["layout2d"]) == ["homes", "layers", "anchors"] and crypt["layout2d"]["layers"] == [layer_entry(PILLAR, "l")]
    assert bare["layout2d"] == {"homes": {"a": 40}}, "an empty list is dropped: no layers is the layout it had before"
    project["locations"][0]["layout2d"]["layers"] = [{"file": "pillar.png", "depth": -1}]
    with pytest.raises(ValueError, match=r"locations\[0\]\.layout2d\.layers\[0\]\.depth"):
        normalize_series_project(project, "show", "default")
    untouched = {"id": "plain", "layout2d": {"homes": {"a": 1}}}
    assert normalize_location(dict(untouched), "l") == untouched


# Planning ---------------------------------------------------------------------

def test_a_shot_without_layers_plans_the_spec_it_always_did():
    plain = spec(series())
    assert "layers" not in plain and "castDepth" not in plain
    assert hashlib.sha1(json.dumps(plain, sort_keys=True).encode()).hexdigest()[:16] == "46e08821933c2799"
    assert spec(series(layers=[COLUMNS]), {**TWO, "layout2d": {**TWO["layout2d"], "layers": []}}) == plain, "[] turns them off"


def test_the_spec_carries_the_set_layers_placed_on_the_framed_background():
    value = series(layers=[COLUMNS, PILLAR, FOG, {"assetId": "asset_smoke", "depth": 0.5}, {"assetId": "missing"}])
    planned = spec(value)
    zoom, focus = BACKGROUND_ZOOM["two"], 50.0  # the cast's x average: (30 + 70) / 2
    assert planned["castDepth"] == CAST_DEPTH
    columns, pillar, fog, smoke = planned["layers"]
    assert columns == {"id": "layer-1", "name": "Back layer 1", "source": "/api/v1/file/columns.png?workspace=cast", "kind": "image",
                       "x": 50.0, "y": 50.0, "scale": zoom, "opacity": 1.0, "depth": 0.25, "front": False}
    assert (pillar["x"], pillar["y"]) == background_point("two", focus, 0.1, 0.6) and pillar["scale"] == round(0.9 * zoom, 4)
    assert pillar["front"] and pillar["name"] == "Front layer 2" and pillar["source"] == "/api/v1/file/fg-pillar.png?workspace=cast"
    assert (fog["kind"], fog["drift"], fog["opacity"]) == ("video", 14.0, 0.5), "a workspace .webm loops as a video layer"
    assert (smoke["kind"], smoke["source"]) == ("video", "/api/v1/file/smoke.mp4?workspace=cast")
    assert [layer["id"] for layer in planned["layers"]] == ["layer-1", "layer-2", "layer-3", "layer-4"], "the missing asset is left out"
    # A tighter framing zooms and pans the background; a layer stays on its spot of it.
    close = spec(value, {**TWO, "visibleCharacterIds": ["kevin"], "layout2d": {"framing": "close"}})
    assert close["layers"][1]["x"] == background_point("close", 50.0, 0.1, 0.6)[0] and close["layers"][0]["scale"] == BACKGROUND_ZOOM["close"]


def test_a_shot_list_replaces_the_location_list_and_the_cast_depth_comes_from_the_shot_first():
    value = series(layers=[COLUMNS], castDepth=0.5)
    assert shot_layers(value["locations"][0], TWO) == ([layer_entry(COLUMNS, "l")], 0.5)
    layers, depth = shot_layers(value["locations"][0], {**OWN, "layout2d": {**OWN["layout2d"], "castDepth": 0.8}})
    assert layers == [layer_entry(PILLAR, "l")] and depth == 0.8
    assert shot_layers(None, STREET) == ([], CAST_DEPTH)
    assert shot_layers({"layout2d": {"layers": [{"depth": 9}, COLUMNS]}}, TWO)[0] == [layer_entry(COLUMNS, "l")], \
        "a hand-edited bad layer is skipped at render time, never a crash"
    assert plan_layers(value, OWN, "two", 50, "cast")["layers"][0]["source"] == "/api/v1/file/fg-pillar.png?workspace=cast"


# Take inputs ------------------------------------------------------------------

GOLDEN = ["9f137c867bc02ff8", "dc9d0489f54c7e54", "05ab93816a80ca6c"]


def test_shots_without_layers_keep_the_digests_they_had():
    assert [render_inputs(series(), shot, KITS) for shot in (TWO, THREE, STREET)] == GOLDEN
    location = series()["locations"][0]
    assert digest_location(location, TWO) is location and digest_location(None, TWO) is None


def test_changing_a_locations_layers_renders_only_its_2d_shots_that_use_them_again():
    def digests(**garage):
        value = series(**garage)
        return {shot["id"]: render_inputs(value, shot, KITS) for shot in (TWO, THREE, STREET, OWN)}

    plain, layered = digests(), digests(layers=[COLUMNS])
    assert [plain[key] for key in ("s1", "s2", "s3")] == GOLDEN
    assert layered["s1"] != plain["s1"], "the 2D shot in the garage draws them"
    assert (layered["s2"], layered["s3"], layered["s4"]) == (plain["s2"], plain["s3"], plain["s4"]), \
        "a 3D shot, a shot elsewhere and a shot with its own layers do not"
    assert digests(layers=[{**COLUMNS, "depth": 0.3}])["s1"] not in (plain["s1"], layered["s1"])
    deeper = digests(layers=[COLUMNS], castDepth=0.8)
    assert deeper["s1"] != layered["s1"] and deeper["s4"] != plain["s4"], "the location's cast depth still applies to s4"
    assert deeper["s2"] == plain["s2"]
    assert render_inputs(series(), {**OWN, "layout2d": {**OWN["layout2d"], "layers": [FOG]}}, KITS) != plain["s4"]


def test_only_the_shots_whose_layers_changed_are_stale():
    value = series(layers=[COLUMNS])
    shots = [{**shot, "attempts": [{"id": f"a-{shot['id']}", "outputAssetIds": [f"take-{shot['id']}"]}], "approvedAttemptId": f"a-{shot['id']}"}
             for shot in (TWO, THREE, STREET, OWN)]
    for shot in shots:
        value["assets"][f"take-{shot['id']}"] = {"metadata": {"renderInputs": render_inputs(value, shot, KITS)}}
    episode = {"id": "ep", "shots": shots}
    assert stale_shot_ids(value, episode, KITS) == []
    value["locations"][0]["layout2d"]["layers"] = [COLUMNS, PILLAR]
    assert stale_shot_ids(value, episode, KITS) == ["s1"]
    del value["locations"][0]["layout2d"]["layers"]
    assert stale_shot_ids(value, episode, KITS) == ["s1"]
    for shot in shots:
        value["assets"][f"take-{shot['id']}"]["metadata"]["renderInputs"] = render_inputs(series(), shot, KITS)
    assert stale_shot_ids(value, episode, KITS) == [], "taking the layers away is the set it was before"


# Script and bible -------------------------------------------------------------

def _script(**shot):
    talk = {**SCRIPT["shots"][1], **shot}
    return {**SCRIPT, "shots": [SCRIPT["shots"][0], talk, SCRIPT["shots"][2]]}


def test_a_script_shot_carries_its_layers_and_an_empty_list():
    tools = Series()
    tools.series["assets"] = {"asset_columns": {"kind": "image", "uri": "columns.png"}}
    apply_script(tools, tools.read, SCRIPT_KITS, FILES | {"fg-pillar.png"}, "cast", _script(layers=[COLUMNS, PILLAR], castDepth=0.7))
    card, talk, _ = tools.calls[1][1]["episode"]["shots"]
    assert talk["layout2d"]["layers"] == [layer_entry(COLUMNS, "l"), layer_entry(PILLAR, "l")] and talk["layout2d"]["castDepth"] == 0.7
    assert "layers" not in card["layout2d"]
    tools = Series()
    apply_script(tools, tools.read, SCRIPT_KITS, FILES, "cast", _script(layers=[]))
    assert tools.calls[1][1]["episode"]["shots"][1]["layout2d"]["layers"] == []


def test_a_script_lists_bad_layers_missing_files_and_unknown_assets_with_the_other_problems():
    tools = Series()
    with pytest.raises(ScriptError) as error:
        apply_script(tools, tools.read, SCRIPT_KITS, FILES, "cast", _script(layers=[{"file": "fg-pillar.png", "front": True}, {"assetId": "nope"}]))
    assert error.value.problems == ["shot 1 (e2s01) layer 0: file fg-pillar.png is not in the workspace",
                                    "shot 1 (e2s01): layer 1 names nope, not an image or video asset of the series"]
    with pytest.raises(ScriptError) as error:
        apply_script(tools, tools.read, SCRIPT_KITS, FILES, "cast", _script(layers=[{"file": "a.png", "depth": 3}], castDepth=0.6))
    assert error.value.problems == ["shot 1 (e2s01): layers[0].depth must be a number from 0 to 1"]
    assert tools.calls == []


def test_the_bible_shows_a_locations_layers():
    value = series(layers=[layer_entry(COLUMNS, "l")], castDepth=0.5)
    garage, street = build_bible({**value, "episodesById": {}}, {}, [])["locations"]
    assert garage["layers"] == [layer_entry(COLUMNS, "l")] and garage["castDepth"] == 0.5
    assert "layers" not in street and "castDepth" not in street
