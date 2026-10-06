"""HTTP API for the game-asset library (``.game-library-v1.json``)."""
from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services.game_library import (
    GameConflictError,
    GameNotFoundError,
    GameValidationError,
    action_catalog,
    approve_attempt,
    approve_style,
    create_game,
    delete_game,
    lock_asset,
    preset_catalog,
    read_library,
    reject_attempt,
    update_asset,
    update_game,
    write_library,
)


# Every service error maps through ``fail``; a corrupt library file surfaces as ValueError.
_SERVICE_ERRORS = (GameConflictError, GameValidationError, GameNotFoundError, ValueError)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class GameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    game: dict[str, Any]


class GamePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    patch: dict[str, Any]
    base_revision: int


class StyleApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    base_revision: int
    references: list[dict[str, Any]]


class AssetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    patch: dict[str, Any]
    base_revision: int


class AttemptApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    attempt_id: str = Field(min_length=1, max_length=80)
    base_revision: int | None = None


class AttemptRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    attempt_id: str = Field(min_length=1, max_length=80)
    note: str = Field(min_length=1, max_length=2000)
    base_revision: int | None = None


class AssetLock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    locked: bool
    base_revision: int | None = None


def create_game_library_router(*, workspace_dir: Callable[[str], str], lock: threading.RLock) -> APIRouter:
    router = APIRouter()

    def fail(error: Exception) -> HTTPException:
        if isinstance(error, GameConflictError):
            return HTTPException(status_code=409, detail={"code": error.code, "message": str(error)})
        if isinstance(error, GameValidationError):
            return HTTPException(status_code=422, detail={"code": error.code, "message": str(error), "problems": error.problems})
        if isinstance(error, GameNotFoundError):
            return HTTPException(status_code=404, detail={"code": error.code, "message": error.code})
        return HTTPException(status_code=400, detail={"code": "invalid_game", "message": str(error)})

    def load(workspace: str) -> dict[str, Any]:
        with lock:
            try:
                return read_library(workspace_dir(workspace))
            except _SERVICE_ERRORS as error:
                raise fail(error) from error

    def mutate(workspace: str, function: Callable[[dict[str, Any]], tuple[dict[str, Any], Any]]) -> Any:
        with lock:
            directory = workspace_dir(workspace)
            try:
                library, payload = function(read_library(directory))
                write_library(directory, library)
            except _SERVICE_ERRORS as error:
                raise fail(error) from error
            return payload

    @router.get("/api/v1/games/presets")
    def list_presets():
        return {"presets": preset_catalog(), "actions": action_catalog()}

    @router.get("/api/v1/games")
    def list_games(workspace: str):
        return load(workspace)

    @router.post("/api/v1/games", status_code=201)
    def post_game(body: GameBody):
        return mutate(body.workspace, lambda library: create_game(library, body.game, now=_now()))

    @router.get("/api/v1/games/{game_id}")
    def get_game(game_id: str, workspace: str):
        library = load(workspace)
        for game in library["games"]:
            if game["id"] == game_id:
                return game
        raise HTTPException(status_code=404, detail={"code": "game_not_found", "message": "game_not_found"})

    @router.put("/api/v1/games/{game_id}")
    def put_game(game_id: str, body: GamePatch):
        return mutate(body.workspace, lambda library: update_game(library, game_id, body.patch, body.base_revision, now=_now()))

    @router.delete("/api/v1/games/{game_id}", status_code=204)
    def remove_game(game_id: str, workspace: str):
        mutate(workspace, lambda library: (delete_game(library, game_id), None))

    @router.post("/api/v1/games/{game_id}/style/approve")
    def post_style(game_id: str, body: StyleApproval):
        return mutate(body.workspace, lambda library: approve_style(library, game_id, body.references, body.base_revision, now=_now()))

    @router.patch("/api/v1/games/{game_id}/assets/{asset_id}")
    def patch_asset(game_id: str, asset_id: str, body: AssetPatch):
        return mutate(body.workspace, lambda library: update_asset(library, game_id, asset_id, body.patch, body.base_revision, now=_now()))

    @router.post("/api/v1/games/{game_id}/assets/{asset_id}/approve")
    def post_approve(game_id: str, asset_id: str, body: AttemptApproval):
        return mutate(
            body.workspace,
            lambda library: approve_attempt(library, game_id, asset_id, body.attempt_id, now=_now(), base_revision=body.base_revision),
        )

    @router.post("/api/v1/games/{game_id}/assets/{asset_id}/reject")
    def post_reject(game_id: str, asset_id: str, body: AttemptRejection):
        return mutate(
            body.workspace,
            lambda library: reject_attempt(library, game_id, asset_id, body.attempt_id, body.note, now=_now(), base_revision=body.base_revision),
        )

    @router.post("/api/v1/games/{game_id}/assets/{asset_id}/lock")
    def post_lock(game_id: str, asset_id: str, body: AssetLock):
        return mutate(
            body.workspace,
            lambda library: lock_asset(library, game_id, asset_id, body.locked, now=_now(), base_revision=body.base_revision),
        )

    return router
