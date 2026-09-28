"""The Video 2D agent guide cites real shared catalog ids."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "agents" / "VIDEO2D_MCP_GUIDE.md"
SHARED = ROOT / "app" / "shared"


def _ids(filename: str) -> set[str]:
    data = json.loads((SHARED / filename).read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else data["entries"]
    return {item["id"] for item in entries}


def _examples(text: str) -> list[dict]:
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", text, flags=re.DOTALL)]


def test_guide_template_ids_exist_in_shared_catalogs():
    examples = _examples(GUIDE.read_text(encoding="utf-8"))
    scene_ids = _ids("scene_templates.json")
    text_ids = _ids("text_templates.json")
    compiled = [
        item["input"]["templateId"]
        for item in examples
        if isinstance(item.get("input"), dict) and "assets" in item["input"] and "templateId" in item["input"]
    ]
    titled = [
        item["input"]["templateId"]
        for item in examples
        if isinstance(item.get("input"), dict) and "fields" in item["input"] and "templateId" in item["input"]
    ]
    assert compiled, "guide must compile a scene template"
    assert titled, "guide must apply a text template"
    assert set(compiled) <= scene_ids
    assert set(titled) <= text_ids
    assert set(compiled).isdisjoint(text_ids)
    assert set(titled).isdisjoint(scene_ids)
