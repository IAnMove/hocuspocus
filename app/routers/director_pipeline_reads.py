"""Director routes that both servers serve the same way.

Launch mounts each section where that route used to be declared, so the
full-server route order does not change. Core mounts the same three
factories. One include of every route at a single site would move
plan-prompts and status past the routes that sit between them.
"""
from __future__ import annotations

import traceback

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse


def create_director_plan_reads_router(ensure_llm_loaded) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/director/plan-prompts")
    async def director_plan_prompts(request: Request):
        """Use LLM to generate per-clip video prompts from audio analysis."""
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
            prompts = llm_service.plan_clip_prompts(
                clips=clips,
                style_prompt=style_prompt,
                lyrics=body.get("lyrics"),
                bpm=body.get("bpm", 120.0),
            )
            return {"prompts": prompts}
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/director/plan-angle-prompts")
    async def director_plan_angle_prompts(request: Request):
        """Use LLM to generate image-edit prompts for camera angle variations."""
        from services import llm_service
        body = await request.json()

        style_prompt = body.get("style_prompt", "")
        if not style_prompt:
            raise HTTPException(status_code=400, detail="style_prompt is required")

        ensure_llm_loaded()

        try:
            prompts = llm_service.plan_angle_prompts(
                style_prompt=style_prompt,
                num_angles=body.get("num_angles", 4),
            )
            return {"prompts": prompts}
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    return router


def create_director_pipeline_status_router(outputs_dir) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/director/pipeline/{pid}")
    def director_pipeline_status(pid: str):
        """Get current pipeline status with rich progress info."""
        from services.director_pipeline import (
            get_pipeline,
            get_pipeline_status,
            load_pipeline_state,
            resume_pipeline,
        )
        base = outputs_dir()
        p = get_pipeline_status(pid, base)
        if not p:
            # A comic PRE is a durable terminal checkpoint rather than a running
            # job. Transparently rehydrate it after a backend restart so the Comic
            # Studio can reopen its inspector by ID.
            base = outputs_dir()
            saved = load_pipeline_state(base, pid)
            if saved and saved.get("status") == "preview_ready":
                ok, _message = resume_pipeline(pid, base)
                if ok:
                    p = get_pipeline(pid)
        if not p:
            raise HTTPException(status_code=404, detail="Pipeline not found")
        # Don't leak full params back to client
        p.pop("params", None)
        fingerprint = p.get("_comic_preflight_fingerprint")
        p["preview_fingerprint"] = fingerprint
        p["preview_approved"] = bool(
            fingerprint
            and p.get("_preview_approved_fingerprint") == fingerprint
        )
        p["quality_gate"] = p.get("_quality_gate") or {
            "status": "pending",
            "fingerprint": fingerprint,
            "required_test_indices": [],
            "tested_indices": [],
            "results": {},
            "failures": [],
        }
        return p

    return router


def create_director_dashboard_reads_router(outputs_dir, active_workspace) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/director/pipelines")
    def list_saved_pipelines(limit: int = 0, offset: int = 0):
        """List saved pipeline states for the active workspace.

        Newest first. ``limit=0`` returns the full list. Workspaces passes a
        small page so opening the tab does not parse every pipeline JSON.
        """
        from services.director_pipeline import count_pipeline_states, list_pipeline_states
        base = outputs_dir()
        workspace = active_workspace()
        pipelines = list_pipeline_states(base, workspace, limit=limit, offset=offset)
        return {
            "pipelines": pipelines,
            "total": count_pipeline_states(base, workspace),
            "limit": limit,
            "offset": offset,
        }

    @router.get("/api/v1/director/pipelines/active")
    def list_active_director_pipelines():
        """List in-memory Director runs so the browser can recover after refresh."""
        from services.director_pipeline import list_active_pipelines
        return {"pipelines": list_active_pipelines(active_workspace())}

    @router.get("/api/v1/director/pipelines/{pid}")
    def get_saved_pipeline(pid: str):
        """Get a full saved pipeline state."""
        from services.director_pipeline import hydrate_queue_clips, load_pipeline_state
        base = outputs_dir()
        state = load_pipeline_state(base, pid)
        if not state:
            return JSONResponse({"error": "Pipeline not found"}, status_code=404)
        return hydrate_queue_clips(state)

    return router
