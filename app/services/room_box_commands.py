"""Create, read and paint a metric box room. MCP, REST and the Wizard share ``run``.

``put`` writes ``scene3d-rooms.json`` and the room's GLB, already wearing a procedural material on every surface (floor, walls,
ceiling, door, trim: chosen from the words of the spec, no model, no GPU). ``paint`` replaces those with pictures from the image
model, as a job in the background; ``paint.status`` tells how it is going. A production ``spec.sets`` entry is the other path
that paints textures.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from services import core_workspace, room_paint, room_plate_commands, room_store
from services.mcp_intent import IntentConflict, check_intent_id, intent_digest, load_intent, store_intent
from services.room_box import normalize, valid_name

PUT = "scene3d.room.put"
GET = "scene3d.room.get"
PAINT = "scene3d.room.paint"
PAINT_STATUS = "scene3d.room.paint.status"
STORE = room_store.STORE
_LOCK = room_store.LOCK


def _root(workspace: str) -> Path:
    return Path(core_workspace.workspace_dir(workspace))


def _result(name: str, record: dict) -> dict:
    paint = record.get("paint") or {}
    result = {"name": name, "file": record.get("file"), "room": record["spec"], "surfaces": room_store.summary(record),
              "paint": {"status": paint.get("status", "not_painted"), "look": room_store.look_of(record)}}
    warnings = room_plate_commands.warnings_of(record["spec"])
    return {**result, "warnings": warnings} if warnings else result


def put_room(workspace: str, name: str, room: dict, intent_id: str) -> dict:
    """Store one normalised room and its GLB. The same intent returns the stored result; the same room again keeps its paint."""
    _named(name)
    if not isinstance(room, dict):
        raise ValueError("room is an object")
    root = _root(workspace)
    spec = normalize(room_plate_commands.read_room(root, workspace, room))
    intent = check_intent_id(intent_id)
    digest = intent_digest({"workspace": workspace, "name": name, "room": room})
    with _LOCK:
        stored = load_intent(root, PUT, intent, digest)
        if stored is not None:
            return stored
        library = room_store.read(root)
        record = library.setdefault("rooms", {}).get(name)
        if not (isinstance(record, dict) and record.get("spec") == spec and "surfaces" in record and (root / str(record.get("file"))).is_file()):
            record = room_store.new_record(root, name, spec)
            library["rooms"][name] = record
            room_store.write(root, library)
        result = _result(name, record)
        store_intent(root, PUT, intent, digest, result)
    return result


def get_room(workspace: str, name: str) -> dict:
    """The stored room, or an error that names it."""
    _named(name)
    record = room_store.record_of(_root(workspace), name)
    if record is None:
        raise ValueError(f"unknown room {name}")
    return _result(name, record)


def paint_room(data: dict, intent_id: str, call: Callable | None) -> dict:
    """Start painting a stored room (see ``room_paint``). The same intent returns the receipt it first got."""
    name = data["name"]
    _named(name)
    intent = check_intent_id(intent_id)
    root = _root(data["workspace"])
    digest = intent_digest(data)
    with _LOCK:
        stored = load_intent(root, PAINT, intent, digest)
        if stored is not None:
            return stored
        result = _paint(call, data["workspace"], root, name, data)
        store_intent(root, PAINT, intent, digest, result)
    return result


def _paint(call: Callable | None, workspace: str, root: Path, name: str, data: dict) -> dict:
    """A picture is the paint of a plate room (no model); words are painted by the image model."""
    record = room_store.record_of(root, name)
    plate = bool(record and record["spec"].get("plate"))
    if room_plate_commands.wants_picture(data) or plate:
        if plate and not room_plate_commands.wants_picture(data):
            raise ValueError("this room's walls are a picture, so there is nothing to paint with words: give walls {file} (or back, left, right) "
                             "to change its pictures, or stage, fov or range to change its camera")
        return room_plate_commands.paint_plate(root, workspace, name, data)
    return room_paint.paint(call, workspace, root, name, data)


def paint_status(data: dict) -> dict:
    name = data["name"]
    _named(name)
    return room_paint.status(_root(data["workspace"]), name)


def run(operation: str, arguments: dict, call: Callable | None = None) -> dict:
    """One result for MCP and for ``POST /api/v1/scene3d/rooms/commands``. ``call`` reaches the image model for ``paint``."""
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
        elif operation == PAINT:
            result = paint_room(data, arguments.get("intent_id"), call)
        elif operation == PAINT_STATUS:
            result = paint_status(data)
        else:
            raise ValueError(f"unknown room operation {operation}")
        return {"version": 1, "operation": operation, "status": "completed", "result": result}
    except IntentConflict as error:
        raise HTTPException(409, str(error)) from error
    except (ValueError, KeyError, OSError) as error:
        raise HTTPException(422, str(error)) from error


def command_catalog() -> list[dict[str, Any]]:
    room = {"type": "object", "description": "kind room, size {w, d, h} in metres, floor, walls, door, windows, props. No mold. walls may be a "
            "picture {file} of the workspace (a painted plate): then the room is the plate's own view with a floor to walk on in front of it, "
            "its size comes from the plate, and stage {horizon, ref: {baseY, heightPct, heightM}, floorTop?} (fractions of the plate's height), "
            "fov and range {orbit_deg, shift_m} describe it. A prop takes image {file}, a PNG with alpha, to hide a person who walks behind it."}
    common = {"workspace": {"type": "string"}, "name": {"type": "string"}}
    put_input = {"type": "object", "additionalProperties": False, "required": ["workspace", "name", "room"],
                 "properties": {**common, "room": room}}
    get_input = {"type": "object", "additionalProperties": False, "required": ["workspace", "name"], "properties": common}
    words = {"type": "string", "description": "Words for the surface, e.g. \"worn green linoleum\"."}
    picture = {"type": "object", "description": "A picture of the workspace: {file} or {asset}."}
    paint_input = {"type": "object", "additionalProperties": False, "required": ["workspace", "name"], "properties": {
        **common,
        "style": {"type": "string", "description": "A look for every material, e.g. \"1950s space hangar\". Kept short: a scene makes the model draw perspective."},
        "floor": words, "ceiling": words,
        "walls": {"description": "Words for the walls or, in a plate room, a picture: {file}, or {back, left, right} pictures. A picture is the paint: "
                  "no model is called.", "anyOf": [{"type": "string"}, picture]},
        "back": picture, "left": picture, "right": picture,
        "stage": {"type": "object", "description": "A plate room's perspective: {horizon, ref: {baseY, heightPct, heightM}, floorTop?}."},
        "fov": {"type": "number", "description": "A plate room's vertical lens in degrees (48 by default)."},
        "range": {"type": "object", "description": "A plate room's camera range: {orbit_deg, shift_m}."},
        "door": {"type": "string", "description": "The door leaf seen from the front, e.g. \"hangar door with warning stripes\"."},
        "trim": {"type": "string", "description": "Skirting, cornice and door frame."},
        "tile_m": {"type": "object", "description": "Metres one repeat of a surface covers: {floor, walls, ceiling, trim}."},
        "seed": {"type": "integer", "minimum": 0},
        "engine": {"enum": ["ai", "procedural"], "description": "ai (default): the image model, in the background. procedural: no model, at once."}}}
    return [
        _operation(PUT, True, "Store a metric box room and its GLB, already wearing a procedural material on every surface (or, when walls is a picture of the workspace, built from that plate). Does not call a model.",
                   ["version", "intent_id", "input"], {"intent_id": {"type": "string"}, "input": put_input}),
        _operation(GET, False, "Read a metric box room stored by scene3d.room.put: its spec, what each surface wears and the paint state.",
                   ["version", "input"], {"input": get_input}),
        _operation(PAINT, True, "Paint a stored box room with the image model (Qwen Image 2.1): a seamless floor, walls, ceiling and trim "
                   "and a door, each at its real metres per repeat. A background job: poll scene3d.room.paint.status. A surface the model cannot paint keeps its procedural material. "
                   "A plate room (walls was a picture) is painted with pictures instead, at once and with no model: walls {file}, back, left, right, stage, fov, range.",
                   ["version", "intent_id", "input"], {"intent_id": {"type": "string"}, "input": paint_input}),
        _operation(PAINT_STATUS, False, "The state of a room's paint: status, warnings, and what each surface wears.",
                   ["version", "input"], {"input": get_input}),
    ]


def command_handlers(call: Callable | None = None) -> dict:
    def make(operation: str):
        async def handler(arguments):
            return run(operation, arguments, call)
        return handler
    return {operation: make(operation) for operation in (PUT, GET, PAINT, PAINT_STATUS)}


def _operation(name: str, mutation: bool, description: str, required: list[str], properties: dict) -> dict:
    return {"name": name, "version": 1, "domain": "scenes", "mutation": mutation, "destructive": False,
            "description": description,
            "inputSchema": {"type": "object", "additionalProperties": False, "required": required,
                             "properties": {"version": {"const": 1}, **properties}}}


def _named(name: str) -> None:
    if not valid_name(name):
        raise ValueError("name matches ^[a-z0-9][a-z0-9_-]{0,63}$")
