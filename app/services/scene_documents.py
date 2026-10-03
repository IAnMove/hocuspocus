"""Save and read editable Video 2D / Video 3D scene documents in a workspace.

Agents compose scenes with ``scenes.effects.*`` and friends, then persist them
here so people can open the exact document in the Video 2D or Video 3D editor.
Every save is an immutable revision (a new file), like the World3D library: a
montage clip can cite the revision it was rendered from.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from services.mcp_intent import IntentConflict, check_intent_id, intent_digest, load_intent, store_intent
from services.scene2d_schema import document_schema
from services.scene_commands import DocumentInput, command_error
from services.scene_library import preview_png, save_world3d

WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 120}
FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.scene\.json")
WORKSPACE_RE = re.compile(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]{0,119})")
# 16:9 neutral placeholder so a Video 3D revision always has a library preview.
_PLACEHOLDER_SIZE = (320, 180)

OPERATIONS: dict[str, tuple[dict[str, Any], list[str], bool, str]] = {
    "scenes.document.save": (
        {"workspace": WORKSPACE, "document": document_schema(), "name": {"type": "string", "maxLength": 120},
         "preview": {"type": "string", "description": "Optional data:image/png;base64 preview (Video 3D library)."}},
        ["workspace", "document"], True,
        "Save a version 1 Video 2D (layers) or Video 3D (slots) scene as a new immutable revision in the workspace so "
        "it opens in the matching editor. Media must already be durable workspace/example URLs. No render or export. "
        "Optional intent_id replays the stored revision and does not write another file.",
    ),
    "scenes.document.get": (
        {"workspace": WORKSPACE, "file": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.scene\.json$"}},
        ["workspace", "file"], False,
        "Read a saved Video 2D or Video 3D scene document by exact file name.",
    ),
}


class SceneDocumentError(ValueError):
    def __init__(self, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _placeholder_preview() -> str:
    import base64
    import struct
    import zlib
    width, height = _PLACEHOLDER_SIZE
    raw = (b"\x00" + bytes((11, 16, 32)) * width) * height

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


def _url(name: str, workspace: str) -> str:
    return "/api/v1/file/" + quote(name) + "?workspace=" + quote(workspace, safe="")


def _remote_sequence(document: dict) -> bool:
    for layer in document.get("layers") or []:
        sequence = layer.get("sequence") if isinstance(layer, dict) else None
        if not isinstance(sequence, dict):
            continue
        urls = list(sequence.get("sources") or [])
        if sequence.get("source"):
            urls.append(sequence.get("source"))
        for url in urls:
            text = str(url or "").strip().lower()
            if text.startswith(("http://", "https://", "blob:", "file:", "//")):
                return True
    return False


def save_document(workspace: str, document: Any, *, name: str | None, preview: str | None,
                  workspace_dir: Callable[[str], str]) -> dict[str, Any]:
    if not isinstance(workspace, str) or not WORKSPACE_RE.fullmatch(workspace):
        raise SceneDocumentError("Use an explicit valid workspace")
    try:
        valid = DocumentInput(document=document).document
    except ValueError as error:
        raise SceneDocumentError(command_error(error)) from error
    if "slots" in valid:
        body = {"workspace": workspace, "document": valid, "name": name, "preview": preview or _placeholder_preview()}
        try:
            return {**save_world3d(body, workspace_dir), "editor": "video3d"}
        except ValueError as error:
            raise SceneDocumentError(str(error)) from error
    encoded = json.dumps(valid, ensure_ascii=False, allow_nan=False, indent=2)
    if re.search(r'"(?:blob:|file:)', encoded):
        raise SceneDocumentError("Upload local scene resources before saving")
    if _remote_sequence(valid):
        raise SceneDocumentError("Sequence frames must be durable workspace or example media")
    if preview:
        preview_png(preview)  # Validate even though Video 2D scenes do not store it.
    label = str(name or valid.get("name") or "scene")[:120]
    stem = (re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-._")[:80] or "scene") + "-" + uuid.uuid4().hex[:10]
    folder = Path(workspace_dir(workspace))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (stem + ".scene.json")
    temporary = folder / (stem + ".scene.json.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(encoded)
    temporary.replace(target)
    return {"name": target.name, "type": "scene", "workspace_id": workspace, "url": _url(target.name, workspace),
            "editor": "video2d"}


def get_document(workspace: str, file: str, *, workspace_dir: Callable[[str], str]) -> dict[str, Any]:
    if not isinstance(workspace, str) or not WORKSPACE_RE.fullmatch(workspace):
        raise SceneDocumentError("Use an explicit valid workspace")
    if not isinstance(file, str) or not FILE_RE.fullmatch(file) or ".." in file:
        raise SceneDocumentError("Use an exact .scene.json file name")
    path = Path(workspace_dir(workspace)) / file
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SceneDocumentError("Scene not found", status=404) from error
    except (OSError, ValueError) as error:
        raise SceneDocumentError("Scene file is unreadable", status=409) from error
    return {"file": file, "workspace": workspace, "document": document, "url": _url(file, workspace),
            "editor": "video3d" if isinstance(document, dict) and "slots" in document else "video2d"}


def _operation_schema(name: str, properties: dict[str, Any], required: list[str], mutation: bool, description: str) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "version": {"type": "integer", "const": 1},
        "input": {"type": "object", "additionalProperties": False, "properties": properties, "required": required},
    }
    if name == "scenes.document.save":
        envelope["intent_id"] = {"type": "string", "minLength": 1, "maxLength": 160}
    return {
        "name": name, "version": 1, "domain": "scenes", "mutation": mutation, "description": description,
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": envelope, "required": ["version", "input"]},
    }


def command_catalog() -> list[dict[str, Any]]:
    return [
        _operation_schema(name, properties, required, mutation, description)
        for name, (properties, required, mutation, description) in OPERATIONS.items()
    ]


def command_handlers(workspace_dir: Callable[[str], str]) -> dict[str, Callable[[Any], Any]]:
    def payload(arguments: Any, name: str) -> dict[str, Any]:
        properties, required, _, _ = OPERATIONS[name]
        data = arguments.get("input") if isinstance(arguments, dict) and arguments.get("version") == 1 else None
        if not isinstance(data, dict) or set(data) - set(properties) or any(key not in data for key in required):
            raise SceneDocumentError(f"Use version 1 with input fields: {', '.join(required)}")
        return data

    def _save_once(data: dict[str, Any], arguments: Any) -> dict[str, Any]:
        intent = arguments.get("intent_id") if isinstance(arguments, dict) else None
        if intent is None:
            return save_document(data["workspace"], data["document"], name=data.get("name"),
                                 preview=data.get("preview"), workspace_dir=workspace_dir)
        try:
            intent_id = check_intent_id(intent)
            digest = intent_digest({
                "workspace": data["workspace"],
                "document": data["document"],
                "name": data.get("name"),
                "preview": data.get("preview"),
            })
            root = Path(workspace_dir(data["workspace"]))
            previous = load_intent(root, "scenes.document.save", intent_id, digest)
        except IntentConflict as error:
            raise SceneDocumentError(str(error), status=409) from error
        except (OSError, json.JSONDecodeError) as error:
            raise SceneDocumentError("Stored intention is unreadable", status=409) from error
        if previous is not None:
            return {**previous, "replayed": True}
        result = save_document(data["workspace"], data["document"], name=data.get("name"),
                               preview=data.get("preview"), workspace_dir=workspace_dir)
        store_intent(root, "scenes.document.save", intent_id, digest, result)
        return result

    def run(name: str, arguments: Any) -> dict[str, Any]:
        data = payload(arguments, name)
        if name == "scenes.document.save":
            result = _save_once(data, arguments)
        else:
            result = get_document(data["workspace"], data["file"], workspace_dir=workspace_dir)
        return {"version": 1, "status": "completed", "operation": name, "result": result}

    def handler(name: str) -> Callable[[Any], Any]:
        async def handle(arguments: Any) -> dict[str, Any]:
            from fastapi import HTTPException
            from starlette.concurrency import run_in_threadpool
            try:
                return await run_in_threadpool(run, name, arguments)
            except SceneDocumentError as error:
                raise HTTPException(error.status, str(error)) from error
        return handle

    return {name: handler(name) for name in OPERATIONS}


__all__ = ["OPERATIONS", "SceneDocumentError", "command_catalog", "command_handlers", "get_document", "save_document"]
