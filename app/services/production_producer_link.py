"""Link a producer to a project immediately before its worker starts.

The generators stay where they are. These functions only call ``bind_producer``.
"""

from __future__ import annotations

from typing import Any

from services.production_project_link import FORMATS, LinkError, bind_producer


def link_production_run(workspace_dir: str, data: dict[str, Any]) -> dict[str, Any]:
    """Bind ``production.run`` before the thread starts. A bad project is HTTP 422."""
    spec = data.get("spec") if isinstance(data.get("spec"), dict) else {}
    form = spec.get("format") if spec.get("format") in FORMATS else "music_video"
    request: dict[str, Any] = {
        "workspace": data.get("workspace"),
        "production_id": data.get("production_id"),
        "origin": data.get("origin") if data.get("origin") in {"mcp", "wizard", "ui"} else "mcp",
        "format": form,
        "title": str(spec.get("title") or data.get("production_id") or ""),
        "write_stub": True,
    }
    if isinstance(data.get("project"), dict):
        request["project"] = data["project"]
    try:
        return bind_producer(workspace_dir, request)
    except LinkError as error:
        from fastapi import HTTPException
        raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": False}) from error


def link_director_start(workspace_dir: str, workspace: str | None, pipeline_id: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Bind one Director pipeline before its worker starts."""
    body = params if isinstance(params, dict) else {}
    form = body.get("format") if body.get("format") in FORMATS else "quick_video"
    title = body.get("title") or body.get("story_description") or pipeline_id
    request: dict[str, Any] = {
        "workspace": workspace or "default",
        "production_id": pipeline_id,
        "origin": "ui",
        "format": form,
        "title": str(title)[:200],
        "write_stub": False,
    }
    if isinstance(body.get("project"), dict):
        request["project"] = body["project"]
    return bind_producer(workspace_dir, request)


def link_series_render(workspace_dir: str, workspace: str, episode_id: str) -> dict[str, Any]:
    """Bind a series render to the episode that already exists. No Story is created."""
    try:
        return bind_producer(workspace_dir, {
            "workspace": workspace,
            "production_id": episode_id,
            "origin": "ui",
            "format": "full_story",
            "title": "Episodio",
            "project": {"kind": "episode", "id": episode_id},
            "write_stub": False,
        })
    except LinkError as error:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=str(error)) from error
