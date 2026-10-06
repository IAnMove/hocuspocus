"""HTTP projection of the shared Video 3D template commands.

The same handlers serve MCP. This router does not import the launch runtime.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request

from services.agent_activity import caller_scope
from services.scene_documents import WORKSPACE_RE
from services.world3d_template_catalog import World3DTemplateError, list_user_templates, user_template_row
from services.world3d_template_commands import command_catalog, command_handlers
from services.world3d_scenes import working_scenes


def create_world3d_templates_router(workspace_dir: Callable[[str], str]) -> APIRouter:
    router = APIRouter(prefix="/api/v1/world3d/templates", tags=["world3d-templates"])
    handlers = command_handlers(workspace_dir)

    @router.get("/commands")
    def commands():
        return {"version": 1, "operations": command_catalog()}

    @router.post("/commands")
    async def command(body: dict, request: Request):
        arguments = dict(body)
        operation = arguments.pop("operation", None)
        if operation not in handlers:
            raise HTTPException(422, detail={"code": "unknown_operation", "message": "Unknown Video 3D template operation"})
        # Attribution only (never a permission): the Wizard declares itself, like on the generation commands.
        surface = "wizard" if request.headers.get("x-hocus-ui-surface") == "wizard" else "studio"
        with caller_scope({"surface": surface, "internal": surface}):
            return await handlers[operation](arguments)

    @router.get("/workspace")
    def workspace_templates(workspace: str):
        """Personal templates saved in the workspace (by an agent, the Wizard or world3d.templates.user.put)."""
        _check_workspace(workspace)
        try:
            return {"version": 1, "workspace": workspace, "templates": list_user_templates(workspace_dir, workspace)}
        except World3DTemplateError as error:
            raise HTTPException(error.status, detail={"code": error.code, "message": str(error)}) from error

    @router.get("/workspace/{template_id}")
    def workspace_template(template_id: str, workspace: str):
        _check_workspace(workspace)
        try:
            return {"version": 1, "workspace": workspace, "template": user_template_row(template_id, workspace_dir, workspace)}
        except World3DTemplateError as error:
            raise HTTPException(error.status, detail={"code": error.code, "message": str(error)}) from error

    @router.get("/working-scenes")
    def working_scene_list(workspace: str, all: bool = False, limit: int = 100):
        """Working Video 3D scenes (``w3d-…``) an agent made, newest first; only the unpublished ones unless ``all``.

        The Video 3D Open dialog lists them beside the saved scenes, so a scene that was never published opens too."""
        _check_workspace(workspace)
        scenes = working_scenes(workspace, workspace_dir, unpublished_only=not all)
        return {"version": 1, "workspace": workspace, "total": len(scenes), "scenes": scenes[:max(1, min(500, limit))]}

    return router


def _check_workspace(workspace: str) -> None:
    if not WORKSPACE_RE.fullmatch(workspace or ""):
        raise HTTPException(422, detail={"code": "invalid_workspace", "message": "Use an explicit valid workspace"})
