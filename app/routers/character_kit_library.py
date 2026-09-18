"""Character Kit library HTTP shared by full launch and core runtime."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from services.character_kit_library import (
    CharacterKitRevisionConflict,
    delete_character_kit,
    patch_character_kit,
    read_character_kit_library,
)


_workspace_dir: Callable[[str | None], str]
_conflict: Callable[[Any], HTTPException]


def _bind_character_kit_library_runtime(
    *,
    workspace_dir: Callable[[str | None], str],
    conflict: Callable[[Any], HTTPException],
) -> None:
    global _workspace_dir, _conflict
    _workspace_dir = workspace_dir
    _conflict = conflict


def create_character_kit_library_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/character-kits/library")
    def get_character_kit_library(workspace: str | None = None):
        """Load reusable cutout characters from one workspace."""
        try:
            return read_character_kit_library(_workspace_dir(workspace))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"Could not read Character Kits: {exc}") from exc

    @router.patch("/api/v1/character-kits/library/kits/{kit_id}")
    def patch_character_kit_library_item(kit_id: str, body: dict):
        """Atomically create or update one kit without replacing its neighbours."""
        try:
            return patch_character_kit(
                _workspace_dir(body.get("workspace")),
                kit_id,
                body.get("kit"),
                base_revision=body.get("baseRevision"),
                make_active=body.get("makeActive") is not False,
            )
        except CharacterKitRevisionConflict as exc:
            raise _conflict(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/v1/character-kits/library/kits/{kit_id}")
    def delete_character_kit_library_item(kit_id: str, body: dict):
        """Delete one kit under the same compare-and-swap contract."""
        try:
            return delete_character_kit(
                _workspace_dir(body.get("workspace")),
                kit_id,
                base_revision=body.get("baseRevision"),
            )
        except CharacterKitRevisionConflict as exc:
            raise _conflict(exc) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Character Kit not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
