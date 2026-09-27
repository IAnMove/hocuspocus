"""Read-only Video 2D catalogs shared with the UI. No GPU, save or export."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1] / "shared"

CATALOG_FILES = {
    "scenes.templates.catalog": "scene_templates.json",
    "scenes.text.catalog": "text_templates.json",
    "scenes.finish.catalog": "finish_presets.json",
    "scenes.fonts.catalog": "fonts.json",
    "scenes.atmospheres.catalog": "atmospheres.json",
    "scenes.motion.catalog": "motion_presets.json",
}

BLURBS = {
    "scenes.templates.catalog": "List scene templates from scene_templates.json (id, family, review status, slots, controls, limits).",
    "scenes.text.catalog": "List kinetic text templates from text_templates.json (fields and 16:9 / 9:16 formats). Builders stay in the UI.",
    "scenes.finish.catalog": "List finish presets from finish_presets.json with clamp ranges.",
    "scenes.fonts.catalog": "List Video 2D font families from fonts.json (weights and license).",
    "scenes.atmospheres.catalog": "List atmosphere kinds from atmospheres.json with parameter defaults and ranges.",
    "scenes.motion.catalog": "List recipe motion and camera presets from motion_presets.json.",
}


class CatalogError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _entries(data: Any, name: str) -> list[Any]:
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = next((data[key] for key in ("entries", "items", "catalog") if isinstance(data.get(key), list)), None)
        if entries is None:
            raise CatalogError("catalog_invalid", name)
    else:
        raise CatalogError("catalog_invalid", name)
    if not entries or any(not isinstance(item, dict) for item in entries):
        raise CatalogError("catalog_invalid", name)
    return entries


def _require_ids(entries: list[Any], name: str) -> None:
    ids = [item.get("id") for item in entries]
    if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
        raise CatalogError("catalog_duplicate_id", name)


def load_catalog(name: str) -> Any:
    if not name or Path(name).name != name:
        raise CatalogError("catalog_missing", name)
    path = ROOT / name
    if not path.is_file():
        raise CatalogError("catalog_missing", name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as error:
        raise CatalogError("catalog_unreadable", name) from error
    except json.JSONDecodeError as error:
        raise CatalogError("catalog_invalid", name) from error
    _require_ids(_entries(data, name), name)
    return data


CATALOGS = {operation: load_catalog(filename) for operation, filename in CATALOG_FILES.items()}
EFFECTS_CATALOG = load_catalog("scene_effects.json")


def command_catalog() -> list[dict[str, Any]]:
    operations = []
    for name, data in CATALOGS.items():
        operations.append({
            "name": name,
            "description": f"{BLURBS[name]} {len(_entries(data, name))} entries. Read-only; no GPU, save or export.",
            "mutation": False,
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "version": {"type": "integer", "const": 1},
                    "input": {"type": "object", "additionalProperties": False, "properties": {}},
                },
                "required": ["version", "input"],
            },
        })
    return operations


def execute(command: Any) -> dict[str, Any]:
    if not isinstance(command, dict) or set(command) != {"version", "operation", "input"}:
        raise CatalogError("catalog_bad_envelope", "Expected version, operation and input only")
    if type(command["version"]) is not int or command["version"] != 1:
        raise CatalogError("catalog_bad_envelope", "Expected version 1")
    name = command["operation"]
    if type(name) is not str or name not in CATALOGS:
        raise CatalogError("catalog_unknown_operation", "Unknown catalog operation")
    if command["input"] != {}:
        raise CatalogError("catalog_bad_envelope", "Catalog input must be empty")
    return {"version": 1, "status": "completed", "operation": name, "result": deepcopy(CATALOGS[name])}


def _handler(name: str) -> Callable[[Any], Any]:
    async def handle(arguments: Any) -> dict[str, Any]:
        from fastapi import HTTPException
        from starlette.concurrency import run_in_threadpool

        payload = arguments if isinstance(arguments, dict) else {}
        try:
            return await run_in_threadpool(execute, {**payload, "operation": name})
        except CatalogError as error:
            raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": False}) from error

    return handle


def command_handlers() -> dict[str, Callable[[Any], Any]]:
    return {name: _handler(name) for name in CATALOGS}


__all__ = [
    "CATALOG_FILES",
    "CatalogError",
    "EFFECTS_CATALOG",
    "command_catalog",
    "command_handlers",
    "execute",
    "load_catalog",
]
