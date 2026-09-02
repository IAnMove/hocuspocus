"""Canonical Production and Run HTTP read models over Director pipelines."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from services.production_run import build_production_run_catalog


def create_productions_router(
    *,
    list_workspaces: Callable[[], Iterable[Mapping[str, Any]]],
    list_pipelines: Callable[[str], Iterable[Mapping[str, Any]]],
) -> APIRouter:
    """Expose a global, path-free view of planned work and execution attempts."""
    router = APIRouter()

    def catalog(workspace: str = "") -> dict[str, Any]:
        available = {
            str(item.get("name") or "").strip()
            for item in list_workspaces()
            if isinstance(item, Mapping) and str(item.get("name") or "").strip()
        }
        if workspace and workspace not in available:
            raise HTTPException(status_code=404, detail="Workspace not found")
        wanted = [workspace] if workspace else sorted(available)
        snapshots: list[dict[str, Any]] = []
        for workspace_id in wanted:
            try:
                values = list_pipelines(workspace_id)
            except (OSError, ValueError):
                continue
            for value in values:
                if not isinstance(value, Mapping):
                    continue
                snapshots.append({**value, "workspace": workspace_id})
        return build_production_run_catalog(snapshots)

    @router.get("/api/v1/productions")
    def list_productions(
        workspace: str = Query(default="", max_length=160),
        limit: int = Query(default=100, ge=0, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        result = catalog(workspace)
        items = result["productions"]
        return {"productions": items[offset:offset + limit] if limit else items[offset:], "total": len(items)}

    @router.get("/api/v1/productions/{production_id}")
    def get_production(production_id: str):
        if not production_id or len(production_id) > 240:
            raise HTTPException(status_code=400, detail="Invalid production ID")
        result = catalog()
        production = next((item for item in result["productions"] if item["id"] == production_id), None)
        if production is None:
            raise HTTPException(status_code=404, detail="Production not found")
        production_runs = [item for item in result["runs"] if item["production_id"] == production_id]
        return {**production, "runs": production_runs}

    @router.get("/api/v1/runs")
    def list_runs(
        workspace: str = Query(default="", max_length=160),
        production_id: str = Query(default="", max_length=240),
        limit: int = Query(default=100, ge=0, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        items = catalog(workspace)["runs"]
        if production_id:
            items = [item for item in items if item["production_id"] == production_id]
        return {"runs": items[offset:offset + limit] if limit else items[offset:], "total": len(items)}

    @router.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str):
        if not run_id or len(run_id) > 240:
            raise HTTPException(status_code=400, detail="Invalid run ID")
        run = next((item for item in catalog()["runs"] if item["id"] == run_id), None)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    return router


__all__ = ["create_productions_router"]
