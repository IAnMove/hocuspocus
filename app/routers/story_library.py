"""Story Lab library HTTP shared by full launch and core runtime."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from services.story_library import (
    StoryLibraryRevisionConflict,
    delete_story_project,
    patch_story_project,
    read_story_library,
    write_story_library,
)


_workspace_dir: Callable[[str | None], str]
_library_lock: Any
_conflict: Callable[[Any], HTTPException]


def _bind_story_library_runtime(
    *,
    workspace_dir: Callable[[str | None], str],
    library_lock: Any,
    conflict: Callable[[Any], HTTPException],
) -> None:
    global _workspace_dir, _library_lock, _conflict
    _workspace_dir = workspace_dir
    _library_lock = library_lock
    _conflict = conflict


def create_story_library_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/stories/library")
    def get_story_library(workspace: str | None = None):
        """Load the durable Story Lab library for one workspace."""
        try:
            with _library_lock:
                return read_story_library(_workspace_dir(workspace))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not read the Story Lab library: {exc}",
            ) from exc

    @router.put("/api/v1/stories/library")
    def put_story_library(body: dict):
        """Atomically replace a workspace Story Lab library."""
        try:
            with _library_lock:
                return write_story_library(
                    _workspace_dir(body.get("workspace")),
                    body.get("library"),
                    base_revision=body.get("baseRevision"),
                )
        except StoryLibraryRevisionConflict as exc:
            raise _conflict(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not save the Story Lab library: {exc}",
            ) from exc

    @router.patch("/api/v1/stories/library/projects/{project_id}")
    def patch_story_library_project(project_id: str, body: dict):
        """Atomically update one Story while preserving unrelated projects."""
        try:
            with _library_lock:
                return patch_story_project(
                    _workspace_dir(body.get("workspace")),
                    project_id,
                    body.get("project"),
                    base_revision=body.get("baseRevision"),
                    make_active=body.get("makeActive") is True,
                )
        except StoryLibraryRevisionConflict as exc:
            raise _conflict(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/v1/stories/library/projects/{project_id}")
    def delete_story_library_project(project_id: str, body: dict):
        """Atomically delete one Story while preserving unrelated projects."""
        try:
            with _library_lock:
                return delete_story_project(
                    _workspace_dir(body.get("workspace")),
                    project_id,
                    base_revision=body.get("baseRevision"),
                )
        except StoryLibraryRevisionConflict as exc:
            raise _conflict(exc) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Story project not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
