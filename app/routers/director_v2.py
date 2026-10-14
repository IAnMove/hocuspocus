"""Director v2 plan routes for the full server.

The core server does not mount these routes. Handlers stay module-level so a
move keeps the launch function name, and the served route table names this
file. This module does not import WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import copy

from fastapi import APIRouter, HTTPException, Request

from services.director_v2_plan import _director_plan_job_store, _director_v2_plan_body


async def director_v2_plan(request: Request):
    """Run a Director plan while checkpointing bounded music-video batches."""
    return await _director_v2_plan_body(await request.json())


def list_director_v2_plan_jobs(workspace: str = "default"):
    """List durable Director planning checkpoints without exposing prompts."""
    store = _director_plan_job_store(workspace)
    return {
        "jobs": [store.public_snapshot(job) for job in store.list()],
    }


def get_director_v2_plan_job(job_id: str, workspace: str = "default"):
    store = _director_plan_job_store(workspace)
    job = store.load(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Director plan job not found")
    return store.public_snapshot(job)


async def resume_director_v2_plan_job(
    job_id: str,
    request: Request,
    workspace: str = "default",
):
    """Resume only the missing indexes from a durable planning checkpoint."""
    store = _director_plan_job_store(workspace)
    job = store.load(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Director plan job not found")
    if job.get("status") == "completed" and isinstance(job.get("result"), dict):
        return copy.deepcopy(job["result"])
    body = copy.deepcopy(job.get("request") or {})
    if not isinstance(body, dict):
        raise HTTPException(status_code=409, detail="Director plan job request is unavailable")
    try:
        override = await request.json()
    except Exception:
        override = {}
    if isinstance(override, dict) and str(override.get("activity_id") or "").strip():
        body["activity_id"] = str(override["activity_id"]).strip()[:160]
    body["workspace"] = workspace
    body["plan_job_id"] = job_id
    return await _director_v2_plan_body(body)


def director_v2_plan_progress(activity_id: str):
    """Return live sub-step and provider-reported token usage for one plan."""
    from services import llm_service
    state = llm_service.get_activity_tracking(activity_id)
    if not state:
        raise HTTPException(status_code=404, detail="Planning activity not found")
    return state


def create_director_v2_router() -> APIRouter:
    """V2 plan routes in the order the full server registered them."""
    router = APIRouter()
    router.add_api_route(
        "/api/v1/director/v2/plan",
        director_v2_plan,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/v2/plan/jobs",
        list_director_v2_plan_jobs,
        methods=["GET"],
    )
    router.add_api_route(
        "/api/v1/director/v2/plan/jobs/{job_id}",
        get_director_v2_plan_job,
        methods=["GET"],
    )
    router.add_api_route(
        "/api/v1/director/v2/plan/jobs/{job_id}/resume",
        resume_director_v2_plan_job,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/v2/plan/progress/{activity_id}",
        director_v2_plan_progress,
        methods=["GET"],
    )
    return router
