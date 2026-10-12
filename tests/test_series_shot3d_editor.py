"""A Video 3D shot's plan opens in the Video 3D editor and the edited scene goes back to the shot."""
import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.series_shot_inspector import create_series_shot_inspector_router
from services.series_shot3d_editor import Scene3DEditorError, editor_scene, from_editor, plan_from_editor, workspace_file

RIFLE_HOLD = {"carrier": "e1", "hand": "right", "offset": [-0.146, 0.013, -0.038], "rotation": [-1.65, 0.11, 2.76]}


def shot():
    return {"id": "e1s115", "order": 116, "sceneId": "e1_plaga", "productionMethod": "animation_3d", "durationSeconds": 5.0,
            "locationId": "madridnoche",
            "layout2d": {"framing": "wide", "fx": [{"kind": "shockwave", "at": 1.0, "duration": 0.8}],
                         "sfx": [{"file": "sfx-shot.wav", "at": 0.7}]},
            "scene3d": {"template": "user-plaga", "cast": [{"characterId": "ines", "objectId": "ines", "poseId": "aim"}],
                        "objects": [
                            {"objectId": "e1", "file": "escolta.glb", "add": True, "position": [-2, 0, 1.4], "scale": 1.8,
                             "clips": [{"clip": {"index": 0, "name": "Aim"}, "start": 0}], "grounded": True},
                            {"objectId": "f1", "file": "fusil.glb", "add": True, "hold": RIFLE_HOLD, "scale": 0.16},
                            {"objectId": "d0", "file": "demonio.glb", "add": True, "position": [3, 4, -5],
                             "motion": {"to": [4, 5, -8], "easing": "smooth"}}],
                        "renderLook": "toon", "toon": {"steps": 2}, "quality": "final"}}


def series():
    episode = {"id": "ep1", "shots": [shot()]}
    return {"id": "mp", "spokenLanguage": "Español", "characters": [], "locations": [{"id": "madridnoche"}],
            "soundDesign": {"stinger": {"file": "sting.wav", "volume": 0.5}}, "episodesById": {"ep1": episode}}


def slot(object_id, **fields):
    return {"id": object_id, "slot": "prop", "media": "model3d", "sourceUrl": f"/api/v1/file/{object_id}.glb?workspace=mp",
            "position": [0, 0, 0], "rotationY": 0, "scale": 1, "clip": None, **fields}


class World3D:
    """The in-process tools the editor routes call."""

    def __init__(self):
        self.calls, self.saved = [], []

    def __call__(self, tool, arguments):
        self.calls.append((tool, copy.deepcopy(arguments)))
        data = arguments.get("input") or {}
        if tool == "world3d.scene.instantiate":
            return {"result": {"scene": {"sceneId": "w3d-1", "revision": 1, "document": {"slots": [slot("ines")]}}}}
        if tool == "world3d.scene.patch":
            document = {"duration": data["duration"], "slots": [slot("ines"), *(slot(item["object_id"]) for item in data.get("bindings") or [])],
                        "sfx": data.get("screenFx") or [], "soundtrack": data.get("soundtrack") or []}
            return {"result": {"scene": {"sceneId": "w3d-1", "revision": 2, "document": document}}}
        if tool == "scenes.document.save":
            self.saved.append(data)
            return {"result": {"name": f"{data['name']}-0a1b2c3d4e.world3d.scene.json"}}
        raise AssertionError(tool)


def test_the_editor_opens_the_shots_scene_with_its_length_look_sound_effects_and_objects():
    tools = World3D()
    project = series()
    opened = editor_scene(tools, "mp", None, project, project["episodesById"]["ep1"], project["episodesById"]["ep1"]["shots"][0])
    assert [name for name, _ in tools.calls] == ["world3d.scene.instantiate", "world3d.scene.patch"]
    assert tools.calls[0][1]["input"]["template_id"] == "user-plaga"
    patch = tools.calls[1][1]["input"]
    assert patch["duration"] == 5.0 and patch["retime"] is True and patch["renderLook"] == "toon"
    assert [item["object_id"] for item in patch["bindings"]] == ["e1", "f1", "d0"] and patch["bindings"][1]["hold"] == RIFLE_HOLD
    assert patch["screenFx"][0]["id"] == "shot-fx-0" and patch["screenFx"][0]["start"] == 1.0
    assert patch["soundtrack"] == [{"id": "scene-stinger", "audio": "/api/v1/file/sting.wav?workspace=mp", "start": 0.0, "gain": 0.5}]
    assert "voiceOver" not in patch, "nobody speaks in the editor's copy: the lines are the render's"
    assert opened["sceneId"] == "w3d-1" and opened["source"] == {"template": "user-plaga"} and len(opened["document"]["slots"]) == 4
    again = World3D()
    editor_scene(again, "mp", None, project, project["episodesById"]["ep1"], project["episodesById"]["ep1"]["shots"][0])
    assert again.calls[0][1]["intent_id"] == tools.calls[0][1]["intent_id"], "the same shot asks with the same intents"


def test_the_editor_scene_carries_the_shots_stop_motion_and_a_new_one_is_another_scene():
    project = series()
    plain, held = World3D(), World3D()
    editor_scene(plain, "mp", None, project, project["episodesById"]["ep1"], project["episodesById"]["ep1"]["shots"][0])
    stepped = shot()
    stepped["layout2d"].update(motionStep=2, stopMotionJitter=0.5)
    editor_scene(held, "mp", None, project, project["episodesById"]["ep1"], stepped)
    patch = held.calls[1][1]["input"]
    assert (patch["motionStep"], patch["stopMotionJitter"]) == (2, 0.5) and "motionStep" not in plain.calls[1][1]["input"]
    assert held.calls[0][1]["intent_id"] != plain.calls[0][1]["intent_id"], "a changed stop-motion asks with new intents"


def edited_document():
    return {"duration": 5.0, "renderLook": "toon", "toon": {"steps": 3},
            "slots": [slot("ines"), slot("e1", position=[-1.0, 0, 2.0], rotationY=2.4, scale=1.9, grounded=True,
                                         clips=[{"clip": {"index": 1, "name": "Fire"}, "start": 0.5}]),
                      slot("f1", hold={**RIFLE_HOLD, "hand": "left"}, scale=0.18),
                      slot("crate", sourceUrl="/api/v1/file/crate%20big.glb?workspace=mp", position=[1, 0, 1])],
            "sfx": [{"id": "shot-fx-0", "kind": "shockwave", "start": 1, "end": 1.8}, {"id": "tpl-dust", "kind": "dust", "start": 0, "end": 5}],
            "soundtrack": [{"id": "scene-stinger", "audio": "/x.wav"}, {"id": "tpl-wind", "audio": "/w.wav"}]}


def test_the_edited_scene_becomes_the_shots_scene_and_its_objects_take_the_editors_values():
    tools = World3D()
    saved = from_editor(tools, "mp", "mp", "ep1", shot(), edited_document())
    assert saved["file"] == "mp-ep1-e1s115-plan-0a1b2c3d4e.world3d.scene.json" and saved["removedObjects"] == ["d0"]
    scene3d = saved["scene3d"]
    assert scene3d["scene"] == saved["file"] and "template" not in scene3d
    assert scene3d["cast"] == [{"characterId": "ines", "objectId": "ines", "poseId": "aim"}] and scene3d["quality"] == "final"
    escort, rifle = scene3d["objects"]
    assert escort["position"] == [-1.0, 0, 2.0] and escort["rotationY"] == 2.4 and escort["scale"] == 1.9
    assert escort["clips"][0]["clip"] == {"index": 1, "name": "Fire"} and escort["file"] == "e1.glb" and escort["add"] is True
    assert rifle["hold"]["hand"] == "left" and rifle["scale"] == 0.18
    assert scene3d["renderLook"] == "toon" and scene3d["toon"]["steps"] == 3
    stored = tools.saved[0]["document"]
    assert [cue["id"] for cue in stored["sfx"]] == ["tpl-dust"] and [track["id"] for track in stored["soundtrack"]] == ["tpl-wind"]
    assert any(item["id"] == "crate" for item in stored["slots"]), "an object added in the editor stays in the scene file"


def test_a_look_taken_off_in_the_editor_is_none_and_a_missing_speaker_object_is_refused():
    document = edited_document()
    document.pop("renderLook")
    plan, _removed = plan_from_editor(shot(), document)
    assert plan["renderLook"] == "none"
    document["slots"] = [item for item in document["slots"] if item["id"] != "ines"]
    with pytest.raises(Scene3DEditorError, match="ines speaks through object ines"):
        plan_from_editor(shot(), document)
    with pytest.raises(Scene3DEditorError) as flat:
        plan_from_editor({**shot(), "productionMethod": "animation_2d"}, edited_document())
    assert flat.value.code == "not_3d"
    with pytest.raises(Scene3DEditorError, match="no objects"):
        plan_from_editor(shot(), {"slots": []})
    assert workspace_file("/api/v1/file/sub/a%20b.glb?workspace=mp") == "sub/a b.glb" and workspace_file("blob:x") is None


def test_the_routes_open_and_save_a_3d_shots_scene():
    tools, project = World3D(), series()
    app = FastAPI()
    app.include_router(create_series_shot_inspector_router(voices=None, read_library=lambda _ws: {"seriesById": {"mp": project}},
                                                           workspace_dir=lambda _ws: "/nowhere", call=tools, bind_loop=lambda _loop: None))
    client = TestClient(app)
    opened = client.post("/api/v1/series/mp/episodes/ep1/shots/116/scene3d/editor", json={"workspace": "mp"})
    assert opened.status_code == 200, opened.text
    assert opened.json()["shotId"] == "e1s115" and opened.json()["document"]["duration"] == 5.0
    saved = client.post("/api/v1/series/mp/episodes/ep1/shots/e1s115/scene3d/from-editor", json={"workspace": "mp", "document": edited_document()})
    assert saved.status_code == 200 and saved.json()["scene3d"]["scene"].endswith(".world3d.scene.json")
    refused = client.post("/api/v1/series/mp/episodes/ep1/shots/e1s115/scene3d/from-editor", json={"workspace": "mp", "document": {"slots": []}})
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "invalid_document"
    assert client.post("/api/v1/series/mp/episodes/ep1/shots/9/scene3d/editor", json={"workspace": "mp"}).status_code == 404


def test_the_pickers_list_the_workspace_files_a_shot_can_name(tmp_path):
    from routers.series_shot_inspector import shot_files
    for name in ("mp-sfx-trueno.wav", "ln-ep1-b0-abc.wav", "ln-ep1-b0-abc.room-hall-v2.wav", ".hidden.wav", "prop-hat.png",
                 "mp3d-fusil.glb", "notes.txt", "speech-raw0.wav"):
        (tmp_path / name).write_bytes(b"x")
    assert shot_files(str(tmp_path), "audio") == ["mp-sfx-trueno.wav"]
    assert shot_files(str(tmp_path), "image") == ["prop-hat.png"] and shot_files(str(tmp_path), "model") == ["mp3d-fusil.glb"]
    assert shot_files(str(tmp_path / "missing"), "video") == []
    app = FastAPI()
    app.include_router(create_series_shot_inspector_router(voices=None, read_library=lambda _ws: {}, workspace_dir=lambda _ws: str(tmp_path),
                                                           call=lambda *_a: {}, bind_loop=lambda _loop: None))
    client = TestClient(app)
    assert client.get("/api/v1/series/mp/shot-files", params={"workspace": "mp", "kind": "model"}).json()["files"] == ["mp3d-fusil.glb"]
    assert client.get("/api/v1/series/mp/shot-files", params={"workspace": "mp", "kind": "text"}).status_code == 422
