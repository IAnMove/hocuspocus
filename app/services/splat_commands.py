"""Place a Gaussian-splat file into a workspace and, when asked, into a Video 3D scene.

MCP, REST and the Wizard share ``run``. ``image`` and ``prompt`` are refused:
FlashWorld's weights are CC-BY-NC-SA-4.0. A ``file`` is a .ply or .spz already
in the workspace. The record is ``splat-sets.json``. A scene id adds a splat
slot and stands models that were on the floor (y within 5 cm) on ``floorY``.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from fastapi import HTTPException

from services import core_workspace
from services.mcp_intent import IntentConflict, check_intent_id, intent_digest, load_intent, store_intent
from services.production_splat import LICENCE, SUFFIXES
from services.world3d_scenes import World3DSceneError, inspect_scene, patch_scene

APPLY = "scene3d.splat.apply"
STORE = "splat-sets.json"
_NAME = __import__("re").compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_LOCK = threading.Lock()
_GROUNDED_Y = 0.05


def run(operation: str, arguments: dict, workspace_dir: Callable[[str], str] | None = None) -> dict:
    """One result for MCP and for ``POST /api/v1/scene3d/rooms/commands``."""
    try:
        if operation != APPLY:
            raise ValueError(f"unknown splat operation {operation}")
        if not isinstance(arguments, dict) or arguments.get("version") != 1:
            raise ValueError("version is 1")
        data = arguments.get("input")
        if not isinstance(data, dict):
            raise ValueError("input is an object")
        result = apply_splat(data, arguments.get("intent_id"), workspace_dir or core_workspace.workspace_dir)
        return {"version": 1, "operation": APPLY, "status": "completed", "result": result}
    except IntentConflict as error:
        raise HTTPException(409, str(error)) from error
    except World3DSceneError as error:
        raise HTTPException(error.status, str(error)) from error
    except (ValueError, KeyError, OSError) as error:
        raise HTTPException(422, str(error)) from error


def apply_splat(data: dict, intent_id: Any, workspace_dir: Callable[[str], str]) -> dict:
    """Store one splat file. The same intent returns the stored result."""
    workspace = data.get("workspace")
    if not isinstance(workspace, str) or not workspace:
        raise ValueError("workspace is required")
    root = Path(workspace_dir(workspace))
    name = data.get("name") or "splat"
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("name matches ^[a-z0-9][a-z0-9_-]{0,63}$")
    record = _record(root, workspace, name, data)
    intent = check_intent_id(intent_id)
    digest = intent_digest({"workspace": workspace, "name": name, "file": record["file"], "floorY": record["floorY"],
                            "scale": record["scale"], "scene_id": data.get("scene_id") or data.get("sceneId")})
    with _LOCK:
        stored = load_intent(root, APPLY, intent, digest)
        if stored is not None:
            return stored
        _write(root, name, record)
        scene_id = data.get("scene_id") or data.get("sceneId")
        if scene_id:
            record = {**record, "scene": _place(workspace, str(scene_id), name, record, data, workspace_dir)}
        store_intent(root, APPLY, intent, digest, record)
    return record


def command_catalog() -> list[dict]:
    source = {"type": "string"}
    put_input = {"type": "object", "additionalProperties": False, "required": ["workspace"],
                 "properties": {"workspace": {"type": "string"}, "name": {"type": "string"},
                                "file": source, "image": source, "prompt": source,
                                "floorY": {"type": "number"}, "scale": {"type": "number"},
                                "position": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                                "rotationY": {"type": "number"},
                                "scene_id": {"type": "string"}, "sceneId": {"type": "string"}}}
    return [{"name": APPLY, "version": 1, "domain": "scenes", "mutation": True, "destructive": False,
             "description": "Place a Gaussian splat already in the workspace (.ply or .spz) as a Video 3D set. "
                            "image and prompt are refused: FlashWorld weights are CC-BY-NC-SA-4.0 and are not integrated. "
                            "Writes splat-sets.json. With scene_id, adds a splat object and stands the cast that was on the floor.",
             "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "intent_id", "input"],
                             "properties": {"version": {"const": 1}, "intent_id": {"type": "string"}, "input": put_input}}}]


def command_handlers(workspace_dir: Callable[[str], str] | None = None) -> dict:
    async def handler(arguments):
        return run(APPLY, arguments, workspace_dir)
    return {APPLY: handler}


def _record(root: Path, workspace: str, name: str, data: dict) -> dict:
    sources = [key for key in ("file", "image", "prompt") if data.get(key) not in (None, "")]
    if len(sources) != 1:
        raise ValueError("give exactly one of file, image or prompt")
    if sources[0] != "file":
        raise ValueError(LICENCE)
    relative = _relative(data.get("file"))
    path = root / relative if relative else None
    if relative is None or Path(relative).suffix.lower() not in SUFFIXES or path is None or not path.is_file():
        raise ValueError("file is a .ply or .spz inside the workspace")
    floor_y = _number(data.get("floorY", 0), -50, 50, "floorY")
    scale = _number(data.get("scale", 1), 0.05, 100, "scale")
    return {"name": name, "kind": "splat", "file": relative, "floorY": floor_y, "scale": scale,
            "url": f"/api/v1/file/{quote(relative)}?workspace={quote(workspace)}"}


def _place(workspace: str, scene_id: str, name: str, record: dict, data: dict, workspace_dir) -> dict:
    view = inspect_scene(workspace, scene_id, workspace_dir)
    floor_y = record["floorY"]
    position = _position(data.get("position"), floor_y)
    bindings = [_lift(slot, floor_y) for slot in view["document"].get("slots") or []]
    bindings.append({"add": True, "objectId": f"set-{name}", "media": "splat", "sourceUrl": record["url"],
                     "position": position, "rotationY": _number(data.get("rotationY", 0), -7, 7, "rotationY"),
                     "scale": record["scale"], "splat": {"floorY": floor_y}})
    patched = patch_scene(workspace, scene_id, workspace_dir, {"bindings": [item for item in bindings if item]}, view["revision"])
    return {"sceneId": scene_id, "revision": patched["revision"], "objectId": f"set-{name}"}


def _lift(slot: dict, floor_y: float) -> dict | None:
    if (slot.get("media") or "model3d") != "model3d" or slot.get("grounded") is False:
        return None
    position = slot.get("position") or [0, 0, 0]
    if not isinstance(position, list) or len(position) != 3 or abs(float(position[1])) > _GROUNDED_Y:
        return None
    return {"objectId": slot["id"], "grounded": True, "position": [position[0], floor_y, position[2]]}


def _write(root: Path, name: str, record: dict) -> None:
    path = root / STORE
    current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    sets = current.get("sets") if isinstance(current, dict) else {}
    if not isinstance(sets, dict):
        sets = {}
    sets[name] = record
    path.write_text(json.dumps({"sets": sets}, indent=2), encoding="utf-8")


def _relative(value: Any) -> str | None:
    from services.production_models import workspace_rel
    return workspace_rel(value) if isinstance(value, str) else None


def _number(value: Any, low: float, high: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= float(value) <= high:
        raise ValueError(f"{label} is from {low} to {high}")
    return float(value)


def _position(value: Any, floor_y: float) -> list[float]:
    if value is None:
        return [0.0, floor_y, 0.0]
    if not isinstance(value, list) or len(value) != 3 or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise ValueError("position is [x, y, z] in metres")
    return [float(item) for item in value]
