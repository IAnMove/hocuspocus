"""HTTP and MCP projections for recoverable World3D export.

The router is testable without importing ``_launch_runtime``. The live API
mounts it from ``_launch_runtime`` after the scene commands router.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from services.world3d_export import (
    CANCEL_OPERATION,
    OPERATION,
    RECEIPT_OPERATION,
    command_catalog,
    command_handlers,
    http_error,
)


def create_world3d_export_router(service) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/scenes/world3d/export/commands")
    def commands():
        return {"version": 1, "operations": command_catalog()}

    @router.get("/api/v1/scenes/world3d/export/capabilities")
    def capabilities():
        return service.capabilities()

    @router.post("/api/v1/scenes/world3d/export")
    async def submit(request: Request):
        data = await request.body()
        if len(data) > 3 * 1024 * 1024:
            raise HTTPException(413, "World3D export command exceeds 3 MB")
        try:
            command = json.loads(data)
        except ValueError as error:
            raise http_error(422, "invalid_command", "Command must be valid JSON") from error
        return await run_in_threadpool(service.submit, command)

    @router.get("/api/v1/scenes/world3d/export/receipt")
    def receipt(workspace: str, intent_id: str):
        return service.receipt(workspace, intent_id)

    @router.post("/api/v1/scenes/world3d/export/cancel")
    async def cancel(request: Request):
        try:
            body = await request.json()
        except ValueError as error:
            raise http_error(422, "invalid_command", "Command must be valid JSON") from error
        if not isinstance(body, dict):
            raise http_error(422, "invalid_command", "Use workspace and intent_id")
        return await run_in_threadpool(service.cancel, body.get("workspace"), body.get("intent_id"))

    return router


def bind_world3d_renderer_origin(api, service) -> None:
    @api.middleware("http")
    async def bind_renderer_origin(request: Request, call_next):
        # Use the listening socket, never a client-controlled Host header.
        server = request.scope.get("server")
        if not service.app_url and server:
            service.app_url = f"http://127.0.0.1:{server[1]}"
        return await call_next(request)

__all__ = [
    "CANCEL_OPERATION",
    "OPERATION",
    "RECEIPT_OPERATION",
    "command_catalog",
    "command_handlers",
    "create_world3d_export_router",
]
