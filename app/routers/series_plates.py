"""HTTP for 3D background plates of series locations (``services/series_plates.py``)."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from services.series_plates import PlateError, SeriesPlates


class PlateStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    scene: str | None = Field(default=None, min_length=1, max_length=200)
    document: dict[str, Any] | None = None
    seconds: float = Field(default=6.0, ge=2, le=20)
    quality: str = "draft"


def create_series_plates_router(service: SeriesPlates, bind_loop: Callable[[asyncio.AbstractEventLoop], None]) -> APIRouter:
    router = APIRouter()

    async def call(function: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
        bind_loop(asyncio.get_running_loop())
        try:
            return await run_in_threadpool(function, *args, **kwargs)
        except PlateError as error:
            raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from error

    @router.post("/api/v1/series/{series_id}/locations/{location_id}/plate3d")
    async def start_location_plate(series_id: str, location_id: str, body: PlateStart):
        """Render a Video 3D scene once, silent and looping, as this location's 2D background."""
        return await call(service.start, body.workspace, series_id, location_id, document=body.document, scene=body.scene,
                          seconds=body.seconds, quality=body.quality)

    @router.get("/api/v1/series/{series_id}/locations/{location_id}/plate3d")
    async def location_plate_status(series_id: str, location_id: str, workspace: str):
        """Follow the export; when its MP4 is ready it becomes the location's plate."""
        return await call(service.status, workspace, series_id, location_id)

    return router
