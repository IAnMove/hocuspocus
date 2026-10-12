"""HTTP read of the aggregated Video 2D catalog. No GPU, save or export.

``POST /api/v1/scenes/templates/commands`` takes ``{operation, version: 1, input}`` for ``scenes.catalog`` and
``scenes.templates.suggest``, so the Wizard reads the 2D cards through the same handlers the MCP tools run.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from services.video2d_catalogs import CatalogError, query_catalog

TEMPLATE_COMMANDS = ("scenes.templates.suggest", "scenes.catalog")


def create_video2d_catalog_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/scenes/catalog")
    def catalog(
        kind: str | None = None,
        family: str | None = None,
        q: str | None = None,
        detail: bool = False,
        id: str | None = None,
    ):
        payload = {
            key: value
            for key, value in (("kind", kind), ("family", family), ("q", q), ("id", id))
            if value is not None
        }
        if detail:
            payload["detail"] = True
        try:
            return query_catalog(payload)
        except CatalogError as error:
            raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": False}) from error

    return router


def create_video2d_template_commands_router(handlers: Callable[[], dict[str, Callable[[Any], Any]]]) -> APIRouter:
    """``handlers`` returns the MCP handler table when a request arrives (it is filled after this router mounts)."""
    router = APIRouter()

    @router.post("/api/v1/scenes/templates/commands")
    async def command(body: dict):
        operation = body.get("operation") if isinstance(body, dict) else None
        handler = handlers().get(operation) if operation in TEMPLATE_COMMANDS else None
        if handler is None:
            raise HTTPException(422, detail={"code": "unknown_operation", "message": f"Use one of {', '.join(TEMPLATE_COMMANDS)}",
                                             "retryable": False})
        reply = handler({"version": body.get("version"), "input": body.get("input")})
        return await reply if inspect.isawaitable(reply) else reply

    return router


__all__ = ["TEMPLATE_COMMANDS", "create_video2d_catalog_router", "create_video2d_template_commands_router"]
