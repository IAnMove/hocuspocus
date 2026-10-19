"""Core MCP handlers on the shared wangp transport.

The transport (auth, JSON-RPC, batches, attribution) lives in ``routers.wangp_mcp``.
This module only supplies the read-only handlers and the legacy envelope core clients already send.
"""
from __future__ import annotations

import inspect
import os
from contextvars import ContextVar

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from routers.system_capabilities import require_capability_http
from routers.wangp_mcp import create_wangp_mcp_router
from services.wangp_agent_adapters import application_endpoint, asset_catalog_handler

LOCAL_MUTATIONS = frozenset({"generate", "recast", "upscale"})
_INSTRUCTIONS = (
    "This profile exposes read-only tools. Use canonical asset IDs and paginate with limit and offset."
)
_APP: ContextVar = ContextVar("core_mcp_app")
_ARGUMENT_TOOLS = frozenset({"assets", "models"})


def _tool_name(body):
    name = body.get("method") or body.get("name") or ""
    params = body.get("params")
    if isinstance(params, dict) and params.get("name"):
        name = params["name"]
    return name


def _models(_arguments):
    return {"models": []}


def _processors():
    return {"processors": []}


def _status(job_id):
    from services.core_remote_image import get_job

    job = get_job(job_id)
    if isinstance(job, dict):
        return job
    return {"jobs": [], "job_id": job_id}


def _assets(arguments):
    endpoint = application_endpoint(_APP.get(), "/api/v1/assets", "GET")
    return asset_catalog_handler(endpoint)(arguments)


def _collections():
    endpoint = application_endpoint(_APP.get(), "/api/v1/workspace-collections", "GET")
    return endpoint()


_HANDLERS = {
    "models": _models,
    "processors": _processors,
    "status": _status,
    "assets": _assets,
    "collections": _collections,
}


def _legacy_value(name, params):
    if not isinstance(params, dict):
        raise ValueError("Tool call params must be an object")
    if not isinstance(name, str) or name not in _HANDLERS:
        raise ValueError("Unknown tool or invalid arguments")
    if name == "status":
        job_id = params.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("job_id is required")
        return _status(job_id)
    if name in _ARGUMENT_TOOLS:
        return _HANDLERS[name](params)
    return _HANDLERS[name]()


async def legacy_envelope(request, body):
    """Raw JSON for the pre-JSON-RPC clients, and 409 before a local mutation runs."""
    _APP.set(request.app)
    if not isinstance(body, dict) or "jsonrpc" in body:
        return None
    params = body.get("params", body)
    name = _tool_name(body)
    if isinstance(name, str) and name in LOCAL_MUTATIONS:
        require_capability_http("wangp_local")
    try:
        value = _legacy_value(name, params)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    if inspect.isawaitable(value):
        value = await value
    return JSONResponse(value)


def create_core_mcp_router(access):
    journal = os.path.join(os.path.dirname(os.path.dirname(__file__)), "settings", "core-mcp-requests.sqlite3")
    return create_wangp_mcp_router(
        handlers=_HANDLERS,
        journal_path=journal,
        token_getter=lambda: access.token(),
        command_operations=[],
        server_name="hocuspocus-core",
        instructions=_INSTRUCTIONS,
        legacy_envelope=legacy_envelope,
        structured_content=True,
    )
