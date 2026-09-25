"""Read-only MCP adapter for core, using the application's canonical catalogs."""
from __future__ import annotations

import json
import inspect
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from routers.system_capabilities import require_capability_http
from routers.wangp_mcp import PROTOCOL, mcp_payload_response, tool_definitions
from services.wangp_agent_adapters import application_endpoint, asset_catalog_handler

LOCAL_MUTATIONS = frozenset({"generate", "recast", "upscale"})


def _tool_name(body):
    name = body.get("method") or body.get("name") or ""
    params = body.get("params")
    if isinstance(params, dict) and params.get("name"):
        name = params["name"]
    return name


def _read_handlers(api):
    handlers = {
        "models": lambda arguments: {"models": []},
        "processors": lambda arguments: {"processors": []},
        "status": lambda arguments: {"jobs": [], "job_id": arguments.get("job_id")},
    }
    for name, path in (("assets", "/api/v1/assets"), ("collections", "/api/v1/workspace-collections")):
        try:
            endpoint = application_endpoint(api, path, "GET")
        except StopIteration:
            continue
        handlers[name] = asset_catalog_handler(endpoint) if name == "assets" else lambda arguments, endpoint=endpoint: endpoint()
    return handlers


def _call_tool(params, handlers):
    if not isinstance(params, dict):
        raise ValueError("Tool call params must be an object")
    name, arguments = params.get("name"), params.get("arguments", {})
    if not isinstance(name, str) or name not in handlers or not isinstance(arguments, dict):
        raise ValueError("Unknown tool or invalid arguments")
    if name == "status" and (not isinstance(arguments.get("job_id"), str) or not arguments["job_id"]):
        raise ValueError("job_id is required")
    return handlers[name](arguments)


async def _dispatch(body, handlers):
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
    if "id" not in body:
        return None
    request_id, method = body["id"], body.get("method")
    try:
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                "serverInfo": {"name": "hocuspocus-core", "version": "1"},
                "instructions": "This profile exposes read-only tools. Use canonical asset IDs and paginate with limit and offset.",
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": tool_definitions(handlers, command_operations=[])}
        elif method == "tools/call":
            value = _call_tool(body.get("params", {}), handlers)
            if inspect.isawaitable(value):
                value = await value
            result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "isError": False}
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except (ValueError, KeyError, TypeError, HTTPException) as error:
        detail = error.detail if isinstance(error, HTTPException) else str(error)
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "isError": True, "content": [{"type": "text", "text": str(detail)}],
        }}


def _require_mcp_bearer(request: Request, token: str) -> None:
    if not token:
        raise HTTPException(503, "External agent access is disabled; configure HOCUS_MCP_TOKEN")
    if not secrets.compare_digest(request.headers.get("authorization", ""), f"Bearer {token}"):
        raise HTTPException(401, "Invalid MCP credentials")
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "Origin is not permitted")


def create_core_mcp_router(access) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/wangp/mcp", include_in_schema=False)
    @router.post("/api/v1/mcp")
    async def mcp(request: Request):
        _require_mcp_bearer(request, access.token())
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
        handlers = _read_handlers(request.app)
        # Preserve old direct requests and their capability-specific HTTP 409.
        if isinstance(body, dict) and "jsonrpc" not in body:
            params = body.get("params", body)
            name = _tool_name(body)
            if isinstance(name, str) and name in LOCAL_MUTATIONS:
                require_capability_http("wangp_local")
            try:
                value = _call_tool({"name": name, "arguments": params}, handlers)
                return await value if inspect.isawaitable(value) else value
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
        return await mcp_payload_response(body, lambda message: _dispatch(message, handlers))

    @router.get("/api/v1/wangp/mcp", include_in_schema=False)
    @router.get("/api/v1/mcp")
    async def no_stream():
        return Response(status_code=405, headers={"Allow": "POST"})

    return router
