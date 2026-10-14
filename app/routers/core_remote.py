"""Remote providers, production profile and Director planning for core/remote."""
from __future__ import annotations

import os
from typing import Any
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request

from services import core_workspace as core
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


class _CoreCollectionLookup:
    """The collections file, opened on the request so boot does not create ``outputs/``."""

    def get(self, key: str):
        from services.workspace_registry import WorkspaceRegistry
        registry = WorkspaceRegistry(os.path.join(str(core.outputs_root()), "_hocuspocus", "workspaces-v1.json"))
        return registry.get(key)


def _core_model3d_engine():
    from services.engine import core_model3d
    return core_model3d


def _core_model3d_input(value: str, workspace: str | None = None) -> str | None:
    from services.model3d_input_path import resolve_model3d_input_path
    return resolve_model3d_input_path(
        value,
        workspace,
        safe_join=core.safe_join,
        workspace_dir=core.workspace_dir,
        save_path=lambda: str(core.outputs_root()),
    )


def _core_model3d_gate(body: dict) -> None:
    from services.core_production import production_profile_response
    from services.provider_profile import alias_model3d_provider

    profile = production_profile_response()["profile"]
    provider = alias_model3d_provider(str(
        (body or {}).get("provider") or profile.get("model3d", {}).get("provider") or "local",
    ).strip().lower())
    if provider not in {"meshy", "hi3d"}:
        require_capability_http("hunyuan3d_local")


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

    from services import execution_mode
    from services.core_canonical_tasks import publish_studio_activity
    from routers.model3d import create_model3d_router

    router.include_router(create_model3d_router(
        engine=_core_model3d_engine,
        resolve_input_path=_core_model3d_input,
        workspace_dir=core.workspace_dir_or_400,
        get_active_workspace=core.active_workspace,
        validate_generation=lambda workspace: execution_mode.validate_generation(workspace),
        collection_registry=_CoreCollectionLookup(),
        publish_task=publish_studio_activity,
        engine_gate=_core_model3d_gate,
    ))

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
