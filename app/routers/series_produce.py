"""HTTP for an episode from a script and its one-call production (services/series_script.py, series_produce.py).

Every script written into an episode is kept with who sent it (services/series_script_history.py): the episode's
scripts are listed, read, downloaded and written again from here."""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from services.agent_activity import current_actor
from services.series_produce import ProduceError, SeriesProduce, public_job
from services.series_script import ScriptError, apply_script
from services.series_script_history import ScriptHistoryError, download_name, list_scripts, read_script, record_script

_LOGGER = logging.getLogger("loreframe.series.scripts")


class FromScript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    script: dict[str, Any]
    episodeId: str | None = Field(default=None, min_length=1, max_length=160)
    check: bool = False


class ScriptRewrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
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

    def keep_script(workspace: str, series_id: str, script: dict, result: dict, *, by: str, created: bool,
                    restored_from: int | None = None) -> dict:
        """The written episode's reply with the revision its script is kept as (a failure to keep it never fails the write)."""
        try:
            kept = record_script(workspace_dir(workspace), series_id, result["episodeId"], script, by=by, created=created,
                                 shots=len(result.get("shots") or []), languages=result.get("languages") or [],
                                 restored_from=restored_from)
        except (ScriptHistoryError, OSError) as error:
            _LOGGER.warning("Could not keep the script of %s/%s: %s", series_id, result.get("episodeId"), error)
            return {**result, "scriptRevision": None}
        return {**result, "scriptRevision": kept["revision"]}

    async def write_script(workspace: str, series_id: str, script: dict, episode_id: str | None, check: bool,
                           restored_from: int | None = None) -> dict:
        def read_series() -> dict:
            found = (read_library(workspace).get("seriesById") or {}).get(series_id)
            if not found:
                raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Series Lab project not found"})
            return found

        by = current_actor()

        def run() -> dict:
            root = workspace_dir(workspace)
            result = apply_script(call, read_series, read_kits(workspace), workspace_files(root), workspace, script,
                                  episode_id=episode_id, check_only=check, root=root)
            if check:
                return result
            return keep_script(workspace, series_id, script, result, by=by, created=not episode_id, restored_from=restored_from)

        bind_loop(asyncio.get_running_loop())
        try:
            return await run_in_threadpool(run)
        except ScriptError as error:
            raise HTTPException(status_code=400, detail={"code": "invalid_script", "message": str(error), "problems": error.problems}) from error

    def history_error(error: ScriptHistoryError) -> HTTPException:
        return HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)})

    @router.post("/api/v1/series/{series_id}/episodes/from-script")
    async def episode_from_script(series_id: str, body: FromScript):
        """Check a compact bilingual script against the series and write it as an episode with its language versions.

        A written script is kept as the episode's next script revision (``scriptRevision`` in the reply)."""
        return await write_script(body.workspace, series_id, body.script, body.episodeId, body.check)

    @router.get("/api/v1/series/{series_id}/episodes/{episode_id}/scripts")
    def episode_scripts(series_id: str, episode_id: str, workspace: str):
        """The scripts written into an episode, newest first: revision, when, who (user, agent, wizard, server), shots."""
        revisions = list_scripts(workspace_dir(workspace), series_id, episode_id)
        return {"revisions": revisions, "total": len(revisions)}

    @router.get("/api/v1/series/{series_id}/episodes/{episode_id}/scripts/{revision}")
    def episode_script(series_id: str, episode_id: str, revision: str, workspace: str, download: bool = False):
        """One script revision (``latest`` for the newest) with the script exactly as it was sent; download saves it."""
        try:
            number = None if revision == "latest" else int(revision)
        except ValueError as error:
            raise HTTPException(status_code=400, detail={"code": "invalid_revision", "message": "Use a revision number or latest"}) from error
        try:
            found = read_script(workspace_dir(workspace), series_id, episode_id, number)
        except ScriptHistoryError as error:
            raise history_error(error) from error
        if not download:
            return found
        name = download_name(series_id, episode_id, found["revision"])
        return JSONResponse(found["script"], headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @router.post("/api/v1/series/{series_id}/episodes/{episode_id}/scripts/{revision}/rewrite")
    async def rewrite_from_script(series_id: str, episode_id: str, revision: int, body: ScriptRewrite):
        """Write the episode again from one of its kept scripts (check true only checks it against the series now)."""
        try:
            found = await run_in_threadpool(read_script, workspace_dir(body.workspace), series_id, episode_id, revision)
        except ScriptHistoryError as error:
            raise history_error(error) from error
        return await write_script(body.workspace, series_id, found["script"], episode_id, body.check, restored_from=revision)

    @router.post("/api/v1/series/{series_id}/episodes/{episode_id}/produce")
    async def produce_episode(series_id: str, episode_id: str, body: ProduceStart):
        """Render the original and every language version with approval, then cut each language."""
        return await job(service.start, body.workspace, series_id, episode_id, languages=body.languages, burn_subtitles=body.burnSubtitles,
                         rerender=body.rerender)

    @router.get("/api/v1/series/produce/jobs")
    async def produce_jobs(workspace: str, series_id: str = "", episode_id: str = "", limit: int = 20):
        """The productions of a workspace, newest first (one series or episode when given): status, steps, chapters.

        Series Lab lists them with resume and cancel, so a production an agent started is found and controlled."""
        bind_loop(asyncio.get_running_loop())
        try:
            found = await run_in_threadpool(service.jobs, workspace)
        except ProduceError as error:
            raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from error
        kept = [item for item in found if (not series_id or item.get("seriesId") == series_id)
                and (not episode_id or item.get("episodeId") == episode_id)]
        kept.sort(key=lambda item: -float(item.get("createdAt") or 0))
        return {"jobs": [public_job(item) for item in kept[:max(1, min(100, limit))]], "total": len(kept)}

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
