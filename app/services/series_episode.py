"""HTTP contract helpers for optimistic Series episode edits."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from services.series_library import EpisodeNumberTaken, SeriesConflictError, create_series_episode, update_series_episode


def _number_taken(exc: EpisodeNumberTaken) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "code": "episode_number_taken", "message": str(exc), "episodeId": exc.holder_id,
    })


def create_checked_episode(series: dict, body: Any) -> dict:
    """Create one episode. An explicit ``episode.number`` that another episode holds is HTTP 409."""
    payload = body if isinstance(body, dict) else {}
    episode = payload.get("episode") if isinstance(payload.get("episode"), dict) else {}
    season = str(payload.get("seasonId") or "") or None
    try:
        return create_series_episode(series, season, **episode)
    except EpisodeNumberTaken as exc:
        raise _number_taken(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def apply_series_episode_update(
    series_id: str,
    episode_id: str,
    body: Any,
    series: dict,
    *,
    updated_at: str,
) -> dict:
    """Validate/map one episode resource update before durable persistence."""
    if not isinstance(body, dict) or not isinstance(body.get("episode"), dict):
        raise HTTPException(status_code=400, detail="Episode is required")
    current = series.get("episodesById", {}).get(episode_id)
    if not isinstance(current, dict):
        raise HTTPException(status_code=404, detail="Series episode not found")
    try:
        return update_series_episode(
            series,
            episode_id,
            body["episode"],
            base_series_revision=body.get("baseSeriesRevision"),
            base_episode_updated_at=body.get("baseEpisodeUpdatedAt"),
            updated_at=updated_at,
        )
    except SeriesConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "series_episode_conflict",
                "message": str(exc),
                "seriesId": series_id,
                "episodeId": episode_id,
                "currentSeriesRevision": int(series.get("revision") or 1),
                "currentEpisodeUpdatedAt": current.get("updatedAt"),
            },
        ) from exc
    except EpisodeNumberTaken as exc:
        raise _number_taken(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
