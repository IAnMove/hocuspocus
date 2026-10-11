"""HTTP projection of the shared Video 3D template commands.

The same handlers serve MCP. This router does not import the launch runtime.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from services.agent_activity import caller_scope
from services.scene_documents import WORKSPACE_RE
from services.world3d_template_catalog import World3DTemplateError, list_user_templates, user_template_row
from services.world3d_template_commands import command_catalog, command_handlers
from services.world3d_scenes import working_scenes
from services.world3d_thumbnails import RETRY_AFTER_SECONDS, ThumbnailUnavailable, World3DThumbnails


def create_world3d_templates_router(workspace_dir: Callable[[str], str],
                                    thumbnails: World3DThumbnails | None = None) -> APIRouter:
    """``thumbnails`` renders the card pictures; by default they are cached in the default workspace's folder."""
    router = APIRouter(prefix="/api/v1/world3d/templates", tags=["world3d-templates"])
    handlers = command_handlers(workspace_dir)
    pictures = thumbnails or World3DThumbnails(outputs_dir=lambda: workspace_dir("default"))

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

    @router.get("/{template_id}/thumbnail")
    def template_thumbnail(template_id: str, request: Request):
        """Our own render of a shipped or stage card at mid-shot (WebP, else PNG), made once per template version.

        A card's ``preview`` is this URL. 503 ``thumbnail_unavailable`` with ``retryable`` when it cannot be painted now."""
        pictures.bind_origin(request.scope.get("server"))
        try:
            picture = pictures.thumbnail(template_id)
        except World3DTemplateError as error:
            raise HTTPException(error.status, detail={"code": error.code, "message": str(error)}) from error
        except ThumbnailUnavailable as error:
            raise HTTPException(503, detail={"code": "thumbnail_unavailable", "reason": error.reason, "message": str(error),
                                             "retryable": True},
                                headers={"Retry-After": str(RETRY_AFTER_SECONDS)}) from error
        return FileResponse(picture.path, media_type=picture.media_type, headers={
            "Cache-Control": "public, max-age=3600", "X-Thumbnail-Cache": "hit" if picture.cached else "miss",
            "X-Thumbnail-Recipe": picture.recipe,
        })

    return router


def _check_workspace(workspace: str) -> None:
    if not WORKSPACE_RE.fullmatch(workspace or ""):
        raise HTTPException(422, detail={"code": "invalid_workspace", "message": "Use an explicit valid workspace"})
