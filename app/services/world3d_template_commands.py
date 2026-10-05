"""MCP, HTTP and Wizard entry for the shared Video 3D template library."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from services.mcp_intent import IntentConflict, check_intent_id, intent_digest, load_intent, store_intent
from services.scene_documents import WORKSPACE_RE
from services.world3d_scenes import (
    World3DSceneError, compile_template_document, inspect_scene, instantiate_template, patch_scene, preview_scene,
    publish_scene, put_user_template, talk_scene,
)
from services.world3d_template_catalog import (
    CATALOG_OPERATION, World3DTemplateError, require_card, search_templates, user_template_document,
)

_LOCK = threading.RLock()
_ID = {"type": "string", "minLength": 1, "maxLength": 120}
_WORKSPACE = {"type": "string", "pattern": WORKSPACE_RE.pattern}
_MUTATIONS = {
    "world3d.scene.instantiate", "world3d.scene.patch", "world3d.scene.publish",
    "world3d.scene.apply_query", "world3d.templates.user.put", "world3d.scene.talk",
}
_OPERATIONS = {
    "world3d.templates.list": (False, "Search Video 3D shots. Returns at most 8 short cards unless limit is set, never the whole library.", {"query": {"type": "string"}, "category": {"type": "string"}, "language": {"enum": ["es", "en"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 24}}, []),
    CATALOG_OPERATION: (False, "Bounded Video 3D template search shared with list. Does not dump every description.", {"query": {"type": "string"}, "category": {"type": "string"}, "language": {"enum": ["es", "en"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 24}}, []),
    "world3d.templates.get": (False, "Return one exact Video 3D template card and its editable document. Unknown ids fail and never fall back to another shot.", {"template_id": _ID}, ["template_id"]),
    "world3d.templates.user.put": (True, "Register a personal Video 3D template in the workspace. Browser localStorage is left untouched. Ids must start with user-.", {"id": _ID, "title": {"type": "string"}, "description": {"type": "string"}, "document": {"type": "object"}}, ["id", "title", "document"]),
    "world3d.scene.instantiate": (True, "Create an editable scene from an exact template id.", {"template_id": _ID}, ["template_id"]),
    "world3d.scene.inspect": (False, "List object ids, markers, traits and the current revision.", {"scene_id": _ID}, ["scene_id"]),
    "world3d.scene.patch": (True, "Bind resources by object id, or by role only when that role is unique. Requires base_revision.", {"scene_id": _ID, "base_revision": {"type": "integer", "minimum": 1}, "bindings": {"type": "array", "description": "{object_id or role, source_url, media, clip {index, name}, clipPlayback {speed, start, loop}, position, rotationY (radians), scale, motion}. add: true creates a new prop object (model3d or image cutout) with that id when the template has none."}, "camera": {"type": "object"}, "playbackSpeed": {"type": "number"}, "duration": {"type": "number"}, "retime": {"type": "boolean", "description": "With duration: stretch the template's effects, texts, appearances and clip cues to the new length."}, "soundtrack": {"type": "array", "maxItems": 32, "description": "The scene's own sound (ids scene-*: ambience, stinger, music): {id, audio (workspace or upload URL), start, gain}. Talk tracks stay."}}, ["scene_id", "base_revision"]),
    "world3d.scene.talk": (True, "Make an image object talk as a Character Kit cutout: its approved pose, the mouth drawing for each cue (audio.mouth_cues output, Rhubarb A-H/X) and its blink. Each line has start (scene seconds), cues and optionally audio (a workspace or upload URL) that joins the scene soundtrack. Calling it again replaces that object's lines. Requires base_revision.", {"scene_id": _ID, "base_revision": {"type": "integer", "minimum": 1}, "object_id": _ID, "role": {"type": "string"}, "kit_id": _ID, "pose": {"type": "string", "maxLength": 120}, "blink": {"type": "boolean"}, "lines": {"type": "array", "maxItems": 24, "items": {"type": "object", "additionalProperties": False, "required": ["start", "cues"], "properties": {"start": {"type": "number", "minimum": 0, "maximum": 600}, "cues": {"type": "array", "maxItems": 10000}, "audio": {"type": ["string", "object"]}, "gain": {"type": "number", "minimum": 0, "maximum": 1}}}}}, ["scene_id", "base_revision", "kit_id", "lines"]),
    "world3d.scene.preview": (False, "Paint cheap frames of the modified revision at concrete times. The frames are this scene, not the template thumbnail.", {"scene_id": _ID, "times": {"type": "array"}, "expected_revision": {"type": "integer"}}, ["scene_id"]),
    "world3d.scene.publish": (True, "Save the working scene through the editor gallery so export reads the same document.", {"scene_id": _ID}, ["scene_id"]),
    "world3d.scene.apply_query": (True, "Search and instantiate only when the top card strictly outranks the next. Otherwise return the cards and create nothing.", {"query": {"type": "string"}, "category": {"type": "string"}, "language": {"enum": ["es", "en"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 24}}, ["query"]),
    "world3d.receipt": (False, "Recover a stored Video 3D mutation after a lost response. Reuse the original intent_id.", {"operation": {"enum": sorted(_MUTATIONS)}, "intent_id": {"type": "string"}}, ["operation", "intent_id"]),
}


def command_catalog():
    result = []
    for name, (mutation, description, properties, required) in _OPERATIONS.items():
        envelope = {"version": {"type": "integer", "const": 1}, "input": {"type": "object", "additionalProperties": False,
                    "properties": {"workspace": _WORKSPACE, **properties}, "required": ["workspace", *required]}}
        keys = ["version", "input"]
        if mutation:
            envelope["intent_id"] = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$"}
            keys.append("intent_id")
        result.append({"name": name, "version": 1, "domain": "scenes", "mutation": mutation,
                       "receipt_tool": "world3d.receipt", "destructive": False, "description": description,
                       "inputSchema": {"type": "object", "additionalProperties": False, "properties": envelope, "required": keys}})
    return result


def execute_command(name, arguments, workspace_dir):
    try:
        if name not in _OPERATIONS:
            raise World3DSceneError("unknown_operation", f"unknown_operation:{name}")
        data = _input(arguments)
        _workspace(data)
        if name == "world3d.receipt":
            return _completed(name, _receipt(data, workspace_dir))
        if name in _MUTATIONS:
            return _mutate(name, arguments, data, workspace_dir)
        return _completed(name, _effect(name, data, workspace_dir))
    except (World3DTemplateError, World3DSceneError, IntentConflict) as exc:
        raise HTTPException(getattr(exc, "status", 409), detail={"code": getattr(exc, "code", "intent_conflict"), "message": str(exc)}) from exc


def command_handlers(workspace_dir):
    def handler(operation):
        async def run(arguments):
            return await run_in_threadpool(execute_command, operation, arguments, workspace_dir)
        return run
    return {operation: handler(operation) for operation in _OPERATIONS}


def _effect(name, data, workspace_dir):
    if name in {"world3d.templates.list", CATALOG_OPERATION}:
        return _search(data, workspace_dir)
    if name == "world3d.templates.get":
        return _get(data, workspace_dir)
    if name == "world3d.scene.inspect":
        return {"status": "completed", "scene": inspect_scene(data["workspace"], data["scene_id"], workspace_dir)}
    if name == "world3d.scene.preview":
        return _preview(data, workspace_dir)
    if name == "world3d.scene.instantiate":
        return {"status": "completed", "scene": instantiate_template(data["workspace"], data["template_id"], workspace_dir)}
    if name == "world3d.scene.patch":
        return {"status": "completed", "scene": patch_scene(data["workspace"], data["scene_id"], workspace_dir, data, data["base_revision"])}
    if name == "world3d.scene.talk":
        return {"status": "completed", "scene": talk_scene(data["workspace"], data["scene_id"], workspace_dir, data, data["base_revision"])}
    if name == "world3d.scene.publish":
        return {"status": "completed", "scene": publish_scene(data["workspace"], data["scene_id"], workspace_dir)}
    if name == "world3d.scene.apply_query":
        return _apply_query(data, workspace_dir)
    if name == "world3d.templates.user.put":
        stored = put_user_template(data["workspace"], workspace_dir, data)
        return {"status": "completed", "template": stored}
    raise World3DSceneError("unknown_operation", f"unknown_operation:{name}")


def _search(data, workspace_dir):
    cards = search_templates(str(data.get("query") or ""), category=data.get("category") or None, language=data.get("language") or None,
                             limit=data.get("limit"), workspace_dir=workspace_dir, workspace=data["workspace"])
    return {"status": "completed", "templates": cards}


def _get(data, workspace_dir):
    template_id = data.get("template_id")
    card = require_card(template_id, workspace_dir=workspace_dir, workspace=data["workspace"])
    document = user_template_document(template_id, workspace_dir, data["workspace"]) if card.get("source") == "workspace" else compile_template_document(template_id)
    return {"status": "completed", "card": card, "document": document, "objects": [
        {"id": slot.get("id"), "role": slot.get("slot"), "media": slot.get("media"), "sourceUrl": slot.get("sourceUrl") or "",
         "marker": not slot.get("sourceUrl")} for slot in document.get("slots") or [] if isinstance(slot, dict)]}


def _preview(data, workspace_dir):
    rendered = preview_scene(data["workspace"], data["scene_id"], workspace_dir, times=data.get("times"),
                             expected_revision=data.get("expected_revision"))
    return {"status": "completed", **rendered}


def _apply_query(data, workspace_dir):
    hits = search_templates(str(data.get("query") or ""), category=data.get("category") or None, language=data.get("language") or None,
                            limit=data.get("limit"), workspace_dir=workspace_dir, workspace=data["workspace"])
    if not hits:
        return {"status": "not_found", "candidates": [], "chosenId": None, "scene": None}
    if len(hits) > 1 and hits[0]["score"] == hits[1]["score"]:
        return {"status": "needs_choice", "candidates": hits, "chosenId": None, "scene": None}
    scene = instantiate_template(data["workspace"], hits[0]["id"], workspace_dir)
    return {"status": "completed", "candidates": hits, "chosenId": hits[0]["id"], "scene": scene}


def _input(arguments):
    if not isinstance(arguments, dict) or arguments.get("version") != 1 or not isinstance(arguments.get("input"), dict):
        raise World3DSceneError("invalid_command", "Use version 1 and an input object")
    return arguments["input"]


def _workspace(data):
    workspace = data.get("workspace")
    if not isinstance(workspace, str) or not WORKSPACE_RE.fullmatch(workspace):
        raise World3DSceneError("invalid_workspace", "Use an explicit valid workspace")
    return workspace


def _mutate(name, arguments, data, workspace_dir):
    intent = check_intent_id(arguments.get("intent_id"))
    digest = intent_digest(data)
    root = Path(workspace_dir(data["workspace"]))
    with _LOCK:
        prior = load_intent(root, name, intent, digest)
        if prior is not None:
            return _completed(name, prior, replayed=True)
        result = _effect(name, data, workspace_dir)
        store_intent(root, name, intent, digest, result)
    return _completed(name, result)


def _completed(name, result, replayed=False):
    status = result.get("status") if isinstance(result, dict) and result.get("status") in {"completed", "needs_choice", "not_found"} else "completed"
    body = {"version": 1, "operation": name, "status": status, "result": result}
    if isinstance(result, dict) and result.get("images"):
        body["images"] = result["images"]
    if replayed:
        body["replayed"] = True
    return body


def _receipt(data, workspace_dir):
    operation = data.get("operation")
    if operation not in _MUTATIONS:
        raise World3DSceneError("invalid_command", "Choose a Video 3D mutation")
    intent = check_intent_id(data.get("intent_id"))
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", operation).strip("-") or "operation"
    path = Path(workspace_dir(data["workspace"])) / ".mcp-intents" / safe / f"{intent}.json"
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise World3DSceneError("receipt_missing", "Video 3D receipt not found", 404) from error
    except (OSError, ValueError) as error:
        raise World3DSceneError("receipt_missing", "Video 3D receipt is unreadable", 409) from error
    result = stored.get("result") if isinstance(stored, dict) else None
    if not isinstance(result, dict):
        raise World3DSceneError("receipt_missing", "Video 3D receipt is unreadable", 409)
    return result
