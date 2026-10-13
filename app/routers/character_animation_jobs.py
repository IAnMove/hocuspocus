"""HTTP for making a character's animations on the server (services/character_animation_job.py).

The Character Creator panel, the ``characters.animation.make`` MCP tools and the Wizard's ``make_character_animation`` all call
these routes: one place that makes the poses, joins the sheet and saves it on the kit for a person to review.

* ``POST /api/v1/character-kits/animations/make`` starts (or returns the running) job;
* ``GET  /api/v1/character-kits/animations/jobs`` lists a workspace's jobs, newest first (``kitId`` narrows them);
* ``GET  /api/v1/character-kits/animations/jobs/{job}`` follows one;
* ``POST /api/v1/character-kits/animations/jobs/{job}/cancel`` stops it; its poses stay for the next try.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from services.character_animation_job import AnimationJobError, CharacterAnimationJobs


class CustomAnimation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=80)
    view: str = Field(pattern="^(bust|front|side)$")
    poses: list[str] = Field(min_length=1, max_length=12)


class MakeAnimation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=120)
    kitId: str = Field(min_length=1, max_length=160)
    animation: str = Field(min_length=1, max_length=64)
    custom: CustomAnimation | None = None
    pose: str | None = Field(default=None, min_length=1, max_length=120)
    model: str | None = Field(default=None, max_length=80)


class JobAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=120)


def create_character_animation_jobs_router(jobs: CharacterAnimationJobs, *, bind_loop: Callable[[asyncio.AbstractEventLoop], Any] | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/character-kits/animations", tags=["Character kits"])

    async def run(function, *args: Any, **kwargs: Any) -> Any:
        try:
            return await run_in_threadpool(function, *args, **kwargs)
        except AnimationJobError as error:
            raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": str(error)}) from error

    @router.post("/make")
    async def make_animation(body: MakeAnimation):
        """Make an animation of a saved character (or, with ``pose``, one pose of it again). It is saved as pending review."""
        if bind_loop is not None:
            bind_loop(asyncio.get_running_loop())  # the job's tool calls run on the server's loop, as an MCP client's would
        custom = body.custom.model_dump() if body.custom else None
        return {"job": await run(jobs.start, body.workspace, body.kitId, body.animation, custom=custom, pose=body.pose, model=body.model)}

    @router.get("/jobs")
    async def list_jobs(workspace: str, kitId: str | None = None):
        return {"jobs": await run(jobs.jobs, workspace, kitId)}

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: str, workspace: str):
        return {"job": await run(jobs.status, workspace, job_id)}

    @router.post("/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str, body: JobAction):
        return {"job": await run(jobs.cancel, body.workspace, job_id)}

    return router
