"""Video 2D document schema and scenes.video2d.validate. No GPU and no scene write."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from services.scene2d_export import command_catalog as export_catalog
from services.scene2d_schema import document_schema
from services.scene2d_validate import OPERATION, command_catalog, command_handlers, normalize_document
from services.scene_documents import OPERATIONS as SAVE_OPERATIONS
from services.scene_documents import command_catalog as save_catalog

WORKSPACE = "demo"
NESTED = (
    "keyframes", "relationship", "effects", "strip", "atmosphere", "emitter",
    "sequence", "path", "texts", "lyrics", "finish", "rhythm", "sfx", "audioTracks",
)


def _layer(**overrides):
    layer = {
        "id": "bg", "name": "bg", "type": "image", "source": f"/api/v1/file/bg.png?workspace={WORKSPACE}",
        "visible": True, "z": 0,
        "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1},
        "animation": {"start": {"x": 50, "y": 50, "scale": 1}, "end": {"x": 50, "y": 50, "scale": 1},
                      "duration": 4, "curve": "ease"},
    }
    layer.update(overrides)
    return layer


def _document(**overrides):
    document = {"version": 1, "name": "Intro", "width": 1280, "height": 720, "duration": 4, "layers": [_layer()]}
    document.update(overrides)
    return document


def _dirs(tmp_path: Path):
    def workspace_dir(name: str) -> str:
        return str(tmp_path / name)

    def uploads_dir() -> str:
        return str(tmp_path / "uploads")

    return workspace_dir, uploads_dir


def _validate(document, tmp_path: Path, workspace: str = WORKSPACE):
    workspace_dir, uploads_dir = _dirs(tmp_path)
    return normalize_document(document, workspace=workspace, workspace_dir=workspace_dir, uploads_dir=uploads_dir)


def _codes(items):
    return [item["code"] for item in items]


def _published_document():
    chunks = [json.dumps(SAVE_OPERATIONS["scenes.document.save"][0]["document"])]
    for catalog in (save_catalog(), export_catalog()):
        for operation in catalog:
            if operation["name"] not in {"scenes.document.save", "scenes.video2d.export"}:
                continue
            document = operation["inputSchema"]["properties"]["input"]["properties"]["document"]
            chunks.append(json.dumps(document))
    return "\n".join(chunks)


def test_save_and_export_publish_the_video2d_schema():
    published = _published_document()
    schema = document_schema()
    assert schema["properties"]["version"]["const"] == 1
    assert schema["additionalProperties"] is True
    for key in ("layers", "texts", "lyrics", "finish", "rhythm", "sfx", "audioTracks", "narrative", "composition"):
        assert key in schema["properties"]
        assert key in published
    for key in NESTED:
        assert key in published
    save = save_catalog()[0]
    export = export_catalog()[0]
    assert save["inputSchema"]["properties"]["input"]["properties"]["document"]["$id"].endswith("video2d-document-v1.json")
    assert export["inputSchema"]["properties"]["input"]["properties"]["document"]["properties"]["layers"]["maxItems"] == 500


def test_schema_accepts_a_rich_document_and_keeps_unknown_keys():
    document = _document(
        fps=24, generationPolicy="provided_only",
        layers=[_layer(
            atmosphere={"kind": "rain", "density": 20, "speed": 1, "size": 1, "wind": 0, "color": "#dbeafe",
                        "emitter": {"mode": "point", "x": 40, "y": 30, "direction": 10, "spread": 20,
                                    "rate": 4, "lifetime": 1, "speed": 12, "gravity": 0}},
            sequence={"kind": "frames", "sources": ["/api/v1/file/a.png?workspace=demo"], "fps": 12, "loop": "loop"},
            relationship={"type": "follow", "targetLayerId": "bg"},
            effects={"blur": 0.2, "blendMode": "screen"},
            strip={"enabled": True, "count": 4, "spacing": 20, "direction": "left", "speed": 8},
            animation={"start": {"x": 10, "y": 20, "scale": 1}, "end": {"x": 80, "y": 20, "scale": 1},
                       "duration": 4, "curve": "ease",
                       "keyframes": [{"id": "k", "time": 0, "x": 10, "y": 20, "scale": 1, "opacity": 1, "rotation": 0, "curve": "linear"}],
                       "path": {"points": [{"x": 10, "y": 20}, {"x": 80, "y": 40}], "orient": False}},
        )],
        texts=[{"id": "title", "text": "Hello", "start": 0, "end": 2, "preset": "impact", "x": 50, "y": 40, "font": "sans"}],
        lyrics={"mode": "karaoke", "lines": [{"id": "line-1", "start": 0, "end": 2, "words": [{"text": "Hello", "start": 0, "end": 1}]}],
                "style": {"font": "serif", "size": 7, "color": "#f4efe6", "activeColor": "#ffe08a", "x": 50, "y": 70,
                          "maxWidth": 80, "align": "center", "visibleLines": 1}},
        finish={"grade": {"exposure": 0, "contrast": 0, "saturation": 0, "temperature": 0, "tint": 0, "fade": 0}},
        rhythm={"bpm": 120, "beats": [0, 0.5]},
        sfx=[{"id": "boom", "kind": "explosion", "start": 0, "end": 1}],
        audioTracks=[{"id": "vo", "filename": "vo.wav", "name": "vo", "kind": "speech", "startTime": 0, "volume": 1}],
        composition={"showGrid": False, "gridSize": 10, "snap": False, "safeArea": "none"},
        narrative={"templateId": "quote", "controls": {"mood": "calm"}},
        copilotAudit=[{"id": "edit-1", "createdAt": "2026-09-28T00:00:00Z", "scope": "scene", "intent": "title",
                       "summary": "added", "operations": [{}], "validation": "applied"}],
        futureField=True,
    )
    errors = list(Draft202012Validator(document_schema()).iter_errors(document))
    assert errors == []
    assert document["futureField"] is True


def test_validate_normalizes_without_writing(tmp_path):
    (tmp_path / WORKSPACE).mkdir()
    (tmp_path / WORKSPACE / "bg.png").write_bytes(b"png")
    before = sorted(path.name for path in tmp_path.rglob("*"))
    result = _validate(_document(texts=[{"id": "title", "text": "Hi", "start": 0, "end": 1, "preset": "rise", "size": 100}]), tmp_path)
    assert sorted(path.name for path in tmp_path.rglob("*")) == before
    assert result["document"]["fps"] == 30
    assert result["document"]["texts"][0]["size"] == 25
    assert result["errors"] == []
    assert result["warnings"] == []


def test_warnings_cover_safe_area_font_frame_duration_and_media(tmp_path):
    portrait = _document(
        width=720, height=1280, duration=70,
        layers=[_layer(id="card", type="overlay", transform={"x": -5, "y": 5, "scale": 1, "opacity": 1}, source="blob:http://local/1")],
        texts=[{"id": "low", "text": "Low", "start": 0, "end": 1, "preset": "impact", "y": 5, "maxWidth": 95, "font": "comic"}],
        lyrics={"mode": "line-fade", "lines": [{"id": "l", "start": 0, "end": 1, "words": [{"text": "a", "start": 0, "end": 0.4}]}],
                "style": {"font": "nope", "size": 7, "color": "#ffffff", "activeColor": "#ffffff", "x": 50, "y": 88,
                          "maxWidth": 80, "align": "center", "visibleLines": 2}},
        audioTracks=[{"id": "vo", "filename": "missing.wav", "name": "vo", "kind": "speech", "startTime": 0, "volume": 1}],
    )
    result = _validate(portrait, tmp_path)
    warnings = result["warnings"]
    assert "text_outside_safe_area" in _codes(warnings)
    assert any(item["path"] == "texts[0].maxWidth" for item in warnings)
    assert any(item["path"] == "layers[0].transform.y" for item in warnings)
    assert any(item["code"] == "unknown_font" and item["path"] == "texts[0].font" for item in warnings)
    assert any(item["code"] == "unknown_font" and item["path"] == "lyrics.style.font" for item in warnings)
    assert any(item["code"] == "layer_outside_frame" for item in warnings)
    duration = next(item for item in warnings if item["code"] == "duration_over_publish_limit")
    assert duration["platform"] == "shorts" and duration["standardSeconds"] == 60 and duration["premiumSeconds"] == 90
    assert "missing_media" in _codes(warnings)
    assert result["document"]["texts"][0]["font"] == "comic"
    landscape = _validate(_document(duration=150, layers=[_layer(source="data:image/png;base64,aaaa")]), tmp_path)
    posted = next(item for item in landscape["warnings"] if item["code"] == "duration_over_publish_limit")
    assert posted["platform"] == "x" and "180" in posted["message"]
    assert "missing_media" not in _codes(landscape["warnings"])
    premium = _validate(_document(duration=200, layers=[_layer(type="effect", source="")]), tmp_path)
    assert "premium" in next(item["message"] for item in premium["warnings"] if item["code"] == "duration_over_publish_limit")
    quiet = _validate(_document(duration=100, layers=[_layer(type="camera", source="")]), tmp_path)
    assert _codes(quiet["warnings"]) == ["empty_timespan"]


def test_errors_use_stable_codes_and_do_not_save(tmp_path):
    workspace_dir, uploads_dir = _dirs(tmp_path)
    duplicate = _document(layers=[_layer(id="bg"), _layer(id="bg")])
    result = normalize_document(duplicate, workspace=WORKSPACE, workspace_dir=workspace_dir, uploads_dir=uploads_dir)
    assert "duplicate_id" in _codes(result["errors"])
    assert _codes(_validate({"version": 2, "name": "x", "width": 10, "height": 10, "duration": 1, "layers": []}, tmp_path)["errors"]) == ["invalid_version"]
    assert "invalid_duration" in _codes(_validate(_document(duration=0), tmp_path)["errors"])
    assert "invalid_duration" in _codes(_validate(_document(duration=601), tmp_path)["errors"])
    assert "invalid_fps" in _codes(_validate(_document(fps=25), tmp_path)["errors"])
    assert "invalid_dimensions" in _codes(_validate(_document(width=0), tmp_path)["errors"])
    assert "not_video2d" in _codes(_validate({"version": 1, "slots": []}, tmp_path)["errors"])
    assert _validate([], tmp_path)["errors"][0]["code"] == "invalid_document"
    assert _validate({"version": 1, "duration": float("nan")}, tmp_path)["errors"][0]["code"] == "invalid_document"
    late = _validate(_document(texts=[{"id": "t", "text": "x", "start": 2, "end": 1, "preset": "impact"}]), tmp_path)
    assert "invalid_timing" in _codes(late["errors"])
    assert not (tmp_path / WORKSPACE).exists()


def test_handler_returns_the_normalized_result_without_gpu(tmp_path):
    workspace_dir, uploads_dir = _dirs(tmp_path)
    handler = command_handlers(workspace_dir, uploads_dir)[OPERATION]
    result = asyncio.run(handler({"version": 1, "input": {"workspace": WORKSPACE, "document": _document(layers=[_layer(type="effect", source="")])}}))
    assert result["operation"] == OPERATION
    assert result["result"]["document"]["fps"] == 30
    assert result["result"]["errors"] == []
    catalog = command_catalog()
    assert catalog[0]["name"] == OPERATION and catalog[0]["mutation"] is False
    assert "duration_over_publish_limit" in catalog[0]["description"]
    for code in ("text_overlap", "text_outside_frame", "lyrics_overlap", "empty_timespan", "reserved_zone", "text_low_contrast"):
        assert code in catalog[0]["description"]
    with pytest.raises(Exception) as error:
        asyncio.run(handler({"version": 1, "input": {"document": {}}}))
    assert error.value.detail["code"] == "invalid_command"
    source = Path(__file__).resolve().parents[1].joinpath("app/services/scene2d_validate.py").read_text(encoding="utf-8")
    assert "torch" not in source and "cuda" not in source


def _covered(duration=8):
    layer = _layer(type="effect", source="")
    layer["animation"]["duration"] = duration
    return layer


def test_text_boxes_warn_on_overlap_outside_frame_and_lyrics(tmp_path):
    from services.video2d_edit_titles import TITLE_BUILDERS

    frame = {"start": 0, "duration": 8, "width": 1280, "height": 720}
    cues = TITLE_BUILDERS["lower-third-date"]({"date": "1968", "caption": "The harbour keeps the light"}, frame)
    lyrics = {
        "mode": "karaoke",
        "lines": [{"id": "line-1", "start": 0, "end": 8, "words": [
            {"text": "The", "start": 0, "end": 1}, {"text": "harbour", "start": 1, "end": 3},
            {"text": "keeps", "start": 3, "end": 5}, {"text": "the", "start": 5, "end": 6},
            {"text": "light", "start": 6, "end": 8},
        ]}],
        "style": {"font": "sans", "size": 7, "color": "#f4efe6", "activeColor": "#ffe08a", "x": 50, "y": 78,
                  "maxWidth": 80, "align": "center", "visibleLines": 1},
    }
    stacked = _validate(_document(duration=8, layers=[_covered()], texts=cues, lyrics=lyrics), tmp_path)
    assert "lyrics_overlap" in _codes(stacked["warnings"])
    assert "text_overlap" in _codes(stacked["warnings"])
    moved = json.loads(json.dumps(lyrics))
    moved["style"]["y"] = 16
    moved["style"]["size"] = 5
    clear = _validate(_document(
        duration=8, layers=[_covered()],
        texts=[{**cues[1], "x": 28, "y": 78}],
        lyrics=moved,
    ), tmp_path)
    assert "lyrics_overlap" not in _codes(clear["warnings"])
    assert "text_overlap" not in _codes(clear["warnings"])
    outside = _validate(_document(
        duration=8, layers=[_covered()],
        texts=[{"id": "low", "text": "Low", "start": 0, "end": 2, "preset": "impact", "x": 50, "y": 4, "size": 20}],
    ), tmp_path)
    assert any(item["code"] == "text_outside_frame" and item["path"] == "texts[0]" for item in outside["warnings"])
    separated = _validate(_document(
        duration=8, layers=[_covered()],
        texts=[
            {"id": "a", "text": "One", "start": 0, "end": 2, "preset": "impact", "x": 50, "y": 40, "size": 6},
            {"id": "b", "text": "Two", "start": 3, "end": 5, "preset": "impact", "x": 50, "y": 40, "size": 6},
        ],
    ), tmp_path)
    assert "text_overlap" not in _codes(separated["warnings"])


def test_left_align_uses_the_text_edge_and_outside_frame_uses_that_box(tmp_path):
    from services.scene2d_text_boxes import text_placements

    wide = {
        "id": "date", "text": "STORY LAB", "start": 0, "end": 4, "preset": "impact",
        "x": 12, "y": 70, "size": 14, "font": "display", "align": "left",
    }
    document = _document(duration=8, layers=[_covered()], texts=[wide])
    left = text_placements(document)[0]
    assert left["left"] == pytest.approx(12)
    assert left["right"] < 100
    centered = json.loads(json.dumps(document))
    centered["texts"][0]["align"] = "center"
    center = text_placements(centered)[0]
    assert center["left"] < 0
    assert "text_outside_frame" in _codes(_validate(centered, tmp_path)["warnings"])
    omitted = json.loads(json.dumps(document))
    del omitted["texts"][0]["align"]
    assert text_placements(omitted)[0]["left"] == pytest.approx(center["left"])
    overflow = json.loads(json.dumps(document))
    overflow["texts"][0]["x"] = 80
    assert any(item["code"] == "text_outside_frame" and item["path"] == "texts[0]" for item in _validate(overflow, tmp_path)["warnings"])
    kept = _validate(document, tmp_path)
    assert "text_outside_frame" not in _codes(kept["warnings"])
    right = json.loads(json.dumps(document))
    right["texts"][0]["align"] = "right"
    right["texts"][0]["x"] = 12
    assert text_placements(right)[0]["right"] == pytest.approx(12)
    assert "text_outside_frame" in _codes(_validate(right, tmp_path)["warnings"])
    bad_focus = _document(layers=[_layer(focus={"x": -1, "y": 50})])
    assert list(Draft202012Validator(document_schema()).iter_errors(bad_focus))


def test_empty_timespan_warns_only_for_gaps_over_two_seconds(tmp_path):
    short = _layer()
    short["animation"]["duration"] = 2
    gap = _validate(_document(duration=4, layers=[short]), tmp_path)
    assert "empty_timespan" not in _codes(gap["warnings"])
    long = _layer()
    long["animation"]["duration"] = 3
    warned = _validate(_document(duration=10, layers=[long]), tmp_path)
    empty = next(item for item in warned["warnings"] if item["code"] == "empty_timespan")
    assert empty["start"] == 3 and empty["end"] == 10
    filled = _validate(_document(
        duration=10, layers=[long],
        texts=[{"id": "tail", "text": "Still here", "start": 3, "end": 10, "preset": "impact", "x": 50, "y": 40, "size": 6}],
    ), tmp_path)
    assert "empty_timespan" not in _codes(filled["warnings"])


def test_reserved_zone_and_sampled_contrast(tmp_path):
    from services.scene2d_text_boxes import contrast_ratio, contrast_warnings

    invaded = _validate(_document(
        duration=4, layers=[_covered(4)],
        reservedZones=[{"id": "counter", "x": 78, "y": 0, "width": 22, "height": 14}],
        texts=[{"id": "clock", "text": "12", "start": 0, "end": 4, "preset": "impact", "x": 88, "y": 6, "size": 6, "align": "center"}],
    ), tmp_path)
    zone = next(item for item in invaded["warnings"] if item["code"] == "reserved_zone")
    assert zone["zone"] == "reservedZones[0]"
    clear = _validate(_document(
        duration=4, layers=[_covered(4)],
        reservedZones=[{"id": "counter", "x": 78, "y": 0, "width": 22, "height": 14}],
        texts=[{"id": "title", "text": "Harbour", "start": 0, "end": 4, "preset": "impact", "x": 50, "y": 40, "size": 8}],
    ), tmp_path)
    assert "reserved_zone" not in _codes(clear["warnings"])
    white = bytes([255, 255, 255]) * 16
    black = bytes([0, 0, 0]) * 16
    box = {"path": "texts[0]", "color": "#ffffff", "left": 0, "top": 0, "right": 100, "bottom": 100}
    assert contrast_warnings([box], white, 4, 4)[0]["code"] == "text_low_contrast"
    assert contrast_warnings([box], black, 4, 4) == []
    assert contrast_ratio((255, 255, 255), (255, 255, 255)) < 3
    assert contrast_ratio((255, 255, 255), (0, 0, 0)) > 3
    assert "text_low_contrast" not in _codes(clear["warnings"])
