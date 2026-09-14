"""MCP surface for the core/remote profile: advertise reads, 409 local engines."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from routers.system_capabilities import require_capability_http
from routers.wangp_mcp import PROTOCOL, tool_definitions

LOCAL_MUTATIONS = frozenset({"generate", "recast", "upscale"})
READ_TOOLS = frozenset({"models", "processors", "status", "assets", "collections"})


def _tool_name(body: dict) -> str:
    name = str(body.get("method") or body.get("name") or "")
    params = body.get("params") if isinstance(body.get("params"), dict) else body
    if isinstance(params, dict) and params.get("name"):
        name = str(params.get("name") or name)
    if name == "tools/call" and isinstance(body.get("params"), dict):
        name = str(body["params"].get("name") or name)
    return name


def _read_result(name: str, arguments: dict) -> dict:
    from services import core_workspace as core

    if name == "models":
        return {"models": []}
    if name == "processors":
        return {"processors": []}
    if name == "status":
        return {"jobs": [], "job_id": arguments.get("job_id")}
    if name == "assets":
        listed = core.list_outputs(str(arguments.get("workspace") or "") or "")
        return {"assets": listed.get("outputs") or [], "total": listed.get("total") or 0}
    if name == "collections":
        return {"collections": []}
    raise HTTPException(status_code=400, detail="Unknown MCP tool")


def _jsonrpc(body: dict) -> dict:
    request_id = body.get("id")
    method = body.get("method")
    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "hocuspocus-core", "version": "1"},
            "instructions": "Local NVIDIA engines are hidden. Use remote MiniMax/Meshy tools and filesystem reads.",
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        tools = [
            tool for tool in tool_definitions(READ_TOOLS, command_operations=[])
            if tool["name"] not in LOCAL_MUTATIONS
        ]
        result = {"tools": tools}
    elif method == "tools/call":
        params = body.get("params") or {}
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if name in LOCAL_MUTATIONS:
            require_capability_http("wangp_local")
        value = _read_result(name, arguments)
        result = {
            "content": [{"type": "text", "text": str(value)}],
            "isError": False,
        }
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


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
    async def wangp_mcp(request: Request):
        _require_mcp_bearer(request, access.token())
        body = await request.json()
        if isinstance(body, dict) and body.get("jsonrpc") == "2.0":
            try:
                return JSONResponse(_jsonrpc(body))
            except HTTPException:
                raise
        name = _tool_name(body if isinstance(body, dict) else {})
        if name in LOCAL_MUTATIONS:
            require_capability_http("wangp_local")
        if name in READ_TOOLS:
            arguments = body.get("params") if isinstance(body, dict) and isinstance(body.get("params"), dict) else {}
            return _read_result(name, arguments if isinstance(arguments, dict) else {})
        raise HTTPException(status_code=400, detail="Unknown MCP tool")

    return router
