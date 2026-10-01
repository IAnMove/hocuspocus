"""HTTP boundary for Character Kit Face Rig overlay cleanup."""

from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from routers.scene3d_speech import create_scene3d_speech_router
from routers.scene3d_profiles import create_scene3d_profiles_router
from routers.lips_creator import create_lips_creator_router

from services.character_kit_face_cleanup import (
    CharacterKitFaceCleanupError,
    clean_character_kit_overlay,
)


class FaceRigCleanupRequest(BaseModel):
    workspace: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=1200)
    padding: int = Field(default=8, ge=0, le=64)


def create_character_kit_face_router(
    *,
    workspace_dir: Callable[[str | None], str],
    uploads_root: Callable[[], str],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/character-kits", tags=["Character kits"])
    router.include_router(create_scene3d_speech_router())
    router.include_router(create_scene3d_profiles_router(workspace_dir))
    router.include_router(create_lips_creator_router(workspace_dir))

    @router.post("/face-rig/cleanup")
    def cleanup_face_rig_overlay(payload: FaceRigCleanupRequest):
        try:
            workspace = workspace_dir(payload.workspace)
            uploads = uploads_root()
            result = clean_character_kit_overlay(
                payload.source,
                uploads_root=uploads,
                workspace_root=workspace,
                output_dir=workspace if os.path.isdir(workspace) else uploads,
                padding=payload.padding,
            )
        except CharacterKitFaceCleanupError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Permitted image file was not found") from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail="Could not clean the Face Rig overlay") from exc
        return result

    return router
