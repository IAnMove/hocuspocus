"""MCP coverage ratchet for Video 2D.

A shared JSON catalog must be read by a module that publishes a ``*.catalog``
operation. A top-level Video 2D document key must appear in the published
save/export schema or description, or stay on the explicit gap list until a
later block publishes it. Adding a key or a catalog without one of those
updates fails this test.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from services.scene2d_export import command_catalog as export_catalog
from services.scene_commands import command_catalog as effects_catalog
from services.scene_documents import OPERATIONS as SAVE_OPERATIONS
from services.scene_documents import command_catalog as save_catalog
from services.video2d_catalogs import command_catalog as video2d_catalog
from services.video2d_catalogs import query_operation as video2d_query_operation
from services.world3d_template_commands import command_catalog as world3d_template_catalog

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "app" / "shared"
SCENE_TS = ROOT / "ui" / "src" / "types" / "index.ts"

# Whole words already present in the save/export description or document schema.
PUBLISHED_KEYS = frozenset({
    "audioMix",
    "audioTracks",
    "composition",
    "copilotAudit",
    "dialogueBeats",
    "duration",
    "finish",
    "fps",
    "generationPolicy",
    "height",
    "layers",
    "lyrics",
    "name",
    "narrative",
    "rhythm",
    "sfx",
    "texts",
    "version",
    "width",
})
# Scene keys save/export still do not name. Empty once the document schema names every key.
KNOWN_SCHEMA_GAPS = frozenset()


def _catalog_files() -> list[Path]:
    found = []
    for path in sorted(SHARED.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data if isinstance(data, list) else None
        if isinstance(data, dict):
            for key in ("items", "entries", "catalog"):
                if isinstance(data.get(key), list):
                    entries = data[key]
                    break
        if not entries or not all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in entries):
            continue
        found.append(path)
    return found


def _catalog_operations() -> list[dict]:
    operations = [*effects_catalog(), *save_catalog(), *export_catalog(), *video2d_catalog(), video2d_query_operation(), *world3d_template_catalog()]
    return [item for item in operations if str(item.get("name", "")).endswith(".catalog")]


def _scene_keys() -> list[str]:
    lines = SCENE_TS.read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("export interface Scene {"))
    depth = 0
    keys = []
    for line in lines[start:]:
        if depth == 1:
            match = re.match(r"  ([A-Za-z_][A-Za-z0-9_]*)\??:", line)
            if match:
                keys.append(match.group(1))
        depth += line.count("{") - line.count("}")
        if depth == 0:
            break
    return keys


def _document_schema(schema: dict) -> dict:
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return {}
    if isinstance(properties.get("document"), dict):
        return properties["document"]
    nested = properties.get("input")
    if isinstance(nested, dict):
        return _document_schema(nested)
    return {}


def _published_document_text() -> str:
    chunks = [json.dumps(SAVE_OPERATIONS["scenes.document.save"][0]["document"], ensure_ascii=False)]
    for catalog in (save_catalog(), export_catalog()):
        for operation in catalog:
            if operation["name"] not in {"scenes.document.save", "scenes.video2d.export"}:
                continue
            chunks.append(operation.get("description") or "")
            chunks.append(json.dumps(_document_schema(operation.get("inputSchema") or {}), ensure_ascii=False))
    return "\n".join(chunks)


def _named(text: str, key: str) -> bool:
    return re.search(rf"\b{re.escape(key)}\b", text) is not None


def test_shared_json_catalogs_are_exposed_by_a_catalog_operation():
    operations = _catalog_operations()
    assert [item["name"] for item in operations] == [
        "scenes.effects.catalog",
        "scenes.templates.catalog",
        "scenes.text.catalog",
        "scenes.finish.catalog",
        "scenes.fonts.catalog",
        "scenes.atmospheres.catalog",
        "scenes.motion.catalog",
        "scenes.catalog",
        "world3d.templates.catalog",
    ]
    for path in _catalog_files():
        readers = [item for item in (ROOT / "app").rglob("*.py") if path.name in item.read_text(encoding="utf-8")]
        assert readers, path.name
        blob = "\n".join(item.read_text(encoding="utf-8") for item in readers)
        assert any(operation["name"] in blob for operation in operations), path.name


def test_video2d_document_keys_are_published_or_listed_as_gaps():
    keys = _scene_keys()
    assert keys, "Scene interface keys were not found"
    published = _published_document_text()
    named = {key for key in keys if _named(published, key)}
    missing = sorted(key for key in keys if key not in named and key not in KNOWN_SCHEMA_GAPS)
    stale = sorted(key for key in KNOWN_SCHEMA_GAPS if key in named)
    assert missing == []
    assert stale == []
    assert named == PUBLISHED_KEYS
    assert set(keys) == KNOWN_SCHEMA_GAPS | PUBLISHED_KEYS
