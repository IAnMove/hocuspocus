"""Versioned ``templates.*`` commands shared by HTTP and external agents (MCP)."""
from __future__ import annotations

from typing import Any, Callable

from services.template_format import LICENSES, TemplateError
from services.template_library import TemplateLibrary

WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 120}
TEMPLATE_ID = {"type": "string", "pattern": r"^[a-z0-9][a-z0-9-]{0,39}/[a-z0-9][a-z0-9-]{0,63}$"}
EDITOR = {"enum": ["video3d", "video2d"]}
FILE = {"type": "string", "minLength": 1, "maxLength": 200}
SLOT = {"type": "object", "properties": {
    "id": {"type": "string"}, "label": {"type": "string"}, "hint": {"type": "string"},
    "accepts": {"type": "array", "items": {"enum": ["model3d", "image", "video", "audio"]}},
    "required": {"type": "boolean"},
    "target": {"type": "string", "description": "Video 3D slot id (subject_1, subject_2, background, prop) or Video 2D layer id"}},
    "required": ["id"]}
CONTROL = {"type": "object", "properties": {
    "id": {"type": "string"}, "label": {"type": "string"}, "type": {"enum": ["number", "text", "color", "boolean", "choice"]},
    "pointer": {"type": "string", "description": "JSON Pointer into the document, e.g. /duration or /texts/0/text"},
    "min": {"type": "number"}, "max": {"type": "number"}, "options": {"type": "array"}, "default": {}},
    "required": ["id", "type", "pointer"]}

OPERATIONS: dict[str, tuple[dict[str, Any], list[str], bool, str]] = {
    "templates.list": ({"editor": EDITOR, "tag": {"type": "string"}, "query": {"type": "string", "maxLength": 120}}, [], False,
                       "List user/imported/community scene templates in the local library: id (author/slug), editor, title, "
                       "author, license, tags, slots to fill, controls to tune and preview URL."),
    "templates.get": ({"id": TEMPLATE_ID}, ["id"], False, "Read one template: manifest (slots, controls, metadata) and its scene document."),
    "templates.save": ({"workspace": WORKSPACE, "editor": EDITOR, "document": {"type": "object"},
                        "title": {"type": "string", "minLength": 1, "maxLength": 80}, "description": {"type": "string", "maxLength": 600},
                        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
                        "author": {"type": "object", "properties": {"name": {"type": "string"}, "x": {"type": "string"}, "url": {"type": "string"}}},
                        "license": {"enum": list(LICENSES)}, "id": TEMPLATE_ID, "templateVersion": {"type": "string"},
                        "slots": {"type": "array", "items": SLOT, "maxItems": 16}, "controls": {"type": "array", "items": CONTROL, "maxItems": 32},
                        "include_media": {"type": "boolean"},
                        "preview": {"type": "string", "description": "Workspace image file name or a data:image/png|jpeg|webp;base64 URL (≤ 2 MB)"},
                        "expected_updated_at": {"type": "string"}},
                       ["workspace", "editor", "document", "title"], True,
                       "Save a Video 3D (slots) or Video 2D (layers) scene from a workspace as a reusable template. Declare slots "
                       "(what the user must provide) and controls (JSON Pointer values to tune). Without include_media, slot media "
                       "are emptied and any other workspace media is an error. To update pass expected_updated_at."),
    "templates.apply": ({"id": TEMPLATE_ID, "workspace": WORKSPACE, "slots": {"type": "object", "additionalProperties": {"type": "string"}},
                         "controls": {"type": "object"}}, ["id", "workspace"], True,
                        "Return a ready scene document from a template: fills slots with workspace/example files, sets controls and "
                        "copies the template's sample media into the workspace. Does not save; use scenes.document.save or an export."),
    "templates.export": ({"id": TEMPLATE_ID, "workspace": WORKSPACE}, ["id", "workspace"], True,
                         "Write the template as a portable .hptemplate file into a workspace and return its URL."),
    "templates.preflight": ({"workspace": WORKSPACE, "file": FILE}, ["workspace", "file"], False,
                            "Inspect a .hptemplate (or legacy *.world3d.template.json) in a workspace before importing: metadata, "
                            "slots, controls, media, issues and whether the id already exists."),
    "templates.import": ({"workspace": WORKSPACE, "file": FILE, "replace": {"type": "boolean"}}, ["workspace", "file"], True,
                         "Import a .hptemplate from a workspace into the library. An existing id needs replace=true."),
    "templates.delete": ({"id": TEMPLATE_ID}, ["id"], True, "Delete a template from the local library."),
}
SAVE_METADATA = ("title", "description", "tags", "author", "license", "id", "templateVersion", "slots", "controls")


def command_catalog() -> list[dict[str, Any]]:
    operations = []
    for name, (properties, required, mutation, description) in OPERATIONS.items():
        payload = {"type": "object", "additionalProperties": False, "properties": properties, "required": required}
        operations.append({
            "name": name, "version": 1, "domain": "templates", "mutation": mutation, "description": description,
            "inputSchema": {"type": "object", "additionalProperties": False,
                            "properties": {"version": {"type": "integer", "const": 1}, "input": payload},
                            "required": ["version", "input"]},
        })
    return operations


def _payload(arguments: Any, name: str) -> dict[str, Any]:
    properties, required, _, _ = OPERATIONS[name]
    if not isinstance(arguments, dict) or arguments.get("version") != 1 or not isinstance(arguments.get("input"), dict):
        raise TemplateError("Use version 1 and an input object", code="invalid_command")
    payload = arguments["input"]
    unknown = set(payload) - set(properties)
    missing = [key for key in required if key not in payload]
    if unknown or missing:
        raise TemplateError(f"Invalid input fields; required: {', '.join(required) or 'none'}", code="invalid_command")
    return payload


class TemplateCommands:
    def __init__(self, library: TemplateLibrary) -> None:
        self.library = library

    def _dispatch(self) -> dict[str, Callable[[dict[str, Any]], Any]]:
        lib = self.library
        return {
            "templates.list": lambda p: {"templates": lib.summaries(editor=p.get("editor"), tag=p.get("tag"), query=p.get("query"))},
            "templates.get": lambda p: lib.get(p["id"]),
            "templates.save": lambda p: lib.save(
                workspace=p["workspace"], editor=p["editor"], document=p["document"],
                metadata={key: p[key] for key in SAVE_METADATA if key in p}, include_media=bool(p.get("include_media")),
                preview=p.get("preview"), expected_updated_at=p.get("expected_updated_at")),
            "templates.apply": lambda p: lib.apply(p["id"], workspace=p["workspace"], slots=p.get("slots"), controls=p.get("controls")),
            "templates.export": lambda p: lib.export_to_workspace(p["id"], p["workspace"]),
            "templates.preflight": lambda p: self._preflight(p["workspace"], p["file"]),
            "templates.import": lambda p: lib.import_from_workspace(p["workspace"], p["file"], replace=bool(p.get("replace"))),
            "templates.delete": lambda p: lib.delete(p["id"]),
        }

    def _preflight(self, workspace: str, file: str) -> dict[str, Any]:
        from pathlib import Path
        data = self.library.reader(workspace, Path(file).name)
        if data is None:
            raise TemplateError("File not found in the workspace", status=404, code="not_found")
        return self.library.preflight(data)

    def execute(self, name: str, arguments: Any) -> dict[str, Any]:
        if name not in OPERATIONS:
            raise TemplateError("Unknown template operation", code="invalid_command")
        result = self._dispatch()[name](_payload(arguments, name))
        return {"version": 1, "status": "completed", "operation": name, "result": result}

    def handlers(self) -> dict[str, Callable[[Any], Any]]:
        return {name: self._handler(name) for name in OPERATIONS}

    def _handler(self, name: str) -> Callable[[Any], Any]:
        async def handle(arguments: Any) -> dict[str, Any]:
            from fastapi import HTTPException
            from starlette.concurrency import run_in_threadpool
            try:
                return await run_in_threadpool(self.execute, name, arguments)
            except TemplateError as error:
                raise HTTPException(error.status, {"code": error.code, "message": str(error)}) from error
        return handle


__all__ = ["OPERATIONS", "TemplateCommands", "command_catalog"]
