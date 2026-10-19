"""A character walks into a 2D shot when and for as long as the script says, and its footsteps can follow its feet."""
import base64
import functools
import io
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from services import series_cast_animation as animations
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


# A kit animation on a cast member ---------------------------------------------------

def test_a_cast_animation_is_an_id_or_a_window_and_bad_values_are_dropped():
    assert animations.entry_fields({"animation": "wave"}) == {"animation": {"id": "wave"}}
    window = {"id": "wave", "at": 1.5, "duration": 2, "loop": "once"}
    assert animations.entry_fields({"animation": window}) == {"animation": {"id": "wave", "at": 1.5, "duration": 2.0, "loop": "once"}}
    assert animations.entry_fields({"animation": {"id": "wave", "at": -1, "duration": 0, "loop": "forever"}}) == {"animation": {"id": "wave"}}
    assert animations.entry_fields({"animation": {"id": "wave", "loop": True}}) == {"animation": {"id": "wave", "loop": "loop"}}
    assert animations.entry_fields({"animation": {"id": "wave", "loop": False}}) == {"animation": {"id": "wave", "loop": "once"}}
    for bad in (None, 3, "", "Not An Id", {"at": 1}, {"id": 4}, [], {"id": "x" * 80}):
        assert animations.entry_fields({"animation": bad}) == {}, bad
    assert animations.entry_fields({"characterId": "kevin"}) == {}


def test_the_layout_keeps_a_cast_animation_next_to_the_entrance_fields():
    layout = {"cast": [{**WALK, "animation": {"id": "wave", "at": 4, "duration": 1.5}}, {"characterId": "kevin", "animation": "angry"},
                       {"characterId": "gary", "animation": 7}]}
    kept = normalize_layout2d(layout)["cast"]
    assert kept[0]["animation"] == {"id": "wave", "at": 4.0, "duration": 1.5} and kept[0]["enterGait"] == "walk"
    assert kept[1] == {"characterId": "kevin", "animation": {"id": "angry"}} and kept[2] == {"characterId": "gary"}
    assert normalize_layout2d({"cast": kept}) == normalize_layout2d(layout), "reading it back and saving it again changes nothing"


def test_the_planned_cast_carries_the_animation_clamped_into_the_shot():
    plan = lambda animation, duration=6.0: plan_cast(series(), shot({"characterId": "kevin", "x": 30, "animation": animation}), "wide", duration)[0].get("animation")
    assert plan({"id": "wave", "at": 1, "duration": 2}) == {"id": "wave", "at": 1.0, "duration": 2.0}
    assert plan({"id": "wave"}) == {"id": "wave", "at": 0.0}, "from the start, as long as the sheet"
    assert plan({"id": "wave", "at": 9, "duration": 2}) == {"id": "wave", "at": 5.9, "duration": 0.1}, "an animation after the end still happens in the shot"
    assert plan({"id": "wave", "at": 4, "duration": 9, "loop": "loop"}) == {"id": "wave", "at": 4.0, "duration": 2.0, "loop": "loop"}
    assert "animation" not in plan_cast(series(), shot({"characterId": "kevin", "x": 30}), "wide", 6.0)[0]


def test_the_full_spec_carries_the_animation_and_the_entrance_is_the_one_it_always_was():
    value = shot({**WALK, "animation": {"id": "wave", "at": 3.5, "duration": 1}})
    value["layout2d"] = normalize_layout2d(value["layout2d"])
    spec = build_shot_spec(series(), {"id": "ep1"}, value, workspace="cast", recorded=RECORDED)
    assert spec["cast"][0]["animation"] == {"id": "wave", "at": 3.5, "duration": 1.0}
    assert spec["cast"][0]["enter"] == {"fromX": -15.0, "start": 0.5, "end": 3.5, "gait": "walk", "step": 0.6, "sway": 1.5}, \
        "which sheet a walk uses is the compiler's choice: the plan and the footfalls are the same with or without one"
    assert animations.walk_window(spec["cast"][0]["enter"]) == (0.5, 3.5)
    assert animations.walk_window({"fromX": -15.0, "start": 0.5, "end": 3.5}) is None, "a hop has no sheet"


def test_a_new_animation_renders_its_shot_again():
    kits = {"kit-kevin": {"id": "kit-kevin"}, "kit-monk": {"id": "kit-monk"}}
    plain = shot({"characterId": "monk", "x": 40})
    before = render_inputs(series(), plain, kits)
    waving = {**plain, "layout2d": normalize_layout2d({**plain["layout2d"], "cast": [{"characterId": "monk", "x": 40, "animation": "wave"}]})}
    assert render_inputs(series(), waving, kits) != before


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
    assert fx_cues(value["layout2d"], [], 5.0) == [{"id": "fx-0", "kind": "confetti", "start": 3.0, "end": 3.5, "size": 104.0}]


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


def test_the_compiler_plays_the_expression_where_series_expression_silence_left_it(tmp_path):
    """The real tsx compile of the spec the render hands over: a moved expression starts at its new second, an opted-out one
    stays at its own, a dropped one is not drawn, and the compiler accepts the allowDuringSpeech key."""
    from services.series_expression_silence import quiet_expressions
    from services.series_shot_bridge import run_series_shot
    from services.video2d_compile import TSX
    if not TSX.is_file():
        pytest.skip("ui/node_modules/tsx is not installed")
    kevin, monk = _kit("kit-kevin", [[(220, 40, 40)], [(40, 180, 60)]]), _kit("kit-monk", [[(50, 80, 220)]])
    kevin["animations"]["angry"] = kevin["animations"]["blocks"]
    kits = {"kit-kevin": kevin, "kit-monk": monk}

    def starts(animation, seconds):
        cast = [{"characterId": "kevin", "x": 30, "motion": "still", "animation": animation}, {"characterId": "monk", "x": 70}]
        value = {"id": "s1", "sceneId": "a", "locationId": "nave", "layout2d": {"framing": "wide", "cast": cast},
                 "dialogueBeats": [{"id": "b1", "characterId": "kevin", "text": "Hola."}, {"id": "b2", "characterId": "monk", "text": "Adiós."}]}
        recorded = {"b1": {"filename": "l1.wav", "duration": 1.0}, "b2": {"filename": "l2.wav", "duration": seconds}}
        spec, _warnings = quiet_expressions(build_shot_spec(series(), {"id": "ep1"}, value, workspace="cast", recorded=recorded), kits, "s1")
        document = run_series_shot({"mode": "shot", "kits": kits, "shot": spec})
        return [layer["sequence"]["start"] for layer in document["layers"] if (layer.get("sequence") or {}).get("kind") == "sheet"]

    assert starts({"id": "angry", "at": 0}, 4.0) == [1.55], "kevin speaks from 0.35 to 1.35: the face comes right after"
    assert starts({"id": "angry", "at": 0, "allowDuringSpeech": True}, 4.0) == [0.0], "the opt-out is the author's call"
    assert starts({"id": "angry", "at": 3.0}, 4.0) == [3.0], "already in kevin's silence: as written"
    assert starts({"id": "angry", "at": 0}, 0.2) == [], "no silence long enough: the figure keeps its pose"


# A real render (CPU) --------------------------------------------------------------------

def _png(draw, size) -> str:
    """A data URL of a transparent picture that ``draw(image)`` paints on."""
    from PIL import Image
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw(image)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def _blocks(colours, size=(100, 200)):
    """A sheet of one row: each cell is a block per colour in ``colours`` (left to right), boots on the line at 96 %."""
    from PIL import ImageDraw

    def draw(image):
        pen = ImageDraw.Draw(image)
        for cell, parts in enumerate(colours):
            wide = size[0] * 0.9 / len(parts)
            for part, colour in enumerate(parts):
                left = cell * size[0] + size[0] * 0.05 + part * wide
                pen.rectangle((left, size[1] * 0.1, left + wide - 2, size[1] * 0.96), fill=colour + (255,))
    return _png(draw, (size[0] * len(colours), size[1]))


def _kit(name, sheet_colours, facing="right", fps=4):
    pose = _png(lambda image: image.paste((128, 128, 128, 255), (0, 0, 100, 200)), (100, 200))
    sheet = _blocks(sheet_colours)
    asset = {"id": f"{name}-base", "name": "base", "source": pose, "kind": "image", "alphaStatus": "transparent", "reviewState": "approved",
             "width": 100, "height": 200}
    count = len(sheet_colours)
    animation = {"sheet": {"source": sheet, "width": 100 * count, "height": 200, "count": count, "columns": count, "rows": 1,
                           "cell": {"width": 100, "height": 200}}, "frames": [], "fps": fps, "loop": "loop", "facing": facing, "reviewState": "approved"}
    return {"version": 1, "id": name, "name": name.title(), "style": {}, "base": asset, "poses": {}, "mouth": {}, "eyes": {}, "anchors": {},
            "provenance": [], "animations": {"blocks": animation, "walk": animation}}


def _nearest(pixel, palette):
    return min(palette, key=lambda name: sum((a - b) ** 2 for a, b in zip(pixel[:3], palette[name])))


@pytest.mark.skipif(os.environ.get("RUN_SERIES_SHEET_RENDER_SMOKE") != "1", reason="explicit built-UI Chromium smoke (ui/dist, Node, Playwright Chromium)")
def test_a_sheet_plays_cell_by_cell_in_a_real_cpu_render_of_a_series_shot(tmp_path, monkeypatch):
    """RUN_SERIES_SHEET_RENDER_SMOKE=1 pytest -q tests/test_series_entrances.py -k real_cpu_render (needs ``vite build`` in ui/).

    A four-cell sheet of colour blocks plays from 0.5 s at 4 cells a second; a two-cell walk sheet (red left half, blue right half,
    looking right) walks in from the right. The exported frames show one block per cell, the pose before and after, and the walk mirrored."""
    from PIL import Image
    from services.scene2d_export import validated_document
    from services.series_shot_bridge import run_series_shot
    from services.world3d_export import export_plan, playwright_module, run_owned_browser
    monkeypatch.setenv("HOCUS_SCENE_RENDER_DEVICE", "cpu")
    dist = Path(__file__).resolve().parents[1] / "ui" / "dist"
    assert (dist / "scene2d-render.html").is_file(), "Build the UI first (cd ui && npx vite build)"
    colours = ((220, 40, 40), (40, 180, 60), (50, 80, 220), (240, 200, 40))
    palette = {"gray": (128, 128, 128), "red": colours[0], "green": colours[1], "blue": colours[2], "yellow": colours[3]}
    kits = {"hero": _kit("hero", [[c] for c in colours]), "walker": _kit("walker", [[colours[0], colours[2]]] * 2)}
    shot = {"name": "smoke", "workspace": "cast", "width": 320, "height": 180, "fps": 24, "duration": 2.4, "framing": "wide", "camera": "static",
            "cast": [{"kitId": "hero", "x": 30, "motion": "still", "animation": {"id": "blocks", "at": 0.5, "duration": 1.0, "loop": "loop"}},
                     {"kitId": "walker", "x": 80, "motion": "still", "enter": {"fromX": 115, "start": 0.2, "end": 1.4, "gait": "walk", "step": 0.6, "sway": 0}}],
            "lines": []}
    scene = run_series_shot({"mode": "shot", "kits": kits, "shot": shot})
    layers = {layer["id"]: layer for layer in scene["layers"]}
    assert layers["kit-hero-sheet-blocks"]["sequence"]["start"] == 0.5 and layers["kit-walker-sheet-walk-in"]["sequence"]["mirror"] is True
    document = validated_document(scene)
    assert document["layers"][0]["id"] and any(layer.get("sequence", {}).get("mirror") for layer in document["layers"]), "the export keeps start and mirror"
    times = [0.2, 0.6, 0.8, 1.05, 1.3, 1.8]
    plan = {**export_plan(document), "times": times}
    handler = functools.partial(type("Quiet", (SimpleHTTPRequestHandler,), {"log_message": lambda *_args: None}), directory=str(dist))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        module = playwright_module()
        assert module is not None, "Playwright is not installed"
        snapshot = {"document": document, "plan": plan, "workspace": "cast", "refs": []}
        (tmp_path / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
        frames = run_owned_browser(snapshot, tmp_path, lambda: False,
                                   app_url=f"http://127.0.0.1:{server.server_port}", module=module, page="/scene2d-render.html", bridge="__scene2dExport")
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
    assert len(frames) == len(times)
    hero_x, hero_y = round(0.30 * 320), round((layers["kit-hero-sheet-blocks"]["transform"]["y"] - 25) / 100 * 180)
    seen = [_nearest(Image.open(path).convert("RGB").getpixel((hero_x, hero_y)), palette) for path in frames]
    assert seen == ["gray", "red", "green", "blue", "yellow", "gray"], f"one block per cell, the pose before and after: {seen}"
    keys = layers["kit-walker-sheet-walk-in"]["animation"]["keyframes"]
    after = next(key for key in keys if key["time"] >= 1.05)
    before = [key for key in keys if key["time"] <= 1.05][-1]
    walk_x = before["x"] + (after["x"] - before["x"]) * (1.05 - before["time"]) / max(1e-9, after["time"] - before["time"])
    walk_y = round((before["y"] - 25) / 100 * 180)
    picture = Image.open(frames[3]).convert("RGB")
    left, right = (picture.getpixel((round(walk_x / 100 * 320) + shift, walk_y)) for shift in (-9, 9))
    assert (_nearest(left, palette), _nearest(right, palette)) == ("blue", "red"), "entering from the right, the sheet that looks right is mirrored"
    assert len({frame.read_bytes() for frame in frames}) == len(times), "every sampled frame is a different picture"


def _band(colour, size=(100, 200), count=2):
    """A sheet whose opaque pixels are exactly the figure band: full cell width, from 10 % to the feet line at 96 %."""
    from PIL import ImageDraw

    def draw(image):
        pen = ImageDraw.Draw(image)
        top, bottom = round(size[1] * 0.10), round(size[1] * 0.96) - 1
        for cell in range(count):
            left = cell * size[0]
            pen.rectangle((left, top, left + size[0] - 1, bottom), fill=colour + (255,))
    return _png(draw, (size[0] * count, size[1]))


def _colour_box(path, channel):
    """Bounding box of pixels whose ``channel`` (0 red, 2 blue) dominates, or None when the colour is absent."""
    from PIL import Image
    image = Image.open(path).convert("RGB")
    pixels, hits = image.load(), []
    for y in range(image.height):
        for x in range(image.width):
            pixel = pixels[x, y]
            others = [pixel[index] for index in range(3) if index != channel]
            if pixel[channel] > 140 and all(pixel[channel] > other + 40 for other in others):
                hits.append((x, y))
    if not hits:
        return None
    xs, ys = [item[0] for item in hits], [item[1] for item in hits]
    return min(xs), min(ys), max(xs), max(ys), image.size


@pytest.mark.skipif(os.environ.get("RUN_SERIES_SHEET_RENDER_SMOKE") != "1", reason="explicit built-UI Chromium smoke (ui/dist, Node, Playwright Chromium)")
def test_an_expression_sheet_covers_the_same_pixels_as_the_snapped_pose(tmp_path, monkeypatch):
    """RUN_SERIES_SHEET_RENDER_SMOKE=1 pytest -q tests/test_series_entrances.py -k same_pixels (needs ``vite build`` in ui/).

    A square bust cut on both sides is enlarged in a medium shot. The expression that replaces it, sampled after the fade,
    must cover the same pixels the pose covered before the fade. The contact sheet is written beside the worktree."""
    from PIL import Image
    from services.scene2d_export import validated_document
    from services.series_shot_bridge import run_series_shot
    from services.world3d_export import export_plan, playwright_module, run_owned_browser
    monkeypatch.setenv("HOCUS_SCENE_RENDER_DEVICE", "cpu")
    dist = Path(__file__).resolve().parents[1] / "ui" / "dist"
    assert (dist / "scene2d-render.html").is_file(), "Build the UI first (cd ui && npx vite build)"
    red, blue = (220, 40, 30), (30, 40, 220)
    pose = _png(lambda image: image.paste(red + (255,), (0, 0, 128, 128)), (128, 128))
    # The figure band is 0.86 of the cell and the full cell width. A cell 172×200 makes that band square, the same shape as the pose.
    cell = (172, 200)
    asset = {"id": "hero-base", "name": "base", "source": pose, "kind": "image", "alphaStatus": "transparent", "reviewState": "approved",
             "width": 128, "height": 128, "cut": {"left": [[0, 1]], "right": [[0, 1]], "bottom": [[0, 1]]}}
    animation = {"sheet": {"source": _band(blue, cell), "width": cell[0] * 2, "height": cell[1], "count": 2, "columns": 2, "rows": 1,
                           "cell": {"width": cell[0], "height": cell[1]}},
                 "frames": [], "fps": 3, "loop": "once", "facing": "front", "scaleBy": "face", "group": "expression", "reviewState": "approved"}
    kit = {"version": 1, "id": "hero", "name": "Hero", "style": {}, "base": asset, "poses": {}, "mouth": {}, "eyes": {}, "anchors": {},
           "provenance": [], "animations": {"angry": animation}}
    shot = {"name": "smoke", "workspace": "cast", "width": 320, "height": 180, "fps": 24, "duration": 3.2, "framing": "medium", "camera": "static",
            "cast": [{"kitId": "hero", "x": 46, "motion": "still", "animation": {"id": "angry", "at": 0.4, "duration": 2}}], "lines": []}
    scene = run_series_shot({"mode": "shot", "kits": {"hero": kit}, "shot": shot})
    layers = {layer["id"]: layer for layer in scene["layers"]}
    pose_layer, sheet_layer = layers["kit-hero-pose-base"], layers["kit-hero-sheet-angry"]
    assert abs(sheet_layer["transform"]["x"] - pose_layer["transform"]["x"]) < 0.05
    assert pose_layer["transform"]["scale"] > 1.5, "both cuts enlarged the pose, so an unsnapped sheet would be smaller"
    document = validated_document(scene)
    times = [0.15, 1.2]
    plan = {**export_plan(document), "times": times}
    handler = functools.partial(type("Quiet", (SimpleHTTPRequestHandler,), {"log_message": lambda *_args: None}), directory=str(dist))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        module = playwright_module()
        assert module is not None, "Playwright is not installed"
        snapshot = {"document": document, "plan": plan, "workspace": "cast", "refs": []}
        (tmp_path / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
        frames = run_owned_browser(snapshot, tmp_path, lambda: False,
                                   app_url=f"http://127.0.0.1:{server.server_port}", module=module, page="/scene2d-render.html", bridge="__scene2dExport")
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
    assert len(frames) == 2
    pose_box, sheet_box = _colour_box(frames[0], 0), _colour_box(frames[1], 2)
    contact = Image.new("RGB", (320 * 2 + 8, 180), (16, 16, 16))
    contact.paste(Image.open(frames[0]).convert("RGB"), (0, 0))
    contact.paste(Image.open(frames[1]).convert("RGB"), (328, 0))
    contact.save("/mnt/outputs/hocuspocus-worktrees/expr-voice-fix.sheet.png")
    assert pose_box is not None and sheet_box is not None, (pose_box, sheet_box)
    width, height = pose_box[4]
    for index, (pose_edge, sheet_edge) in enumerate(zip(pose_box[:4], sheet_box[:4])):
        limit = max(2, round(0.01 * (width if index % 2 == 0 else height)))
        assert abs(pose_edge - sheet_edge) <= limit, f"edge {index}: pose {pose_box[:4]} sheet {sheet_box[:4]} limit {limit}"
