"""HTTP for an episode from a script and its one-call production (services/series_script.py, series_produce.py)."""
from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from services.series_produce import ProduceError, SeriesProduce, public_job
from services.series_script import ScriptError, apply_script


class FromScript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    script: dict[str, Any]
    episodeId: str | None = Field(default=None, min_length=1, max_length=160)
    check: bool = False


class ProduceStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    languages: list[str] | None = Field(default=None, max_length=10)
    burnSubtitles: bool = True
    rerender: bool = False


class ProduceAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)


def workspace_files(root: str, depth: int = 1) -> set[str]:
    """Relative paths of the workspace files a script may name, up to ``depth`` folders down (``music/theme.wav``)."""
    found: set[str] = set()
    base = os.path.abspath(root)
    try:
        for current, folders, names in os.walk(base):
            relative = os.path.relpath(current, base)
            level = 0 if relative == "." else relative.count(os.sep) + 1
            folders[:] = [] if level >= depth else [folder for folder in folders if not folder.startswith(".")]
            for name in names:
                if not name.startswith("."):
                    found.add(name if relative == "." else f"{relative}/{name}".replace(os.sep, "/"))
    except OSError:
        pass
    return found


def create_series_produce_router(service: SeriesProduce, *, call: Callable[[str, dict], dict], bind_loop: Callable[[asyncio.AbstractEventLoop], None],
                                 read_library: Callable[[str], dict], read_kits: Callable[[str], dict],
                                 workspace_dir: Callable[[str], str]) -> APIRouter:
    router = APIRouter()

    async def job(function: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
        # The job runs tools on this loop (see services/local_mcp.py).
        bind_loop(asyncio.get_running_loop())
        try:
            return public_job(await run_in_threadpool(function, *args, **kwargs))
        except ProduceError as error:
            raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from error

    @router.post("/api/v1/series/{series_id}/episodes/from-script")
    async def episode_from_script(series_id: str, body: FromScript):
        """Check a compact bilingual script against the series and write it as an episode with its language versions."""
        def read_series() -> dict:
            found = (read_library(body.workspace).get("seriesById") or {}).get(series_id)
            if not found:
                raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Series Lab project not found"})
            return found

        def run() -> dict:
            root = workspace_dir(body.workspace)
            return apply_script(call, read_series, read_kits(body.workspace), workspace_files(root), body.workspace, body.script,
                                episode_id=body.episodeId, check_only=body.check, root=root)

        bind_loop(asyncio.get_running_loop())
        try:
            return await run_in_threadpool(run)
        except ScriptError as error:
            raise HTTPException(status_code=400, detail={"code": "invalid_script", "message": str(error), "problems": error.problems}) from error

    @router.post("/api/v1/series/{series_id}/episodes/{episode_id}/produce")
    async def produce_episode(series_id: str, episode_id: str, body: ProduceStart):
        """Render the original and every language version with approval, then cut each language."""
        return await job(service.start, body.workspace, series_id, episode_id, languages=body.languages, burn_subtitles=body.burnSubtitles,
                         rerender=body.rerender)

    @router.get("/api/v1/series/produce/jobs/{job_id}")
    async def produce_status(job_id: str, workspace: str):
        return await job(service.status, workspace, job_id)

    @router.post("/api/v1/series/produce/jobs/{job_id}/cancel")
    async def cancel_produce(job_id: str, body: ProduceAction):
        return await job(service.cancel, body.workspace, job_id)

    @router.post("/api/v1/series/produce/jobs/{job_id}/resume")
    async def resume_produce(job_id: str, body: ProduceAction):
        return await job(service.resume, body.workspace, job_id)

    return router
