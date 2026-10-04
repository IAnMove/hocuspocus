"""HTTP projection of the shared Video 3D template commands.

The same handlers serve MCP. This router does not import the launch runtime.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from services.world3d_template_commands import command_catalog, command_handlers


def create_world3d_templates_router(workspace_dir: Callable[[str], str]) -> APIRouter:
    router = APIRouter(prefix="/api/v1/world3d/templates", tags=["world3d-templates"])
    handlers = command_handlers(workspace_dir)

    @router.get("/commands")
    def commands():
        return {"version": 1, "operations": command_catalog()}

    @router.post("/commands")
    async def command(body: dict):
        arguments = dict(body)
        operation = arguments.pop("operation", None)
        if operation not in handlers:
            raise HTTPException(422, detail={"code": "unknown_operation", "message": "Unknown Video 3D template operation"})
        return await handlers[operation](arguments)

    return router
