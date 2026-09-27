"""HTTP projection for recoverable Video 2D export (``scenes.video2d.export``)."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from services.scene2d_export import command_catalog
from services.world3d_export import http_error


def create_scene2d_export_router(service) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/scenes/video2d/export/commands")
    def commands():
        return {"version": 1, "operations": command_catalog()}

    @router.get("/api/v1/scenes/video2d/export/capabilities")
    def capabilities():
        return service.capabilities()

    @router.post("/api/v1/scenes/video2d/export")
    async def submit(request: Request):
        data = await request.body()
        if len(data) > 3 * 1024 * 1024:
            raise HTTPException(413, "Video 2D export command exceeds 3 MB")
        try:
            command = json.loads(data)
        except ValueError as error:
            raise http_error(422, "invalid_command", "Command must be valid JSON") from error
        return await run_in_threadpool(service.submit, command)

    @router.get("/api/v1/scenes/video2d/export/receipt")
    def receipt(workspace: str, intent_id: str):
        return service.receipt(workspace, intent_id)

    @router.post("/api/v1/scenes/video2d/export/cancel")
    async def cancel(request: Request):
        try:
            body = await request.json()
        except ValueError as error:
            raise http_error(422, "invalid_command", "Command must be valid JSON") from error
        if not isinstance(body, dict):
            raise http_error(422, "invalid_command", "Use workspace and intent_id")
        return await run_in_threadpool(service.cancel, body.get("workspace"), body.get("intent_id"))

    return router


__all__ = ["create_scene2d_export_router"]
