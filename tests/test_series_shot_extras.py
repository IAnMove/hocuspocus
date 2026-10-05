"""Rhythm, timed sound and screen effects, perched characters and 3D dialogue shots in the server render."""
import time

from services import series_shot3d
from services.series_native_render import NativeRenderDeps, NativeRenderError, SeriesNativeRender
from services.series_shot_extras import cue_time, fx_cues, perch, sfx_tracks
from services.series_shot_plan import build_shot_spec, normalize_layout2d, plan_timing


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
    assert fx_cues(layout, timing, duration) == [{"id": "fx-0", "kind": "confetti", "start": 3.7, "end": 5.198, "x": 30}]


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


def test_a_speaker_without_an_object_or_a_failing_tool_stops_the_shot():
    shot = {"id": "s20", "scene3d": {"template": "user-mars", "cast": []}}
    lines = [{"characterId": "elon", "start": 0.3, "filename": "a.wav"}]
    try:
        series_shot3d.build_scene(World3D(), "cast", "job", shot, lines, 3, {}, {"elon": "kit-elon"}, NativeRenderError)
    except NativeRenderError as error:
        assert error.code == "unbound_speaker" and "elon" in str(error)
    else:
        raise AssertionError("expected unbound_speaker")
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
    assert export["input"] == {"workspace": "cast", "document": {"v": 1}, "quality": "final"}
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


def _glb(path, names):
    import json as _json
    import struct as _struct
    body = _json.dumps({"asset": {"version": "2.0"}, "animations": [{"name": name} for name in names]}).encode()
    body += b" " * (-len(body) % 4)
    path.write_bytes(b"glTF" + _struct.pack("<II", 2, 20 + len(body)) + _struct.pack("<I4s", len(body), b"JSON") + body)


def test_a_3d_shot_places_its_objects_with_the_clip_found_in_the_model(tmp_path):
    _glb(tmp_path / "zeppelin.glb", ["Idle", "Fly"])
    value = series_shot3d.normalize_scene3d({"template": "anime-face-off", "objects": [
        {"objectId": "zep", "file": "zeppelin.glb", "add": True, "clip": "Fly", "clipPlayback": {"speed": 2, "loop": "yes"},
         "position": [0, 2, -6], "rotationY": 1.57, "motion": {"to": [5, 2, -6], "faceTravel": True, "points": [[1, 2, 3], "x"]}},
        {"objectId": "bad", "file": "../secret.glb", "add": True},
        {"objectId": "abs", "file": "/etc/passwd"},
        {"objectId": "nothing"},
        {"objectId": "flat", "media": "screen", "file": "a.png"}]})
    assert value["objects"] == [{"objectId": "zep", "media": "model3d", "file": "zeppelin.glb", "add": True, "clip": "Fly",
                                 "clipPlayback": {"speed": 2.0}, "position": [0.0, 2.0, -6.0], "motion": {"to": [5.0, 2.0, -6.0], "faceTravel": True},
                                 "rotationY": 1.57}]
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
