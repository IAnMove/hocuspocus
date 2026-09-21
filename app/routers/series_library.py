"""Series Lab library and project HTTP surface shared by full launch and core runtime.

Plan/render/assembly jobs stay on their existing owners. This module does not
import WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException


_resolve_workspace: Callable[..., str]
_library_lock: Any
_read_library: Callable[[str], dict]
_write_library: Callable[[str, dict], dict]
_project_or_404: Callable[[dict, str], dict]


def _bind_series_library_runtime(
    *,
    resolve_workspace: Callable[..., str],
    library_lock: Any,
    read_library: Callable[[str], dict],
    write_library: Callable[[str, dict], dict],
    project_or_404: Callable[[dict, str], dict],
) -> None:
    global _resolve_workspace, _library_lock, _read_library, _write_library, _project_or_404
    _resolve_workspace = resolve_workspace
    _library_lock = library_lock
    _read_library = read_library
    _write_library = write_library
    _project_or_404 = project_or_404


def create_series_library_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/series/library")
    def get_series_library(workspace: str | None = None):
        """Load the authoritative Series Lab library for one workspace."""
        target_workspace = _resolve_workspace(workspace)
        try:
            with _library_lock:
                return _read_library(target_workspace)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"Could not read the Series Lab library: {exc}") from exc

    @router.put("/api/v1/series/library")
    def put_series_library(body: dict):
        """Atomically replace a Series library; resource endpoints are preferred."""
        target_workspace = _resolve_workspace(body.get("workspace"))
        try:
            with _library_lock:
                return _write_library(target_workspace, body.get("library"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Could not save the Series Lab library: {exc}") from exc

    @router.get("/api/v1/series")
    def list_series_projects(workspace: str | None = None):
        target_workspace = _resolve_workspace(workspace)
        with _library_lock:
            library = _read_library(target_workspace)
        return {
            "workspaceId": target_workspace,
            "seriesOrder": library["seriesOrder"],
            "series": [library["seriesById"][item] for item in library["seriesOrder"]],
        }

    @router.post("/api/v1/series")
    def create_series_project_endpoint(body: dict):
        from services.series_library import create_series_project, normalize_series_project

        workspace = _resolve_workspace(body.get("workspace"))
        try:
            with _library_lock:
                library = _read_library(workspace)
                raw_series = body.get("series")
                series = (
                    normalize_series_project(raw_series, str(raw_series.get("id") or ""), workspace)
                    if isinstance(raw_series, dict)
                    else create_series_project(workspace, title=str(body.get("title") or "Untitled series"))
                )
                if series["id"] in library["seriesById"]:
                    raise HTTPException(status_code=409, detail="A Series Lab project with this id already exists")
                library["seriesById"][series["id"]] = series
                library["seriesOrder"].append(series["id"])
                stored = _write_library(workspace, library)
                return stored["seriesById"][series["id"]]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/v1/series/{series_id}")
    def get_series_project_endpoint(series_id: str, workspace: str | None = None):
        target_workspace = _resolve_workspace(workspace)
        with _library_lock:
            return _project_or_404(_read_library(target_workspace), series_id)

    return router
