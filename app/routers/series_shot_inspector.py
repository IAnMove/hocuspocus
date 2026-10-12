"""HTTP for Series Lab's shot inspector: one line's voice now, and a 3D shot's plan in the Video 3D editor.

* ``GET  .../shots/{shot}/voices`` lists each line's recording (``services/series_line_voice.py``) and
  ``POST`` records one line (or a retake) as a job, followed at ``GET /api/v1/series/voice-jobs/{job}``.
  ``series.shot.voices``, ``series.shot.voice`` and ``series.shot.voice.status`` (MCP) call these.
* ``GET /api/v1/series/{series_id}/shot-files`` lists the workspace files of a kind for the inspector's pickers.
* ``POST .../shots/{shot}/scene3d/editor`` returns the shot's 3D scene to open in the Video 3D editor and
  ``POST .../scene3d/from-editor`` saves the edited scene and returns the shot's new ``scene3d``
  (``services/series_shot3d_editor.py``), which the caller writes with the shot edit.
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from services.series_line_voice import SeriesLineVoice
from services.series_native_render import NativeRenderError
from services.series_shot3d_editor import Scene3DEditorError, editor_scene, from_editor
from services.series_shot_edit import ShotEditError, find_shot

_SHOTS = "/api/v1/series/{series_id}/episodes/{episode_id}/shots/{shot}"
# What a shot can name, by kind; recordings, render intermediates and hidden files are left out.
FILE_KINDS = {"audio": (".wav", ".mp3", ".flac", ".ogg", ".m4a"), "image": (".png", ".webp", ".jpg", ".jpeg"),
              "video": (".mp4", ".webm", ".mov"), "model": (".glb", ".gltf")}
_SKIPPED = (".", "_", "ln-", "foley-", "tmp-")
MAX_FILES = 500


def shot_files(root: str, kind: str) -> list[str]:
    """The workspace's files of ``kind`` (top level, newest first), at most ``MAX_FILES``."""
    suffixes = FILE_KINDS[kind]
    try:
        entries = [entry for entry in os.scandir(root) if entry.is_file() and entry.name.lower().endswith(suffixes)
                   and not entry.name.startswith(_SKIPPED) and ".room-" not in entry.name and "-raw" not in entry.name]
    except OSError:
        return []
    entries.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
    return [entry.name for entry in entries[:MAX_FILES]]


class VoiceStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    # The line's beat id, or its number among the shot's lines (1 = the first).
    line: str | int
    retake: bool = False
    language: str | None = Field(default=None, min_length=2, max_length=40)


class Scene3DOpen(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)


class Scene3DSave(Scene3DOpen):
    document: dict[str, Any]


def create_series_shot_inspector_router(*, voices: SeriesLineVoice, read_library: Callable[[str], dict],
                                        workspace_dir: Callable[[str], str], call: Callable[[str, dict], dict],
                                        bind_loop: Callable[[asyncio.AbstractEventLoop], None]) -> APIRouter:
    router = APIRouter()

    def shot_of(workspace: str, series_id: str, episode_id: str, ref: str) -> tuple[dict, dict, dict]:
        series = (read_library(workspace).get("seriesById") or {}).get(series_id)
        episode = ((series or {}).get("episodesById") or {}).get(episode_id)
        if not isinstance(episode, dict):
            raise ShotEditError("Series episode not found", status=404, code="not_found")
        return series, episode, find_shot(episode, ref)[0]

    async def run(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        # Tools run in process on this loop (services/local_mcp.py).
        bind_loop(asyncio.get_running_loop())
        try:
            return await run_in_threadpool(function, *args, **kwargs)
        except (NativeRenderError, Scene3DEditorError, ShotEditError) as error:
            status = getattr(error, "status", 400)
            raise HTTPException(status_code=status if status < 500 else 502,
                                detail={"code": getattr(error, "code", "invalid"), "message": str(error)}) from error

    @router.get("/api/v1/series/{series_id}/shot-files")
    async def series_shot_files(series_id: str, workspace: str, kind: str = Query(pattern="^(audio|image|video|model)$")):
        """Workspace files a shot can name in the inspector's pickers (sounds, props, layers, 3D models)."""
        return {"kind": kind, "files": await run_in_threadpool(shot_files, workspace_dir(workspace), kind)}

    @router.get(f"{_SHOTS}/voices")
    async def shot_voices(series_id: str, episode_id: str, shot: str, workspace: str, language: str | None = None):
        """Each line of the shot with the recording the next render reuses (file, length, newer than the take)."""
        return await run(voices.voices, workspace, series_id, episode_id, shot, language)

    @router.post(f"{_SHOTS}/voices")
    async def record_shot_voice(series_id: str, episode_id: str, shot: str, body: VoiceStart):
        """Record one line now (or another take of it) with the render's speech path; returns the job."""
        return await run(voices.start, body.workspace, series_id, episode_id, shot, body.line, retake=body.retake,
                         language=body.language)

    @router.get("/api/v1/series/voice-jobs/{job_id}")
    async def shot_voice_job(job_id: str, workspace: str):
        return await run(voices.status, workspace, job_id)

    @router.post(f"{_SHOTS}/scene3d/editor")
    async def open_shot_scene3d(series_id: str, episode_id: str, shot: str, body: Scene3DOpen):
        """The 3D shot's scene before anyone talks, to edit in the Video 3D editor."""
        def build() -> dict[str, Any]:
            series, episode, found = shot_of(body.workspace, series_id, episode_id, shot)
            return {"shotId": found["id"], **editor_scene(call, body.workspace, workspace_dir(body.workspace), series, episode, found)}
        return await run(build)

    @router.post(f"{_SHOTS}/scene3d/from-editor")
    async def save_shot_scene3d(series_id: str, episode_id: str, shot: str, body: Scene3DSave):
        """Save the edited scene as a Video 3D scene file; returns the shot's new scene3d to write with the shot edit."""
        def save() -> dict[str, Any]:
            _series, _episode, found = shot_of(body.workspace, series_id, episode_id, shot)
            return {"shotId": found["id"], **from_editor(call, body.workspace, series_id, episode_id, found, body.document)}
        return await run(save)

    return router


__all__ = ["FILE_KINDS", "create_series_shot_inspector_router", "shot_files"]
