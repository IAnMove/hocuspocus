"""Shared plumbing for the production media tools (frame, compose, trim, cross-workspace import).

Every tool takes the same versioned envelope ``{version: 1, input: {...}, intent_id?}``,
works inside one workspace, publishes its file with a canonical ``/api/v1/file`` URL and
writes a ``.meta.json`` provenance sidecar that names the tool and its source files.
An ``output_name`` follows the generation rule (``generation_output_name``): one file
name inside the workspace; an existing name gets ``name(2).ext``, never an overwrite.
"""
from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import HTTPException

WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 120}
SOURCE = {"type": "string", "minLength": 1, "maxLength": 2000}
OUTPUT_NAME = {"type": "string", "minLength": 1, "maxLength": 180, "description": (
    "File name for the result in the workspace (its extension is set by the tool). An existing name gets "
    "name(2).ext; nothing is overwritten.")}
_ENVELOPE_KEYS = frozenset({"version", "input", "intent_id"})


class MediaToolError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def operation_schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """One MCP catalog entry in the studio.key envelope (optional intent_id replays the stored result)."""
    payload = {"type": "object", "additionalProperties": False, "properties": properties, "required": required}
    return {
        "name": name, "version": 1, "domain": name.split(".")[0], "mutation": True, "description": description,
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["version", "input"],
            "properties": {
                "version": {"type": "integer", "const": 1},
                "intent_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "input": payload,
            },
        },
    }


def read_input(arguments: Any, allowed: frozenset[str], required: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(arguments, dict) or arguments.get("version") != 1 or set(arguments) - _ENVELOPE_KEYS:
        raise MediaToolError("invalid_command", "Use version 1 and an input object.")
    payload = arguments.get("input")
    if not isinstance(payload, dict):
        raise MediaToolError("invalid_command", "Use version 1 and an input object.")
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise MediaToolError("invalid_command", f"Unknown input fields: {', '.join(unknown)}.")
    missing = [key for key in required if key not in payload]
    if missing:
        raise MediaToolError("invalid_command", f"Required input fields: {', '.join(missing)}.")
    return payload


def workspace_folder(workspace_dir: Callable[[str], str], name: Any, *, field: str = "workspace", create: bool = True) -> str:
    """The workspace's folder; ``create`` false refuses a workspace that does not exist (a source to read from)."""
    if not isinstance(name, str) or not name.strip() or name != name.strip():
        raise MediaToolError("invalid_workspace", f"{field} is required.")
    try:
        folder = workspace_dir(name)
    except Exception as exc:  # an HTTPException or ValueError from the workspace resolver
        raise MediaToolError("invalid_workspace", f"{field} {name} is not available.") from exc
    if not isinstance(folder, str) or not folder:
        raise MediaToolError("invalid_workspace", f"{field} {name} is not available.")
    if not create and not os.path.isdir(folder):
        raise MediaToolError("invalid_workspace", f"{field} {name} does not exist.", 404)
    os.makedirs(folder, exist_ok=True)
    return os.path.realpath(folder)


def uploads_root(uploads_dir: Callable[[], str] | str) -> str:
    root = uploads_dir() if callable(uploads_dir) else uploads_dir
    if not isinstance(root, str) or not root:
        raise MediaToolError("storage_unavailable", "Upload storage is unavailable.", 503)
    return root


def resolve_source(value: Any, workspace: str, folder: str, uploads: str, kinds: tuple[str, ...], field: str = "source") -> str:
    """A workspace file name, a /api/v1/file URL of this workspace or an upload, of one of ``kinds``."""
    from services.media_paths import MediaPathNotAllowed, resolve_permitted_media_path

    if not isinstance(value, str) or not value.strip():
        raise MediaToolError("invalid_command", f"{field} is required.")
    try:
        return resolve_permitted_media_path(value, uploads_root=uploads, workspace_root=folder, kinds=kinds,
                                            workspace_name=workspace)
    except MediaPathNotAllowed as exc:
        if str(exc) == "Media type is not allowed":
            raise MediaToolError("unsupported_media", f"{field} must be {' or '.join(kinds)}.") from exc
        raise MediaToolError("path_not_allowed", f"{field} is not a file of this workspace.") from exc
    except FileNotFoundError as exc:
        raise MediaToolError("media_not_found", f"{field} was not found in the workspace.", 404) from exc


def _taken(folder: str, name: str) -> bool:
    """A name is taken by its file or by a sidecar of the same stem (song.wav owns song.meta.json)."""
    return os.path.lexists(os.path.join(folder, name)) or os.path.lexists(
        os.path.join(folder, f"{Path(name).stem}.meta.json"))


def available_name(folder: str, name: str) -> str:
    """The generation rule: ``name.ext``, else ``name(2).ext``, ``name(3).ext``..."""
    stem, extension = os.path.splitext(name)
    candidate, counter = name, 2
    while _taken(folder, candidate):
        candidate = f"{stem}({counter}){extension}"
        counter += 1
        if counter > 10_000:
            raise MediaToolError("output_failed", "No free file name for the result.", 500)
    return candidate


def output_path(folder: str, output_name: Any, default_stem: str, extension: str) -> str:
    """Where the result goes: ``output_name`` (validated like generation's) or ``default_stem``, with ``extension``."""
    if output_name is None:
        stem = default_stem
    else:
        from services.generation_output_name import OutputNameError, validate_output_name
        try:
            stem = Path(validate_output_name(output_name)).stem
        except OutputNameError as exc:
            raise MediaToolError("invalid_output_name", str(exc)) from exc
        if not stem or stem in {".", ".."}:
            raise MediaToolError("invalid_output_name", "Output name must be a single file name inside the workspace")
    safe = "".join(char if char.isalnum() or char in "-_.() " else "_" for char in stem).strip(" .")[:160] or "output"
    return os.path.join(folder, available_name(folder, f"{safe}{extension}"))


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def media_url(path: str, workspace: str, uploads: str, folder: str) -> str:
    from services.wangp_submission import wangp_media_url
    try:
        return wangp_media_url(path, workspace, uploads_dir=uploads, workspace_dir=folder)
    except ValueError as exc:
        raise MediaToolError("path_not_allowed", "Media path is not allowed.") from exc


def source_ref(path: str, workspace: str, role: str = "source") -> dict[str, str]:
    """A lineage reference to a source file: its manifest asset id when it has one."""
    from services.asset_catalog import _stable_unmanaged_id
    from services.asset_manifest import infer_asset_kind, read_asset_manifest

    manifest = read_asset_manifest(path, workspace_id=workspace) or {}
    asset_id = ((manifest.get("asset") or {}).get("id")) or _stable_unmanaged_id(workspace, os.path.basename(path))
    return {"id": asset_id, "kind": infer_asset_kind(path), "uri": os.path.basename(path), "role": role}


def publish_sidecar(path: str, workspace: str, operation: str, mode: str, params: dict[str, Any],
                    sources: list[dict[str, str]]) -> bool:
    """A provenance sidecar naming the tool, its parameters and its source files. Never raises."""
    from services.asset_manifest import publish_generation_sidecar_best_effort

    sidecar = {
        "params": {**params, "source": operation}, "generation_mode": mode, "created_at": time.time(),
        "inputs": sources, "parents": sources,
        "transformations": [{"tool": operation, **params}],
    }
    return publish_generation_sidecar_best_effort(path, sidecar, workspace_id=workspace, tool=operation,
                                                  capability=operation) is not None


def remove_quietly(path: str | None) -> None:
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def run_once(arguments: Any, operation: str, folder_for: Callable[[dict], str], run: Callable[[], dict]) -> dict:
    """With an intent_id, the same input returns the stored result instead of a second file."""
    intent = arguments.get("intent_id") if isinstance(arguments, dict) else None
    if intent is None:
        return run()
    from services.mcp_intent import IntentConflict, check_intent_id, intent_digest, load_intent, store_intent

    payload = arguments.get("input") if isinstance(arguments.get("input"), dict) else {}
    try:
        intent_id = check_intent_id(intent)
        digest = intent_digest(payload)
        root = Path(folder_for(payload))
        previous = load_intent(root, operation, intent_id, digest)
    except IntentConflict as exc:
        raise MediaToolError("intent_conflict", str(exc), 409) from exc
    if previous is not None:
        return {**previous, "replayed": True}
    result = run()
    store_intent(root, operation, intent_id, digest, result)
    return result


def handler(operation: str, run: Callable[[dict], dict], folder_for: Callable[[dict], str]):
    """An async MCP handler: runs ``run(arguments)`` off the event loop and maps errors to tool errors."""
    async def handle(arguments: Any) -> dict:
        from starlette.concurrency import run_in_threadpool
        try:
            result = await run_in_threadpool(run_once, arguments, operation, folder_for, lambda: run(arguments))
        except MediaToolError as exc:
            raise HTTPException(exc.status, {"code": exc.code, "message": exc.message, "retryable": False}) from exc
        return {"version": 1, "status": "completed", "operation": operation, "result": result}
    return handle


def number(payload: dict, key: str, low: float, high: float, default: float | None = None) -> float | None:
    value = payload.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= float(value) <= high:
        raise MediaToolError("invalid_command", f"{key} must be a number from {low:g} to {high:g}.")
    return float(value)
