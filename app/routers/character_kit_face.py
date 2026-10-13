"""HTTP boundary for Character Kit Face Rig overlay cleanup."""

from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from routers.scene3d_speech import create_scene3d_speech_router
from routers.scene3d_profiles import create_scene3d_profiles_router
from routers.lips_creator import create_lips_creator_router

from services.character_animations import CharacterAnimationError, build_sheet, catalog as animation_catalog, pose_prompt
from services.character_kit_face_cleanup import (
    CharacterKitFaceCleanupError,
    clean_character_kit_overlay,
)


class FaceRigCleanupRequest(BaseModel):
    workspace: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=1200)
    padding: int = Field(default=8, ge=0, le=64)


class AnimationPromptRequest(BaseModel):
    animation: str = Field(min_length=1, max_length=64)
    pose: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    style: str | None = Field(default=None, max_length=80)
    screen: str | None = Field(default=None, pattern="^(green|blue|magenta)$")


class AnimationSheetRequest(BaseModel):
    workspace: str = Field(min_length=1, max_length=120)
    sources: list[str] = Field(min_length=1, max_length=12)
    name: str = Field(default="animation", min_length=1, max_length=80)
    columns: int | None = Field(default=None, ge=1, le=12)


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

    @router.get("/animations/catalog")
    def get_animation_catalog():
        """The small animations a character can have (walk, wave, anime expressions...) and the sheet contract."""
        return animation_catalog()

    @router.post("/animations/prompt")
    def build_animation_prompt(payload: AnimationPromptRequest):
        """Prompt, negative prompt, screen colour and resolution for one pose, made with the character as its reference."""
        try:
            return pose_prompt(payload.animation, payload.pose, payload.description, payload.style, payload.screen)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown animation, pose or style: {exc.args[0]}") from exc

    @router.post("/animations/sheet")
    def build_animation_sheet(payload: AnimationSheetRequest):
        """Join keyed pose pictures into one sprite sheet of equal cells: the figure on a ground line, its torso centred."""
        try:
            workspace = workspace_dir(payload.workspace)
            result = build_sheet(payload.sources, uploads_root=uploads_root(), workspace_root=workspace, workspace=payload.workspace,
                                 name=payload.name, columns=payload.columns, output_dir=workspace if os.path.isdir(workspace) else None)
        except (CharacterAnimationError, CharacterKitFaceCleanupError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Permitted image file was not found") from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail="Could not build the sprite sheet") from exc
        return {key: value for key, value in result.items() if key != "path"}

    return router
