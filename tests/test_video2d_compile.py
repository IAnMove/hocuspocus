"""MCP envelopes for template compile, text templates, and lyrics import."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.video2d_compile import CompileError, command_catalog, execute

ROOT = Path(__file__).resolve().parents[1]
TSX = ROOT / "ui" / "node_modules" / "tsx" / "dist" / "cli.mjs"
ASSETS = {"hero": "/api/v1/file/hero.png", "plate": "/api/v1/file/plate.png"}


def _compile(template_id="cinema-establishing", *, full=False, **extra):
    payload = {"templateId": template_id, "assets": ASSETS, **extra}
    if full:
        payload["full"] = True
    return {"version": 1, "operation": "scenes.template.compile", "input": payload}


def test_catalog_lists_compile_operations_without_mutation():
    published = command_catalog()
    assert [item["name"] for item in published] == [
        "scenes.template.compile",
        "scenes.text.template",
        "scenes.lyrics.import",
    ]
    assert all(item["mutation"] is False and item["inputSchema"]["properties"]["version"]["const"] == 1 for item in published)


def test_unknown_template_is_rejected_before_node_starts(monkeypatch):
    def explode(payload):
        raise AssertionError(payload)

    monkeypatch.setattr("services.video2d_compile.spawn_bridge", explode)
    with pytest.raises(CompileError) as caught:
        execute(_compile("not-a-template"))
    assert caught.value.code == "template_unknown"
    assert str(caught.value).startswith("template_unknown:")


def test_missing_required_slot_is_rejected_before_node_starts(monkeypatch):
    monkeypatch.setattr("services.video2d_compile.spawn_bridge", lambda payload: pytest.fail(str(payload)))
    with pytest.raises(CompileError) as caught:
        execute({"version": 1, "operation": "scenes.template.compile", "input": {
            "templateId": "cinema-establishing",
            "assets": {"hero": "/api/v1/file/hero.png"},
        }})
    assert caught.value.code == "template_missing_slot"


def test_unknown_text_template_and_bad_lyrics_format_do_not_spawn(monkeypatch):
    monkeypatch.setattr("services.video2d_compile.spawn_bridge", lambda payload: pytest.fail(str(payload)))
    with pytest.raises(CompileError) as unknown:
        execute({"version": 1, "operation": "scenes.text.template", "input": {"templateId": "not-a-title"}})
    assert unknown.value.code == "text_template_unknown"
    with pytest.raises(CompileError) as lyrics:
        execute({"version": 1, "operation": "scenes.lyrics.import", "input": {"format": "vtt", "text": "1\n00:00:01,000 --> 00:00:02,000\nHi"}})
    assert lyrics.value.code == "lyrics_bad_format"


def test_compile_envelope_returns_the_document_and_does_not_save(monkeypatch):
    seen = {}

    def fake_bridge(payload):
        seen["payload"] = payload
        return {"ok": True, "result": {"document": {"version": 1, "name": "kept", "layers": [{"id": "plate"}]}, "warnings": [], "saved": True}}

    monkeypatch.setattr("services.video2d_compile.spawn_bridge", fake_bridge)
    result = execute(_compile())
    assert seen["payload"]["input"]["templateId"] == "cinema-establishing"
    assert "full" not in seen["payload"]["input"]
    assert result["status"] == "completed"
    assert result["result"]["layerIds"] == ["plate"]
    assert "document" not in result["result"]
    full = execute(_compile(full=True))
    assert set(full["result"]) == {"document", "warnings"}
    assert full["result"]["document"]["layers"][0]["id"] == "plate"


@pytest.mark.parametrize(
    ("command", "code"),
    [
        ({"version": 1, "input": {"templateId": "cinema-establishing"}}, "compile_bad_envelope"),
        ({"version": 2, "operation": "scenes.template.compile", "input": {"templateId": "cinema-establishing"}}, "compile_bad_envelope"),
        ({"version": 1, "operation": "scenes.template.compile", "input": {"assets": ASSETS}}, "compile_bad_envelope"),
    ],
)
def test_bad_envelopes_use_a_stable_code(command, code, monkeypatch):
    monkeypatch.setattr("services.video2d_compile.spawn_bridge", lambda payload: pytest.fail(str(payload)))
    with pytest.raises(CompileError) as caught:
        execute(command)
    assert caught.value.code == code


@pytest.mark.skipif(not TSX.is_file(), reason="ui node_modules is not installed")
def test_compile_calls_the_typescript_builders():
    result = execute(_compile(full=True))
    assert result["result"]["document"]["name"] == "Plano de establecimiento · candidata"
    assert [layer["id"] for layer in result["result"]["document"]["layers"]] == ["plate", "hero", "camera", "atmosphere-dust"]


def test_example_urls_are_durable_and_reach_the_bridge(monkeypatch):
    seen = {}

    def fake_bridge(payload):
        seen["payload"] = payload
        return {"ok": True, "result": {"document": {"version": 1, "layers": []}, "warnings": []}}

    monkeypatch.setattr("services.video2d_compile.spawn_bridge", fake_bridge)
    examples = {"hero": "/examples/hero.png", "plate": "/examples/plate.png"}
    execute(_compile("trailer-teaser", assets=examples))
    assert seen["payload"]["input"]["assets"] == examples
    execute(_compile("cinema-establishing", assets=examples))
    assert seen["payload"]["input"]["assets"] == examples


def test_video2d_candidate_forwards_catalog_duration_and_keeps_assets(monkeypatch):
    seen = {}

    def fake_bridge(payload):
        seen["payload"] = payload
        return {"ok": True, "result": {"document": {"version": 1, "layers": []}, "warnings": []}}

    monkeypatch.setattr("services.video2d_compile.spawn_bridge", fake_bridge)
    execute(_compile("documentary-history"))
    assert seen["payload"]["input"]["duration"] == 4
    assert seen["payload"]["input"]["controls"]["duration"] == 4
    assert seen["payload"]["input"]["assets"] == ASSETS


@pytest.mark.skipif(not TSX.is_file(), reason="ui node_modules is not installed")
def test_video2d_candidate_compile_keeps_slot_images():
    result = execute(_compile("documentary-history", full=True))
    layers = {layer["id"]: layer for layer in result["result"]["document"]["layers"]}
    assert result["result"]["document"]["duration"] == 4
    assert layers["hero"]["source"] == ASSETS["hero"]
    assert layers["plate"]["source"] == ASSETS["plate"]
    assert layers["plate"]["type"] == "image"
    assert layers["atmosphere-plate"]["type"] == "effect"
