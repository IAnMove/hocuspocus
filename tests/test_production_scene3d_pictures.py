"""A picture cast where a template authored a 3D model stands as a grounded cutout on every path: a pack card, a card
played in a world, a room, a stage and a Series binding (``world3d.scene.patch``)."""
from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from services.production_scene3d import compile_document
from services.world3d_scenes import PICTURE_SCALE, compile_template_document, patch_scene
from services.world3d_stage_documents import room_of

ROOT = Path(__file__).resolve().parents[1]
NODE = pytest.mark.skipif(not (ROOT / "ui/node_modules/tsx/dist/loader.mjs").is_file(),
                          reason="UI dependencies not installed in Python-only CI")
PICTURE = "/api/v1/file/ines.png?workspace=t"
PACKS = ("transition-", "speed-", "title-", "dialogue-", "reaction-", "group-")
CARDS = [card for card in json.loads((ROOT / "app/shared/world3d_templates.json").read_text(encoding="utf-8"))["catalog"]
         if card["id"].startswith(PACKS)]


def people(card):
    """The objects of a card that stand for a person: the subjects and the numbered extras of a group or a crowd."""
    return {item["id"]: item["media"] for item in card["required"]
            if item["role"] in ("subject_1", "subject_2") or item["id"].split("_")[0] in ("person", "crowd")}


def compile_card(card, **extra):
    cast = {object_id: PICTURE for object_id in people(card)}
    return compile_document({"key": card["id"], "kind": "scene3d", "scene3d": {"template": card["id"], "cast": cast, **extra}},
                            card["duration"])


def assert_standing_pictures(document, ids, where):
    """``ids`` maps each cast object to the media its card authored: a model's place gets a grounded stand-in, a
    cutout's place keeps the card's own look (the plain-colour cards draw their cutouts unlit, with no floor)."""
    slots = {slot["id"]: slot for slot in document["slots"]}
    for object_id, authored in ids.items():
        slot = slots[object_id]
        assert (slot["media"], slot["surface"], slot["sourceUrl"]) == ("image", "cutout", PICTURE), f"{where} {object_id}"
        if authored == "model3d":
            assert slot["imageLook"].get("grounded") is True, f"{where} {object_id}: stands on its feet"
        assert 1.6 <= 2 * slot["scale"] <= 2.0, f"{where} {object_id}: a {2 * slot['scale']:.2f} m picture"
        motion = slot.get("motion") or {}
        assert not motion.get("faceTravel"), f"{where} {object_id}: a flat picture never turns edge-on along its path"
        if motion and motion["to"][0] != slot["position"][0] and motion.get("turnTo") is None:
            assert slot["rotationY"] in (0, math.pi), f"{where} {object_id}: a travelling picture faces the camera"


def test_every_pack_card_has_people_to_cast():
    assert len(CARDS) == 32
    assert all(people(card) for card in CARDS)


@NODE
@pytest.mark.parametrize("world", [None, "atmos-rooftop-night-wide"])
def test_a_picture_cast_into_every_pack_card_compiles_to_a_standing_cutout(world):
    extra = {"world": world} if world else {}
    with ThreadPoolExecutor(8) as pool:
        documents = list(pool.map(lambda card: compile_card(card, **extra), CARDS))
    for card, document in zip(CARDS, documents):
        assert_standing_pictures(document, people(card), f"{card['id']} in {world or 'its own place'}")
        if world:
            assert document["dressing"] == "atmos-rooftop-night"


@NODE
def test_the_pilot_reaction_on_the_rooftop_stands_the_picture_where_the_model_stood():
    document = compile_document({"key": "reaction", "kind": "scene3d", "scene3d": {
        "template": "reaction-push-face", "world": "atmos-rooftop-night-wide", "light": "candle",
        "cast": {"subject_1": {"source": PICTURE, "grounded": True}}}}, 5)
    subject = next(slot for slot in document["slots"] if slot["id"] == "subject_1")
    assert (subject["surface"], subject["imageLook"], subject["scale"]) == ("cutout", {"grounded": True}, PICTURE_SCALE)
    assert subject["position"] == [0, 0, 0] and subject["rotationY"] == 0.12
    assert document["camera"]["framing"]["targetSlot"] == "subject_1"
    told = compile_document({"key": "reaction", "kind": "scene3d", "scene3d": {"template": "reaction-push-face", "cast": {
        "subject_1": {"source": PICTURE, "scale": 1.1, "grounded": False, "imageLook": {"unlit": True}}}}}, 5)
    subject = next(slot for slot in told["slots"] if slot["id"] == "subject_1")
    assert (subject["scale"], subject["imageLook"]) == (1.1, {"unlit": True}), "what the cast says wins"
    single = compile_document({"key": "reaction", "kind": "scene3d", "scene3d": {"template": "reaction-push-face", "subject": PICTURE}}, 5)
    assert next(slot for slot in single["slots"] if slot["id"] == "subject_1")["surface"] == "cutout", "scene3d.subject too"


@NODE
def test_a_running_picture_faces_the_camera_and_a_seated_one_turns_toward_it():
    dash = compile_document({"key": "dash", "kind": "scene3d", "scene3d": {"template": "speed-side-dash", "cast": {"subject_1": PICTURE}}}, 5)
    runner = next(slot for slot in dash["slots"] if slot["slot"] == "subject_1")
    assert runner["rotationY"] == 0 and runner["motion"]["to"] == [5, 0, 0] and not runner["motion"].get("faceTravel")
    table = compile_document({"key": "talk", "kind": "scene3d", "scene3d": {"template": "dialogue-table",
                                                                           "cast": {"subject_1": PICTURE, "subject_2": PICTURE}}}, 6)
    seats = {slot["id"]: slot["rotationY"] for slot in table["slots"]}
    assert 0.5 < seats["subject_1"] < 1.25 and -1.25 <= seats["subject_2"] < -0.5, "still turned toward each other"
    kept = compile_document({"key": "talk", "kind": "scene3d", "scene3d": {"template": "dialogue-table", "cast": {
        "subject_1": {"source": PICTURE, "rotationY": 1.5}, "subject_2": PICTURE}}}, 6)
    assert next(slot for slot in kept["slots"] if slot["id"] == "subject_1")["rotationY"] == 1.5, "a turn the cast gives is kept"


@NODE
def test_a_picture_in_a_room_and_on_a_stage_is_a_cutout_as_tall_as_the_model():
    room = compile_document({"key": "ots", "kind": "scene3d", "scene3d": {
        "template": "dialogue-ots-a", "background": {"room": room_of("stage-cocina", camera="ots_a")}, "roomCamera": "ots_a",
        "cast": {"subject_1": PICTURE, "subject_2": PICTURE}}}, 6)
    assert_standing_pictures(room, {"subject_1": "model3d", "subject_2": "model3d"}, "dialogue-ots-a in a room")
    assert room["camera"]["family"] == "fixed" and room["room"]["camera"] == "ots_a"
    stage = compile_document({"key": "talk", "kind": "scene3d", "scene3d": {
        "template": "stage-cocina", "cast": {"subject_1": PICTURE, "subject_2": {"source": PICTURE, "scale": 0.9}}}}, 6)
    assert_standing_pictures(stage, {"subject_1": "model3d", "subject_2": "model3d"}, "stage-cocina")
    scales = {slot["id"]: slot["scale"] for slot in stage["slots"]}
    assert scales == {"subject_1": PICTURE_SCALE, "subject_2": 0.9}


def _scene(tmp_path, slots, base=None):
    folder = tmp_path / "studio" / "world3d-edits"
    folder.mkdir(parents=True)
    document = {**(base or {"templateId": "two-shot"}), "duration": 6, "slots": slots,
                "camera": {"family": "fixed", "fov": 40, "eye": [0, 1.5, 5], "look": [0, 1.2, 0]}}
    (folder / "w3d-00000000beef.json").write_text(json.dumps({"revision": 1, "templateId": "two-shot", "document": document,
                                                                "warnings": []}), encoding="utf-8")
    return lambda name: str(tmp_path / name)


def _model(object_id, **patch):
    return {"id": object_id, "slot": "subject_1", "media": "model3d", "sourceUrl": "", "clip": None, "position": [0, 0, 0],
            "rotationY": 0.4, "scale": 1, **patch}


def test_a_series_binding_of_a_picture_to_a_model_object_makes_a_standing_cutout(tmp_path):
    workspace_dir = _scene(tmp_path, [
        _model("hero"), _model("runner", position=[-5, 0, 0], rotationY=-1.5708, motion={"to": [-9, 0, 0], "faceTravel": True}),
        _model("listener", scale=0.85, surface="cutout"), _model("told"), _model("robot")])
    out = patch_scene("studio", "w3d-00000000beef", workspace_dir, {"bindings": [
        {"object_id": "hero", "media": "image", "source_url": PICTURE},
        {"object_id": "runner", "media": "image", "source_url": PICTURE},
        {"object_id": "listener", "media": "image", "source_url": PICTURE, "imageLook": {"grounded": True}},
        {"object_id": "told", "media": "image", "source_url": PICTURE, "scale": 1.2, "grounded": False, "imageLook": {"unlit": True}},
        {"object_id": "robot", "source_url": "/api/v1/file/robot.glb?workspace=t"}]}, 1)["document"]
    slots = {slot["id"]: slot for slot in out["slots"]}
    hero = slots["hero"]
    assert (hero["media"], hero["surface"], hero["imageLook"], hero["scale"], hero["rotationY"]) == ("image", "cutout", {"grounded": True}, 0.85, 0.4)
    runner = slots["runner"]
    assert runner["rotationY"] == math.pi and runner["motion"] == {"to": [-9, 0, 0]}, "runs left facing the camera, mirrored"
    assert slots["listener"]["scale"] == 0.85, "a Series room marker already sized as a cutout keeps its size"
    told = slots["told"]
    assert (told["scale"], told["imageLook"]) == (1.2, {"unlit": True})
    assert slots["robot"]["media"] == "model3d" and "surface" not in slots["robot"], "a model stays a model"
    again = patch_scene("studio", "w3d-00000000beef", workspace_dir, {"bindings": [
        {"object_id": "hero", "media": "image", "source_url": "/api/v1/file/other.png?workspace=t"}]}, 2)["document"]
    assert next(slot for slot in again["slots"] if slot["id"] == "hero")["scale"] == 0.85, "rebinding a picture does not shrink it again"


@NODE
def test_a_series_picture_in_profile_turns_toward_the_camera_as_far_as_a_production_one(tmp_path):
    slots = [_model("side", rotationY=1.4), _model("near", position=[1, 0, 0]), _model("given", position=[-1, 0, 0], rotationY=1.4),
             _model("robot", rotationY=1.4)]
    workspace_dir = _scene(tmp_path, slots, compile_template_document("two-shot"))
    out = patch_scene("studio", "w3d-00000000beef", workspace_dir, {"bindings": [
        {"object_id": "side", "media": "image", "source_url": PICTURE},
        {"object_id": "near", "media": "image", "source_url": PICTURE},
        {"object_id": "given", "media": "image", "source_url": PICTURE, "rotationY": 1.4},
        {"object_id": "robot", "source_url": "/api/v1/file/robot.glb?workspace=t"}]}, 1)
    turns = {slot["id"]: slot["rotationY"] for slot in out["document"]["slots"]}
    assert turns["side"] == pytest.approx(math.pi / 3, abs=1e-6), "a picture in profile turns to 60° from the camera"
    assert turns["near"] == 0.4, "one already within 60° keeps the model's turn"
    assert (turns["given"], turns["robot"]) == (1.4, 1.4), "a turn the binding gives and a model are kept"
    assert out["warnings"] == []


def test_a_picture_turn_the_tool_cannot_measure_keeps_the_binding_and_says_so(tmp_path, monkeypatch):
    from services import world3d_scenes

    def broken(command, payload, template_id=None):
        raise world3d_scenes.World3DSceneError("template_tool_failed", "invalid_world3d_document")

    monkeypatch.setattr(world3d_scenes, "_run_tool", broken)
    workspace_dir = _scene(tmp_path, [_model("side", rotationY=1.4)])
    out = patch_scene("studio", "w3d-00000000beef", workspace_dir, {"bindings": [
        {"object_id": "side", "media": "image", "source_url": PICTURE}]}, 1)
    side = out["document"]["slots"][0]
    assert (side["media"], side["surface"], side["rotationY"]) == ("image", "cutout", 1.4)
    assert out["warnings"] == ["picture_turn_skipped: invalid_world3d_document"]


@NODE
def test_a_long_stage_shot_keeps_its_room_dust_to_the_end():
    stage = compile_document({"key": "talk", "kind": "scene3d", "scene3d": {"template": "stage-cocina", "cast": {"subject_1": PICTURE}}}, 14)
    dust = [cue for cue in stage["worldSfx"] if cue["id"] == "room-dust"]
    assert stage["duration"] == 14 and [(cue["start"], cue["end"]) for cue in dust] == [(0, 14)]


@pytest.mark.parametrize("retime", [None, False, True])
def test_a_duration_patch_stretches_the_room_dust_over_the_new_length(tmp_path, retime):
    workspace_dir = _scene(tmp_path, [_model("hero")])
    record = tmp_path / "studio" / "world3d-edits" / "w3d-00000000beef.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["document"]["worldSfx"] = [{"id": "room-dust", "kind": "dust", "start": 0, "end": 6},
                                    {"id": "flash", "kind": "explosion", "start": 2, "end": 3}]
    record.write_text(json.dumps(data), encoding="utf-8")
    changes = {"duration": 14, **({} if retime is None else {"retime": retime})}
    cues = {cue["id"]: cue for cue in patch_scene("studio", "w3d-00000000beef", workspace_dir, changes, 1)["document"]["worldSfx"]}
    assert (cues["room-dust"]["start"], cues["room-dust"]["end"]) == (0, 14)
    assert cues["flash"]["end"] == (7.0 if retime else 3), "other cues keep the retime rule"
