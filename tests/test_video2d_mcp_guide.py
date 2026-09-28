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


def _known_tools() -> set[str]:
    from services.montage_commands import command_catalog as montages
    from services.scene2d_export import command_catalog as export_catalog
    from services.scene2d_validate import command_catalog as validate_catalog
    from services.scene_asset_facts import command_catalog as assets
    from services.scene_commands import command_catalog as effects
    from services.scene_documents import command_catalog as documents
    from services.video2d_catalogs import command_catalog as catalogs
    from services.video2d_catalogs import query_operation
    from services.video2d_compile import command_catalog as compile_catalog
    from services.video2d_edit import command_catalog as edit_catalog
    from services.video2d_preview import command_catalog as preview_catalog

    names: set[str] = set()
    groups = (
        effects(), catalogs(), [query_operation()], compile_catalog(), edit_catalog(),
        preview_catalog(), validate_catalog(), documents(), export_catalog(), montages(), assets(),
    )
    for group in groups:
        for item in group:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                names.add(item["name"])
    return names


def test_guide_names_only_real_tools_and_does_not_forbid_one():
    text = GUIDE.read_text(encoding="utf-8")
    known = _known_tools()
    named = set(re.findall(r"\b((?:scenes|montages)\.[a-z0-9_.]+)\b", text))
    assert named, "guide must name the tools an agent calls"
    assert sorted(named - known) == []
    forbid = re.compile(r"no está disponible|no llames|no invoques|unavailable|do not call|don't call", re.IGNORECASE)
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if not forbid.search(sentence):
            continue
        banned = [name for name in re.findall(r"\b((?:scenes|montages)\.[a-z0-9_.]+)\b", sentence) if name in known]
        assert banned == [], sentence
    order = [
        "scenes.catalog",
        "scenes.assets.inspect",
        "scenes.template.compile",
        "scenes.text.template",
        "scenes.lyrics.import",
        "scenes.video2d.edit",
        "scenes.video2d.validate",
        "scenes.video2d.preview",
        "scenes.document.save",
        "scenes.video2d.export",
        "montages.save",
    ]
    indexes = [text.index(name) for name in order]
    assert indexes == sorted(indexes)


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
