"""A Character Kit cutout talks in Video 3D: pose, mouth per cue, blink and its line's audio."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.character_kit_library import write_character_kit_library
from services.world3d_scenes import _write, inspect_scene
from services.world3d_talk import TalkError, apply_talk, blink_times, kit_state, talk_block
from services.world3d_template_commands import command_catalog, execute_command


def asset(name, review="approved"):
    return {"id": name, "name": name, "source": f"/api/v1/file/kits/lola/{name}.png?workspace=studio", "reviewState": review,
            "width": 400, "height": 800}


def kit(**extra):
    return {"id": "lola", "name": "Lola", "style": "cutout", "base": asset("base"), "poses": {"wave": asset("wave", "pending")},
            "mouth": {"closed": asset("m-closed"), "wide": asset("m-wide"), "round": asset("m-round"), "small": asset("m-small", "rejected")},
            "eyes": {"blink": asset("blink")},
            "anchors": {"base": {"mouth": {"offsetX": 1, "offsetY": -19, "scale": 0.06, "rotation": 0},
                                 "mouthStates": {"round": {"offsetX": 1, "offsetY": -18, "scale": 0.07, "rotation": 0}},
                                 "eyes": {"offsetX": 0, "offsetY": -27, "scale": 0.1, "rotation": 0}}}, **extra}


LINES = [{"start": 1.0, "cues": [{"start": 0, "end": 0.2, "value": "D"}, {"start": 0.2, "end": 0.4, "value": "E"},
                                 {"start": 0.4, "end": 0.6, "value": "X"}, {"start": 0.6, "end": 0.5, "value": "D"}],
          "audio": "/api/v1/file/voices/lola-0.wav?workspace=studio"},
         {"start": 3.5, "cues": [{"start": 0, "end": 0.3, "value": "B"}]}]


def test_cues_become_the_kit_drawings_with_its_own_mapping_and_fallbacks():
    mouths = {"closed": "c", "wide": "w", "round": "r"}
    assert [kit_state(sound, None, mouths) for sound in ("D", "E", "X", "A", "C", "B")] == ["wide", "round", "closed", "closed", "wide", ""]
    assert kit_state("D", {"A": "round"}, mouths) == "round", "the kit's own mapping wins"


def test_the_talk_block_uses_approved_art_anchors_and_shifted_cues():
    talk = talk_block(kit(), LINES, duration=8)
    assert talk["base"].endswith("/base.png?workspace=studio")
    assert set(talk["mouths"]) == {"closed", "wide", "round"}, "rejected drawings stay out"
    assert talk["cues"] == [{"start": 1.0, "end": 1.2, "state": "wide"}, {"start": 1.2, "end": 1.4, "state": "round"},
                            {"start": 1.4, "end": 1.6, "state": "closed"}], "times move by the line start; no drawing for B"
    assert talk["rest"] == "closed" and talk["mouth"]["scale"] == 0.06 and talk["mouthAnchors"] == {"round": kit()["anchors"]["base"]["mouthStates"]["round"]}
    assert talk["blink"]["anchor"]["offsetY"] == -27 and talk["blinks"] == blink_times("lola", 8) and talk["blinks"][0] == 0.9
    assert all(2.6 <= b - a <= 4.6 for a, b in zip(talk["blinks"], talk["blinks"][1:]))
    assert "blink" not in talk_block(kit(), LINES, blink=False)
    with pytest.raises(TalkError) as pending:
        talk_block(kit(), LINES, pose="wave")
    assert pending.value.code == "pose_not_ready"
    with pytest.raises(TalkError) as silent:
        talk_block(kit(mouth={}), LINES)
    assert silent.value.code == "mouths_not_ready"


def test_applying_binds_the_screen_and_replaces_only_that_objects_tracks():
    document = {"duration": 6, "soundtrack": [{"id": "music", "audio": {"workspaceId": "studio", "filename": "m.mp3", "url": "/api/v1/file/m.mp3"},
                                               "start": 0, "offset": 0, "gain": 0.4},
                                              {"id": "talk-hero-7", "audio": {"workspaceId": "studio", "filename": "old.wav", "url": "/x"},
                                               "start": 0, "offset": 0, "gain": 1}],
                "slots": [{"id": "hero", "slot": "subject_1", "media": "image", "sourceUrl": "", "screen": {"poseSequence": [{}], "fit": "contain"}}]}
    slot = document["slots"][0]
    result = apply_talk(document, slot, kit(), LINES, workspace="studio")
    assert slot["sourceUrl"] == slot["screen"]["sourceUrl"] == result["talk"]["base"]
    assert slot["screen"]["media"] == "image" and slot["screen"]["fit"] == "contain" and "poseSequence" not in slot["screen"]
    assert slot["character"] == {"id": "lola", "name": "Lola"}
    assert [track["id"] for track in document["soundtrack"]] == ["music", "talk-hero-0"]
    assert document["soundtrack"][1]["audio"] == {"workspaceId": "studio", "filename": "lola-0.wav", "url": LINES[0]["audio"]}
    assert document["soundtrack"][1]["start"] == 1.0 and result["tracks"] == ["talk-hero-0"] and result["cues"] == 3
    with pytest.raises(TalkError) as model:
        apply_talk(document, {"id": "bot", "media": "model3d"}, kit(), LINES, workspace="studio")
    assert model.value.code == "not_a_cutout"
    with pytest.raises(TalkError):
        apply_talk(document, slot, kit(), [{"start": 0, "cues": [], "audio": "https://example.com/a.wav"}], workspace="studio")


def test_the_mcp_operation_talks_by_object_id_with_a_revision(tmp_path):
    root = lambda workspace: str(tmp_path / workspace)
    (tmp_path / "studio").mkdir()
    write_character_kit_library(root("studio"), {"version": 1, "activeId": "lola", "kits": {"lola": kit()}}, base_revision=0)
    _write("studio", "w3d-talk00000000", {"revision": 1, "templateId": "t", "warnings": [], "document": {
        "duration": 6, "camera": {}, "slots": [{"id": "hero", "slot": "subject_1", "media": "image", "sourceUrl": ""}]}}, root)
    assert "world3d.scene.talk" in {item["name"] for item in command_catalog() if item["mutation"]}
    arguments = {"version": 1, "intent_id": "talk-1", "input": {"workspace": "studio", "scene_id": "w3d-talk00000000", "base_revision": 1,
                                                                "object_id": "hero", "kit_id": "lola", "lines": LINES}}
    reply = execute_command("world3d.scene.talk", arguments, root)
    scene = reply["result"]["scene"]
    assert scene["revision"] == 2 and scene["talk"] == {"objectId": "hero", "cues": 3, "mouths": ["closed", "round", "wide"],
                                                        "blinks": 2, "tracks": ["talk-hero-0"]}
    stored = inspect_scene("studio", "w3d-talk00000000", root)
    assert stored["document"]["slots"][0]["screen"]["talk"]["cues"][0]["state"] == "wide"
    assert execute_command("world3d.scene.talk", arguments, root)["replayed"] is True
    with pytest.raises(HTTPException) as stale:
        execute_command("world3d.scene.talk", {**arguments, "intent_id": "talk-2"}, root)
    assert stale.value.status_code == 409
    with pytest.raises(HTTPException) as missing:
        execute_command("world3d.scene.talk", {**arguments, "intent_id": "talk-3",
                                               "input": {**arguments["input"], "base_revision": 2, "kit_id": "nobody"}}, root)
    assert missing.value.status_code == 404 and missing.value.detail["code"] == "unknown_kit"
