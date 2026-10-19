"""HTTP for putting a Video 2D card on a Series shot (``services/series_shot_card.py``).

``POST /api/v1/series/{series}/episodes/{episode}/shots/{shot}/card`` is the door of the ``series.shot.card.apply`` MCP tool and the
Wizard's ``apply_series_shot_card``. The shot is its id or its number in the episode. It answers ``completed`` with the new take, or
``exporting`` when the scene is still being exported: send the same request again to finish.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from services.series_shot_card import CardApplyError, SeriesShotCard


class CardCast(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: str | None = Field(default=None, max_length=40)
    characterId: str = Field(min_length=1, max_length=160)
    animation: str | dict[str, Any] | None = None
    poseId: str | None = Field(default=None, max_length=160)


class CardApply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    card: str = Field(min_length=1, max_length=120)
    controls: dict[str, Any] | None = None
    cast: list[CardCast] | None = Field(default=None, max_length=6)
    assets: dict[str, str] | None = None
    language: str | None = Field(default=None, min_length=2, max_length=40)
    approve: bool = False


def create_series_shot_card_router(service: SeriesShotCard, bind_loop: Callable[[asyncio.AbstractEventLoop], None]) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/series/{series_id}/episodes/{episode_id}/shots/{shot}/card")
    async def apply_card(series_id: str, episode_id: str, shot: str, body: CardApply):
        """Compile a card with the shot's characters and plate, save it as an editable scene and attach it as a new take."""
        bind_loop(asyncio.get_running_loop())  # the server's tools run on this loop (services/local_mcp.py)
        cast = [item.model_dump(exclude_none=True) for item in body.cast] if body.cast is not None else None
        try:
            return await run_in_threadpool(
                service.apply, body.workspace, series_id, episode_id, shot, body.card, controls=body.controls, cast=cast,
                assets=body.assets, language=body.language, approve=body.approve)
        except CardApplyError as error:
            raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from error

    return router
