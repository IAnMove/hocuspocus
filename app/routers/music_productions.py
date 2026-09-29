"""Read model for musical ``*.production.json`` files.

This is not ``/api/v1/productions`` (the Director run catalog). A row is the
production status plus the ``<id>.shots.json`` manifest the run already writes.
Shot actions call the same Python the MCP commands call.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException

_WORKSPACE = re.compile(r"^(?:default|[A-Za-z0-9][A-Za-z0-9_-]{0,158})$")
_PRODUCTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_SUFFIX = ".production.json"


def _file_url(workspace: str, name: object) -> str | None:
    if not isinstance(name, str) or not name or "/" in name or ".." in name:
        return None
    return f"/api/v1/file/{quote(name)}?workspace={quote(workspace, safe='')}"


def _root(workspace_dir: Callable[[str], str], workspace: str) -> Path:
    if not _WORKSPACE.fullmatch(workspace or ""):
        raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        root = Path(workspace_dir(workspace)).resolve()
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=404, detail="Workspace not found") from error
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Workspace not found")
    return root


def _production_id(name: str) -> str | None:
    if not name.endswith(_SUFFIX):
        return None
    production_id = name[: -len(_SUFFIX)]
    if not _PRODUCTION.fullmatch(production_id):
        return None
    return production_id


def _read_json(path: Path) -> dict | None:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def production_card(workspace: str, production_id: str, state: dict) -> dict[str, Any]:
    """The list row: status, title, duration and the montage contact sheet."""
    from services.production_package import editable_summary
    spec = state.get("spec") if isinstance(state.get("spec"), dict) else {}
    song = spec.get("song") if isinstance(spec.get("song"), dict) else {}
    return {
        "production_id": production_id,
        "status": state.get("status") or "unknown",
        "title": spec.get("title") or production_id,
        "duration": song.get("duration"),
        "contact_sheet": _file_url(workspace, state.get("contact_sheet")),
        "montage": state.get("montage_file"),
        "video": _file_url(workspace, state.get("final")),
        "editable": editable_summary(state),
    }


def shots_of(root: Path, production_id: str) -> list[dict]:
    """The manifest rows as ``write_manifest`` stored them. Missing file means no shots yet."""
    body = _read_json(root / f"{production_id}.shots.json")
    shots = body.get("shots") if isinstance(body, dict) else None
    if not isinstance(shots, list):
        return []
    return [row for row in shots if isinstance(row, dict)]


def _spec(state: dict) -> dict:
    spec = state.get("spec")
    if not isinstance(spec, dict):
        raise HTTPException(status_code=422, detail={"code": "invalid_spec", "message": "This production has no spec"})
    return spec


def create_music_productions_router(
    *,
    workspace_dir: Callable[[str], str],
    uploads_dir: Callable[[], str] | None = None,
    app_url: Callable[[], str] | None = None,
    token: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter()

    def state_of(workspace: str, production_id: str) -> tuple[Path, dict]:
        if not _PRODUCTION.fullmatch(production_id or ""):
            raise HTTPException(status_code=404, detail="Production not found")
        root = _root(workspace_dir, workspace)
        state = _read_json(root / f"{production_id}{_SUFFIX}")
        if state is None:
            raise HTTPException(status_code=404, detail="Production not found")
        return root, state

    def studio():
        if uploads_dir is None or app_url is None or token is None or not token() or not app_url():
            raise HTTPException(status_code=503, detail={"code": "mcp_unavailable", "message": "Shot editing needs the studio runtime"})
        from services.music_production import Production, loopback_mcp
        return Production, loopback_mcp(app_url, token)

    @router.get("/api/v1/music-productions")
    def list_music_productions(workspace: str):
        root = _root(workspace_dir, workspace)
        cards = []
        for path in sorted(root.glob(f"*{_SUFFIX}")):
            production_id = _production_id(path.name)
            state = _read_json(path)
            if production_id and state is not None:
                cards.append(production_card(workspace, production_id, state))
        return {"productions": cards}

    @router.get("/api/v1/music-productions/{production_id}")
    def get_music_production(production_id: str, workspace: str):
        from services.music_production import status_summary
        root, state = state_of(workspace, production_id)
        return {
            "production": production_card(workspace, production_id, state),
            "status": status_summary(state, workspace, str(root)),
            "shots": shots_of(root, production_id),
        }

    @router.post("/api/v1/music-productions/{production_id}/shots/{shot}/use-take")
    def post_use_take(production_id: str, shot: str, workspace: str, body: dict):
        from services.production_shot_edit import ShotEditError, use_take
        production_cls, mcp = studio()
        _root_path, state = state_of(workspace, production_id)
        production = production_cls(workspace, production_id, workspace_dir=workspace_dir, uploads_dir=uploads_dir, mcp=mcp)
        try:
            return use_take(production, _spec(state), shot, str((body or {}).get("take_file") or ""))
        except ShotEditError as error:
            raise HTTPException(status_code=422, detail={"code": error.code, "message": str(error)}) from error

    @router.post("/api/v1/music-productions/{production_id}/shots/{shot}/retake")
    async def post_retake(production_id: str, shot: str, workspace: str):
        from services.music_production import RUN, command_handlers
        studio()
        state_of(workspace, production_id)
        handlers = command_handlers(workspace_dir, uploads_dir, app_url, token)
        return await handlers[RUN]({"version": 1, "input": {"workspace": workspace, "production_id": production_id, "retake": [shot]}})

    @router.post("/api/v1/music-productions/{production_id}/shots/{shot}")
    def post_update(production_id: str, shot: str, workspace: str, body: dict):
        from services.production_shot_edit import ShotEditError, update_shot
        production_cls, mcp = studio()
        _root_path, state = state_of(workspace, production_id)
        production = production_cls(workspace, production_id, workspace_dir=workspace_dir, uploads_dir=uploads_dir, mcp=mcp)
        payload = body or {}
        try:
            return update_shot(
                production, _spec(state), shot,
                lyric_style=payload.get("lyric_style"), title=payload.get("title"), camera=payload.get("camera"),
            )
        except ShotEditError as error:
            raise HTTPException(status_code=422, detail={"code": error.code, "message": str(error)}) from error

    return router
