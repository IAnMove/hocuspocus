"""HTTP for the server-side Series episode render (``services/series_native_render.py``)."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from services.series_native_render import NativeRenderError, SeriesNativeRender, public_job


class NativeRenderStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    shotIds: list[str] | None = Field(default=None, max_length=500)
    approve: bool = False
    language: str | None = Field(default=None, min_length=2, max_length=40)
    # Only the shots that need a render: out of date, and let through by the episode's staged review.
    changed: bool = False


class NativeRenderAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)


def _http(error: NativeRenderError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)})


def create_series_native_render_router(service: SeriesNativeRender, bind_loop: Callable[[asyncio.AbstractEventLoop], None]) -> APIRouter:
    router = APIRouter()

    async def call(function: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
        # The job runs tools on this loop (see services/local_mcp.py).
        bind_loop(asyncio.get_running_loop())
        try:
            return public_job(await run_in_threadpool(function, *args, **kwargs))
        except NativeRenderError as error:
            raise _http(error) from error

    @router.post("/api/v1/series/{series_id}/episodes/{episode_id}/native-render")
    async def start_native_render(series_id: str, episode_id: str, body: NativeRenderStart):
        """Voices, scene, headless export and take for every 2D shot, on the server."""
        return await call(service.start, body.workspace, series_id, episode_id, shot_ids=body.shotIds, approve=body.approve,
                          language=body.language, changed=body.changed)

    @router.get("/api/v1/series/native-render/jobs/{job_id}")
    async def native_render_status(job_id: str, workspace: str):
        return await call(service.status, workspace, job_id)

    @router.post("/api/v1/series/native-render/jobs/{job_id}/cancel")
    async def cancel_native_render(job_id: str, body: NativeRenderAction):
        return await call(service.cancel, body.workspace, job_id)

    @router.post("/api/v1/series/native-render/jobs/{job_id}/resume")
    async def resume_native_render(job_id: str, body: NativeRenderAction):
        return await call(service.resume, body.workspace, job_id)

    @router.get("/api/v1/series/native-render/recovery")
    async def native_render_recovery(workspace: str):
        bind_loop(asyncio.get_running_loop())
        jobs = await run_in_threadpool(service.jobs, workspace)
        return {"jobs": [public_job(job) for job in jobs]}

    return router
