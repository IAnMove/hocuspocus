"""Create and read a metric box room. MCP, REST and the Wizard share ``run``.

``put`` writes ``scene3d-rooms.json`` and a flat-colour placeholder GLB. It does not call an image model.
A production ``spec.sets`` entry is still the path that paints textures.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from services import core_workspace
from services.mcp_intent import IntentConflict, check_intent_id, intent_digest, load_intent, store_intent
from services.prop_library import atomic_json
from services.room_box import normalize, placeholder_room, valid_name

PUT = "scene3d.room.put"
GET = "scene3d.room.get"
STORE = "scene3d-rooms.json"
_LOCK = threading.RLock()


def put_room(workspace: str, name: str, room: dict, intent_id: str) -> dict:
    """Store one normalised room and its placeholder GLB. The same intent returns the stored result."""
    _named(name)
    if not isinstance(room, dict):
        raise ValueError("room is an object")
    spec = normalize(room)
    intent = check_intent_id(intent_id)
    root = Path(core_workspace.workspace_dir(workspace))
    payload = {"workspace": workspace, "name": name, "room": room}
    digest = intent_digest(payload)
    with _LOCK:
        stored = load_intent(root, PUT, intent, digest)
        if stored is not None:
            return stored
        file = f"rooms/{name}.glb"
        placeholder_room(root / file, spec)
        library = _read(root)
        library.setdefault("rooms", {})[name] = {"spec": spec, "file": file}
        atomic_json(root / STORE, library)
        result = {"name": name, "file": file, "room": spec}
        store_intent(root, PUT, intent, digest, result)
    return result


def get_room(workspace: str, name: str) -> dict:
    """The stored room, or an error that names it."""
    _named(name)
    root = Path(core_workspace.workspace_dir(workspace))
    record = (_read(root).get("rooms") or {}).get(name)
    if not isinstance(record, dict) or not isinstance(record.get("spec"), dict):
        raise ValueError(f"unknown room {name}")
    return {"name": name, "file": record.get("file"), "room": record["spec"]}


def run(operation: str, arguments: dict) -> dict:
    """One result for MCP and for ``POST /api/v1/scene3d/rooms/commands``."""
    try:
        if not isinstance(arguments, dict) or arguments.get("version") != 1:
            raise ValueError("version is 1")
        data = arguments["input"]
        if not isinstance(data, dict):
            raise ValueError("input is an object")
        if operation == PUT:
            result = put_room(data["workspace"], data["name"], data["room"], arguments.get("intent_id"))
        elif operation == GET:
            result = get_room(data["workspace"], data["name"])
        else:
            raise ValueError(f"unknown room operation {operation}")
        return {"version": 1, "operation": operation, "status": "completed", "result": result}
    except IntentConflict as error:
        raise HTTPException(409, str(error)) from error
    except (ValueError, KeyError, OSError) as error:
        raise HTTPException(422, str(error)) from error


def command_catalog() -> list[dict[str, Any]]:
    room = {"type": "object", "description": "kind room, size {w, d, h} in metres, floor, walls, door, windows, props. No mold."}
    common = {"workspace": {"type": "string"}, "name": {"type": "string"}}
    put_input = {"type": "object", "additionalProperties": False, "required": ["workspace", "name", "room"],
                 "properties": {**common, "room": room}}
    get_input = {"type": "object", "additionalProperties": False, "required": ["workspace", "name"], "properties": common}
    return [
        _operation(PUT, True, "Store a metric box room and a flat-colour placeholder GLB. Does not paint textures.",
                   ["version", "intent_id", "input"], {"intent_id": {"type": "string"}, "input": put_input}),
        _operation(GET, False, "Read a metric box room stored by scene3d.room.put.",
                   ["version", "input"], {"input": get_input}),
    ]


def command_handlers() -> dict:
    def make(operation: str):
        async def handler(arguments):
            return run(operation, arguments)
        return handler
    return {PUT: make(PUT), GET: make(GET)}


def _operation(name: str, mutation: bool, description: str, required: list[str], properties: dict) -> dict:
    return {"name": name, "version": 1, "domain": "scenes", "mutation": mutation, "destructive": False,
            "description": description,
            "inputSchema": {"type": "object", "additionalProperties": False, "required": required,
                             "properties": {"version": {"const": 1}, **properties}}}


def _named(name: str) -> None:
    if not valid_name(name):
        raise ValueError("name matches ^[a-z0-9][a-z0-9_-]{0,63}$")


def _read(root: Path) -> dict:
    path = root / STORE
    if not path.is_file():
        return {"rooms": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("rooms"), dict):
        raise ValueError("scene3d-rooms.json is unreadable")
    return data
