"""Remote providers, production profile and Director planning for core/remote."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from services import core_remote_3d, core_remote_music, core_workspace as core
from services.core_production import (
    ensure_llm_loaded,
    production_profile_response,
    save_production_profile,
)
from routers.director_pipeline_reads import (
    create_director_dashboard_reads_router,
    create_director_pipeline_status_router,
    create_director_plan_reads_router,
)
from routers.system_capabilities import require_capability_http


def _workspace(value: Any) -> str:
    name = str(value or core.active_workspace() or "default").strip()
    try:
        core.workspace_dir(name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return name


def create_core_remote_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/production-profile")
    def get_production_profile():
        return production_profile_response()

    @router.put("/api/v1/production-profile")
    async def put_production_profile(request: Request):
        body = await request.json()
        try:
            return save_production_profile(body.get("profile") if isinstance(body, dict) else None)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/api/v1/model3d/capabilities")
    def model3d_capabilities():
        return core_remote_3d.capabilities()

    @router.post("/api/v1/model3d/generate")
    async def generate_model3d(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        workspace = _workspace(body.get("workspace"))
        try:
            return core_remote_3d.start_job(body, workspace=workspace, output_dir=core.workspace_dir(workspace))
        except HTTPException:
            raise
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/api/v1/model3d/status/{job_id}")
    def model3d_status(job_id: str):
        job = core_remote_3d.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="3D generation job not found")
        return job

    @router.post("/api/v1/model3d/jobs/{job_id}/cancel")
    def model3d_cancel(job_id: str):
        job = core_remote_3d.cancel_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="3D generation job not found")
        return job

    @router.post("/api/v1/stories/music-candidates/jobs", status_code=202)
    def start_music_job(body: dict):
        workspace = _workspace(body.get("workspace") if isinstance(body, dict) else None)
        try:
            return core_remote_music.start_job(body or {}, workspace=workspace)
        except HTTPException:
            raise
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/api/v1/stories/music-candidates/jobs/{job_id}")
    def music_job_status(job_id: str):
        job = core_remote_music.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="MiniMax Music job not found")
        return job

    @router.post("/api/v1/stories/music-candidates/jobs/{job_id}/cancel")
    def music_job_cancel(job_id: str):
        job = core_remote_music.cancel_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="MiniMax Music job not found")
        return job

    router.include_router(create_director_plan_reads_router(ensure_llm_loaded=ensure_llm_loaded))
    router.include_router(create_director_pipeline_status_router(
        outputs_dir=lambda: str(core.outputs_root()),
    ))
    router.include_router(create_director_dashboard_reads_router(
        outputs_dir=lambda: str(core.outputs_root()),
        active_workspace=core.active_workspace,
    ))

    @router.post("/api/v1/director/pipeline/start")
    def director_start():
        require_capability_http("wangp_local")
        return {"status": "ok"}

    @router.post("/api/v1/director/pipeline/{pid}/continue")
    def director_continue(pid: str):
        require_capability_http("wangp_local")
        return {"status": "ok", "pipeline_id": pid}

    return router
