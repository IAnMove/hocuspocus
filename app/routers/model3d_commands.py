"""Versioned MCP adapters over the existing native Model3D HTTP contract.

No second generation queue: the mounted REST endpoints own validation,
GPU admission, cancellation, task identity and workspace publication.
"""
from __future__ import annotations

import hashlib
import inspect
from urllib.parse import urlencode

from fastapi import HTTPException

from routers.wangp_mcp import RequestJournal, UncertainRequest
from services.generation_provenance import normalize_submission_provenance
from services.mcp_intent import check_intent_id, intent_digest
from services.wangp_submission import JsonRequest


def command_catalog() -> list[dict]:
    workspace = {"type": "string", "minLength": 1, "maxLength": 120}
    generate = {
        "type": "object", "additionalProperties": True,
        "properties": {
            "workspace": workspace,
            "prompt": {"type": "string"},
            "image_path": {"type": "string"},
            "images": {"type": "object", "additionalProperties": {"type": "string"}},
            "model_id": {"type": "string"},
            "preset": {"type": "string"},
            "output_format": {"type": "string", "enum": ["glb", "obj", "ply", "stl"]},
        },
        "required": ["workspace"],
        "description": "The existing /api/v1/model3d/generate body; GLB is the default output.",
    }
    status = {
        "type": "object", "additionalProperties": False,
        "properties": {"workspace": workspace, "job_id": {"type": "string", "minLength": 1}},
        "required": ["workspace", "job_id"],
    }
    entries = []
    for name, payload, mutation, description in (
        ("model3d.generate", generate, True,
         "Submit image or text to Hunyuan3D using the native GPU lane and workspace publisher. "
         "Text requires the existing MiniMax reference-image configuration. Poll model3d.status."),
        ("model3d.status", status, False,
         "Read a native Model3D job in its exact workspace, including the published GLB URL."),
    ):
        properties = {"version": {"type": "integer", "const": 1}, "input": payload}
        required = ["version", "input"]
        if mutation:
            properties["intent_id"] = {"type": "string", "minLength": 1, "maxLength": 160}
            required.append("intent_id")
        entries.append({
            "name": name, "version": 1, "domain": "model3d", "mutation": mutation,
            "description": description,
            "inputSchema": {"type": "object", "additionalProperties": False,
                            "properties": properties, "required": required},
        })
    return entries


def _input(arguments: dict, *, mutation: bool) -> dict:
    keys = {"version", "input", "intent_id"} if mutation else {"version", "input"}
    if not isinstance(arguments, dict) or type(arguments.get("version")) is not int or arguments["version"] != 1:
        raise ValueError("Use version 1 and an input object")
    payload = arguments.get("input")
    if set(arguments) - keys or not isinstance(payload, dict):
        raise ValueError("Use version 1 and an input object")
    workspace = payload.get("workspace")
    if not isinstance(workspace, str) or not workspace.strip() or len(workspace) > 120:
        raise ValueError("An exact workspace is required")
    return dict(payload)


def _result(operation: str, job: dict) -> dict:
    job = dict(job)
    url = job.get("url")
    if isinstance(url, str) and url.startswith("/api/v1/file/") and "?" not in url:
        job["url"] = f"{url}?{urlencode({'workspace': job['workspace']})}"
    return {"version": 1, "operation": operation, "status": job.get("status", "accepted"), "result": job}


def command_handlers(*, generate, status, journal_path) -> dict:
    journal = RequestJournal(journal_path)

    async def submit(arguments: dict) -> dict:
        payload = _input(arguments, mutation=True)
        intent = check_intent_id(arguments.get("intent_id"))
        digest = intent_digest(payload)
        provenance = normalize_submission_provenance(payload.get("provenance"), trusted_tool="external_agent")
        # Scope retries to the workspace without exposing paths in a journal key.
        identity = hashlib.sha256(f"model3d.generate:{payload['workspace']}:{intent}".encode()).hexdigest()
        try:
            stored = journal.reserve(identity, digest)
        except UncertainRequest as error:
            raise HTTPException(409, {"code": "submission_uncertain", "message": str(error),
                                      "retryable": False}) from error
        if stored is not None:
            return stored
        provenance.update(actor="user", capability="model3d.generate")
        provenance["command"]["command_id"] = intent
        payload["provenance"] = provenance
        try:
            job = generate(JsonRequest(payload, trusted_tool="external_agent"))
            job = await job if inspect.isawaitable(job) else job
            result = _result("model3d.generate", job)
        except HTTPException as error:
            if error.status_code >= 500:
                raise  # Admission may have happened; retain uncertainty rather than resubmit.
            result = {"version": 1, "operation": "model3d.generate", "status": "failed",
                      "error": error.detail, "status_code": error.status_code}
        journal.finish(identity, result)
        return result

    async def read(arguments: dict) -> dict:
        payload = _input(arguments, mutation=False)
        job_id = payload.get("job_id")
        if set(payload) - {"workspace", "job_id"} or not isinstance(job_id, str) or not job_id:
            raise ValueError("workspace and job_id are required")
        job = status(job_id)
        job = await job if inspect.isawaitable(job) else job
        if job.get("workspace") != payload["workspace"]:
            raise HTTPException(404, "3D generation job not found in this workspace")
        return _result("model3d.status", job)

    return {"model3d.generate": submit, "model3d.status": read}
