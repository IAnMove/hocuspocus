"""Global asset catalog HTTP surface with injected workspace boundaries."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query

from services.asset_catalog import find_asset, scan_asset_catalog
from services.asset_manifest import ASSET_KINDS


def create_assets_router(
    *,
    list_workspaces: Callable[[], Iterable[Mapping[str, Any]]],
    workspace_dir: Callable[[str], str],
    uploads_dir: Callable[[], str],
) -> APIRouter:
    router = APIRouter()

    def roots() -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
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
        result.append({"workspace_id": "__uploads__", "path": uploads_dir()})
        return result

    def add_urls(record: dict[str, Any]) -> dict[str, Any]:
        result = dict(record)
        locations = []
        for location in record.get("locations") or []:
            workspace = str(location.get("workspace_id") or "")
            filename = str(location.get("filename") or "")
            if not workspace or not filename:
                continue
            encoded_name = quote(filename, safe="")
            if workspace == "__uploads__":
                url = f"/api/v1/uploads/{encoded_name}"
            else:
                url = f"/api/v1/file/{encoded_name}?workspace={quote(workspace, safe='')}"
            locations.append({**location, "url": url})
        result["locations"] = locations
        result["url"] = locations[0]["url"] if locations else ""
        return result

    @router.get("/api/v1/assets")
    def list_assets(
        search: str = Query(default="", max_length=300),
        kind: str = Query(default="", max_length=30),
        workspace: str = Query(default="", max_length=160),
        limit: int = Query(default=100, ge=0, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        wanted_kind = str(kind or "").strip().casefold()
        if wanted_kind and wanted_kind not in ASSET_KINDS:
            raise HTTPException(status_code=400, detail="Unknown asset kind")
        available = roots()
        known_workspaces = {item["workspace_id"] for item in available}
        if workspace and workspace not in known_workspaces:
            raise HTTPException(status_code=404, detail="Workspace not found")
        result = scan_asset_catalog(
            available,
            search=search,
            kind=wanted_kind,
            workspace_id=workspace,
            limit=limit,
            offset=offset,
        )
        result["assets"] = [add_urls(item) for item in result["assets"]]
        return result

    @router.get("/api/v1/assets/{asset_id}")
    def get_asset(asset_id: str):
        if not asset_id or len(asset_id) > 180:
            raise HTTPException(status_code=400, detail="Invalid asset ID")
        record = find_asset(roots(), asset_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Asset not found")
        return add_urls(record)

    return router


__all__ = ["create_assets_router"]
