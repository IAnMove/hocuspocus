"""Workspace-scoped mouth collections, independent of the character cast."""
from collections.abc import Callable
import json

from fastapi import APIRouter, HTTPException
from services.lips_creator_commands import command_catalog, command_handlers
from services.character_kit_library import (
    CharacterKitRevisionConflict, LIPS_CREATOR_LIBRARY_FILENAME,
    delete_character_kit, patch_character_kit, read_character_kit_library,
)


def create_lips_creator_router(workspace_dir: Callable[[str | None], str]) -> APIRouter:
    router = APIRouter(prefix="/lips-creator", tags=["Lips Creator"])
    options = {"library_filename": LIPS_CREATOR_LIBRARY_FILENAME}
    handlers = command_handlers(workspace_dir)

    @router.get("/commands")
    def catalog():
        return {"version": 1, "operations": command_catalog()}

    @router.post("/commands")
    async def command(body: dict):
        arguments = dict(body)
        operation = arguments.pop("operation", None)
        if operation not in handlers:
            raise HTTPException(422, detail="Unknown Lips Creator operation")
        return await handlers[operation](arguments)

    def conflict(exc: CharacterKitRevisionConflict):
        return HTTPException(status_code=409, detail={
            "message": "The mouth collection changed in another tab. Reload before saving.",
            "expected": exc.expected, "current": exc.current,
        })

    @router.get("/library")
    def read_library(workspace: str | None = None):
        try:
            return read_character_kit_library(workspace_dir(workspace), **options)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail="Could not read the mouth collection") from exc

    @router.patch("/packs/{pack_id}")
    def save_pack(pack_id: str, body: dict):
        try:
            return patch_character_kit(workspace_dir(body.get("workspace")), pack_id, body.get("kit"),
                                       base_revision=body.get("baseRevision"), **options)
        except CharacterKitRevisionConflict as exc:
            raise conflict(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail="Could not save the mouth collection") from exc

    @router.delete("/packs/{pack_id}")
    def delete_pack(pack_id: str, body: dict):
        try:
            return delete_character_kit(workspace_dir(body.get("workspace")), pack_id,
                                        base_revision=body.get("baseRevision"), **options)
        except CharacterKitRevisionConflict as exc:
            raise conflict(exc) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Mouth collection not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail="Could not delete the mouth collection") from exc

    return router
