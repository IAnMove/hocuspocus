"""Global project registry HTTP surface over explicit workspace roots."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from services.project_catalog import PROJECT_KINDS, find_project, scan_project_catalog


def create_projects_router(
    *,
    list_workspaces: Callable[[], Iterable[Mapping[str, Any]]],
    workspace_dir: Callable[[str], str],
) -> APIRouter:
    router = APIRouter()

    def roots() -> list[dict[str, str]]:
        result = []
        seen: set[str] = set()
        for item in list_workspaces():
            name = str(item.get("name") or "").strip() if isinstance(item, Mapping) else ""
            if not name or name in seen:
                continue
            try:
                path = workspace_dir(name)
            except Exception:
                continue
            result.append({"workspace_id": name, "path": path})
            seen.add(name)
        return result

    @router.get("/api/v1/projects")
    def list_projects(
        search: str = Query(default="", max_length=300),
        kind: str = Query(default="", max_length=40),
        workspace: str = Query(default="", max_length=160),
        limit: int = Query(default=100, ge=0, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        wanted_kind = str(kind or "").strip().casefold()
        if wanted_kind and wanted_kind not in PROJECT_KINDS:
            raise HTTPException(status_code=400, detail="Unknown project kind")
        available = roots()
        if workspace and workspace not in {item["workspace_id"] for item in available}:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return scan_project_catalog(
            available,
            search=search,
            kind=wanted_kind,
            workspace_id=workspace,
            limit=limit,
            offset=offset,
        )

    @router.get("/api/v1/projects/{project_id}")
    def get_project(project_id: str):
        if not project_id or len(project_id) > 240:
            raise HTTPException(status_code=400, detail="Invalid project ID")
        record = find_project(roots(), project_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return record

    return router


__all__ = ["create_projects_router"]
