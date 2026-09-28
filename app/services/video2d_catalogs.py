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

OPERATION = "scenes.catalog"
KINDS = ("templates", "text", "finish", "fonts", "atmospheres", "motion", "effects")
PAGE_LIMIT = 200
QUERY_LIMIT = 80
_KIND_SOURCE = {
    "templates": "scenes.templates.catalog",
    "text": "scenes.text.catalog",
    "finish": "scenes.finish.catalog",
    "fonts": "scenes.fonts.catalog",
    "atmospheres": "scenes.atmospheres.catalog",
    "motion": "scenes.motion.catalog",
}


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


def _kind_data(kind: str) -> Any:
    if kind == "effects":
        return EFFECTS_CATALOG
    return CATALOGS[_KIND_SOURCE[kind]]


def _field(entry: dict, key: str) -> str:
    value = entry.get(key)
    return value if isinstance(value, str) else ""


def _haystack(entry: dict) -> str:
    return f"{_field(entry, 'id')}\n{_field(entry, 'name')}".casefold()


def _selected(kind: str, family: str, needle: str) -> list[dict]:
    entries = _entries(_kind_data(kind), kind)
    if family:
        entries = [item for item in entries if item.get("family") == family]
    if needle:
        entries = [item for item in entries if needle in _haystack(item)]
    return entries


def _visible(kind: str, family: str, needle: str) -> list[dict]:
    return _selected(kind, family if kind == "templates" else "", needle)


def _require_text(value: Any, field: str, limit: int) -> str:
    if value is None:
        return ""
    if type(value) is not str:
        raise CatalogError("catalog_bad_envelope", field)
    if len(value) > limit:
        raise CatalogError("catalog_bad_envelope", field)
    return value


def _query_fields(data: Any) -> tuple[str, str, str]:
    if not isinstance(data, dict):
        raise CatalogError("catalog_bad_envelope", "Expected an object")
    if set(data) - {"kind", "family", "q"}:
        raise CatalogError("catalog_bad_envelope", "Unexpected catalog field")
    kind = _require_text(data.get("kind"), "kind", QUERY_LIMIT)
    family = _require_text(data.get("family"), "family", QUERY_LIMIT)
    query = _require_text(data.get("q"), "q", QUERY_LIMIT)
    if kind and kind not in KINDS:
        raise CatalogError("catalog_unknown_kind", kind)
    if family and kind not in ("", "templates"):
        raise CatalogError("catalog_bad_envelope", "family filters templates")
    return kind, family, query.casefold()


def _summary(family: str, needle: str) -> dict[str, Any]:
    rows = [{"kind": kind, "count": len(_visible(kind, family, needle))} for kind in KINDS]
    return {"kinds": rows}


def _page(kind: str, family: str, needle: str) -> dict[str, Any]:
    entries = _visible(kind, family, needle)
    total = len(entries)
    return {
        "kind": kind,
        "entries": deepcopy(entries[:PAGE_LIMIT]),
        "total": total,
        "truncated": total > PAGE_LIMIT,
    }


def query_catalog(data: Any) -> dict[str, Any]:
    kind, family, needle = _query_fields(data)
    result = _summary(family, needle) if not kind else _page(kind, family, needle)
    return {"version": 1, "status": "completed", "operation": OPERATION, "result": result}


def execute_query(command: Any) -> dict[str, Any]:
    if not isinstance(command, dict) or set(command) != {"version", "operation", "input"}:
        raise CatalogError("catalog_bad_envelope", "Expected version, operation and input only")
    if type(command["version"]) is not int or command["version"] != 1:
        raise CatalogError("catalog_bad_envelope", "Expected version 1")
    if command["operation"] != OPERATION:
        raise CatalogError("catalog_unknown_operation", "Unknown catalog operation")
    return query_catalog(command["input"])


def query_operation() -> dict[str, Any]:
    kinds = ", ".join(KINDS)
    return {
        "name": OPERATION,
        "description": (
            f"Query Video 2D catalogs ({kinds}). Omit kind for counts only "
            "({kinds:[{kind, count}]}, no entry dump). family filters templates. "
            "q matches id and name, case-insensitive, at most 80 characters. "
            f"At most {PAGE_LIMIT} entries; truncated and total when over the cap. "
            "Effects entries are scene_effects.json; world kinds stay on scenes.effects.catalog. "
            "Read-only; no GPU, save or export."
        ),
        "mutation": False,
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "const": 1},
                "input": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "kind": {"type": "string", "enum": list(KINDS)},
                        "family": {"type": "string", "maxLength": QUERY_LIMIT},
                        "q": {"type": "string", "maxLength": QUERY_LIMIT},
                    },
                },
            },
            "required": ["version", "input"],
        },
    }


def query_handlers() -> dict[str, Callable[[Any], Any]]:
    async def handle(arguments: Any) -> dict[str, Any]:
        from fastapi import HTTPException
        from starlette.concurrency import run_in_threadpool

        payload = arguments if isinstance(arguments, dict) else {}
        try:
            return await run_in_threadpool(execute_query, {**payload, "operation": OPERATION})
        except CatalogError as error:
            raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": False}) from error

    return {OPERATION: handle}


__all__ = [
    "CATALOG_FILES",
    "CatalogError",
    "EFFECTS_CATALOG",
    "KINDS",
    "command_catalog",
    "command_handlers",
    "execute",
    "execute_query",
    "load_catalog",
    "query_catalog",
    "query_handlers",
    "query_operation",
]
