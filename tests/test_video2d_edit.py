"""Small Video 2D edits return a document and warnings without saving."""
from __future__ import annotations

import json

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


def test_motion_preset_is_rejected_until_m1_json():
    with pytest.raises(Video2dEditError) as error:
        _edit([{"op": "add_layer", "id": "ship", "source": "/examples/ship.png", "preset": "zoom-in"}])
    assert error.value.code == "unknown_preset"


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
