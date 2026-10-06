"""HTTP for an episode's staged review (``services/series_review.py``): its production mode, the plan and preview
decision of each shot, and the user's and agents' notes. Shared by the full launch and the core runtime."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services.agent_activity import current_actor
from services.series_review import MAX_CHANGES, ReviewError, apply_review_change, report, stored_review, summary


class ReviewWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    baseRevision: int | None = Field(default=None, ge=0)
    mode: str | None = Field(default=None, max_length=20)
    shots: list[dict[str, Any]] | None = Field(default=None, max_length=MAX_CHANGES)


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "not_found", "message": message})


def _locate(library: dict, series_id: str, episode_id: str) -> tuple[dict, dict]:
    series = (library.get("seriesById") or {}).get(series_id)
    if not isinstance(series, dict):
        raise _not_found("Series Lab project not found")
    episode = (series.get("episodesById") or {}).get(episode_id)
    if not isinstance(episode, dict):
        raise _not_found("Series episode not found")
    return series, episode


def create_series_review_router(*, resolve_workspace: Callable[[Any], str], lock: Any, read_library: Callable[[str], dict],
                                write_library: Callable[[str, dict], dict], iso_now: Callable[[], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/series/{series_id}/episodes/{episode_id}/review")
    def get_episode_review(series_id: str, episode_id: str, workspace: str | None = None):
        """Mode, counts, the steps left and every shot's decisions and notes."""
        target = resolve_workspace(workspace)
        with lock:
            series, episode = _locate(read_library(target), series_id, episode_id)
            return report(series, episode)

    @router.post("/api/v1/series/{series_id}/episodes/{episode_id}/review")
    def set_episode_review(series_id: str, episode_id: str, body: ReviewWrite):
        """Set the mode and/or decide shots and write notes; nothing is applied when one change is refused."""
        target = resolve_workspace(body.workspace)
        with lock:
            library = read_library(target)
            series, episode = _locate(library, series_id, episode_id)
            revision = int(series.get("revision") or 1)
            if body.baseRevision is not None and body.baseRevision != revision:
                raise HTTPException(status_code=409, detail={
                    "code": "series_conflict", "currentSeriesRevision": revision,
                    "message": f"Series revision changed from {body.baseRevision} to {revision}; reload before reviewing"})
            now = iso_now()
            try:
                # Who decides: a person, or an agent / the Wizard through its declared actor (ActorHeaderMiddleware).
                note_ids = apply_review_change(episode, body.model_dump(include={"mode", "shots"}, exclude_none=True), now=now,
                                               by=current_actor())
            except ReviewError as error:
                raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from error
            series.update(revision=revision + 1, updatedAt=now)
            stored = write_library(target, library)
        saved = stored["seriesById"][series_id]["episodesById"][episode_id]
        return {"revision": revision + 1, "episodeId": episode_id, "episodeUpdatedAt": saved.get("updatedAt"),
                "review": stored_review(saved), "noteIds": note_ids, "summary": summary(saved)}

    return router
