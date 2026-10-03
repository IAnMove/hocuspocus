"""Editable Video 3D scenes addressed by object id.

The working copy lives under the workspace. Publishing uses the same gallery
save as the editor, so export reads that document rather than a second library.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from copy import deepcopy
from pathlib import Path

from services.scene_documents import get_document, save_document
from services.world3d_template_catalog import require_card, user_template_document

_ROOT = Path(__file__).resolve().parents[2]
_EDITS = "world3d-edits"
_COMPILED: dict[str, dict] = {}
_SLOT_FIELDS = {"sourceUrl", "sourceRef", "clip", "position", "rotationY", "scale", "motion", "grounded", "media"}
_SCREEN_SOURCE_FIELDS = {"sourceUrl", "sourceRef"}
_CAMERA_FIELDS = {"family", "fov", "eye", "look", "orbitRadius", "orbitHeight", "orbitTurns", "framing", "eyeOffset", "targetOffset", "frameFormat"}


class World3DSceneError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        self.code = code
        self.status = status
        super().__init__(message)


def instantiate_template(workspace: str, template_id: str, workspace_dir) -> dict:
    card = require_card(template_id, workspace_dir=workspace_dir, workspace=workspace)
    document = user_template_document(template_id, workspace_dir, workspace) if card.get("source") == "workspace" else compile_template_document(template_id)
    scene_id = "w3d-" + uuid.uuid4().hex[:12]
    record = {"revision": 1, "templateId": document.get("templateId") or template_id, "document": document, "warnings": []}
    _write(workspace, scene_id, record, workspace_dir)
    return _view(scene_id, record)


def inspect_scene(workspace: str, scene_id: str, workspace_dir) -> dict:
    return _view(scene_id, _read(workspace, scene_id, workspace_dir))


def patch_scene(workspace: str, scene_id: str, workspace_dir, changes: dict, base_revision: int) -> dict:
    record = _read(workspace, scene_id, workspace_dir)
    if type(base_revision) is not int or base_revision != record["revision"]:
        raise World3DSceneError("revision_conflict", "The scene changed since this revision. Reload before editing.", 409)
    document = record["document"]
    warnings = []
    for binding in _bindings(changes):
        warnings.extend(_bind(document, binding))
    if isinstance(changes.get("camera"), dict):
        document["camera"] = {**document["camera"], **{key: deepcopy(value) for key, value in changes["camera"].items() if key in _CAMERA_FIELDS}}
    if "playbackSpeed" in changes or "playback_speed" in changes:
        document["playbackSpeed"] = _speed(changes.get("playbackSpeed", changes.get("playback_speed")))
    if "duration" in changes:
        duration = changes["duration"]
        if type(duration) not in (int, float) or not 0 < duration <= 600:
            raise World3DSceneError("invalid_duration", "duration must be between 0 and 600 seconds")
        document["duration"] = duration
    _retarget(document)
    record["revision"] += 1
    record["warnings"] = warnings
    record["templateId"] = document.get("templateId") or record["templateId"]
    _write(workspace, scene_id, record, workspace_dir)
    viewed = _view(scene_id, record)
    viewed["warnings"] = warnings
    return viewed


def preview_scene(workspace: str, scene_id: str, workspace_dir, *, times=None, expected_revision: int | None = None) -> dict:
    record = _read(workspace, scene_id, workspace_dir)
    if expected_revision is not None and expected_revision != record["revision"]:
        raise World3DSceneError("revision_conflict", "Preview revision does not match the scene.", 409)
    rendered = _run_tool("preview", json.dumps({"document": record["document"], "times": times}))
    frames = rendered.get("frames") or []
    return {
        "sceneId": scene_id, "revision": record["revision"], "templateId": record["templateId"],
        "times": [frame.get("time") for frame in frames], "frames": frames,
        "pending": rendered.get("pending") or _pending(record["document"]),
        "loadErrors": rendered.get("loadErrors") or [],
        "images": [{"mimeType": "image/png", "data": frame.get("png")} for frame in frames if frame.get("png")],
    }


def publish_scene(workspace: str, scene_id: str, workspace_dir) -> dict:
    record = _read(workspace, scene_id, workspace_dir)
    saved = save_document(workspace, record["document"], name=scene_id, preview=None, workspace_dir=workspace_dir)
    opened = get_document(workspace, saved["name"], workspace_dir=workspace_dir)
    traits = _traits(opened["document"])
    return {"sceneId": scene_id, "revision": record["revision"], "file": saved["name"], "url": saved.get("url"),
            "editor": opened.get("editor"), "document": opened["document"], "traits": traits}


def put_user_template(workspace: str, workspace_dir, row: dict) -> dict:
    template_id = row.get("id")
    title = row.get("title")
    document = row.get("document")
    if not isinstance(template_id, str) or not template_id.startswith("user-"):
        raise World3DSceneError("invalid_user_template", "Personal template ids start with user-")
    if template_id in {card["id"] for card in require_builtin_ids()}:
        raise World3DSceneError("invalid_user_template", "A personal id cannot replace a built-in template")
    if not isinstance(title, str) or not title.strip():
        raise World3DSceneError("invalid_user_template", "A personal template needs a title")
    if not isinstance(document, dict) or not isinstance(document.get("slots"), list):
        raise World3DSceneError("invalid_user_template", "A personal template needs a Video 3D document")
    path = Path(workspace_dir(workspace))
    path.mkdir(parents=True, exist_ok=True)
    target = path / "world3d-user-templates.json"
    current = {"templates": []}
    if target.is_file():
        current = json.loads(target.read_text(encoding="utf-8"))
    rows = [item for item in current.get("templates") or [] if not (isinstance(item, dict) and item.get("id") == template_id)]
    stored = {"id": template_id, "title": title.strip()[:80], "description": str(row.get("description") or "")[:240],
              "document": document}
    rows.append(stored)
    _atomic(target, {"version": 1, "templates": rows})
    return {"id": template_id, "source": "workspace", "title": stored["title"]}


def compile_template_document(template_id: str) -> dict:
    cached = _COMPILED.get(template_id)
    if cached is not None:
        return deepcopy(cached)
    require_card(template_id)
    try:
        document = _run_tool("document", None, template_id)
    except World3DSceneError as error:
        if "unknown_template:" in str(error):
            raise World3DSceneError("unknown_template", f"unknown_template:{template_id}", 404) from error
        raise
    _COMPILED[template_id] = document
    return deepcopy(document)


def require_builtin_ids() -> list[dict]:
    from services.world3d_template_catalog import builtin_cards
    return list(builtin_cards())


def _bindings(changes: dict) -> list[dict]:
    bindings = changes.get("bindings") or []
    if not isinstance(bindings, list) or any(not isinstance(item, dict) for item in bindings):
        raise World3DSceneError("invalid_patch", "bindings must be a list of objects")
    return bindings


def _bind(document: dict, binding: dict) -> list[str]:
    slot = _target(document["slots"], binding)
    warnings = _clip_warning(slot, binding)
    for key in _SLOT_FIELDS:
        snake = _snake(key)
        if key in binding:
            slot[key] = deepcopy(binding[key])
        elif snake in binding:
            slot[key] = deepcopy(binding[snake])
    _bind_screen(slot, binding)
    return warnings


def _bind_screen(slot: dict, binding: dict) -> None:
    """Screens render `screen.sourceUrl`, not the slot-root URL the API accepts."""
    if slot.get("media") != "screen":
        return
    updates = {}
    for key in _SCREEN_SOURCE_FIELDS:
        if key in binding or _snake(key) in binding:
            updates[key] = deepcopy(slot.get(key))
    if not updates:
        return
    screen = slot.get("screen")
    if not isinstance(screen, dict):
        screen = {}
        slot["screen"] = screen
    screen.update(updates)


def _clip_warning(slot: dict, binding: dict) -> list[str]:
    clips = binding.get("clips")
    current = slot.get("clip")
    name = current.get("name") if isinstance(current, dict) else None
    if isinstance(clips, list):
        if name and name not in clips:
            slot["clip"] = None
            return [f"incompatible_clip:{slot.get('id')}:{name}"]
        return []
    if name and ("sourceUrl" in binding or "source_url" in binding):
        return [f"clip_unverified:{slot.get('id')}:{name}"]
    return []


def _target(slots: list[dict], binding: dict) -> dict:
    object_id = binding.get("objectId", binding.get("object_id"))
    if isinstance(object_id, str) and object_id:
        found = [slot for slot in slots if slot.get("id") == object_id]
        if len(found) != 1:
            raise World3DSceneError("unknown_object", f"unknown_object:{object_id}", 404)
        return found[0]
    role = binding.get("role")
    if not isinstance(role, str) or not role:
        raise World3DSceneError("object_required", "Name an object id. A role resolves only when one object has it.")
    found = [slot for slot in slots if slot.get("slot") == role]
    if len(found) != 1:
        code = "ambiguous_role" if len(found) > 1 else "missing_role"
        raise World3DSceneError(code, f"{code}:{role}")
    return found[0]


def _retarget(document: dict) -> None:
    framing = (document.get("camera") or {}).get("framing")
    if not isinstance(framing, dict):
        return
    slots = document.get("slots") or []
    if any(slot.get("id") == framing.get("targetSlot") for slot in slots):
        return
    subjects = [slot for slot in slots if slot.get("slot") == "subject_1"]
    models = [slot for slot in slots if slot.get("media") == "model3d"]
    target = subjects[0] if len(subjects) == 1 else models[0] if len(models) == 1 else None
    if target is None:
        raise World3DSceneError("framing_target_missing", f"framing_target_missing:{framing.get('targetSlot')}")
    framing["targetSlot"] = target["id"]


def _view(scene_id: str, record: dict) -> dict:
    document = record["document"]
    return {
        "sceneId": scene_id, "revision": record["revision"], "templateId": record["templateId"],
        "document": document, "objects": _objects(document), "pending": _pending(document),
        "warnings": record.get("warnings") or [], "traits": _traits(document),
        "editable": ["sourceUrl", "sourceRef", "clip", "position", "rotationY", "scale", "motion", "grounded",
                     "camera", "playbackSpeed", "duration", "dressing", "light"],
    }


def _objects(document: dict) -> list[dict]:
    objects = []
    for slot in document.get("slots") or []:
        source = slot.get("sourceUrl") or ""
        objects.append({
            "id": slot.get("id"), "role": slot.get("slot"), "media": slot.get("media"), "sourceUrl": source,
            "marker": not source, "finished": bool(source), "clip": slot.get("clip"), "position": slot.get("position"),
            "rotationY": slot.get("rotationY"), "scale": slot.get("scale"), "motion": slot.get("motion"),
            "accepted": [slot.get("media") or "model3d"],
        })
    return objects


def _pending(document: dict) -> list[dict]:
    return [{"id": slot.get("id"), "role": slot.get("slot"), "media": slot.get("media"),
             "requirements": "A durable workspace image or video" if slot.get("media") in ("image", "screen") else "A durable workspace GLB"}
            for slot in document.get("slots") or [] if not slot.get("sourceUrl")]


def _traits(document: dict) -> dict:
    camera = document.get("camera") or {}
    framing = camera.get("framing") or {}
    return {
        "templateId": document.get("templateId"), "playbackSpeed": document.get("playbackSpeed") or 1,
        "duration": document.get("duration"), "width": document.get("width"), "height": document.get("height"),
        "format": "portrait" if (document.get("height") or 0) > (document.get("width") or 0) else "landscape",
        "fov": camera.get("fov"), "fovTo": framing.get("fovTo"), "orbitTurns": framing.get("orbitTurns"),
        "targetSlot": framing.get("targetSlot"), "dressing": document.get("dressing"),
        "worldSfx": [cue.get("kind") for cue in document.get("worldSfx") or [] if isinstance(cue, dict)],
        "roles": [slot.get("slot") for slot in document.get("slots") or []],
        "slotIds": [slot.get("id") for slot in document.get("slots") or []],
    }


def _speed(value) -> float:
    if type(value) not in (int, float) or not value > 0:
        raise World3DSceneError("invalid_speed", "playbackSpeed must be a positive number")
    return max(0.25, min(4.0, float(value)))


def _snake(key: str) -> str:
    return "".join(f"_{char.lower()}" if char.isupper() else char for char in key)


def _path(workspace: str, scene_id: str, workspace_dir) -> Path:
    if not isinstance(scene_id, str) or not scene_id.startswith("w3d-") or len(scene_id) != 16:
        raise World3DSceneError("unknown_scene", f"unknown_scene:{scene_id}", 404)
    return Path(workspace_dir(workspace)) / _EDITS / f"{scene_id}.json"


def _read(workspace: str, scene_id: str, workspace_dir) -> dict:
    path = _path(workspace, scene_id, workspace_dir)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise World3DSceneError("unknown_scene", f"unknown_scene:{scene_id}", 404) from error
    except (OSError, ValueError) as error:
        raise World3DSceneError("scene_unreadable", "The Video 3D scene is unreadable", 409) from error
    if not isinstance(record, dict) or not isinstance(record.get("document"), dict):
        raise World3DSceneError("scene_unreadable", "The Video 3D scene is unreadable", 409)
    return record


def _write(workspace: str, scene_id: str, record: dict, workspace_dir) -> None:
    path = _path(workspace, scene_id, workspace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic(path, record)


def _atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _run_tool(command: str, payload: str | None, template_id: str | None = None) -> dict:
    node = shutil.which("node")
    loader = _ROOT / "ui/node_modules/tsx/dist/loader.mjs"
    if not node or not loader.is_file():
        raise World3DSceneError("template_tool_missing", "Video 3D template compilation requires the app's installed UI dependencies", 500)
    args = [node, "--import", str(loader), str(_ROOT / "ui/scripts/world3d-template-tool.mjs"), command]
    if template_id:
        args.append(template_id)
    result = subprocess.run(args, input=payload, capture_output=True, text=True, cwd=_ROOT / "ui", timeout=60, check=False)
    if result.returncode:
        detail = f"{result.stderr or ''}\n{result.stdout or ''}"
        if "unknown_template:" in detail:
            raise World3DSceneError("unknown_template", f"unknown_template:{template_id or ''}", 404)
        message = next((line for line in reversed(detail.splitlines()) if line.strip()), "template tool failed")
        raise World3DSceneError("template_tool_failed", message)
    try:
        parsed = json.loads(result.stdout)
    except ValueError as error:
        raise World3DSceneError("template_tool_failed", "Video 3D template tool did not return JSON") from error
    if not isinstance(parsed, dict):
        raise World3DSceneError("template_tool_failed", "Video 3D template tool did not return an object")
    return parsed
