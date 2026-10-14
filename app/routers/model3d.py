"""Model3D routes shared by the full server and the core server.

The full server passes its Hunyuan3D service. The core server passes the
remote Meshy/Hi3D adapter. Capability gates and the Activity publisher are
injected so each server keeps its own answer.
"""
from __future__ import annotations

import os
import traceback
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from services import execution_mode


def create_model3d_router(
    *,
    engine: Callable[[], Any],
    resolve_input_path: Callable[..., str | None],
    workspace_dir: Callable[..., str],
    get_active_workspace: Callable[[], str],
    validate_generation: Callable[[str], None],
    collection_registry: Any,
    publish_task: Callable[..., Any] | None,
    engine_gate: Callable[[dict], None] | None = None,
) -> APIRouter:
    """The five ``/api/v1/model3d`` routes, in the full server's order."""
    router = APIRouter()

    @router.get("/api/v1/model3d/capabilities")
    def model3d_capabilities():
        return engine().capabilities()

    @router.post("/api/v1/model3d/generate")
    async def generate_model3d(request: Request):
        from services.generation_provenance import normalize_submission_provenance

        body = await request.json()
        body["provenance"] = normalize_submission_provenance(body.pop("provenance", None), trusted_tool=getattr(request, "trusted_tool", None))
        collection_id = body["provenance"].get("workspace_id")
        if collection_id and not collection_registry.get(collection_id):
            raise HTTPException(status_code=400, detail="Unknown Workspace collection")
        workspace = body.get("workspace") if "workspace" in body else get_active_workspace()
        workspace_dir(workspace)
        try:
            validate_generation(workspace)
        except execution_mode.ExecutionModeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if engine_gate is not None:
            engine_gate(body)
        raw_images = body.get("images") or {}
        if not isinstance(raw_images, dict):
            raise HTTPException(status_code=400, detail="images must be an object keyed by front/left/right/back")
        # Backward-compatible single-image input becomes the front view.
        if body.get("image_path") and not raw_images.get("front"):
            raw_images["front"] = body["image_path"]
        image_paths = {}
        for view, value in raw_images.items():
            if view not in {"front", "left", "right", "back"} or not value:
                continue
            resolved = resolve_input_path(str(value), workspace)
            if not resolved or not os.path.isfile(resolved):
                raise HTTPException(status_code=400, detail=f"3D {view} image not found")
            image_paths[view] = resolved
        source_mesh_path = None
        if str(body.get("operation") or "generate").lower() == "retexture":
            source_mesh_path = resolve_input_path(
                str(body.get("source_model") or ""), workspace,
            )
            if not source_mesh_path or not os.path.isfile(source_mesh_path):
                raise HTTPException(status_code=400, detail="Source GLB not found")
        try:
            job = engine().start_job(
                body=body,
                image_paths=image_paths,
                output_dir=workspace_dir(workspace),
                source_mesh_path=source_mesh_path,
                workspace=workspace,
            )
            if publish_task is not None:
                publish_task(job, "model3d")
            return job
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/model3d/status/{job_id}")
    def model3d_job_status(job_id: str):
        job = engine().get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="3D generation job not found")
        if publish_task is not None:
            publish_task(job, "model3d")
        return job

    @router.post("/api/v1/model3d/jobs/{job_id}/cancel")
    def cancel_model3d_job(job_id: str):
        job = engine().cancel_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="3D generation job not found")
        if publish_task is not None:
            publish_task(job, "model3d")
        return job

    @router.post("/api/v1/model3d/unload")
    def unload_model3d():
        """Stop active workers. Completed jobs already release all Hunyuan VRAM."""
        cancelled = engine().cancel_all_jobs()
        return {"status": "ok", "cancelled_jobs": cancelled, "model_loaded": False}

    # Launch's task cancel and Model3D commands call these by name.
    globals()["generate_model3d"] = generate_model3d
    globals()["model3d_job_status"] = model3d_job_status
    globals()["cancel_model3d_job"] = cancel_model3d_job
    return router
