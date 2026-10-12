"""MCP tools for the media steps of a production that used to need scripts outside HocusPocus.

- ``media.frame``: one frame of a workspace video (seconds, first or last) as a PNG.
- ``media.compose``: a still from image layers over a base image, a video frame or a blank canvas.
- ``audio.trim``: an exact cut (start + length) of an audio file as a new audio file.
- ``assets.import_from_workspace``: a file copied from another workspace of this install, with its provenance.

Each one writes its result into the workspace with a ``.meta.json`` sidecar that names
the tool and its sources, so the file can be found, reused and redone in the app.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from services import audio_trim, media_compose, media_frame, workspace_asset_import
from services.production_media_common import handler, workspace_folder

_TOOLS = (media_frame, media_compose, audio_trim, workspace_asset_import)


def command_catalog() -> list[dict[str, Any]]:
    return [tool.catalog() for tool in _TOOLS]


def command_handlers(workspace_dir: Callable[[str], str], uploads_dir: Callable[[], str] | str) -> dict[str, Callable]:
    def folder_for(payload: dict) -> str:
        return workspace_folder(workspace_dir, payload.get("workspace"))

    def bind(tool) -> Callable[[dict], dict]:
        return lambda arguments: tool.run(arguments, workspace_dir=workspace_dir, uploads_dir=uploads_dir)

    return {tool.OPERATION: handler(tool.OPERATION, bind(tool), folder_for) for tool in _TOOLS}


__all__ = ["command_catalog", "command_handlers"]
