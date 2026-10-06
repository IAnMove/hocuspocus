"""A character walks into a 2D shot when and for as long as the script says, and its footsteps can follow its feet."""
import pytest

from services import series_entrances as entrances
from services.series_script import ScriptError, apply_script
from services.series_shot_extras import cue_time, fx_cues, sfx_tracks
from services.series_shot_plan import build_shot_spec, normalize_layout2d, plan_cast
from services.series_take_inputs import render_inputs
from tests.test_series_script_produce import FILES, KITS as SCRIPT_KITS, SCRIPT, Series


def series():
    character = lambda cid: {"id": cid, "voiceProfile": {"characterKitRef": {"id": f"kit-{cid}", "workspace": "cast"}}}
    return {"id": "uv", "title": "Valle", "spokenLanguage": "Español de España", "characters": [character("kevin"), character("monk")],
            "locations": [{"id": "nave", "referenceAssetIds": [], "variants": []}], "assets": {}}


WALK = {"characterId": "monk", "x": 60, "enterFrom": "left", "enterAt": 0.5, "enterDuration": 3.0, "enterGait": "walk", "enterStep": 0.6}


def shot(*cast, **layout):
    return {"id": "s1", "sceneId": "a", "locationId": "nave", "dialogueBeats": [{"id": "b1", "characterId": "kevin", "text": "Hola."}],
            "layout2d": {"framing": "wide", "cast": list(cast), **layout}}


RECORDED = {"b1": {"filename": "l1.wav", "duration": 4.0, "cues": []}}


# Planning the entrance -----------------------------------------------------------

def test_the_default_entrance_is_the_one_shots_were_rendered_with():
    assert entrances.entrance({"enterFrom": "left"}, 5.0) == {"fromX": -15.0, "start": 0.2, "end": 1.4}
    assert entrances.entrance({"enterFrom": "right"}, 1.2) == {"fromX": 115.0, "start": 0.2, "end": 1.2}, "never past the shot"
    assert entrances.entrance({"characterId": "kevin"}, 5.0) is None and entrances.entrance({"enterFrom": "top"}, 5.0) is None


def test_an_entrance_can_start_later_and_last_longer_inside_the_shot():
    assert entrances.entrance({"enterFrom": "right", "enterAt": 2.0}, 5.0) == {"fromX": 115.0, "start": 2.0, "end": 3.2}, \
        "a later start keeps the default 1.2 s"
    assert entrances.entrance({"enterFrom": "left", "enterDuration": 4.0}, 6.0) == {"fromX": -15.0, "start": 0.2, "end": 4.2}
    assert entrances.entrance({"enterFrom": "left", "enterAt": 0, "enterDuration": 9}, 3.0)["end"] == 3.0
    late = entrances.entrance({"enterFrom": "left", "enterAt": 9}, 3.0)
    assert late["start"] < late["end"] <= 3.0, "an entrance after the end still happens in the shot"


def test_a_walk_takes_a_whole_number_of_steps_and_lands_on_every_one():
    walk = entrances.entrance(WALK, 6.0)
    assert walk == {"fromX": -15.0, "start": 0.5, "end": 3.5, "gait": "walk", "step": 0.6, "sway": 1.5}
    assert entrances.footfalls(walk) == [0.5, 1.1, 1.7, 2.3, 2.9, 3.5]
    stretched = entrances.entrance({**WALK, "enterStep": 0.55}, 6.0)
    assert stretched["step"] == 0.6, "3 s is not a whole number of 0.55 s steps: 5 steps of 0.6"
    assert entrances.entrance({**WALK, "enterStep": None, "enterSway": 0}, 6.0)["step"] == 0.5, "0.5 s steps by default"
    assert entrances.entrance({**WALK, "enterSway": 0}, 6.0)["sway"] == 0.0
    assert entrances.entrance({**WALK, "enterDuration": 0.2}, 6.0)["step"] == 0.2, "at least one step"


def test_the_hop_lands_where_the_compiler_puts_the_puppet_down():
    # bodyKeyframes: round(1.2 / 0.22) = 5 hops, up on the odd ones, down on the start, the even ones and the end.
    assert entrances.footfalls({"start": 0.2, "end": 1.4}) == [0.2, 0.68, 1.16, 1.4]
    assert entrances.footfalls({"start": 0.0, "end": 0.88}) == [0.0, 0.44, 0.88], "four hops: down on 0, 2 and 4"


def test_the_layout_keeps_the_entrance_fields_and_drops_bad_ones():
    kept = normalize_layout2d({"cast": [WALK, {"characterId": "kevin", "enterFrom": "left", "enterAt": -1, "enterDuration": 0,
                                               "enterGait": "run", "enterStep": 5, "enterSway": 20}]})
    assert kept["cast"] == [{"characterId": "monk", "x": 60.0, "enterFrom": "left", "enterAt": 0.5, "enterDuration": 3.0,
                             "enterStep": 0.6, "enterGait": "walk"}, {"characterId": "kevin", "enterFrom": "left"}]


def test_the_planned_cast_carries_the_entrance_to_the_compiler():
    cast = plan_cast(series(), shot(WALK, {"characterId": "kevin", "x": 30}), "wide", 6.0)
    assert cast[0]["enter"] == {"fromX": -15.0, "start": 0.5, "end": 3.5, "gait": "walk", "step": 0.6, "sway": 1.5}
    assert "enter" not in cast[1]


def test_a_new_entrance_renders_its_shot_again_and_an_old_shot_keeps_its_digest():
    kits = {"kit-kevin": {"id": "kit-kevin"}, "kit-monk": {"id": "kit-monk"}}
    plain = shot({"characterId": "monk", "enterFrom": "left"})
    before = render_inputs(series(), plain, kits)
    assert render_inputs(series(), {**plain, "layout2d": normalize_layout2d(plain["layout2d"])}, kits) == before
    walking = {**plain, "layout2d": normalize_layout2d({**plain["layout2d"], "cast": [{**plain["layout2d"]["cast"][0], "enterGait": "walk"}]})}
    assert render_inputs(series(), walking, kits) != before


# Sound on the entrance ---------------------------------------------------------------

def test_a_cue_on_an_entrance_is_kept_by_index_or_by_character():
    layout = normalize_layout2d({"sfx": [{"file": "steps.wav", "anchor": "enter", "cast": 0, "offset": 0.1},
                                         {"file": "steps.wav", "anchor": "enter", "cast": "monk", "repeat": "steps", "volume": 0.5},
                                         {"file": "x.wav", "anchor": "enter"}, {"file": "y.wav", "anchor": "enter", "cast": 9},
                                         {"file": "z.wav", "line": 0, "repeat": "always"}],
                                 "fx": [{"kind": "confetti", "anchor": "enter", "cast": 1, "duration": 0.5}]})
    assert layout["sfx"] == [{"file": "steps.wav", "anchor": "enter", "cast": 0, "offset": 0.1, "volume": 0.8},
                             {"file": "steps.wav", "anchor": "enter", "cast": "monk", "volume": 0.5, "repeat": "steps"},
                             {"file": "x.wav", "volume": 0.8}, {"file": "y.wav", "volume": 0.8},
                             {"file": "z.wav", "line": 0, "anchor": "start", "volume": 0.8}], "no cast, no entrance: at the start"
    assert layout["fx"] == [{"kind": "confetti", "anchor": "enter", "cast": 1, "duration": 0.5}]


def test_a_cue_on_an_entrance_starts_with_it_and_falls_back_to_the_start():
    moves = entrances.shot_entrances(shot({"characterId": "kevin", "x": 30}, WALK), 6.0)
    assert moves[0] is None and moves[1]["characterId"] == "monk" and moves[1]["start"] == 0.5
    timing = [(0.35, 4.35)]
    assert cue_time({"anchor": "enter", "cast": 1}, timing, 6.0, moves) == 0.5
    assert cue_time({"anchor": "enter", "cast": "monk", "offset": -0.2}, timing, 6.0, moves) == 0.3
    for missing in ({"anchor": "enter", "cast": 0}, {"anchor": "enter", "cast": 5}, {"anchor": "enter", "cast": "gary"}):
        assert cue_time(missing, timing, 6.0, moves) == 0.0, "a cast member who does not enter: the start of the shot"
    assert cue_time({"anchor": "enter", "cast": 1}, timing, 6.0) == 0.0, "a shot without entrances (a 3D shot)"


def test_footsteps_on_every_footfall_of_the_walk():
    moves = entrances.shot_entrances(shot(WALK), 6.0)
    layout = {"sfx": [{"file": "step.wav", "anchor": "enter", "cast": 0, "repeat": "steps", "volume": 0.6},
                      {"file": "door.wav", "anchor": "enter", "cast": "monk", "offset": -0.3}]}
    tracks = sfx_tracks(layout, [(0.35, 4.35)], 6.0, moves)
    assert [(track["id"], track["startTime"], track["volume"]) for track in tracks] == [
        ("sfx-0-step0", 0.5, 0.6), ("sfx-0-step1", 1.1, 0.6), ("sfx-0-step2", 1.7, 0.6), ("sfx-0-step3", 2.3, 0.6),
        ("sfx-0-step4", 2.9, 0.6), ("sfx-0-step5", 3.5, 0.6), ("sfx-1", 0.2, 0.8)]
    shifted = sfx_tracks({"sfx": [{**layout["sfx"][0], "offset": -0.6}]}, [], 6.0, moves)
    assert [track["startTime"] for track in shifted] == [0.5, 1.1, 1.7, 2.3, 2.9], "an offset moves them all; none before the shot"
    assert [track["id"] for track in sfx_tracks(layout, [], 6.0)] == ["sfx-0", "sfx-1"], "without the entrance: one cue at the start"


def test_the_full_spec_lines_the_steps_up_with_the_walk_and_the_screen_effects_too():
    value = shot(WALK, sfx=[{"file": "step.wav", "anchor": "enter", "cast": "monk", "repeat": "steps"}],
                 fx=[{"kind": "confetti", "anchor": "enter", "cast": 0, "offset": 3.0, "duration": 0.5}])
    value["layout2d"] = normalize_layout2d(value["layout2d"])
    spec = build_shot_spec(series(), {"id": "ep1"}, value, workspace="cast", recorded=RECORDED)
    walk = spec["cast"][0]["enter"]
    assert [track["startTime"] for track in spec["audioTracks"]] == entrances.footfalls(walk) == [0.5, 1.1, 1.7, 2.3, 2.9, 3.5]
    assert [(cue["start"], cue["end"]) for cue in spec["sfx"]] == [(3.5, 4.0)], "the arrival, three seconds after the first step"
    titled = build_shot_spec(series(), {"id": "ep1"}, {**value, "layout2d": {**value["layout2d"], "framing": "title"}},
                             workspace="cast", recorded=RECORDED)
    assert titled["cast"] == [] and [track["id"] for track in titled["audioTracks"]] == ["sfx-0"], "nobody walks in a title shot"
    assert fx_cues(value["layout2d"], [], 5.0) == [{"id": "fx-0", "kind": "confetti", "start": 3.0, "end": 3.5}]


# The script ---------------------------------------------------------------------------

def test_a_script_times_the_entrance_and_anchors_its_steps():
    talk = SCRIPT["shots"][1]
    cast = [talk["cast"][0], {"characterId": "gary", "x": 70, "enterFrom": "right", "enterAt": 0.4, "enterDuration": 2.5,
                              "enterGait": "walk", "enterStep": 0.5}]
    sfx = [{"file": "sfx-pen.wav", "anchor": "enter", "cast": 1, "repeat": "steps"}, {"file": "sfx-pen.wav", "anchor": "enter", "cast": "gary"}]
    tools = Series()
    apply_script(tools, tools.read, SCRIPT_KITS, FILES, "cast", {**SCRIPT, "shots": [{**talk, "cast": cast, "sfx": sfx}]})
    layout = tools.calls[1][1]["episode"]["shots"][0]["layout2d"]
    assert layout["cast"][1] == cast[1] and layout["sfx"] == sfx


@pytest.mark.parametrize("change, problem", [
    ({"cast": [{"characterId": "gary", "enterFrom": "left", "enterGait": "run"}]}, "enterGait must be one of hop, walk"),
    ({"sfx": [{"file": "sfx-pen.wav", "anchor": "enter"}]}, "sfx 0: anchor enter needs cast"),
    ({"sfx": [{"file": "sfx-pen.wav", "anchor": "enter", "cast": 4}]}, "sfx 0: anchor enter needs cast"),
    ({"fx": [{"kind": "confetti", "anchor": "enter", "cast": "gary"}]}, "fx 0: gary does not enter"),
])
def test_a_script_lists_an_entrance_it_cannot_follow(change, problem):
    talk = {**SCRIPT["shots"][1], **change}
    with pytest.raises(ScriptError, match=problem):
        apply_script(Series(), Series().read, SCRIPT_KITS, FILES, "cast", {**SCRIPT, "shots": [talk]})


def test_the_compiled_walk_puts_the_feet_down_on_the_footsteps(tmp_path):
    from PIL import Image
    from services.series_shot_bridge import run_series_shot, with_pose_sizes
    from services.video2d_compile import TSX
    if not TSX.is_file():
        pytest.skip("ui/node_modules/tsx is not installed")
    Image.new("RGBA", (300, 600), (255, 0, 0, 255)).save(tmp_path / "k.png")
    asset = lambda aid, kind="overlay": {"id": aid, "name": aid, "kind": kind, "alphaStatus": "transparent", "reviewState": "approved",
                                         "source": "/api/v1/file/k.png?workspace=cast" if kind == "image" else f"/api/v1/file/{aid}.png?workspace=cast"}
    kit = {"version": 1, "id": "kit-monk", "name": "Monk", "style": "cutout", "base": asset("base", "image"), "poses": {}, "mouth": {},
           "eyes": {}, "provenance": [], "mouthMapping": {}, "anchors": {}}
    value = shot({**WALK, "motion": "still"}, sfx=[{"file": "step.wav", "anchor": "enter", "cast": 0, "repeat": "steps"}])
    value["layout2d"] = normalize_layout2d(value["layout2d"])
    spec = build_shot_spec(series(), {"id": "ep1"}, value, workspace="cast", recorded=RECORDED)
    document = run_series_shot({"mode": "shot", "kits": {"kit-monk": with_pose_sizes(kit, str(tmp_path))}, "shot": spec})
    pose = next(layer for layer in document["layers"] if (layer.get("characterKitRef") or {}).get("id") == "kit-monk"
                and not layer.get("faceBinding") and layer["type"] == "image")
    frames = {round(frame["time"], 3): frame for frame in pose["animation"]["keyframes"]}
    steps = [track["startTime"] for track in document["audioTracks"] if track["id"].startswith("sfx-0-step")]
    assert steps == [0.5, 1.1, 1.7, 2.3, 2.9, 3.5]
    rest = frames[3.5]["y"]
    assert all(frames[time]["y"] == rest and frames[time]["rotation"] == 0 for time in steps), "each footstep on a footfall"
    assert all(frames[round(time + 0.3, 3)]["y"] < rest for time in steps[:-1]), "and the body up between them"
    assert [frames[round(time, 3)]["x"] for time in steps] == sorted(frames[round(time, 3)]["x"] for time in steps)
