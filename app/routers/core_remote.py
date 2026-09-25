"""Remote providers, production profile and Director planning for core/remote."""
from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from services import core_remote_3d, core_remote_music, core_workspace as core
from services.core_production import (
    ensure_llm_loaded,
    production_profile_response,
    save_production_profile,
)
from services.director_pipeline_state import (
    _find_pipeline_file,
    _iter_pipeline_state_files,
    count_pipeline_states,
)
from routers.system_capabilities import require_capability_http


def _workspace(value: Any) -> str:
    name = str(value or core.active_workspace() or "default").strip()
    try:
        core.workspace_dir(name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return name


def _summarize_pipeline(filepath: str, workspace_name: str) -> dict[str, Any] | None:
    try:
        with open(filepath, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    clips = data.get("clips") or data.get("clip_plans") or data.get("planned_clips") or []
    return {
        "id": data.get("pipeline_id", ""),
        "status": data.get("status", "unknown"),
        "phase": data.get("phase") or data.get("status"),
        "pipeline_type": data.get("pipeline_type", ""),
        "generation_mode": data.get("generation_mode", "image_guided"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "completed_at": data.get("completed_at"),
        "progress": dict(data.get("progress") or {}),
        "error": data.get("error"),
        "clip_count": len(clips) if isinstance(clips, list) else 0,
        "output_count": len(data.get("output_files") or []),
        "output_files": list(data.get("output_files") or []),
        "scene_description": (data.get("scene_description") or "")[:100],
        "workspace": workspace_name,
    }


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

    @router.get("/api/v1/director/pipelines")
    def list_pipelines(limit: int = 0, offset: int = 0):
        workspace = core.active_workspace()
        base = str(core.outputs_root())
        files = _iter_pipeline_state_files(base, workspace)
        if offset < 0:
            offset = 0
        selected = files[offset:offset + limit] if limit and limit > 0 else files[offset:]
        pipelines = [row for path in selected if (row := _summarize_pipeline(path[1], path[2]))]
        return {"pipelines": pipelines, "total": count_pipeline_states(base, workspace), "limit": limit, "offset": offset}

    @router.get("/api/v1/director/pipelines/active")
    def active_pipelines():
        return {"pipelines": []}

    @router.get("/api/v1/director/pipelines/{pid}")
    def get_pipeline(pid: str):
        path = _find_pipeline_file(str(core.outputs_root()), pid)
        if not path or not os.path.isfile(path):
            raise HTTPException(status_code=404, detail="Pipeline not found")
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=404, detail="Pipeline not found") from error
        if isinstance(data, dict):
            data.pop("params", None)
        return data

    @router.get("/api/v1/director/pipeline/{pid}")
    def pipeline_status(pid: str):
        return get_pipeline(pid)

    @router.post("/api/v1/director/plan-prompts")
    async def plan_prompts(request: Request):
        from services import llm_service

        body = await request.json()
        clips = body.get("clips")
        style_prompt = body.get("style_prompt", "")
        if not clips:
            raise HTTPException(status_code=400, detail="clips is required")
        if not style_prompt:
            raise HTTPException(status_code=400, detail="style_prompt is required")
        ensure_llm_loaded()
        try:
            return {"prompts": llm_service.plan_clip_prompts(
                clips=clips, style_prompt=style_prompt,
                lyrics=body.get("lyrics"), bpm=body.get("bpm", 120.0),
            )}
        except Exception as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    @router.post("/api/v1/director/plan-angle-prompts")
    async def plan_angle_prompts(request: Request):
        from services import llm_service

        body = await request.json()
        style_prompt = body.get("style_prompt", "")
        if not style_prompt:
            raise HTTPException(status_code=400, detail="style_prompt is required")
        ensure_llm_loaded()
        try:
            return {"prompts": llm_service.plan_angle_prompts(
                style_prompt=style_prompt, num_angles=body.get("num_angles", 4),
            )}
        except Exception as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    @router.post("/api/v1/director/pipeline/start")
    def director_start():
        require_capability_http("wangp_local")
        return {"status": "ok"}

    @router.post("/api/v1/director/pipeline/{pid}/continue")
    def director_continue(pid: str):
        require_capability_http("wangp_local")
        return {"status": "ok", "pipeline_id": pid}

    return router
