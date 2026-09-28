"""Short MCP replies and save idempotency. No GPU and no committed media."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.mcp_compact import summarize_model_catalog
from services.scene2d_validate import OPERATION as VALIDATE, command_handlers as validate_handlers
from services.scene_documents import command_handlers as save_handlers, save_document
from services.video2d_catalogs import execute, query_catalog
from services.video2d_edit import edit

WORKSPACE = "compact-b6"


def _schema(node) -> bool:
    if isinstance(node, dict):
        if {"min", "max", "default"} <= set(node):
            return True
        return any(_schema(value) for value in node.values())
    if isinstance(node, list):
        return any(_schema(value) for value in node)
    return False


def _layer(layer_id="bg"):
    return {
        "id": layer_id, "name": layer_id, "type": "image",
        "source": f"/examples/{layer_id}.png", "visible": True, "z": 0,
        "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1},
        "animation": {"start": {"x": 50, "y": 50, "scale": 1}, "end": {"x": 50, "y": 50, "scale": 1},
                      "duration": 4, "curve": "linear"},
    }


def _document():
    return {
        "version": 1, "name": "Intro", "width": 1280, "height": 720, "fps": 30, "duration": 4,
        "layers": [_layer()], "texts": [{"id": "title", "text": "Hola", "start": 0, "end": 1}],
    }


def _workspace_dir(tmp_path: Path):
    def resolve(name: str) -> str:
        path = tmp_path / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    return resolve


def test_catalog_without_detail_omits_control_schema_and_base64():
    short = execute({"version": 1, "operation": "scenes.templates.catalog", "input": {}})
    full = execute({"version": 1, "operation": "scenes.templates.catalog", "input": {"detail": True}})
    short_text = json.dumps(short)
    full_text = json.dumps(full)
    assert len(short_text) < len(full_text)
    assert "base64" not in short_text
    assert _schema(short) is False
    assert _schema(full) is True
    row = short["result"]["entries"][0]
    assert set(row) == {"id", "name", "description", "counts"}
    assert isinstance(row["counts"].get("controls"), int)
    one = execute({"version": 1, "operation": "scenes.templates.catalog", "input": {"id": "cinema-establishing"}})
    assert "min" in one["result"]["entry"]["controls"]["duration"]
    finish = execute({"version": 1, "operation": "scenes.finish.catalog", "input": {}})
    assert "ranges" not in finish["result"]
    assert "exposure" not in json.dumps(finish)
    page = query_catalog({"kind": "templates"})["result"]
    assert _schema(page) is False
    assert "controls" not in page["entries"][0]
    detailed = query_catalog({"kind": "templates", "id": "cinema-establishing"})["result"]
    assert detailed["entry"]["id"] == "cinema-establishing"
    assert "controls" in detailed["entry"]


def test_model_summary_drops_requirement_blobs():
    catalog = summarize_model_catalog({
        "families": [{"id": "qwen", "label": "Qwen", "order": 1}],
        "models": [{
            "model_type": "qwen_image_21",
            "name": "Qwen Image",
            "description": "One line\nthat must not leak",
            "resource_requirements": {"vram_gb": 24},
            "director": {"ready": True, "notes": "x" * 400},
        }],
    })
    text = json.dumps(catalog)
    assert "base64" not in text
    assert "vram_gb" not in text
    assert "\n" not in catalog["models"][0]["description"]
    assert catalog["models"][0]["id"] == "qwen_image_21"
    assert catalog["models"][0]["counts"]["requirements"] == 1
    assert catalog["counts"] == {"models": 1, "families": 1}


def test_edit_and_validate_default_to_a_short_summary(tmp_path):
    edited = edit({"version": 1, "input": {"document": _document(), "operations": []}})
    assert edited["result"]["layerIds"] == ["bg"]
    assert edited["result"]["textIds"] == ["title"]
    assert edited["result"]["duration"] == 4
    assert edited["result"]["size"] == {"width": 1280, "height": 720}
    assert edited["result"]["saved"] is False
    assert "document" not in edited["result"]
    workspace_dir = _workspace_dir(tmp_path)
    handler = validate_handlers(workspace_dir, lambda: str(tmp_path / "uploads"))[VALIDATE]
    checked = asyncio.run(handler({"version": 1, "input": {"workspace": WORKSPACE, "document": _document()}}))
    assert "document" not in checked["result"]
    assert checked["result"]["layerIds"] == ["bg"]
    assert "errorCodes" in checked["result"]
    assert "base64" not in json.dumps(checked)


def test_same_intent_id_does_not_save_twice(tmp_path, monkeypatch):
    calls = {"n": 0}
    real = save_document

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr("services.scene_documents.save_document", wrapped)
    workspace_dir = _workspace_dir(tmp_path)
    handler = save_handlers(workspace_dir)["scenes.document.save"]
    command = {
        "version": 1,
        "intent_id": "save-once",
        "input": {"workspace": WORKSPACE, "name": "Intro", "document": _document()},
    }
    first = asyncio.run(handler(command))
    second = asyncio.run(handler(command))
    assert calls["n"] == 1
    assert second["result"]["replayed"] is True
    assert second["result"]["name"] == first["result"]["name"]
    stored = list((tmp_path / WORKSPACE).glob("*.scene.json"))
    assert len(stored) == 1
    changed = {
        **command,
        "input": {**command["input"], "name": "Other"},
    }
    with pytest.raises(HTTPException) as error:
        asyncio.run(handler(changed))
    assert error.value.status_code == 409
    assert calls["n"] == 1
    assert len(list((tmp_path / WORKSPACE).glob("*.scene.json"))) == 1
