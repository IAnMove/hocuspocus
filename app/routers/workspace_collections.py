"""HTTP API for explicit Workspace collections (not output directories)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from services.workspace_registry import WorkspaceRegistry


def create_workspace_collections_router(*, registry: Callable[[], WorkspaceRegistry]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/workspace-collections")
    def list_workspace_collections():
        items = registry().list()
        return {"workspaces": items, "total": len(items)}

    @router.get("/api/v1/workspace-collections/{workspace_id}")
    def get_workspace_collection(workspace_id: str):
        item = registry().get(workspace_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return item

    @router.post("/api/v1/workspace-collections", status_code=201)
    async def create_workspace_collection(request: Request):
        body: Any = await request.json()
        if not isinstance(body, Mapping):
            raise HTTPException(status_code=400, detail="Request body must be an object")
        try:
            return registry().create(dict(body))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/v1/workspace-collections/{workspace_id}")
    async def update_workspace_collection(workspace_id: str, request: Request):
        body: Any = await request.json()
        if not isinstance(body, Mapping):
            raise HTTPException(status_code=400, detail="Request body must be an object")
        try:
            return registry().update(workspace_id, dict(body))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workspace not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/v1/workspace-collections/{workspace_id}", status_code=204)
    def delete_workspace_collection(workspace_id: str):
        if not registry().delete(workspace_id):
            raise HTTPException(status_code=404, detail="Workspace not found")

    return router


__all__ = ["create_workspace_collections_router"]
