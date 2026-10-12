"""HTTP for the production media tools, so the Wizard and the UI call the same handlers as MCP agents.

``POST /api/v1/media/commands`` takes ``{operation, version: 1, input, intent_id?}`` for ``media.frame``,
``media.compose``, ``audio.trim``, ``assets.import_from_workspace`` and ``studio.key``
(services/production_media_commands.py, services/studio_key.py).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException


def create_production_media_router(handlers: dict[str, Callable[[Any], Awaitable[dict]]]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/media/commands")
    def catalog():
        return {"version": 1, "operations": sorted(handlers)}

    @router.post("/api/v1/media/commands")
    async def command(body: dict):
        arguments = dict(body) if isinstance(body, dict) else {}
        operation = arguments.pop("operation", None)
        if operation not in handlers:
            raise HTTPException(422, detail={"code": "unknown_operation", "message": f"Use one of {', '.join(sorted(handlers))}",
                                             "retryable": False})
        return await handlers[operation](arguments)

    return router


__all__ = ["create_production_media_router"]
