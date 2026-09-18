"""HTTP surface for Series Lab planning on the core/remote profile."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services import core_series_plan as plans


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc) or "Not found")
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def create_core_series_plan_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/series/{series_id}/episodes/{episode_id}/plan/start")
    def start_episode(series_id: str, episode_id: str, body: dict):
        try:
            return plans.start_episode_plan(series_id, episode_id, body or {})
        except (KeyError, ValueError, PermissionError) as error:
            raise _http(error) from error

    @router.post("/api/v1/series/{series_id}/canon/prepare/start")
    def start_canon(series_id: str, body: dict):
        try:
            return plans.start_canon_plan(series_id, body or {})
        except (KeyError, ValueError, PermissionError) as error:
            raise _http(error) from error

    @router.get("/api/v1/series/plan/jobs/{job_id}")
    def get_job(job_id: str):
        job = plans.load_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Series planning job not found")
        return plans._public(job)

    @router.post("/api/v1/series/plan/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        try:
            return plans.cancel_job(job_id)
        except KeyError as error:
            raise _http(error) from error

    @router.post("/api/v1/series/plan/jobs/{job_id}/resume")
    def resume_job(job_id: str):
        try:
            return plans.resume_job(job_id)
        except KeyError as error:
            raise _http(error) from error

    @router.post("/api/v1/series/plan/jobs/{job_id}/apply")
    def apply_episode(job_id: str, body: dict | None = None):
        try:
            edited = body.get("episodeResult") if isinstance(body, dict) else None
            return plans.apply_episode(job_id, edited)
        except (KeyError, ValueError, PermissionError) as error:
            raise _http(error) from error

    @router.post("/api/v1/series/plan/jobs/{job_id}/apply-canon")
    def apply_canon(job_id: str):
        try:
            return plans.apply_canon(job_id)
        except (KeyError, ValueError, PermissionError) as error:
            raise _http(error) from error

    return router
