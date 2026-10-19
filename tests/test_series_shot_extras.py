"""Rhythm, timed sound and screen effects, perched characters and 3D dialogue shots in the server render."""
import time

from services import series_shot3d
from services.series_native_render import NativeRenderDeps, NativeRenderError, SeriesNativeRender
from services.series_shot_extras import cue_time, fx_cues, perch, sfx_tracks
from services.series_shot_plan import build_shot_spec, normalize_layout2d, plan_timing
from services.series_take_inputs import render_inputs


def series():
    character = lambda cid, **more: {"id": cid, "voiceProfile": {"characterKitRef": {"id": f"kit-{cid}", "workspace": "cast"}}, **more}
    desk = {"perch": {"file": "desk cut.png", "width": 808, "height": 246}}
    return {"id": "uv", "title": "Valle", "spokenLanguage": "Español de España",
            "characters": [character("kevin"), character("gary", layout2d=desk), character("elon")],
            "locations": [{"id": "garage", "referenceAssetIds": [], "variants": []}], "assets": {}}


def test_layout_keeps_timing_sound_and_screen_effects_and_drops_bad_ones():
    layout = normalize_layout2d({
        "timing": {"intro": 1.2, "tail": 9, "gap": "x"},
        "sfx": [{"file": "sfx-pen.wav", "line": 1, "anchor": "end", "offset": 0.2}, {"file": "../etc"}, {"file": "boom.wav", "at": 2}],
        "fx": [{"kind": "confetti", "line": 0, "duration": 2, "x": 70, "color": "#ffcc00"}, {"kind": "nope"}],
    })
    assert layout["timing"] == {"intro": 1.2}
    assert layout["sfx"] == [{"file": "sfx-pen.wav", "line": 1, "anchor": "end", "offset": 0.2, "volume": 0.8},
                             {"file": "boom.wav", "at": 2.0, "volume": 0.8}]
    assert layout["fx"] == [{"kind": "confetti", "line": 0, "anchor": "start", "duration": 2.0, "x": 70.0, "color": "#ffcc00"}]


def test_a_pause_before_a_line_and_cues_at_lines_or_seconds():
    timing, duration = plan_timing([1.0, 0.5], intro=1.0, gap=0.2, tail=1.0, pauses=[0.0, 1.5])
    assert timing == [(1.0, 2.0), (3.7, 4.2)] and duration == 5.2083
    assert cue_time({"line": 1, "anchor": "end", "offset": 0.3}, timing, duration) == 4.5
    assert cue_time({"line": 7}, timing, duration) == 0.0, "a line the shot does not have falls back to the start"
    assert cue_time({"at": 9}, timing, duration) == round(duration - 0.05, 3), "never after the shot"
    layout = {"sfx": [{"file": "pen.wav", "line": 0, "volume": 0.5}], "fx": [{"kind": "confetti", "line": 1, "duration": 3, "x": 30}]}
    assert sfx_tracks(layout, timing, duration) == [
        {"id": "sfx-0", "filename": "pen.wav", "name": "Sound effect", "kind": "sfx", "startTime": 1.0, "volume": 0.5}]
    assert fx_cues(layout, timing, duration) == [{"id": "fx-0", "kind": "confetti", "start": 3.7, "end": 5.198, "x": 30, "size": 104.0}]


def test_a_full_spec_carries_the_rhythm_the_effects_and_the_seat():
    shot = {"id": "s1", "sceneId": "a", "locationId": "garage", "layout2d": {
        "framing": "two", "timing": {"intro": 0.8}, "cast": [{"characterId": "kevin"}, {"characterId": "gary"}],
        "sfx": [{"file": "ding.wav", "line": 1}], "fx": [{"kind": "confetti", "line": 1}]},
        "dialogueBeats": [{"id": "b1", "characterId": "kevin", "text": "Hola."},
                          {"id": "b2", "characterId": "gary", "text": "...No.", "pauseBefore": 1.0}]}
    recorded = {"b1": {"filename": "l1.wav", "duration": 1.0, "cues": []}, "b2": {"filename": "l2.wav", "duration": 0.5, "cues": []}}
    spec = build_shot_spec(series(), {"id": "ep1"}, shot, workspace="cast", recorded=recorded)
    assert [(line["start"], line["end"]) for line in spec["lines"]] == [(0.8, 1.8), (3.02, 3.52)]
    assert [track["id"] for track in spec["audioTracks"]] == ["sfx-0"] and spec["audioTracks"][0]["startTime"] == 3.02
    assert spec["sfx"][0]["kind"] == "confetti" and spec["sfx"][0]["start"] == 3.02
    seat = spec["cast"][1]["perch"]
    assert seat == {"source": "/api/v1/file/desk%20cut.png?workspace=cast", "width": 808.0, "height": 246.0, "top": 0.04, "widthRatio": 1.45}
    assert "perch" not in spec["cast"][0]
    assert perch({"layout2d": {"perch": {"file": "x.png"}}}, "cast") is None, "a seat needs its size"


class World3D:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, tool, arguments):
        self.calls.append((tool, arguments))
        data = arguments.get("input") or {}
        if tool == self.fail:
            return {"_is_error": True, "error": {"message": "nope"}}
        if tool == "scenes.document.get":
            return {"result": {"document": {"version": 1, "objects": []}}}
        if tool == "world3d.templates.user.put":
            return {"result": {"template": {"id": data["id"]}}}
        if tool == "world3d.scene.instantiate":
            return {"result": {"scene": {"sceneId": "w3d-1", "revision": 1}}}
        if tool in ("world3d.scene.patch", "world3d.scene.talk"):
            revision = data["base_revision"] + 1
            return {"result": {"scene": {"sceneId": "w3d-1", "revision": revision}}}
        if tool == "world3d.scene.publish":
            return {"result": {"scene": {"sceneId": "w3d-1", "revision": 9, "file": "w3d-1.world3d.scene.json", "document": {"v": 1}}}}
        if tool == "scenes.world3d.export":
            return {"receipt": {"status": "queued"}}
        if tool == "scenes.world3d.export.receipt":
            return {"result": {"receipt": {"artifacts": [{"name": "elon-3d.mp4"}]}, "task": {"status": "completed"}}}
        raise AssertionError(tool)


def test_scene3d_needs_one_source_and_a_valid_cast():
    assert series_shot3d.normalize_scene3d({"template": "user-mars", "scene": "a.scene.json"}) is None
    assert series_shot3d.normalize_scene3d({"cast": []}) is None
    value = series_shot3d.normalize_scene3d({"scene": "mars.world3d.scene.json", "quality": "master",
                                             "cast": [{"characterId": "elon", "objectId": "elon", "poseId": "phone"}, {"characterId": "x"}]})
    assert value == {"scene": "mars.world3d.scene.json", "cast": [{"characterId": "elon", "objectId": "elon", "poseId": "phone"}], "quality": "draft"}
    assert series_shot3d.wants_render({"productionMethod": "animation_3d", "scene3d": {"template": "user-mars"}})
    assert not series_shot3d.wants_render({"productionMethod": "animation_3d"})


def test_a_3d_shot_instantiates_sets_the_length_makes_each_speaker_talk_and_publishes():
    tools = World3D()
    shot = {"id": "s20", "scene3d": {"scene": "mars.world3d.scene.json", "cast": [{"characterId": "elon", "objectId": "elon", "poseId": "phone"}]}}
    lines = [{"characterId": "elon", "start": 0.8, "filename": "ln 1.wav", "cues": [{"start": 0, "end": 1, "value": "D"}]}]
    scene = series_shot3d.build_scene(tools, "cast", "job", shot, lines, 4.5, {}, {"elon": "kit-elon"}, NativeRenderError)
    assert scene["revision"] == 9
    names = [tool for tool, _ in tools.calls]
    assert names == ["scenes.document.get", "world3d.templates.user.put", "world3d.scene.instantiate", "world3d.scene.patch",
                     "world3d.scene.patch", "world3d.scene.talk", "world3d.scene.publish"]
    put = tools.calls[1][1]["input"]
    assert put["id"].startswith("user-") and put["document"] == {"version": 1, "objects": []}
    assert tools.calls[3][1]["input"]["duration"] == 4.5
    assert tools.calls[4][1]["input"]["bindings"] == [{"object_id": "elon", "media": "image"}]
    talk = tools.calls[5][1]["input"]
    assert (talk["kit_id"], talk["pose"], talk["base_revision"]) == ("kit-elon", "phone", 3)
    assert talk["lines"] == [{"start": 0.8, "cues": lines[0]["cues"], "audio": "/api/v1/file/ln%201.wav?workspace=cast"}]


class HeldWorld3D(World3D):
    """A template whose document already has a stop-motion step (a scene saved from the editor)."""

    def __call__(self, tool, arguments):
        if tool == "world3d.scene.instantiate":
            self.calls.append((tool, arguments))
            return {"result": {"scene": {"sceneId": "w3d-1", "revision": 1, "document": {"motionStep": 2, "slots": []}}}}
        return super().__call__(tool, arguments)


def test_a_3d_shot_saves_its_stop_motion_in_the_scene_and_a_plain_shot_asks_as_before():
    def length(tools):
        return next(args["input"] for tool, args in tools.calls if tool == "world3d.scene.patch" and "duration" in args["input"])

    held = {"id": "s20", "layout2d": {"motionStep": 3, "stopMotionJitter": 1.5}, "scene3d": {"template": "user-mars", "cast": []}}
    tools = World3D()
    series_shot3d.build_scene(tools, "cast", "job", held, [], 4.0, {}, {}, NativeRenderError)
    assert (length(tools)["motionStep"], length(tools)["stopMotionJitter"]) == (3, 1.5)
    plain = {"id": "s20", "scene3d": {"template": "user-mars", "cast": []}}
    tools = World3D()
    series_shot3d.build_scene(tools, "cast", "job", plain, [], 4.0, {}, {}, NativeRenderError)
    assert not {"motionStep", "stopMotionJitter"} & set(length(tools)), "the patch earlier renders asked for"
    tools = HeldWorld3D()
    series_shot3d.build_scene(tools, "cast", "job", plain, [], 4.0, {}, {}, NativeRenderError)
    assert length(tools)["motionStep"] == 0 and "stopMotionJitter" not in length(tools), "the shot took it off"


def test_a_speaker_without_an_object_is_heard_over_the_shot_and_a_failing_tool_stops_it():
    shot = {"id": "s20", "scene3d": {"template": "user-mars", "cast": []}}
    lines = [{"characterId": "elon", "start": 0.3, "filename": "a b.wav"}]
    tools = World3D()
    series_shot3d.build_scene(tools, "cast", "job", shot, lines, 3, {}, {"elon": "kit-elon"}, NativeRenderError)
    length = tools.calls[1][1]["input"]
    assert length["voiceOver"] == [{"start": 0.3, "audio": "/api/v1/file/a%20b.wav?workspace=cast"}]
    assert not any(tool == "world3d.scene.talk" for tool, _ in tools.calls), "nobody talks on screen"
    try:
        series_shot3d.build_scene(World3D(fail="world3d.scene.instantiate"), "cast", "job", shot, [], 3, {}, {}, NativeRenderError)
    except NativeRenderError as error:
        assert error.code == "tool_failed" and "nope" in str(error)
    else:
        raise AssertionError("expected tool_failed")


class RenderTools(World3D):
    def __init__(self, root):
        super().__init__()
        self.root = root

    def __call__(self, tool, arguments):
        data = arguments.get("input") or {}
        if tool == "generation.speech":
            self.calls.append((tool, arguments))
            (self.root / f"{data['output_name']}.wav").write_bytes(b"x")
            return {"receipt": {"result": {"job_id": "j1"}}}
        if tool == "jobs.wait":
            speech = [args for name, args in self.calls if name == "generation.speech"][-1]
            return {"status": "completed", "outputs": [{"path": f"{speech['input']['output_name']}.wav"}]}
        if tool == "audio.mouth_cues":
            return {"result": {"mouthCues": [{"start": 0, "end": 0.5, "value": "D"}]}}
        if tool == "series.asset.import":
            self.calls.append((tool, arguments))
            return {"result": {"attempt": {"id": "attempt-3d"}}}
        if tool == "series.take.approve":
            self.calls.append((tool, arguments))
            return {"result": {"shot": {}}}
        return super().__call__(tool, arguments)


def test_the_server_render_makes_a_3d_dialogue_shot_a_take(tmp_path):
    project = series()
    project["episodesById"] = {"ep1": {"id": "ep1", "shots": [{
        "id": "s20", "order": 1, "sceneId": "a", "productionMethod": "animation_3d", "durationSeconds": 3,
        "layout2d": {"timing": {"intro": 0.8, "tail": 0.9}},
        "scene3d": {"template": "user-mars", "quality": "final", "cast": [{"characterId": "elon", "objectId": "elon"}]},
        "dialogueBeats": [{"id": "s20_b0", "characterId": "elon", "text": "Marte."}]}]}}
    kits = {f"kit-{cid}": {"id": f"kit-{cid}", "base": {"source": "k.png", "width": 4, "height": 8}, "poses": {},
                           "voice": {"model": "qwen3_tts_customvoice", "voiceId": "ryan"}} for cid in ("kevin", "gary", "elon")}
    tools, lengths = RenderTools(tmp_path), []

    def trim(source, target):
        (tmp_path / target.split("/")[-1]).write_bytes(b"x")
        return 1.5

    render = SeriesNativeRender(NativeRenderDeps(
        call=tools, workspace_dir=lambda _ws: str(tmp_path), read_library=lambda _ws: {"seriesById": {"uv": project}},
        read_kits=lambda _ws: kits, trim=trim, sleep=lambda _s: None, poll_seconds=0, check_speech=False,
        set_shot_duration=lambda *args: lengths.append(args)))
    job = render.start("cast", "uv", "ep1", approve=True)
    for _ in range(200):
        job = render.status("cast", job["jobId"])
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.02)
    assert job["status"] == "completed", job
    export = next(args for tool, args in tools.calls if tool == "scenes.world3d.export")
    assert export["input"] == {"workspace": "cast", "document": {"v": 1, "width": 1920, "height": 1080, "fps": 24}, "quality": "final"}
    talk = next(args for tool, args in tools.calls if tool == "world3d.scene.talk")["input"]
    assert talk["lines"][0]["start"] == 0.8
    imported = next(args for tool, args in tools.calls if tool == "series.asset.import")["input"]
    assert imported["file"] == "elon-3d.mp4" and imported["metadata"]["productionMethod"] == "animation_3d"
    assert imported["metadata"]["dialogueBeats"] == [{"text": "Marte.", "start": 0.8, "end": 2.3}], "the take carries its subtitles"
    assert lengths == [("cast", "uv", "ep1", "s20", 3.208)], "intro 0.8 + 1.5 s line + tail 0.9, on the frame grid"


def test_a_3d_take_subtitles_come_from_its_own_lines():
    from services.episode_finishing import episode_cues, scene_beats
    from services.series_assembly import episode_assembly_plan
    beats = [{"text": "Desde Marte: aprobado.", "start": 0.35, "end": 2.0}]
    series = {"assets": {
        "a2d": {"id": "a2d", "kind": "video", "uri": "outputs/a.mp4", "metadata": {"sceneFilename": "a.scene.json"}},
        "a3d": {"id": "a3d", "kind": "video", "uri": "outputs/b.mp4", "metadata": {"sceneFilename": "w3d.world3d.scene.json", "dialogueBeats": beats}}}}
    shot = lambda sid, order, asset: {"id": sid, "order": order, "approvedAttemptId": f"t{sid}",
                                      "attempts": [{"id": f"t{sid}", "status": "completed", "outputAssetIds": [asset]}]}
    plan = episode_assembly_plan(series, {"shots": [shot("s1", 1, "a2d"), shot("s2", 2, "a3d")]})
    assert "dialogueBeats" not in plan[0] and plan[1]["dialogueBeats"] == beats
    assert scene_beats("/nonexistent", plan[1]["dialogueBeats"]) == beats
    cues = episode_cues([{"offset": 5.0, "duration": 2.5, "beats": scene_beats("/nonexistent", beats)}])
    assert [(cue["start"], cue["end"], cue["text"]) for cue in cues] == [(5.35, 7.0, "Desde Marte: aprobado.")]


def test_sound_effects_keep_a_zero_volume_and_a_subfolder_but_never_leave_the_workspace():
    layout = normalize_layout2d({"sfx": [{"file": "sfx/pen.wav", "line": 0, "volume": 0}, {"file": "../pen.wav", "line": 0},
                                         {"file": "sfx/../../pen.wav", "line": 0}, {"file": "/etc/pen.wav", "line": 0}]})
    assert layout["sfx"] == [{"file": "sfx/pen.wav", "line": 0, "anchor": "start", "volume": 0}]


def test_scene_sound_joins_a_3d_shot_soundtrack_balanced_and_ducked_by_the_page():
    tools = World3D()
    shot = {"id": "s20", "scene3d": {"scene": "mars.world3d.scene.json", "cast": [{"characterId": "elon", "objectId": "elon", "poseId": "phone"}]}}
    lines = [{"characterId": "elon", "start": 0.8, "filename": "ln 1.wav", "cues": []}]
    tracks = [{"id": "ambience", "filename": "amb/mars wind.wav", "kind": "sfx", "startTime": 0, "volume": 0.3},
              {"id": "music", "filename": "theme.wav", "kind": "music", "startTime": 1.5, "volume": 1.8}]
    series_shot3d.build_scene(tools, "cast", "job", shot, lines, 4.5, {}, {"elon": "kit-elon"}, NativeRenderError, tracks=tracks)
    length = tools.calls[3][1]["input"]
    assert length["duration"] == 4.5
    assert length["soundtrack"] == [
        {"id": "scene-ambience", "audio": "/api/v1/file/amb/mars%20wind.wav?workspace=cast", "start": 0.0, "gain": 0.3},
        {"id": "scene-music", "audio": "/api/v1/file/theme.wav?workspace=cast", "start": 1.5, "gain": 1.0}]
    plain = World3D()
    series_shot3d.build_scene(plain, "cast", "job", shot, lines, 4.5, {}, {"elon": "kit-elon"}, NativeRenderError)
    assert "soundtrack" not in plain.calls[3][1]["input"], "no tracks, no soundtrack patch"


def test_a_directional_effect_keeps_its_rotation_so_a_laser_leaves_the_gun():
    layout = normalize_layout2d({"fx": [{"kind": "laser", "line": 0, "x": 30, "y": 36, "rotation": 180},
                                        {"kind": "laser", "line": 0, "rotation": 400}]})
    assert layout["fx"][0]["rotation"] == 180.0 and "rotation" not in layout["fx"][1]
    cues = fx_cues(layout, [(0.4, 1.4)], 3.0)
    assert cues[0]["rotation"] == 180.0 and cues[0]["x"] == 30.0


def test_a_beam_can_start_on_a_cast_member_or_at_a_point_of_the_frame():
    layout = normalize_layout2d({"fx": [
        {"kind": "laser", "at": 0.6, "duration": 0.3, "x": 90, "y": 20, "color": "#ffd56a", "from": {"cast": 0, "point": [95, 46]}},
        {"kind": "lightning", "at": 1, "from": {"cast": " blas ", "point": [10, -20]}},
        {"kind": "laser", "at": 1, "from": {"point": [70, 40]}},
        {"kind": "confetti", "at": 1, "from": {"point": [70, 40]}},
        {"kind": "laser", "at": 1, "from": {"cast": True, "point": [70, 40]}},
        {"kind": "laser", "at": 1, "from": {"cast": 0, "point": [70]}},
        {"kind": "laser", "at": 1, "from": {"cast": 9, "point": [70, 40]}},
        {"kind": "laser", "at": 1, "from": {"point": [70, 400]}},
    ]})
    assert [cue.get("from") for cue in layout["fx"]] == [
        {"cast": 0, "point": [95.0, 46.0]}, {"cast": "blas", "point": [10.0, -20.0]}, {"point": [70.0, 40.0]}, None, None, None, None, None]
    cues = fx_cues(layout, [(0.4, 1.4)], 3.0)
    assert cues[0] == {"id": "fx-0", "kind": "laser", "start": 0.6, "end": 0.9, "x": 90.0, "y": 20.0, "color": "#ffd56a", "size": 80.0,
                       "from": {"cast": 0, "point": [95.0, 46.0]}}
    assert "from" not in cues[3]


def test_a_3d_shot_keeps_a_beam_from_the_frame_and_drops_one_from_a_cutout():
    effects = series_shot3d._shot_effects([{"id": "fx-0", "kind": "laser", "start": 1, "end": 1.3, "from": {"point": [70.0, 40.0]}},
                                           {"id": "fx-1", "kind": "laser", "start": 1, "end": 1.3, "from": {"cast": 0, "point": [95.0, 46.0]}},
                                           {"id": "fx-2", "kind": "vignette", "start": 0, "end": 3}])
    assert effects == [{"id": "shot-fx-0", "kind": "laser", "start": 1, "end": 1.3, "from": {"x": 70.0, "y": 40.0}},
                       {"id": "shot-fx-1", "kind": "laser", "start": 1, "end": 1.3},
                       {"id": "shot-fx-2", "kind": "vignette", "start": 0, "end": 3}]


def _glb(path, names):
    import json as _json
    import struct as _struct
    body = _json.dumps({"asset": {"version": "2.0"}, "animations": [{"name": name} for name in names]}).encode()
    body += b" " * (-len(body) % 4)
    path.write_bytes(b"glTF" + _struct.pack("<II", 2, 20 + len(body)) + _struct.pack("<I4s", len(body), b"JSON") + body)


def test_a_3d_shot_places_its_objects_with_the_clip_found_in_the_model(tmp_path):
    _glb(tmp_path / "zeppelin.glb", ["Idle", "Fly"])
    value = series_shot3d.normalize_scene3d({"template": "anime-face-off", "objects": [
        {"objectId": "zep", "file": "zeppelin.glb", "add": True, "clip": "Fly", "clipPlayback": {"speed": 2, "loop": "yes"}, "grounded": "no",
         "position": [0, 2, -6], "rotationY": 1.57, "motion": {"to": [5, 2, -6], "faceTravel": True, "points": [[1, 2, 3], "x"]}},
        {"objectId": "bad", "file": "../secret.glb", "add": True},
        {"objectId": "abs", "file": "/etc/passwd"},
        {"objectId": "nothing"},
        {"objectId": "hero", "file": "rayo.glb", "clip": {"index": 1, "name": "Run"}, "grounded": True},
        {"objectId": "flat", "media": "screen", "file": "a.png"}]})
    assert value["objects"] == [{"objectId": "zep", "media": "model3d", "file": "zeppelin.glb", "add": True, "clip": "Fly",
                                 "clipPlayback": {"speed": 2.0}, "position": [0.0, 2.0, -6.0], "motion": {"to": [5.0, 2.0, -6.0], "faceTravel": True},
                                 "rotationY": 1.57},
                                {"objectId": "hero", "media": "model3d", "file": "rayo.glb", "clip": {"index": 1, "name": "Run"}, "grounded": True}]
    value["objects"] = value["objects"][:1]
    tools = World3D()
    shot = {"id": "s30", "scene3d": value}
    series_shot3d.build_scene(tools, "cast", "job", shot, [], 5, {}, {}, NativeRenderError, root=str(tmp_path))
    patch = tools.calls[1][1]["input"]
    assert patch["retime"] is True and patch["duration"] == 5
    assert patch["bindings"] == [{"object_id": "zep", "media": "model3d", "add": True, "source_url": "/api/v1/file/zeppelin.glb?workspace=cast",
                                  "clip": {"index": 1, "name": "Fly"}, "clipPlayback": {"speed": 2.0}, "position": [0.0, 2.0, -6.0],
                                  "rotationY": 1.57, "motion": {"to": [5.0, 2.0, -6.0], "faceTravel": True}}]
    shot["scene3d"] = {**value, "retime": False, "objects": [{**value["objects"][0], "clip": "Explode"}]}
    try:
        series_shot3d.build_scene(World3D(), "cast", "job", shot, [], 5, {}, {}, NativeRenderError, root=str(tmp_path))
    except NativeRenderError as error:
        assert error.code == "unknown_clip" and "Idle, Fly" in str(error)
    else:
        raise AssertionError("expected unknown_clip")
    kept = series_shot3d.normalize_scene3d({"template": "anime-face-off", "retime": False})
    assert kept["retime"] is False and "objects" not in kept


def test_a_3d_shot_plays_its_sound_effects_and_screen_effects_like_a_2d_shot(tmp_path):
    project = series()
    project["episodesById"] = {"ep1": {"id": "ep1", "shots": [{
        "id": "s21", "order": 1, "sceneId": "a", "productionMethod": "animation_3d", "durationSeconds": 4,
        "layout2d": {"sfx": [{"file": "boom.wav", "at": 1.25, "volume": 0.9}],
                     "fx": [{"kind": "manga_impact", "at": 1.2, "duration": 0.4, "x": 40, "y": 30, "size": 25}]},
        "scene3d": {"template": "user-sky", "quality": "draft"}}]}}
    tools = RenderTools(tmp_path)
    render = SeriesNativeRender(NativeRenderDeps(
        call=tools, workspace_dir=lambda _ws: str(tmp_path), read_library=lambda _ws: {"seriesById": {"uv": project}},
        read_kits=lambda _ws: {}, trim=lambda source, target: 1.0, sleep=lambda _s: None, poll_seconds=0, check_speech=False,
        set_shot_duration=lambda *args: None))
    job = render.start("cast", "uv", "ep1", approve=True)
    for _ in range(200):
        job = render.status("cast", job["jobId"])
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.02)
    assert job["status"] == "completed", job
    length = next(args["input"] for tool, args in tools.calls if tool == "world3d.scene.patch" and "duration" in args["input"])
    assert {"id": "scene-sfx-0", "audio": "/api/v1/file/boom.wav?workspace=cast", "start": 1.25, "gain": 0.9} in length["soundtrack"]
    assert length["screenFx"] == [{"id": "shot-fx-0", "kind": "manga_impact", "start": 1.2, "end": 1.6, "x": 40.0, "y": 30.0, "size": 25.0}]


def test_a_3d_shot_asks_for_the_toon_look_and_drops_bad_settings():
    value = series_shot3d.normalize_scene3d({"template": "anime-face-off", "renderLook": "toon", "toon": {"steps": 2, "ink": "#AA0000"}})
    assert (value["renderLook"], value["toon"]) == ("toon", {"steps": 2, "ink": "#aa0000"})
    bad = series_shot3d.normalize_scene3d({"template": "anime-face-off", "renderLook": "cel", "toon": {"steps": 9}})
    assert "renderLook" not in bad and "toon" not in bad
    tools = World3D()
    series_shot3d.build_scene(tools, "cast", "job", {"id": "s31", "scene3d": value}, [], 4, {}, {}, NativeRenderError)
    patch = tools.calls[1][1]["input"]
    assert (patch["renderLook"], patch["toon"]) == ("toon", {"steps": 2, "ink": "#aa0000"})


def test_a_3d_object_keeps_a_heading_offset_for_a_model_whose_nose_is_not_plus_z():
    value = series_shot3d.normalize_scene3d({"template": "user-sky", "objects": [
        {"objectId": "ship", "file": "ship.glb", "add": True, "motion": {"to": [0, 2, -30], "faceTravel": True, "headingOffset": 1.5708}},
        {"objectId": "bad", "file": "ship.glb", "add": True, "motion": {"to": [0, 2, -30], "headingOffset": 40}}]})
    assert value["objects"][0]["motion"] == {"to": [0.0, 2.0, -30.0], "faceTravel": True, "headingOffset": 1.5708}
    assert "headingOffset" not in value["objects"][1]["motion"]


def _durations(value):
    return [cue["duration"] for cue in normalize_layout2d({"fx": [{"kind": "vignette", "at": 0, "duration": value}]})["fx"]]


def test_a_screen_effect_longer_than_the_maximum_is_clamped_not_reset_to_one_second():
    # An author who writes 99 for "the whole shot" used to get 1 s: the grade vanished after one second.
    assert _durations(99) == [30.0] and _durations(30.0001) == [30.0] and _durations(1e9) == [30.0]
    assert _durations(0.05) == [0.1] and _durations(0) == [0.1] and _durations(-5) == [0.1]
    assert _durations(0.1) == [0.1] and _durations(30) == [30.0] and _durations(2) == [2.0]


def test_a_missing_or_non_numeric_effect_duration_is_left_out_so_the_class_default_applies_and_shot_is_kept():
    for value in (None, "soon", "", True, [3], {"s": 3}, float("nan")):
        layout = normalize_layout2d({"fx": [{"kind": "vignette", "at": 0, "duration": value}]})
        assert "duration" not in layout["fx"][0], value
    layout = normalize_layout2d({"fx": [{"kind": "impact_flash", "line": 0}, {"kind": "vignette", "at": 0, "duration": "shot"},
                                        {"kind": "film_grain", "at": 0, "duration": " Shot "}]})
    assert ["duration" in cue and cue["duration"] for cue in layout["fx"]] == [False, "shot", "shot"]


def test_a_shot_duration_lasts_to_the_end_of_the_shot_and_a_clamped_one_keeps_its_seconds():
    timing, duration = plan_timing([1.0, 0.5], intro=1.0, gap=0.2, tail=1.0)
    layout = normalize_layout2d({"fx": [{"kind": "vignette", "at": 0, "duration": "shot"},
                                        {"kind": "candlelight", "line": 1, "duration": "shot"},
                                        {"kind": "film_grain", "at": 0.5, "duration": 99},
                                        {"kind": "confetti", "at": 1, "duration": 2},
                                        {"kind": "glitch", "at": 1}]})
    ends = {cue["kind"]: (cue["start"], cue["end"]) for cue in fx_cues(layout, timing, duration)}
    last = round(duration - 0.01, 3)
    assert ends["vignette"] == (0.0, last) and last == 3.698, "until the end of the shot"
    assert ends["candlelight"] == (2.2, last)
    assert ends["film_grain"] == (0.5, last), "99 is clamped to 30 s and the shot ends first"
    assert ends["confetti"] == (1.0, 3.0) and ends["glitch"] == (1.0, last), "seconds are unchanged; glitch is a presence effect, so it lasts the shot"
    long_shot = fx_cues(layout, [(0.0, 1.0)], 45.0)
    assert {cue["kind"]: cue["end"] for cue in long_shot} == {
        "vignette": 44.99, "candlelight": 44.99, "film_grain": 30.5, "confetti": 3.0, "glitch": 44.99}, "30 s is the clamp, shot is not"


def test_a_shot_with_valid_screen_effect_durations_keeps_its_take_digest():
    raw = {"framing": "wide", "fx": [{"kind": "confetti", "line": 0, "duration": 1.5, "x": 70}, {"kind": "vignette", "at": 0.5, "duration": 30},
                                     {"kind": "film_grain", "at": 1, "duration": 0.1}, {"kind": "impact_flash", "line": 0},
                                     {"kind": "confetti", "line": 0, "duration": "x"}],
           "sfx": [{"file": "pen.wav", "line": 0}]}
    fresh = normalize_layout2d(raw)
    assert [cue.get("duration") for cue in fresh["fx"]] == [1.5, 30.0, 0.1, None, None], "a missing or bad duration is left to the effect's class"
    # A layout saved before presence and hit has the 1 s written out: it stays what it was.
    layout = {**fresh, "fx": [{**cue, "duration": cue.get("duration", 1.0)} for cue in fresh["fx"]]}
    series = {"id": "show", "spokenLanguage": "English", "locations": [{"id": "sky", "name": "Sky"}],
              "characters": [{"id": "ana", "voiceProfile": {"characterKitRef": {"id": "kit-ana", "workspace": "ws"}}}]}
    kits = {"kit-ana": {"id": "kit-ana", "voice": {"model": "qwen3_tts_customvoice", "voiceId": "ryan"}}}
    shot = {"id": "s1", "order": 1, "locationId": "sky", "productionMethod": "animation_3d", "visibleCharacterIds": ["ana"],
            "dialogueBeats": [{"id": "s1_b0", "characterId": "ana", "text": "Hold on!"}], "layout2d": layout,
            "scene3d": {"template": "user-airship", "cast": [{"characterId": "ana", "objectId": "ana"}], "quality": "draft"}}
    # Computed with the code before this fix: takes rendered then stay up to date.
    assert render_inputs(series, shot, kits) == "efa49e2c1b00e41b"
    clamped = {**shot, "layout2d": normalize_layout2d({**raw, "fx": [{**raw["fx"][1], "duration": 99}]})}
    assert render_inputs(series, clamped, kits) != render_inputs(
        series, {**shot, "layout2d": normalize_layout2d({**raw, "fx": [{**raw["fx"][1], "duration": 1}]})}, kits), "30 s is not 1 s"


class World3DWithSlots(World3D):
    """A template whose instantiated document lists its objects (the cast member elon is a model of the template)."""

    def __call__(self, tool, arguments):
        reply = super().__call__(tool, arguments)
        if tool == "world3d.scene.instantiate":
            reply["result"]["scene"]["document"] = {"slots": [{"id": "elon", "media": "model3d"}, {"id": "sky", "media": "image"}]}
        return reply


def test_a_3d_object_plays_a_clip_sequence_rides_in_a_hand_and_materializes(tmp_path):
    _glb(tmp_path / "guard.glb", ["Idle", "Run", "Aim"])
    _glb(tmp_path / "rifle.glb", [])
    value = series_shot3d.normalize_scene3d({"template": "user-plaza", "objects": [
        {"objectId": "guard", "file": "guard.glb", "add": True, "grounded": True,
         "clips": [{"clip": "Aim", "start": 1.5, "fade": 0.4, "loop": False}, {"clip": {"index": 0, "name": "Idle"}, "start": 0}]},
        {"objectId": "rifle", "file": "rifle.glb", "add": True, "scale": 0.19,
         "hold": {"carrier": "guard", "hand": "right", "offset": [0, 0.02, 0.05], "rotation": [-1.65, 0.11, 2.76]},
         "appearance": {"start": 0.5, "duration": 0.6, "color": "#ffcc00"}},
        {"objectId": "poster", "media": "image", "file": "p.png", "add": True, "clips": [{"clip": "Idle", "start": 0}],
         "hold": {"carrier": "poster", "hand": "left"}, "appearance": {"start": 900}}]})
    guard, rifle, poster = value["objects"]
    assert guard["clips"] == [{"clip": {"index": 0, "name": "Idle"}, "start": 0.0}, {"clip": "Aim", "start": 1.5, "fade": 0.4, "loop": False}]
    assert rifle["hold"] == {"carrier": "guard", "hand": "right", "offset": [0.0, 0.02, 0.05], "rotation": [-1.65, 0.11, 2.76]}
    assert rifle["appearance"] == {"start": 0.5, "duration": 0.6, "color": "#ffcc00"}
    assert set(poster) == {"objectId", "media", "file", "add"}, "an image plays no clips, holds nothing of itself, bad times are dropped"
    shot = {"id": "s40", "scene3d": {**value, "objects": [guard, rifle]}}
    tools = World3D()
    series_shot3d.build_scene(tools, "cast", "job", shot, [], 4, {}, {}, NativeRenderError, root=str(tmp_path))
    bindings = tools.calls[1][1]["input"]["bindings"]
    assert bindings[0]["clips"] == [{"clip": {"index": 0, "name": "Idle"}, "start": 0.0},
                                    {"clip": {"index": 2, "name": "Aim"}, "start": 1.5, "fade": 0.4, "loop": False}]
    assert bindings[1]["hold"] == rifle["hold"] and bindings[1]["appearance"] == rifle["appearance"] and bindings[1]["scale"] == 0.19

    def refused(code, config, lines=(), tools_class=World3D):
        try:
            series_shot3d.build_scene(tools_class(), "cast", "job", {"id": "s41", "scene3d": config}, list(lines), 4, {}, {"elon": "kit-elon"},
                                      NativeRenderError, root=str(tmp_path))
        except NativeRenderError as error:
            assert error.code == code, (error.code, str(error))
            return str(error)
        raise AssertionError(f"expected {code}")
    typo = {**value, "objects": [{**guard, "clips": [{"clip": "Aimm", "start": 0}]}]}
    assert "Idle, Run, Aim" in refused("unknown_clip", typo)
    cast = [{"characterId": "elon", "objectId": "elon"}]
    by_elon = {**value, "cast": cast, "objects": [{**rifle, "hold": {"carrier": "elon", "hand": "right"}}]}
    line = [{"characterId": "elon", "start": 0.2, "filename": "e.wav"}]
    assert "cutout" in refused("carrier_is_cutout", by_elon, line)
    quiet = World3DWithSlots()
    series_shot3d.build_scene(quiet, "cast", "job", {"id": "s42", "scene3d": by_elon}, [], 4, {}, {"elon": "kit-elon"}, NativeRenderError,
                              root=str(tmp_path))
    assert quiet.calls[1][1]["input"]["bindings"][0]["hold"]["carrier"] == "elon", "a cast member with no line in the shot is a model"
    by_sky = {**value, "objects": [{**rifle, "hold": {"carrier": "sky", "hand": "left"}}]}
    assert "(models: elon)" in refused("unknown_carrier", by_sky, tools_class=World3DWithSlots)
    by_nobody = {**value, "objects": [{**rifle, "hold": {"carrier": "nobody", "hand": "left"}}]}
    refused("unknown_carrier", by_nobody, tools_class=World3DWithSlots)


def test_scene3d_problems_name_bad_holds_sequences_and_appearances_without_a_workspace():
    problems = series_shot3d.scene3d_problems({"template": "user-plaza", "objects": [
        {"objectId": "gun", "hold": {"carrier": "hero", "hand": "right", "rotation": [0, 9, 0]}},
        {"objectId": "hero", "clips": [{"clip": "Idle", "start": 0, "fadeIn": 1}], "appearance": {"start": 1, "duration": 99}},
        {"objectId": "ok", "file": "missing.glb", "clips": [{"clip": "Idle", "start": 0}]}]})
    assert problems == ["scene3d object gun: hold.rotation must be [x, y, z], each -6.2832 to 6.2832 radians",
                        "scene3d object hero: clips[0] must be {clip, start, duration?, fade?, speed?, offset?, loop?}",
                        "scene3d object hero: appearance.duration must be 0.1-30 seconds"], "files and clip names wait for a workspace"


class _PlatedWorld(World3D):
    def __call__(self, tool, arguments):
        result = super().__call__(tool, arguments)
        if tool == "world3d.scene.instantiate":
            result["result"]["scene"]["document"] = {"slots": [
                {"id": "background", "slot": "background", "surface": "environment", "sourceUrl": "/old/madrid.png"},
                {"id": "hero", "slot": "subject", "surface": "character"},
            ]}
        return result


def test_a_location_backdrop_replaces_only_the_environment_slot():
    plate = "/api/v1/file/plaza.png?workspace=cast"
    shot = {"id": "s20", "scene3d": {"template": "user-mars", "cast": [{"characterId": "elon", "objectId": "elon"}], "backdrop": "location"}}
    tools = _PlatedWorld()
    series_shot3d.build_scene(tools, "cast", "job", shot, [], 4, {}, {}, NativeRenderError, plate=plate)
    length = next(args["input"] for name, args in tools.calls if name == "world3d.scene.patch" and "duration" in args["input"])
    assert length["bindings"] == [{"object_id": "background", "source_url": plate}]
    plain = {"id": "s20", "scene3d": {"template": "user-mars", "cast": [{"characterId": "elon", "objectId": "elon"}]}}
    first = series_shot3d.build_scene(World3D(), "cast", "job", plain, [], 4, {}, {}, NativeRenderError)
    second = series_shot3d.build_scene(World3D(), "cast", "job", plain, [], 4, {}, {}, NativeRenderError)
    moved = series_shot3d.build_scene(World3D(), "cast", "job", plain, [], 4, {}, {}, NativeRenderError, plate=plate)
    assert first["renderDigest"] == second["renderDigest"] != moved["renderDigest"]
    untouched = _PlatedWorld()
    series_shot3d.build_scene(untouched, "cast", "job", plain, [], 4, {}, {}, NativeRenderError)
    bare = next(args["input"] for name, args in untouched.calls if name == "world3d.scene.patch" and "duration" in args["input"])
    assert "bindings" not in bare
    assert "backdrop" not in series_shot3d.normalize_scene3d({"template": "user-mars", "backdrop": "template"})
    assert series_shot3d.normalize_scene3d({"template": "user-mars", "backdrop": "location"})["backdrop"] == "location"
    assert series_shot3d.normalize_scene3d({"template": "user-mars", "backdrop": {"asset": "asset_1"}})["backdrop"] == {"asset": "asset_1"}
    assert "backdrop" not in series_shot3d.normalize_scene3d({"template": "user-mars", "backdrop": {"asset": "../x"}})
    assert series_shot3d.scene3d_problems({"template": "user-mars", "backdrop": 3}) == [
        "scene3d.backdrop must be template, location, or {asset}"]


def test_an_effect_speed_reaches_the_shot_cues_and_a_3d_scene():
    from services.scene2d_validate import _normalize_sfx
    from services.world3d_scenes import _screen_fx_entry, _screen_fx_kinds
    layout = normalize_layout2d({"fx": [{"kind": "rain", "at": 0, "duration": "shot", "speed": 0.05}, {"kind": "dust", "speed": 9}]})
    assert layout["fx"][0]["speed"] == 0.05 and "speed" not in layout["fx"][1], "out of range is dropped"
    cues = fx_cues(layout, [], 6.0)
    assert cues[0]["speed"] == 0.05
    entry = _screen_fx_entry(0, {**cues[0], "id": "shot-fx-0"}, _screen_fx_kinds())
    assert entry["speed"] == 0.05
    document = {"version": 1, "sfx": [{"id": "a", "kind": "rain", "start": 0, "end": 2, "speed": 0.001}]}
    _normalize_sfx(document)
    assert document["sfx"][0]["speed"] == 0.02


# Presence and hit: what an effect lasts and how big it is when the script says nothing -----------------------------------

PRESENCE = {
    "rain", "snow", "embers", "smoke", "fog", "bubbles", "stars", "portal", "scanline", "etching", "aurora", "magic_circle",
    "summoning_gate", "black_hole", "meteor_shower", "lightning_storm", "anime_aura", "energy_orb", "fire", "shield", "tornado",
    "dust", "media_portal", "code_rain", "psx", "n64", "nes", "snes", "gameboy", "gameboy_color", "genesis", "vhs", "crt", "c64",
    "candlelight", "vignette", "film_grain", "light_rays", "glitch", "canvas"}
HIT = {"sparks", "explosion", "fireworks", "confetti", "shockwave", "lightning", "speedlines", "laser", "arcane_missiles", "ice_burst",
       "energy_beam", "sword_slash", "manga_impact", "impact_flash", "impact_invert", "splash"}


def test_every_effect_of_the_catalog_is_classified_as_presence_or_hit_and_the_owner_reviews_the_list_here():
    import json
    from pathlib import Path

    from services.series_fx_classes import EFFECT_CLASSES, effect_class
    shared = Path(__file__).resolve().parents[1] / "app" / "shared"
    catalog = {item["id"] for item in json.loads((shared / "scene_effects.json").read_text(encoding="utf-8"))}
    classes = json.loads((shared / "scene_effect_classes.json").read_text(encoding="utf-8"))
    assert set(classes["effects"]) == catalog and set(EFFECT_CLASSES) == catalog, "an effect without a class, or a class without an effect"
    assert {kind for kind in catalog if effect_class(kind) == "presence"} == PRESENCE
    assert {kind for kind in catalog if effect_class(kind) == "hit"} == HIT
    assert PRESENCE | HIT == catalog and not PRESENCE & HIT and len(catalog) == 56
    for kind, entry in classes["effects"].items():
        assert entry["size"] in ("cover", "framing", "own"), kind
        if entry["class"] == "hit":
            assert 0.25 <= entry["duration"] <= 1, f"a hit is brief: {kind}"
        else:
            assert "duration" not in entry, f"a presence effect lasts the shot: {kind}"
        assert entry.get("scale", 1) <= 2, kind


def _cue(effect, framing=None, duration=6.0, **fields):
    layout = normalize_layout2d({"fx": [{"kind": effect, "at": 0, **fields}]})
    return fx_cues(layout, [], duration, framing=framing)[0]


def test_a_presence_effect_with_no_duration_lasts_the_shot():
    for kind in ("anime_aura", "shield", "candlelight", "rain", "crt", "fog"):
        cue = _cue(kind)
        assert (cue["start"], cue["end"]) == (0.0, 5.99), kind
    late = fx_cues(normalize_layout2d({"fx": [{"kind": "anime_aura", "at": 2}]}), [], 6.0)[0]
    assert (late["start"], late["end"]) == (2.0, 5.99), "from its start to the end of the shot"


def test_a_presence_effect_covers_the_screen_or_the_subject_it_names():
    assert _cue("anime_aura")["size"] == 178, "nobody named: the whole screen (16:9 needs 178 % of the height)"
    assert _cue("anime_aura", framing="close")["size"] == 178
    assert [_cue("anime_aura", framing=framing, x=40)["size"] for framing in ("wide", "two", "medium", "close", None)] == [80, 125, 190, 200, 125]
    assert _cue("shield", framing="two", y=60)["size"] == 125, "a y alone names a place too"
    entering = normalize_layout2d({"fx": [{"kind": "anime_aura", "anchor": "enter", "cast": 0}]})
    assert fx_cues(entering, [], 6.0, framing="medium")[0]["size"] == 190, "a cast member is a subject"


def test_a_hit_is_brief_and_sized_to_the_framing_and_a_few_small_painters_are_scaled_up():
    assert [_cue("explosion", framing=framing)["size"] for framing in ("wide", "two", "medium", "close", None)] == [65, 80, 100, 120, 80]
    assert _cue("sparks", framing="two")["size"] == 120 and _cue("fireworks", framing="close")["size"] == 168
    assert _cue("confetti", framing="close")["size"] == 156 and _cue("energy_orb", framing="close")["size"] == 156
    assert _cue("sparks", framing="close")["size"] == 180
    assert _cue("laser", framing="close", x=30)["size"] == 120, "naming a place does not change a hit's size"
    spans = {kind: round(cue["end"] - cue["start"], 3) for kind in ("sparks", "explosion", "lightning", "sword_slash", "impact_flash", "arcane_missiles")
             for cue in [_cue(kind)]}
    assert spans == {"sparks": 0.8, "explosion": 1.0, "lightning": 0.5, "sword_slash": 0.5, "impact_flash": 0.25, "arcane_missiles": 1.0}
    assert all(0.25 <= _cue(kind)["end"] - _cue(kind)["start"] <= 1 for kind in HIT)


def test_an_effect_whose_size_means_something_else_keeps_its_own_default():
    for kind in ("rain", "snow", "fog", "code_rain", "vignette", "candlelight", "film_grain", "light_rays", "glitch", "canvas",
                 "scanline", "vhs", "impact_flash", "impact_invert"):
        for framing in (None, "close"):
            assert "size" not in _cue(kind, framing=framing, x=30), kind


def test_a_script_that_gives_a_duration_or_a_size_gets_exactly_that_and_the_other_comes_from_its_class():
    script = [
        {"kind": "anime_aura", "at": 1, "duration": 0.7, "x": 30, "y": 40, "size": 20, "color": "#ff0000", "intensity": 1.5},
        {"kind": "explosion", "at": 2, "duration": 4, "size": 150},
        {"kind": "shield", "at": 0, "duration": "shot", "size": 90},
        {"kind": "anime_aura", "at": 0, "size": 33},
        {"kind": "explosion", "at": 0, "duration": 3},
    ]
    cues = fx_cues(normalize_layout2d({"fx": script}), [], 6.0, framing="two")
    assert cues == [
        {"id": "fx-0", "kind": "anime_aura", "start": 1.0, "end": 1.7, "x": 30.0, "y": 40.0, "size": 20.0, "intensity": 1.5, "color": "#ff0000"},
        {"id": "fx-1", "kind": "explosion", "start": 2.0, "end": 5.99, "size": 150.0},
        {"id": "fx-2", "kind": "shield", "start": 0.0, "end": 5.99, "size": 90.0},
        {"id": "fx-3", "kind": "anime_aura", "start": 0.0, "end": 5.99, "size": 33.0},
        {"id": "fx-4", "kind": "explosion", "start": 0.0, "end": 3.0, "size": 80.0},
    ]


def test_a_layout_saved_with_its_duration_written_out_compiles_as_it_did():
    saved = {"fx": [{"kind": "anime_aura", "line": 0, "anchor": "start", "duration": 1.0}, {"kind": "fog", "at": 0.5, "duration": "shot"}]}
    cues = fx_cues(saved, [(0.4, 1.4)], 5.0, framing="two")
    assert [(cue["start"], cue["end"]) for cue in cues] == [(0.4, 1.4), (0.5, 4.99)]


def test_the_shot_plan_sizes_the_effects_to_its_framing():
    shot = {"id": "s1", "sceneId": "a", "locationId": "garage", "durationSeconds": 6, "layout2d": {
        "framing": "medium", "cast": [{"characterId": "kevin"}], "fx": [{"kind": "anime_aura", "at": 0, "x": 50}, {"kind": "explosion", "at": 1}]}}
    shot["layout2d"] = normalize_layout2d(shot["layout2d"])
    spec = build_shot_spec(series(), {"id": "ep1"}, shot, workspace="cast", recorded={})
    assert [(cue["kind"], cue["size"], cue["end"]) for cue in spec["sfx"]] == [("anime_aura", 190, spec["duration"] - 0.01), ("explosion", 100, 2.0)]


def test_the_full_shot_halo_fixture_is_what_the_planner_compiles():
    """The cue ui/e2e/specs/scene-fx-presence.spec.ts paints at the start, the middle and the end of the shot."""
    import json
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / "fixtures" / "series_fx_presence_shot.json").read_text(encoding="utf-8"))
    shot = {"id": "s1", "sceneId": "a", "locationId": "garage", "durationSeconds": fixture["duration"],
            "layout2d": normalize_layout2d(fixture["shot"])}
    spec = build_shot_spec(series(), {"id": "ep1"}, shot, workspace="cast", recorded={})
    assert (spec["width"], spec["height"], spec["duration"]) == (fixture["width"], fixture["height"], fixture["duration"])
    assert spec["sfx"] == [fixture["cue"]]
    assert fixture["cue"]["end"] > fixture["frames"][-1] > fixture["frames"][1] > fixture["frames"][0] >= fixture["cue"]["start"], "active at all three"


def test_a_3d_shot_takes_the_same_defaults_and_its_scene_accepts_every_one():
    from services.series_fx_classes import EFFECT_CLASSES
    from services.world3d_scenes import _screen_fx_entry, _screen_fx_kinds
    kinds = _screen_fx_kinds()
    checked = 0
    for kind in sorted(set(EFFECT_CLASSES) & kinds):
        for framing in (None, "wide", "two", "medium", "close"):
            for named in ({}, {"x": 40}):
                cue = _cue(kind, framing=framing, **named)
                effect = series_shot3d.shot_effects([cue])[0]
                assert effect["end"] == cue["end"] and effect.get("size") == cue.get("size"), "the shot's cues reach the 3D document as they are"
                entry = _screen_fx_entry(0, effect, kinds)
                assert entry["end"] > entry["start"] and entry.get("size", 65) <= 200, (kind, framing, named)
                checked += 1
    assert checked >= 200
    shot = series_shot3d.shot_effects([_cue("anime_aura")])[0]
    assert (shot["id"], shot["size"], shot["end"]) == ("shot-fx-0", 178, 5.99), "the default halo covers a 3D frame too"
