"""Workspaces, the gallery list, file serving and storage usage.

The gallery list and the storage report stay module-level in the services
layer, under the names they had in the full server. These factories only
register the routes, so each server can mount them at the old positions.
"""
from __future__ import annotations

import inspect
import os
import re

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from routers import workspace_busy_probes
from services import output_listing, workspace_busy
from services import storage_usage as storage_usage_service


def create_workspace_router(
    *,
    list_workspaces,
    get_active_workspace,
    persist_active,
    workspace_dir,
    generation_idle,
    safe_join,
    save_path,
    jobs=None,
    busy_profile=None,
):
    """The full server's workspace routes. Each server passes its own workspace service.

    ``busy_profile`` names the server ("full" or "core"): the delete route refuses while a
    family of that profile has work running in the workspace (``workspace_busy_probes``).
    ``None`` registers nothing, which is what a test that supplies its own probes wants.
    """
    router = APIRouter()
    if busy_profile:
        workspace_busy_probes.register_profile(busy_profile)
    jobs = jobs or (lambda: ())

    @router.get("/api/v1/workspaces")
    def list_workspaces_endpoint():
        """List all workspaces and the active one."""
        return {
            "workspaces": list_workspaces(),
            "active": get_active_workspace(),
        }

    @router.put("/api/v1/workspaces/active")
    async def set_active_workspace(request: Request):
        """Switch to a different workspace."""
        body = await request.json()
        name = body.get("name", "default")

        # Validate name (alphanumeric, hyphens, underscores)
        if name != "default" and not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", name):
            raise HTTPException(status_code=400, detail="Invalid workspace name. Use letters, numbers, hyphens, underscores.")

        # Persist the switch; only touch wgp.save_path when idle. If a job is
        # in progress it has locked wgp.save_path to its target workspace —
        # overwriting mid-generation scatters clips across workspaces. The
        # config is saved either way, so the next job or restart picks it up.
        idle = generation_idle()
        try:
            ws_dir = persist_active(name, apply_save_paths=idle)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if idle:
            print(f"[Workspace] Switched to: {name} ({ws_dir})")
        else:
            print(f"[Workspace] Config switched to: {name} (save_path deferred — generation in progress)")
        return {"status": "ok", "active": name, "path": ws_dir}

    @router.post("/api/v1/workspaces")
    async def create_workspace(request: Request):
        """Create a new workspace."""
        body = await request.json()
        name = body.get("name", "").strip()

        if not name:
            raise HTTPException(status_code=400, detail="Workspace name is required")

        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", name):
            raise HTTPException(status_code=400, detail="Invalid workspace name. Use letters, numbers, hyphens, underscores.")

        try:
            ws_dir = workspace_dir(name)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        os.makedirs(ws_dir, exist_ok=True)

        return {"status": "ok", "name": name, "path": ws_dir}

    @router.delete("/api/v1/workspaces/{name}")
    def delete_workspace(name: str):
        """Delete a workspace folder and every asset inside it.

        Refused while anything is queued or generating: jobs capture their
        workspace at submit time and _workspace_dir() recreates folders on
        demand, so a mid-generation delete would silently resurrect the
        workspace and scatter files into it.
        """
        if name == "default":
            raise HTTPException(status_code=400, detail="The default workspace is the outputs folder itself and cannot be deleted.")
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", name):
            raise HTTPException(status_code=400, detail="Invalid workspace name.")
        base = os.path.abspath(save_path())
        # _safe_join resolves symlinks/junctions before the containment check —
        # the regex blocks traversal but not a junction inside outputs/.
        ws_dir = safe_join(base, name)
        if ws_dir is None:
            raise HTTPException(status_code=400, detail="Invalid workspace path.")
        if not os.path.isdir(ws_dir):
            raise HTTPException(status_code=404, detail=f"Workspace not found: {name}")

        busy = any(j.get("status") in ("queued", "running") for j in jobs())
        if busy or not generation_idle():
            raise HTTPException(status_code=409, detail="A generation is queued or running. Wait for it to finish before deleting a workspace.")
        # Director pipelines are alive between their generation jobs (LLM
        # planning, review pauses) with no _jobs entry — but their next step
        # would resurrect the folder via _workspace_dir().
        try:
            from services.director_pipeline import any_pipeline_active
            if any_pipeline_active():
                raise HTTPException(status_code=409, detail="A Director pipeline is running or paused. Stop it before deleting a workspace.")
        except ImportError:
            pass
        # Every other family of long jobs (editor exports, music, comics, rig and 3D, planners,
        # Series, game produce) registers with the busy registry. Unlike the two checks above,
        # which are global on purpose, these refuse only the workspace the job writes into.
        blocking = workspace_busy.blocking(name, ws_dir)
        if blocking:
            return JSONResponse(status_code=409, content=workspace_busy.refusal(name, blocking))

        # Deleting the active workspace switches to default first. Safe to write
        # wgp.save_path directly here: nothing is generating (guards above).
        switched = False
        if get_active_workspace() == name:
            persist_active("default")
            switched = True
            print("[Workspace] Active workspace deleted — switched to default")

        from services.task_manager import forget_task_registry
        from services.win_safe_files import safe_delete_dir
        result = safe_delete_dir(ws_dir)
        # The folder held the workspace's task database. A cached registry would keep using its
        # path, and a workspace created again under the same name would fail with "no such table".
        forget_task_registry(ws_dir)
        print(f"[Workspace] Deleted '{name}': {result['files_deleted']} files removed, "
              f"{result['files_deferred']} deferred, dir_removed={result['removed']}")
        return {
            "status": "ok", "name": name,
            "files_deleted": result["files_deleted"], "files_deferred": result["files_deferred"],
            "dir_removed": result["removed"], "switched_to_default": switched, "errors": result["errors"],
        }

    return router


def create_list_outputs_router():
    """GET /api/v1/outputs at the full server's original position."""
    router = APIRouter()

    # The description is the service function's docstring, so the OpenAPI text
    # is what the full server published when it defined these handlers itself.
    @router.get("/api/v1/outputs", description=inspect.cleandoc(output_listing.list_outputs.__doc__))
    def list_outputs(
        response: Response,
        limit: int = 0,
        offset: int = 0,
        favorites_only: bool = False,
        multiclip_only: bool = False,
        edits_only: bool = False,
        search: str = "",
        workspace: str = "",
        media_type: str = "",
        result_kind: str = "",
        order: str = "",
        origin: str = "",
    ):
        try:
            return output_listing.list_outputs(
                response, limit, offset, favorites_only, multiclip_only, edits_only,
                search, workspace, media_type, result_kind, order, origin,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    return router


def create_serve_file_router():
    """GET /api/v1/file/{filename} at the full server's original position."""
    router = APIRouter()

    @router.get("/api/v1/file/{filename:path}", description=inspect.cleandoc(output_listing.serve_file.__doc__))
    def serve_file(filename: str, workspace: str | None = None, sha256: str | None = None):
        try:
            return output_listing.serve_file(filename, workspace, sha256)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    return router


def create_storage_usage_router():
    """GET /api/v1/storage/usage. The full server mounts this; the report reads WanGP weights."""
    router = APIRouter()

    @router.get("/api/v1/storage/usage", description=inspect.cleandoc(storage_usage_service.storage_usage.__doc__))
    def storage_usage():
        return storage_usage_service.storage_usage()

    return router
