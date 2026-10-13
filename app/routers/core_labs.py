"""Story, Character Kit and Series filesystem persistence for core/remote."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from services import core_workspace as core
from services.series_library import (
    read_series_library,
    validate_workspace_id,
    write_series_library,
)
_LOCK = threading.RLock()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _workspace(value: Any) -> str:
    name = str(value or core.active_workspace() or "default").strip()
    try:
        core.workspace_dir(name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return name


def _dir(value: Any) -> str:
    return core.workspace_dir(_workspace(value))


def _conflict(code: str, exc: Any) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": code,
            "message": str(exc),
            "expectedRevision": getattr(exc, "expected", None),
            "currentRevision": getattr(exc, "current", None),
        },
    )


def _series_workspace(value: Any) -> str:
    try:
        name = validate_workspace_id(value or core.active_workspace())
        core.workspace_dir(name)
        return name
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _read_series(workspace: str) -> dict:
    return read_series_library(_dir(workspace), workspace)


def _write_series(workspace: str, library: dict) -> dict:
    return write_series_library(_dir(workspace), library, workspace)


def _series_or_404(library: dict, series_id: str) -> dict:
    series = library.get("seriesById", {}).get(series_id)
    if not isinstance(series, dict):
        raise HTTPException(status_code=404, detail="Series Lab project not found")
    return series






def create_core_labs_router() -> APIRouter:
    router = APIRouter()

    from routers.story_library import (
        _bind_story_library_runtime,
        create_story_library_router,
    )

    _bind_story_library_runtime(
        workspace_dir=_dir,
        library_lock=_LOCK,
        conflict=lambda exc: _conflict("story_library_revision_conflict", exc),
    )
    router.include_router(create_story_library_router())

    from routers.production_projects import create_production_projects_router

    router.include_router(create_production_projects_router(workspace_dir=core.workspace_dir))

    from routers.character_kit_library import (
        _bind_character_kit_library_runtime,
        create_character_kit_library_router,
    )

    _bind_character_kit_library_runtime(
        workspace_dir=_dir,
        conflict=lambda exc: _conflict("character_kit_revision_conflict", exc),
    )
    router.include_router(create_character_kit_library_router())

    from routers.series_library import (
        _bind_series_library_runtime,
        create_series_attempt_approval_router,
        create_series_attempt_reject_router,
        create_series_library_router,
        create_series_shot_duration_router,
    )

    _bind_series_library_runtime(
        resolve_workspace=_series_workspace,
        library_lock=_LOCK,
        read_library=_read_series,
        write_library=_write_series,
        project_or_404=_series_or_404,
        workspace_dir=core.workspace_dir,
        safe_join=core.safe_join,
    )
    router.include_router(create_series_library_router())
    router.include_router(create_series_shot_duration_router())
    router.include_router(create_series_attempt_approval_router())
    router.include_router(create_series_attempt_reject_router())
    return router
