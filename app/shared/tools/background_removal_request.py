"""Canonical request and source resolution for the background-removal tool.

The HTTP router only coordinates the queue.  Keeping validation and exact
asset/path resolution here lets the API and the Wizard share one boundary.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, Field

from services.character_kit_face_cleanup import IMAGE_EXTENSIONS, _contained


class RemoveBackgroundRequest(BaseModel):
    """Canonical request accepted by both Tools and the Wizard adapter."""

    asset_id: str | None = Field(default=None, max_length=180)
    source: str | None = Field(default=None, max_length=1200)
    source_workspace: str | None = Field(default=None, max_length=160)
    workspace: str | None = Field(default=None, max_length=160)
    instruction: str = Field(default="", max_length=2_000)
    provenance: dict[str, Any] = Field(default_factory=dict)


def _valid_workspace_name(value: str) -> bool:
    return bool(re.fullmatch(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)", value))


def _safe_image_in_root(filename: str, root: str) -> str | None:
    if not isinstance(filename, str) or not filename or os.path.basename(filename) != filename:
        return None
    if os.path.splitext(filename)[1].casefold() not in IMAGE_EXTENSIONS:
        return None
    root_real = os.path.realpath(os.path.abspath(root))
    candidate = os.path.realpath(os.path.abspath(os.path.join(root_real, filename)))
    if candidate == root_real or not _contained(candidate, root_real):
        return None
    return candidate if os.path.isfile(candidate) else None


def _asset_locations(
    asset: Mapping[str, Any], preferred_workspace: str | None, destination_workspace: str,
) -> list[Mapping[str, Any]]:
    locations = asset.get("locations")
    if not isinstance(locations, list):
        return []
    candidates = [item for item in locations if isinstance(item, Mapping)]
    if preferred_workspace:
        return [item for item in candidates if str(item.get("workspace_id") or "") == preferred_workspace]
    return sorted(candidates, key=lambda item: int(str(item.get("workspace_id") or "") != destination_workspace))


def _location_root(
    scope: str, workspace_dir: Callable[[str], str], uploads_dir: Callable[[], str],
) -> str | None:
    try:
        return uploads_dir() if scope == "__uploads__" else workspace_dir(scope)
    except Exception:
        return None


def _asset_location(
    asset: Mapping[str, Any],
    *,
    source_workspace: str | None,
    destination_workspace: str,
    workspace_dir: Callable[[str], str],
    uploads_dir: Callable[[], str],
) -> tuple[str, str] | None:
    for location in _asset_locations(asset, source_workspace, destination_workspace):
        scope = str(location.get("workspace_id") or "").strip()
        filename = str(location.get("filename") or "").strip()
        if not scope or not filename:
            continue
        root = _location_root(scope, workspace_dir, uploads_dir)
        if root is None:
            continue
        path = _safe_image_in_root(filename, root)
        if path:
            return path, scope
    return None


def _source_from_asset(
    payload: RemoveBackgroundRequest,
    *,
    destination_workspace: str,
    workspace_dir: Callable[[str], str],
    uploads_dir: Callable[[], str],
    asset_finder: Callable[[str], Mapping[str, Any] | None],
) -> tuple[str, str, str]:
    asset = asset_finder(payload.asset_id or "")
    if not asset:
        raise HTTPException(status_code=404, detail="Source asset not found")
    if str(asset.get("kind") or "") != "image":
        raise HTTPException(status_code=400, detail="Source asset must be an image")
    scope = payload.source_workspace.strip() if payload.source_workspace else None
    location = _asset_location(
        asset,
        source_workspace=scope,
        destination_workspace=destination_workspace,
        workspace_dir=workspace_dir,
        uploads_dir=uploads_dir,
    )
    if not location:
        raise HTTPException(status_code=404, detail="Source asset location is unavailable")
    path, resolved_scope = location
    filename = os.path.basename(path)
    if payload.source and os.path.basename(unquote(payload.source.split("?", 1)[0])) != filename:
        raise HTTPException(status_code=409, detail="Source does not match asset_id")
    return path, filename, resolved_scope


def _parse_source(payload: RemoveBackgroundRequest) -> tuple[str, str, str, str | None, bool]:
    raw = payload.source.strip() if payload.source else ""
    source_without_query = raw.split("?", 1)[0].split("#", 1)[0]
    if source_without_query.startswith("/api/v1/"):
        source_without_query = unquote(source_without_query)
    source_name = os.path.basename(source_without_query)
    is_api_path = source_without_query.startswith("/api/v1/")
    is_virtual = source_without_query in {
        f"/api/v1/file/{source_name}", f"/api/v1/uploads/{source_name}",
    }
    if not source_name or (
        (is_api_path and not is_virtual)
        or (not is_api_path and source_without_query != source_name and not os.path.isabs(source_without_query))
    ):
        raise HTTPException(status_code=400, detail="Source image path is not allowed")
    scope = payload.source_workspace.strip() if payload.source_workspace else None
    if scope is None and source_without_query.startswith("/api/v1/file/"):
        query_workspace = parse_qs(urlsplit(raw).query).get("workspace", [None])[0]
        if isinstance(query_workspace, str) and query_workspace.strip():
            scope = query_workspace.strip()
    return raw, source_without_query, source_name, scope, is_virtual


def _absolute_source(
    source: str,
    source_name: str,
    scope: str | None,
    *,
    destination_workspace: str,
    workspace_dir: Callable[[str], str],
    uploads_dir: Callable[[], str],
) -> tuple[str, str, str]:
    absolute = os.path.realpath(os.path.abspath(source))
    uploads_root = os.path.realpath(os.path.abspath(uploads_dir()))
    if scope == "__uploads__":
        root = uploads_root
    elif scope:
        root = os.path.realpath(os.path.abspath(workspace_dir(scope)))
    else:
        destination_root = os.path.realpath(os.path.abspath(workspace_dir(destination_workspace)))
        if _contained(absolute, uploads_root):
            scope, root = "__uploads__", uploads_root
        elif _contained(absolute, destination_root):
            scope, root = destination_workspace, destination_root
        else:
            raise HTTPException(status_code=400, detail="Source image path is not allowed")
    if not _contained(absolute, root) or absolute == root:
        raise HTTPException(status_code=400, detail="Source image path is not allowed")
    if os.path.splitext(source_name)[1].casefold() not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Source must be an image")
    if not os.path.isfile(absolute):
        raise HTTPException(status_code=404, detail="Source image not found")
    return absolute, source_name, scope or destination_workspace


def _validate_virtual_scope(source_without_query: str, scope: str | None) -> None:
    if not (scope and source_without_query.startswith("/api/v1/")):
        return
    is_upload = source_without_query.startswith("/api/v1/uploads/")
    if (is_upload and scope != "__uploads__") or (not is_upload and scope == "__uploads__"):
        detail = "Upload source does not match source_workspace" if is_upload else "Workspace source does not match source_workspace"
        raise HTTPException(status_code=409, detail=detail)


def _canonical_source_scope(
    source_without_query: str, scope: str | None, destination_workspace: str,
) -> str:
    if scope is not None:
        return scope
    if source_without_query.startswith("/api/v1/uploads/"):
        return "__uploads__"
    return destination_workspace


def _validate_source_scope(scope: str) -> None:
    if scope != "__uploads__" and not _valid_workspace_name(scope):
        raise HTTPException(status_code=400, detail="Invalid source workspace")


def _named_source(
    source_without_query: str,
    source_name: str,
    scope: str | None,
    is_virtual: bool,
    *,
    destination_workspace: str,
    workspace_dir: Callable[[str], str],
    uploads_dir: Callable[[], str],
) -> tuple[str, str, str]:
    _validate_virtual_scope(source_without_query if is_virtual else "", scope)
    scope = _canonical_source_scope(source_without_query, scope, destination_workspace)
    _validate_source_scope(scope)
    root = uploads_dir() if scope == "__uploads__" else workspace_dir(scope)
    path = _safe_image_in_root(source_name, root)
    if not path:
        raise HTTPException(status_code=404, detail="Source image not found")
    return path, os.path.basename(path), scope


def resolve_source(
    payload: RemoveBackgroundRequest,
    *,
    destination_workspace: str,
    workspace_dir: Callable[[str], str],
    uploads_dir: Callable[[], str],
    asset_finder: Callable[[str], Mapping[str, Any] | None],
) -> tuple[str, str, str]:
    """Resolve a canonical asset ID or a safe exact source path."""
    if payload.asset_id:
        return _source_from_asset(
            payload,
            destination_workspace=destination_workspace,
            workspace_dir=workspace_dir,
            uploads_dir=uploads_dir,
            asset_finder=asset_finder,
        )
    if not payload.source:
        raise HTTPException(status_code=400, detail="asset_id or source is required")
    _raw, source_without_query, source_name, scope, is_virtual = _parse_source(payload)
    if os.path.isabs(source_without_query) and not is_virtual:
        return _absolute_source(
            source_without_query,
            source_name,
            scope,
            destination_workspace=destination_workspace,
            workspace_dir=workspace_dir,
            uploads_dir=uploads_dir,
        )
    return _named_source(
        source_without_query,
        source_name,
        scope,
        is_virtual,
        destination_workspace=destination_workspace,
        workspace_dir=workspace_dir,
        uploads_dir=uploads_dir,
    )


def validate_requested_workspace(
    requested: str | None,
    list_workspaces: Callable[[], Iterable[Mapping[str, Any]]],
) -> None:
    if not requested or requested == "__uploads__":
        return
    if not _valid_workspace_name(requested):
        raise HTTPException(status_code=400, detail="Invalid source workspace")
    known = {
        str(item.get("name") or "").strip()
        for item in list_workspaces()
        if isinstance(item, Mapping)
    }
    if requested not in known:
        raise HTTPException(status_code=404, detail="Source workspace not found")


def destination_context(
    payload: RemoveBackgroundRequest,
    *,
    get_active_workspace: Callable[[], str],
    list_workspaces: Callable[[], Iterable[Mapping[str, Any]]],
    workspace_dir: Callable[[str], str],
) -> tuple[str, str]:
    destination = str(payload.workspace or get_active_workspace() or "default").strip()
    if not _valid_workspace_name(destination):
        raise HTTPException(status_code=400, detail="Invalid workspace")
    requested = payload.source_workspace.strip() if payload.source_workspace else None
    validate_requested_workspace(requested, list_workspaces)
    try:
        output_dir = workspace_dir(destination)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace") from exc
    return destination, output_dir


def job_response(
    accepted: Mapping[str, Any],
    *,
    fallback_id: str,
    source_asset_id: str,
    source_filename: str,
) -> dict[str, Any]:
    return {
        "job_id": accepted.get("id") or fallback_id,
        "status": accepted.get("status") or "queued",
        "task_id": accepted.get("task_id"),
        "root_task_id": accepted.get("root_task_id") or accepted.get("task_id"),
        "generation_details": {
            "model_type": "rembg-u2net",
            "model_name": "rembg U2Net",
            "generation_mode": "image",
            "source_asset_id": source_asset_id,
            "source_filename": source_filename,
        },
    }


__all__ = [
    "RemoveBackgroundRequest", "destination_context", "job_response", "resolve_source",
    "validate_requested_workspace",
]
