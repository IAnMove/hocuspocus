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

    @router.post("/api/v1/character-kits/library/kits/{kit_id}/flat-rig")
    def rig_flat_character_kit(kit_id: str, body: dict):
        """Wipe the painted mouths, draw nine paper (or ink, or per-pose warp) mouths and a blink, and save the anchors."""
        from services.flat_rig import FlatRigError, rig_character

        workspace = str(body.get("workspace") or "")
        poses = body.get("poses")
        if poses is not None and (not isinstance(poses, list) or not all(isinstance(pose, str) for pose in poses)):
            raise HTTPException(status_code=400, detail="poses must be a list of pose ids")
        try:
            folder = _workspace_dir(workspace)
            rigged = rig_character(folder, workspace, kit_id, base_revision=body.get("baseRevision"),
                                   style=body.get("style"), pose_ids=poses, hints=body.get("hints"))
            # Every image it wrote names the kit, the rig settings and the poses it came from (tool_sidecars).
            from services.tool_sidecars import rig_sidecars
            return rig_sidecars(rigged, workspace=workspace, kit_id=kit_id, folder=folder, request={"poses": poses})
        except FlatRigError as exc:
            raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc)}) from exc
        except CharacterKitRevisionConflict as exc:
            raise _conflict(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/v1/character-kits/library/kits/{kit_id}/flat-rig/preview")
    def preview_flat_rig_mouth(kit_id: str, body: dict):
        """Warp one pose's mouths at a mouth line (point and width) without saving: the Face Rig mouth editor."""
        from services.flat_rig import FlatRigError
        from services.flat_rig_preview import preview_mouth

        workspace = str(body.get("workspace") or "")
        try:
            return preview_mouth(_workspace_dir(workspace), workspace, kit_id, str(body.get("pose") or "base"),
                                 mouth=body.get("mouth"), mouth_width=body.get("mouthWidth"), states=body.get("states"),
                                 sheet=body.get("sheet") is True)
        except FlatRigError as exc:
            raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/v1/character-kits/rig-check")
    def check_flat_rig_pose(body: dict):
        """Say whether one keyed pose can be rigged. Nothing is painted or saved."""
        from services.flat_rig import FlatRigError
        from services.flat_rig_metrics import check_pose

        workspace = str(body.get("workspace") or "")
        try:
            return check_pose(_workspace_dir(workspace), workspace, str(body.get("source") or ""))
        except FlatRigError as exc:
            raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc)}) from exc

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
