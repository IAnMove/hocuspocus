"""Small Video 2D edits return a document and warnings without saving."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.video2d_edit import create_video2d_edit_router
from routers.wangp_mcp import create_wangp_mcp_router
from services.video2d_edit import Video2dEditError, command_catalog, command_handlers, edit


def _layer(layer_id, z=0):
    return {
        "id": layer_id, "name": layer_id, "type": "image", "source": f"/examples/{layer_id}.png",
        "visible": True, "z": z,
        "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
        "animation": {"start": {"x": 50, "y": 50, "scale": 1}, "end": {"x": 50, "y": 50, "scale": 1}, "duration": 8, "curve": "linear", "spin": False},
    }


def _document():
    return {"version": 1, "name": "Plano", "width": 1280, "height": 720, "fps": 30, "duration": 8, "layers": [_layer("a", 0), _layer("b", 10), _layer("c", 20)]}


def _edit(operations, document=None):
    return edit({"version": 1, "input": {"document": _document() if document is None else document, "operations": operations, "full": True}})


def _result(operations, document=None):
    body = _edit(operations, document)
    assert body["result"]["saved"] is False
    return body["result"]


def test_add_layer_replaces_existing_id_and_keeps_order():
    original = _document()
    snapshot = json.loads(json.dumps(original))
    result = _result([{"op": "add_layer", "id": "b", "source": "/examples/plate.png", "preset": "camera-push-in"}])
    document = result["document"]
    assert [layer["id"] for layer in document["layers"]] == ["a", "b", "c"]
    replaced = document["layers"][1]
    assert replaced["source"] == "/examples/plate.png"
    assert replaced["z"] == 10
    assert replaced["animation"]["end"]["scale"] == 1.55
    assert replaced["animation"]["curve"] == "ease"
    assert replaced["animation"]["duration"] == 6
    assert result["warnings"] == []
    assert original == snapshot


def test_cover_is_stored_without_rewriting_motion():
    added = _result([{"op": "add_layer", "id": "plate", "source": "/examples/plate.png", "cover": True}])
    plate = next(item for item in added["document"]["layers"] if item["id"] == "plate")
    assert plate["cover"] is True
    assert plate["animation"]["start"]["scale"] == 1
    assert plate["transform"]["x"] == 50
    updated = _result([{
        "op": "update_layer",
        "id": "a",
        "patch": {"cover": True, "animation": {"end": {"x": 12, "y": 88, "scale": 0.45}}},
    }])
    layer = updated["document"]["layers"][0]
    assert layer["cover"] is True
    assert layer["animation"]["end"] == {"x": 12, "y": 88, "scale": 0.45}
    assert layer["animation"]["start"]["x"] == 50
    cleared = _result([{"op": "update_layer", "id": "a", "patch": {"cover": False}}])
    assert cleared["document"]["layers"][0]["cover"] is False
    untouched = _result([{"op": "update_layer", "id": "b", "patch": {"name": "plate"}}])["document"]["layers"][1]
    assert "cover" not in untouched
    with pytest.raises(Video2dEditError) as error:
        _edit([{"op": "add_layer", "id": "bad", "source": "/examples/bad.png", "cover": "yes"}])
    assert error.value.code == "invalid_input"


def test_update_layer_focus_pins_a_frame_point_without_moving_the_anchor():
    result = _result([{
        "op": "update_layer",
        "id": "a",
        "patch": {
            "focus": {"x": 0, "y": 100},
            "animation": {"end": {"x": 50, "y": 50, "scale": 4}},
        },
    }])
    layer = result["document"]["layers"][0]
    assert layer["focus"] == {"x": 0, "y": 100}
    assert layer["animation"]["end"]["x"] == 50
    assert layer["animation"]["end"]["scale"] == 4
    untouched = _result([{"op": "update_layer", "id": "b", "patch": {"name": "plate"}}])["document"]["layers"][1]
    assert "focus" not in untouched
    with pytest.raises(Video2dEditError) as error:
        _edit([{"op": "update_layer", "id": "a", "patch": {"focus": {"x": 140, "y": 50}}}])
    assert error.value.code == "invalid_input"


def test_remove_layer():
    document = _result([{"op": "remove_layer", "id": "b"}])["document"]
    assert [layer["id"] for layer in document["layers"]] == ["a", "c"]
    with pytest.raises(Video2dEditError) as error:
        _edit([{"op": "remove_layer", "id": "missing"}])
    assert error.value.code == "not_found"


def test_reorder_layers():
    document = _result([{"op": "reorder", "ids": ["c", "a", "b"]}])["document"]
    assert [layer["id"] for layer in document["layers"]] == ["c", "a", "b"]
    assert [layer["z"] for layer in document["layers"]] == [0, 10, 20]
    with pytest.raises(Video2dEditError) as error:
        _edit([{"op": "reorder", "ids": ["a", "b"]}])
    assert error.value.code == "invalid_reorder"


def test_update_text_after_shorter_duration_keeps_unrelated_patches():
    result = _result([
        {"op": "add_title", "template": "title-card", "fields": {"title": "Uno"}, "start": 0, "duration": 8},
        {"op": "set_duration", "duration": 3},
        {"op": "update_text", "id": "title", "patch": {"text": "Dos"}},
    ])
    cue = result["document"]["texts"][0]
    assert cue["text"] == "Dos"
    assert cue["start"] == 0
    assert cue["end"] == 8
    assert result["warnings"][0]["code"] == "content_after_duration"
    with pytest.raises(Video2dEditError) as error:
        _edit([
            {"op": "add_title", "template": "title-card", "fields": {"title": "Uno"}, "start": 0, "duration": 3},
            {"op": "update_text", "id": "title", "patch": {"end": 9}},
        ])
    assert error.value.code == "timing_exceeds_duration"


def test_set_finish_preset():
    finish = _result([{"op": "set_finish", "preset": "warmCinema"}])["document"]["finish"]
    assert finish["letterbox"] == {"ratio": 2.39, "color": "#000000"}
    assert finish["grade"]["temperature"] == 0.25
    assert finish["vignette"]["amount"] == 0.35
    assert "riso" not in finish


def test_riso_press_preset_is_opt_in():
    old = _result([{"op": "set_finish", "preset": "oldDoc"}])["document"]["finish"]
    assert "riso" not in old
    assert old["texture"]["kind"] == "scratches"
    riso = _result([{"op": "set_finish", "preset": "risoPress"}])["document"]["finish"]
    assert "grade" not in riso
    assert len(riso["riso"]["inks"]) == 4
    assert riso["riso"]["inks"][0] == "#FF6A2B"


@pytest.mark.parametrize("duration", [0, 601, -1, True])
def test_duration_limit(duration):
    with pytest.raises(Video2dEditError) as error:
        _edit([{"op": "set_duration", "duration": duration}])
    assert error.value.code == "invalid_duration"


def test_duration_accepts_the_upper_bound():
    assert _result([{"op": "set_duration", "duration": 600}])["document"]["duration"] == 600


def test_unknown_operation():
    with pytest.raises(Video2dEditError) as error:
        _edit([{"op": "explode"}])
    assert error.value.code == "invalid_operation"


def test_rejects_more_than_32_operations():
    with pytest.raises(Video2dEditError) as error:
        _edit([{"op": "set_duration", "duration": 8}] * 33)
    assert error.value.code == "too_many_operations"


def test_add_title_uses_template_defaults_and_replaces_by_id():
    first = _result([{"op": "add_title", "template": "lower-third-date", "start": 0, "duration": 3}])["document"]["texts"]
    assert [cue["id"] for cue in first] == ["date", "caption"]
    assert first[0]["text"] == "1991"
    assert first[0]["y"] == 70
    assert first[0]["template"] == "lower-third-date"
    assert first[1]["text"] == "A city keeps its name"
    second = _result([
        {"op": "add_title", "template": "title-card", "fields": {"title": "Uno", "subtitle": "Dos"}, "start": 1, "duration": 2},
        {"op": "add_title", "template": "title-card", "fields": {"title": "Dos", "subtitle": "Dos"}, "start": 1, "duration": 2},
    ])["document"]["texts"]
    assert [cue["id"] for cue in second] == ["title", "sub"]
    assert second[0]["text"] == "Dos"


def test_ransom_dymo_and_card_titles():
    ransom = _result([{"op": "add_title", "template": "ransom", "start": 0.4, "duration": 3.2}])["document"]["texts"]
    assert [cue["text"] for cue in ransom] == ["THE", "BIRD", "IS", "FREED"]
    assert [cue["box"]["kind"] for cue in ransom] == ["paper", "paper", "paper", "paper"]
    assert [cue["rotation"] for cue in ransom] == [-3, 2, -1, 4]
    assert [cue["x"] for cue in ransom] == [23, 41, 59, 77]
    assert {cue["y"] for cue in ransom} == {48}
    tape = _result([{"op": "add_title", "template": "dymo", "start": 0, "duration": 3}])["document"]["texts"][0]
    assert tape["text"] == "KEEP THE LINE"
    assert tape["box"]["color"] == "#141210"
    assert tape["color"] == "#f4efe6"
    assert tape["y"] == 78
    dark = _result([{
        "op": "add_title", "template": "dymo",
        "fields": {"line": "KEEP THE LINE", "background": "dark"}, "start": 0, "duration": 3,
    }])["document"]["texts"][0]
    assert dark["color"] == "#141210"
    assert dark["box"]["color"] == "#f2b705"
    assert dark["rotation"] == tape["rotation"]
    card = _result([{"op": "add_title", "template": "card", "start": 0, "duration": 3}])["document"]["texts"][0]
    assert card["text"] == "Musktopia"
    assert card["box"]["kind"] == "card"
    assert card["rotation"] == -1
    assert card["y"] == 46
    kept = _result([
        {"op": "add_title", "template": "dymo", "start": 0, "duration": 3},
        {"op": "update_text", "id": "tape", "patch": {"box": tape["box"]}},
        {"op": "add_title", "template": "card", "start": 0, "duration": 3},
        {"op": "update_text", "id": "card", "patch": {"box": card["box"]}},
    ])["document"]["texts"]
    assert [cue["box"]["kind"] for cue in kept] == ["tape", "card"]


def test_set_lyrics_stores_lines_without_fetching():
    lyrics = _result([{"op": "set_lyrics", "lyrics": {"lines": [{"start": 0, "end": 2, "text": "Hola mundo"}]}}])["document"]["lyrics"]
    assert lyrics["mode"] == "karaoke"
    assert lyrics["lines"][0]["words"][0]["text"] == "Hola"
    assert lyrics["lines"][0]["words"][1]["text"] == "mundo"
    assert "source" not in lyrics


def test_set_rhythm_stores_the_object_without_analysis():
    rhythm = _result([{"op": "set_rhythm", "rhythm": {"bpm": 120, "beats": [0.5, 1.0]}}])["document"]["rhythm"]
    assert rhythm == {"bpm": 120, "beats": [0.5, 1.0]}
    with pytest.raises(Video2dEditError) as error:
        _edit([{"op": "set_rhythm", "rhythm": {"bpm": 10, "beats": [0], "filename": "song.wav"}}])
    assert error.value.code == "invalid_rhythm"


def test_add_audio_track_replaces_by_id_and_set_format_rejects_odd_sizes():
    tracks = _result([
        {"op": "add_audio_track", "track": {"id": "bed", "filename": "bed.mp3", "kind": "music", "startTime": 0, "volume": 0.4}},
        {"op": "add_audio_track", "track": {"id": "bed", "filename": "bed.mp3", "kind": "music", "startTime": 1, "volume": 0.8}},
    ])
    assert tracks["document"]["audioTracks"] == [{
        "id": "bed", "filename": "bed.mp3", "name": "bed", "kind": "music", "startTime": 1, "volume": 0.8,
    }]
    assert tracks["warnings"][0]["code"] == "audio_not_loaded"
    document = _result([{"op": "set_format", "width": 1080, "height": 1920}])["document"]
    assert document["width"] == 1080 and document["height"] == 1920
    with pytest.raises(Video2dEditError) as error:
        _edit([{"op": "set_format", "width": 1281, "height": 720}])
    assert error.value.code == "invalid_format"


def test_raw_finish_clamps_like_the_ui_parser_and_preset_duration_is_limited():
    result = _result([
        {"op": "add_layer", "id": "bg", "source": "/examples/bg.png", "preset": "camera-handheld"},
        {"op": "set_finish", "finish": {"grade": {"exposure": 4}, "texture": {"kind": "nope", "amount": 1}}},
    ], {"version": 1, "name": "P", "width": 1280, "height": 720, "fps": 30, "duration": 4, "layers": []})
    assert result["document"]["finish"]["grade"]["exposure"] == 1
    assert "texture" not in result["document"]["finish"]
    assert result["document"]["layers"][0]["animation"]["duration"] == 4
    assert result["document"]["layers"][0]["animation"]["shake"]["seed"] == 1.7
    assert result["warnings"][0]["code"] == "preset_duration_clamped"


def test_camera_and_finish_ids_come_from_the_shared_catalogs():
    motion = json.loads((Path(__file__).resolve().parents[1] / "app/shared/motion_presets.json").read_text(encoding="utf-8"))
    finish = json.loads((Path(__file__).resolve().parents[1] / "app/shared/finish_presets.json").read_text(encoding="utf-8"))
    cameras = [entry["id"] for entry in motion["entries"] if entry["kind"] == "camera"]
    description = command_catalog()[0]["description"]
    schema = command_catalog()[0]["inputSchema"]["properties"]["input"]["properties"]["operations"]["items"]["oneOf"]
    layer = next(item for item in schema if item["properties"]["op"]["const"] == "add_layer")
    finish_schema = next(item for item in schema if item["properties"]["op"]["const"] == "set_finish")
    assert layer["properties"]["preset"]["enum"] == cameras
    assert finish_schema["properties"]["preset"]["enum"] == [entry["id"] for entry in finish["entries"]]
    assert "M1" not in description and "hardcoded" not in description.lower()
    with pytest.raises(Video2dEditError) as error:
        _edit([{"op": "add_layer", "id": "ship", "source": "/examples/ship.png", "preset": "zoom-in"}])
    assert error.value.code == "unknown_preset"
    assert "motion_presets.json" in str(error.value)


def test_http_and_mcp_return_the_same_document(tmp_path):
    app = FastAPI()
    app.include_router(create_video2d_edit_router())
    app.include_router(create_wangp_mcp_router(
        handlers=command_handlers(), token_getter=lambda: "test-token",
        journal_path=str(tmp_path / "journal.db"), command_operations=command_catalog(),
    ))
    client = TestClient(app)
    command = {"version": 1, "input": {"document": _document(), "operations": [{"op": "set_finish", "preset": "paperComic"}]}}
    http = client.post("/api/v1/scenes/video2d/edit", json=command)
    assert http.status_code == 200
    mcp = client.post("/api/v1/wangp/mcp", headers={"Authorization": "Bearer test-token"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "scenes.video2d.edit", "arguments": command},
    })
    assert mcp.status_code == 200
    assert mcp.json()["result"]["isError"] is False
    assert mcp.json()["result"]["structuredContent"] == http.json()
    unknown = client.post("/api/v1/scenes/video2d/edit", json={"version": 1, "input": {"document": _document(), "operations": [{"op": "nope"}]}})
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "invalid_operation"
    assert command_catalog()[0]["name"] == "scenes.video2d.edit"
    assert command_catalog()[0]["mutation"] is False
