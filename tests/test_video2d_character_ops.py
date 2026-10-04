"""An agent mounts a talking Character Kit in a Video 2D scene without running the editor."""
import shutil

import pytest

from services import video2d_character_ops
from services.video2d_edit import Video2dEditError, edit
from services.video2d_compile import TSX

pytestmark = pytest.mark.skipif(shutil.which("node") is None or not TSX.is_file(), reason="node and ui/node_modules/tsx required")

STATES = ["closed", "small", "wide", "round", "pressed", "medium", "pucker", "bite", "tongue"]


def kit():
    asset = lambda aid, kind="overlay", **size: {"id": aid, "name": aid, "source": f"/api/v1/file/{aid}.png?workspace=cast", "kind": kind,
                                                 "alphaStatus": "transparent", "reviewState": "approved", **size}
    return {"version": 1, "id": "kevin", "name": "Kevin", "style": "cutout", "base": asset("base", "image", width=400, height=800), "poses": {},
            "mouth": {state: asset(f"m-{state}") for state in STATES}, "eyes": {"blink": asset("blink")}, "provenance": [],
            "mouthMapping": {"rest": "closed", "M": "pressed", "A": "wide", "E": "medium", "I": "small", "O": "round", "U": "pucker", "F": "bite", "L": "tongue"},
            "anchors": {"base": {"mouth": {"offsetX": 0, "offsetY": -9, "scale": 0.1, "rotation": 0},
                                 "eyes": {"offsetX": 0, "offsetY": -22, "scale": 0.2, "rotation": 0}}}}


def scene():
    background = {"id": "bg", "name": "bg", "type": "image", "source": "/api/v1/file/bg.png?workspace=cast", "visible": True, "locked": False,
                  "z": 0, "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
                  "animation": {"start": {"x": 50, "y": 50, "scale": 1}, "end": {"x": 50, "y": 50, "scale": 1}, "duration": 3, "curve": "linear"}}
    return {"version": 1, "name": "Garage", "width": 1920, "height": 1080, "fps": 24, "duration": 3, "layers": [background]}


def run(document, operations):
    return edit({"version": 1, "input": {"document": document, "operations": operations, "full": True}})["result"]


def test_mount_add_a_line_and_animate_through_scene_edit():
    video2d_character_ops.bind_kit_reader(lambda workspace, kit_id: kit() if (workspace, kit_id) == ("cast", "kevin") else None)
    result = run(scene(), [
        {"op": "mount_character", "workspace": "cast", "kit_id": "kevin", "x": 40, "framing": "medium"},
        {"op": "add_line", "kit_id": "kevin", "id": "l1", "text": "Hola, Gary.", "start": 0.3, "end": 3.5, "filename": "l1.wav",
         "cues": {"mouthCues": [{"start": 0, "end": 0.5, "value": "D"}, {"start": 0.5, "end": 1, "value": "B"}]}},
        {"op": "animate_talk"},
    ])
    document = result["document"]
    assert document["duration"] == 3.95
    assert len([layer for layer in document["layers"] if layer.get("characterKitRef", {}).get("id") == "kevin"]) == 11
    beat = document["dialogueBeats"][0]
    assert beat["confidence"] == "aligned-audio" and len(beat["mouthLayerIds"]) == 9
    assert document["audioTracks"][0]["filename"] == "l1.wav"
    without = run(document, [{"op": "add_line", "kit_id": "kevin", "id": "l2", "text": "Adiós.", "start": 4, "end": 5, "filename": "l2.wav"}])
    assert without["warnings"][-1]["code"] == "line_without_cues"


def test_unknown_kits_and_bad_framings_fail_with_a_code():
    video2d_character_ops.bind_kit_reader(lambda workspace, kit_id: None)
    with pytest.raises(Video2dEditError) as missing:
        run(scene(), [{"op": "mount_character", "workspace": "cast", "kit_id": "ghost", "x": 50, "framing": "two"}])
    assert missing.value.code == "character_not_found"
    with pytest.raises(Video2dEditError) as framing:
        run(scene(), [{"op": "mount_character", "workspace": "cast", "kit_id": "ghost", "x": 50, "framing": "aerial"}])
    assert framing.value.code == "invalid_input"
