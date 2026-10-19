"""HTTP for making several animations of a character as one server job (services/character_animation_set_job.py).

The Characters › Animaciones button «Crear andares completos», the ``characters.animation.make_set`` MCP tool and the Wizard's
``make_character_animation_set`` all call these routes: one place that decides which sheets are missing, makes them one after another and
saves each on the character for a person to review.

* ``POST /api/v1/character-kits/animations/make-set`` starts (or returns the running) set job; ``autoApprove`` asks each sheet to be approved
  when it passes the automatic checks, in «Modo un solo disparo» only;
* ``GET  /api/v1/character-kits/animations/sets`` lists a workspace's set jobs, newest first (``kitId`` narrows them);
* ``GET  /api/v1/character-kits/animations/sets/{job}`` follows one (its ``sheets`` say which are done);
* ``POST /api/v1/character-kits/animations/sets/{job}/cancel`` stops it; every sheet and pose already made stays.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from services.character_animation_job import AnimationJobError
from services.character_animation_set_job import CharacterAnimationSets


class MakeSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=120)
    kitId: str = Field(min_length=1, max_length=160)
    set: str = Field(min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=80)
    autoApprove: bool = False


class SetAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=120)


def create_character_animation_sets_router(sets: CharacterAnimationSets, *, bind_loop: Callable[[asyncio.AbstractEventLoop], Any] | None = None) -> APIRouter:
    router = APIRouter(prefix="/animations", tags=["Character kits"])  # mounted under /api/v1/character-kits
    # No busy probe of its own: the set service adds its live jobs to the ``character-animation`` probe of the animation jobs router.

    async def run(function, *args: Any, **kwargs: Any) -> Any:
        try:
            return await run_in_threadpool(function, *args, **kwargs)
        except AnimationJobError as error:
            raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": str(error)}) from error

    @router.post("/make-set")
    async def make_set(body: MakeSet):
        """Make the sheets of a set that the character does not have, one after another. Each is saved as pending review."""
        if bind_loop is not None:
            bind_loop(asyncio.get_running_loop())  # the job's tool calls run on the server's loop, as an MCP client's would
        return {"job": await run(sets.start, body.workspace, body.kitId, body.set, model=body.model, auto_approve=body.autoApprove)}

    @router.get("/sets")
    async def list_sets(workspace: str, kitId: str | None = None):
        return {"jobs": await run(sets.jobs, workspace, kitId)}

    @router.get("/sets/{job_id}")
    async def get_set(job_id: str, workspace: str):
        return {"job": await run(sets.status, workspace, job_id)}

    @router.post("/sets/{job_id}/cancel")
    async def cancel_set(job_id: str, body: SetAction):
        return {"job": await run(sets.cancel, body.workspace, job_id)}

    return router
