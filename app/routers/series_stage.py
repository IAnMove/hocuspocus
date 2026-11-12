"""HTTP for calibrating a location plate's perspective (``services/series_stage_ops.py``).

``POST /api/v1/series/{series}/locations/{location}/stage`` is the door of the ``series.location.stage.set`` MCP tool and the Wizard's
``set_series_location_stage``; ``.../stage/check`` of ``series.location.stage.check`` and ``check_series_location_stage``. Series Lab's
location panel (``SeriesLocationStage``) calls the same two.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from services.series_stage_ops import SeriesStage, StageError


class StageSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    horizon: float | None = None
    ref: dict[str, Any] | None = None
    floorTop: float | None = None
    clear: bool = False


class StageCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    asset_id: str | None = Field(default=None, max_length=160)
    file: str | None = Field(default=None, max_length=300)
    step: float | None = None
    horizon: float | None = None
    ref: dict[str, Any] | None = None
    floorTop: float | None = None


def create_series_stage_router(service: SeriesStage, bind_loop: Callable[[asyncio.AbstractEventLoop], None]) -> APIRouter:
    router = APIRouter()

    async def call(function: Callable[..., dict[str, Any]], *args: Any) -> dict[str, Any]:
        bind_loop(asyncio.get_running_loop())
        try:
            return await run_in_threadpool(function, *args)
        except StageError as error:
            raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from error

    @router.post("/api/v1/series/{series_id}/locations/{location_id}/stage")
    async def set_stage(series_id: str, location_id: str, body: StageSet):
        """Store the plate's perspective on the location (or ``clear``): 2D wide and two-shots are then sized by it."""
        workspace = body.workspace
        return await call(service.set, workspace, series_id, location_id, body.model_dump(exclude={"workspace"}, exclude_none=True))

    @router.post("/api/v1/series/{series_id}/locations/{location_id}/stage/check")
    async def check_stage(series_id: str, location_id: str, body: StageCheck):
        """Draw a grid over the plate (a workspace file) and answer with the numbers to read it by and a horizon guess."""
        return await call(service.check, body.workspace, series_id, location_id, body.model_dump(exclude={"workspace"}, exclude_none=True))

    return router
