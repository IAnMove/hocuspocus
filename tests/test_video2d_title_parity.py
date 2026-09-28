"""Python add_title cues must match the TypeScript buildTextTemplate bridge."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from services.video2d_compile import execute
from services.video2d_edit import edit

ROOT = Path(__file__).resolve().parents[1]
TSX = ROOT / "ui" / "node_modules" / "tsx" / "dist" / "cli.mjs"
CATALOG = ROOT / "app" / "shared" / "text_templates.json"


def _same(left, right, path: str) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        assert set(left) == set(right), path
        for key in left:
            _same(left[key], right[key], f"{path}.{key}")
        return
    if isinstance(left, list) and isinstance(right, list):
        assert len(left) == len(right), path
        for index, (item, other) in enumerate(zip(left, right)):
            _same(item, other, f"{path}[{index}]")
        return
    if isinstance(left, bool) or isinstance(right, bool) or not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        assert left == right, (path, left, right)
        return
    assert math.isclose(float(left), float(right), rel_tol=0, abs_tol=1e-9), (path, left, right)


def _document(width: int, height: int) -> dict:
    return {
        "version": 1, "name": "parity", "width": width, "height": height, "fps": 30, "duration": 8,
        "layers": [{
            "id": "plate", "name": "plate", "type": "image", "source": "/examples/plate.png",
            "visible": True, "z": 0,
            "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
            "animation": {"start": {"x": 50, "y": 50, "scale": 1}, "end": {"x": 50, "y": 50, "scale": 1}, "duration": 8, "curve": "linear", "spin": False},
        }],
    }


@pytest.mark.skipif(not TSX.is_file(), reason="ui node_modules is not installed")
@pytest.mark.parametrize("width,height", [(1280, 720), (720, 1280)])
def test_add_title_matches_the_typescript_template(width, height):
    import json
    entries = json.loads(CATALOG.read_text(encoding="utf-8"))["entries"]
    assert entries, "text catalog is empty"
    for entry in entries:
        template_id = entry["id"]
        fields = {field["key"]: field["default"] for field in entry["fields"]}
        python = edit({"version": 1, "input": {"document": _document(width, height), "operations": [
            {"op": "add_title", "template": template_id, "fields": fields, "start": 0.4, "duration": 3.2},
        ]}})["result"]["document"]["texts"]
        bridged = execute({
            "version": 1,
            "operation": "scenes.text.template",
            "input": {"templateId": template_id, "fields": fields, "start": 0.4, "duration": 3.2, "width": width, "height": height},
        })["result"]["texts"]
        _same(python, bridged, template_id)
