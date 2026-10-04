"""HTTP projection for Video 2D scene edits (``scenes.video2d.edit``)."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from services.video2d_edit import Video2dEditError, command_catalog, edit, http_error


def create_video2d_edit_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/scenes/video2d/edit/commands")
    def commands():
        return {"version": 1, "operations": command_catalog()}

    @router.post("/api/v1/scenes/video2d/edit")
    async def submit(request: Request):
        data = await request.body()
        if len(data) > 3 * 1024 * 1024:
            raise HTTPException(413, {"code": "payload_too_large", "message": "Video 2D edit command exceeds 3 MB", "retryable": False, "recoverable": False})
        try:
            command = json.loads(data)
        except ValueError as error:
            raise http_error("invalid_command", "Command must be valid JSON") from error
        try:
            return await run_in_threadpool(edit, command)
        except Video2dEditError as error:
            raise http_error(error.code, str(error)) from error

    return router


__all__ = ["create_video2d_edit_router"]
