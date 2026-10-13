"""Remote providers, production profile and Director planning for core/remote."""
from __future__ import annotations

from typing import Any
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request

from services import core_remote_3d, core_workspace as core
from services.core_canonical_tasks import publish_music_activity
from services.story_music_jobs import bind_story_music_jobs
from routers.story_music import create_story_music_router
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


class _CoreMusicServices:
    """Live services map. The worker reads it when a candidate starts, not at boot."""

    def get(self, key, default=None):
        if key == "services":
            return core.services_raw()
        return default


def _core_music_workspace_dir(workspace: str | None = None) -> str:
    try:
        return core.workspace_dir(workspace)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _core_story_cover_reference_path(filename: str, workspace: str) -> str | None:
    try:
        return core.resolve_media(str(filename or ""), workspace)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def core_music_generation_gate(body: dict) -> None:
    """Local music stays unavailable (409) before Story Lab's paid-model check."""
    from routers.system_capabilities import require_capability_http as require_local
    from services.music_model_contract import DEFAULT_MUSIC_MODEL
    from services.music_submission import MusicSubmissionError, classify_music_route

    model = str((body or {}).get("model") or DEFAULT_MUSIC_MODEL).strip()
    try:
        route = classify_music_route(model)
    except MusicSubmissionError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    if route != "remote_minimax":
        require_local("local_audio_ai")


def _core_music_before_reserve(workspace: str) -> None:
    """Open Activity before the reservation writes a task, so startup interrupt cannot eat it."""
    from services import core_generation_commands

    core_generation_commands.registry_for(str(workspace or "default"))


def _core_story_music_binding():
    music_wgp = SimpleNamespace(server_config=_CoreMusicServices())
    jobs = bind_story_music_jobs(
        workspace_dir=_core_music_workspace_dir,
        list_workspaces=core.list_workspaces,
        wgp_module=music_wgp,
        publish_legacy_task=publish_music_activity,
    )
    return jobs, music_wgp


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

    music_jobs, music_wgp = _core_story_music_binding()
    router.include_router(create_story_music_router(
        music_jobs,
        get_active_workspace=core.active_workspace,
        story_cover_reference_path=_core_story_cover_reference_path,
        wgp_module=music_wgp,
        music_generation_gate=core_music_generation_gate,
        before_reserve=_core_music_before_reserve,
        resolve_workspace=_workspace,
    ))

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
