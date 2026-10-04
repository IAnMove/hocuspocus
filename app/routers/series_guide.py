"""HTTP for the agent guide and compact episodes (services/series_guide.py)."""
from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from services.series_guide import build_bible, compact_episode, guide_text


def create_series_guide_router(*, read_library: Callable[[str], dict], read_kits: Callable[[str], dict],
                               workspace_dir: Callable[[str], str]) -> APIRouter:
    router = APIRouter()

    def series(workspace: str, series_id: str) -> dict:
        found = (read_library(workspace).get("seriesById") or {}).get(series_id)
        if not found:
            raise HTTPException(status_code=404, detail="Series Lab project not found")
        return found

    @router.get("/api/v1/series-agent/guide")
    def agent_guide():
        """How an agent makes an episode with the MCP tools (no series data)."""
        return {"guide": guide_text()}

    @router.get("/api/v1/series/{series_id}/guide")
    def series_guide(series_id: str, workspace: str):
        """The guide and this series' bible: characters with kits, poses and voices, locations, audio files, episodes."""
        try:
            files = os.listdir(workspace_dir(workspace))
        except OSError:
            files = []
        return {"guide": guide_text(), "bible": build_bible(series(workspace, series_id), read_kits(workspace), files)}

    @router.get("/api/v1/series/{series_id}/episodes/{episode_id}/compact")
    def compact(series_id: str, episode_id: str, workspace: str):
        project = series(workspace, series_id)
        episode = (project.get("episodesById") or {}).get(episode_id)
        if not episode:
            raise HTTPException(status_code=404, detail="Series episode not found")
        return compact_episode(project, episode)

    return router
