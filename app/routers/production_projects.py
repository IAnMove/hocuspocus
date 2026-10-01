"""HTTP for the production-to-project link and the shared work catalog."""

from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Query

from services.production_project_link import LinkError, note_production_status, resolve_production_project
from services.production_shot_actions import ActionError, perform
from services.production_shot_view import shot_view
from services.production_work_catalog import find_work, list_works


_STATUS = {
    "invalid_request": 422,
    "invalid_project": 422,
    "invalid_production": 422,
    "workspace_not_found": 404,
    "revision_conflict": 409,
    "partial_write": 503,
}
_RETRYABLE = frozenset({"revision_conflict", "partial_write", "stale_revision"})
_ACTION_STATUS = {
    "not_found": 404,
    "shot_not_found": 404,
    "stale_revision": 409,
}


def create_production_projects_router(*, workspace_dir: Callable[[str], str]) -> APIRouter:
    router = APIRouter()

    def root(workspace: str) -> str:
        token = str(workspace or "").strip()
        if not token or len(token) > 160:
            raise HTTPException(status_code=404, detail="Workspace not found")
        try:
            path = workspace_dir(token)
        except Exception as error:
            raise HTTPException(status_code=404, detail="Workspace not found") from error
        if not path or not os.path.isdir(path):
            raise HTTPException(status_code=404, detail="Workspace not found")
        return path

    def fail(error: LinkError) -> HTTPException:
        return HTTPException(status_code=_STATUS.get(error.code, 400), detail={
            "code": error.code,
            "message": str(error),
            "retryable": error.code in _RETRYABLE,
        })

    @router.post("/api/v1/production-projects/resolve")
    def resolve_route(body: dict):
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail={"code": "invalid_request", "message": "JSON object required"})
        workspace = str(body.get("workspace") or "")
        try:
            return resolve_production_project(root(workspace), body)
        except LinkError as error:
            raise fail(error) from error

    @router.post("/api/v1/production-projects/status")
    def status_route(body: dict):
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail={"code": "invalid_request", "message": "JSON object required"})
        try:
            return note_production_status(
                root(str(body.get("workspace") or "")),
                str(body.get("production_id") or ""),
                str(body.get("status") or ""),
            )
        except LinkError as error:
            raise fail(error) from error

    @router.get("/api/v1/production-projects")
    def list_route(
        workspace: str = Query(default="", max_length=160),
        format: str = Query(default="", max_length=40),
        status: str = Query(default="", max_length=40),
        limit: int = Query(default=100, ge=0, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        listed = list_works(
            root(workspace),
            workspace,
            form=format,
            status=status,
            limit=limit,
            offset=offset,
        )
        return listed

    @router.get("/api/v1/production-projects/{production_id}")
    def get_route(production_id: str, workspace: str = Query(default="", max_length=160)):
        if not production_id or len(production_id) > 240:
            raise HTTPException(status_code=400, detail="Invalid production ID")
        found = find_work(root(workspace), workspace, production_id)
        if found is None:
            raise HTTPException(status_code=404, detail="Production not found")
        return found

    @router.get("/api/v1/production-projects/{production_id}/shots")
    def shots_route(production_id: str, workspace: str = Query(default="", max_length=160)):
        if not production_id or len(production_id) > 240:
            raise HTTPException(status_code=400, detail="Invalid production ID")
        view = shot_view(root(workspace), workspace, production_id)
        if view is None:
            raise HTTPException(status_code=404, detail="Production not found")
        return view

    @router.post("/api/v1/production-projects/{production_id}/shots/{shot_id}")
    def act_route(production_id: str, shot_id: str, body: dict):
        if not production_id or len(production_id) > 240 or not shot_id or len(shot_id) > 80:
            raise HTTPException(status_code=400, detail="Invalid production ID")
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail={"code": "invalid_request", "message": "JSON object required"})
        workspace = str(body.get("workspace") or "")
        try:
            return perform(root(workspace), workspace, production_id, shot_id, body)
        except ActionError as error:
            raise HTTPException(status_code=_ACTION_STATUS.get(error.code, 422), detail={
                "code": error.code,
                "message": str(error),
                "retryable": error.code == "stale_revision",
            }) from error

    return router


__all__ = ["create_production_projects_router"]
