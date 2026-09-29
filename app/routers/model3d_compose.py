"""CPU Model3D composition with workspace publication and retry identity."""
from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from routers.wangp_mcp import RequestJournal
from services.asset_manifest import publish_generation_sidecar
from services.mcp_intent import check_intent_id, intent_digest
from services.procedural_3d.compose import KINDS, MAX_PIECES, compose_glb

OPERATION = "model3d.compose"


def command_catalog():
    transform = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
    piece = {"type": "object", "additionalProperties": False, "required": ["type"], "properties": {
        "type": {"enum": list(KINDS)}, "position": transform, "scale": transform, "rotation": transform,
        "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
    }}
    return [{"name": OPERATION, "version": 1, "domain": "model3d", "mutation": True,
             "description": "Build a low-poly GLB from 1..128 box/sphere/cylinder/cone pieces on CPU. "
                            "Metres, Y-up, Euler radians, positive scales, #RRGGBB colors. "
                            "Flat triangle normals and linear vertex colors; no AI or GPU. Returns file and workspace URL.",
             "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "intent_id", "input"],
                             "properties": {"version": {"const": 1, "type": "integer"},
                                            "intent_id": {"type": "string", "minLength": 1, "maxLength": 160},
                                            "input": {"type": "object", "additionalProperties": False,
                                                      "required": ["workspace", "name", "pieces"], "properties": {
                                                          "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
                                                          "name": {"type": "string", "minLength": 1, "maxLength": 64},
                                                          "pieces": {"type": "array", "items": piece, "minItems": 1, "maxItems": MAX_PIECES}}}}}}]


def _input(arguments):
    if not isinstance(arguments, dict) or type(arguments.get("version")) is not int or arguments["version"] != 1:
        raise ValueError("Use version 1, intent_id and input")
    if set(arguments) - {"version", "intent_id", "input"}:
        raise ValueError("Unknown envelope field")
    payload = arguments.get("input")
    if not isinstance(payload, dict) or set(payload) != {"workspace", "name", "pieces"}:
        raise ValueError("input needs workspace, name and pieces")
    for field, limit in (("workspace", 120), ("name", 64)):
        value = payload[field]
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f"{field} must be a nonempty string (max {limit})")
    return payload, check_intent_id(arguments.get("intent_id"))


def command_handlers(workspace_dir, journal_path):
    journal = RequestJournal(journal_path)

    def compose(arguments):
        payload, intent = _input(arguments)
        data = compose_glb(payload["pieces"], payload["name"])
        folder = Path(workspace_dir(payload["workspace"]))
        digest = intent_digest(payload)
        identity = hashlib.sha256(f"{OPERATION}:{payload['workspace']}:{intent}".encode()).hexdigest()
        stored = journal.reserve(identity, digest)
        if stored is not None:
            return stored
        folder.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9_-]+", "-", payload["name"]).strip("-")[:48] or "model"
        filename = f"compose-{stem}-{identity[:16]}.glb"
        target = folder / filename
        temporary = folder / f".{filename}-{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_bytes(data)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        publish_generation_sidecar(target, {"generation_mode": "model3d", "model_type": "procedural-compose",
                                            "command_id": intent, "params": payload},
                                   output_folder=payload["workspace"], tool="model3d", actor="user", capability=OPERATION)
        result = {"version": 1, "operation": OPERATION, "status": "completed", "result": {
            "file": filename, "name": payload["name"], "workspace": payload["workspace"],
            "url": f"/api/v1/file/{filename}?{urlencode({'workspace': payload['workspace']})}",
            "sha256": hashlib.sha256(data).hexdigest(), "pieces": len(payload["pieces"]), "bytes": len(data),
        }}
        journal.finish(identity, result)
        return result

    async def handle(arguments):
        return await run_in_threadpool(compose, arguments)

    return {OPERATION: handle}


def create_model3d_compose_router(handlers):
    router = APIRouter()

    @router.post("/api/v1/model3d/compose")
    async def compose(request: Request):
        try:
            return await handlers[OPERATION](await request.json())
        except ValueError as error:
            raise HTTPException(422, {"code": "invalid_command", "message": str(error), "retryable": False}) from error

    return router
