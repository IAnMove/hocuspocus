"""MCP tools for the media steps of a production that used to need scripts outside HocusPocus.

- ``media.frame``: one frame of a workspace video (seconds, first or last) as a PNG.
- ``media.compose``: a still from image layers over a base image, a video frame or a blank canvas.
- ``audio.trim``: an exact cut (start + length) of an audio file as a new audio file.
- ``assets.import_from_workspace``: a file copied from another workspace of this install, with its provenance.
- ``shot.lipsync.redo``: a new lip-synced take of one shot, keeping the original.

Each one writes its result into the workspace with a ``.meta.json`` sidecar that names
the tool and its sources, so the file can be found, reused and redone in the app.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from services import audio_trim, media_compose, media_frame, shot_lipsync_redo, workspace_asset_import
from services.production_media_common import handler, workspace_folder

_TOOLS = (media_frame, media_compose, audio_trim, workspace_asset_import, shot_lipsync_redo)


def command_catalog() -> list[dict[str, Any]]:
    return [tool.catalog() for tool in _TOOLS]


def command_handlers(workspace_dir: Callable[[str], str], uploads_dir: Callable[[], str] | str) -> dict[str, Callable]:
    def folder_for(payload: dict) -> str:
        return workspace_folder(workspace_dir, payload.get("workspace"))

    def bind(tool) -> Callable[[dict], dict]:
        return lambda arguments: tool.run(arguments, workspace_dir=workspace_dir, uploads_dir=uploads_dir)

    handlers = {tool.OPERATION: handler(tool.OPERATION, bind(tool), folder_for) for tool in _TOOLS}
    handlers[shot_lipsync_redo.OPERATION] = _one_lipsync(handlers[shot_lipsync_redo.OPERATION])
    return handlers


def _one_lipsync(raw: Callable) -> Callable:
    """Refuse a second redo of the same take while the first request is still inside ``_wait_job``."""
    async def guarded(arguments: Any) -> dict:
        key = shot_lipsync_redo.flight_key(arguments)
        if key is not None and not shot_lipsync_redo.claim_flight(key):
            raise HTTPException(409, {
                "code": "already_running",
                "message": "A lip redo of this take is already running.",
                "retryable": True,
            })
        try:
            return await raw(arguments)
        finally:
            if key is not None:
                shot_lipsync_redo.release_flight(key)
    return guarded


__all__ = ["command_catalog", "command_handlers"]
