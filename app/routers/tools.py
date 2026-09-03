"""HTTP boundary for standalone image tools."""

from __future__ import annotations

import os
import re
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.asset_catalog import find_asset
from services.character_kit_face_cleanup import IMAGE_EXTENSIONS
from services.generation_provenance import normalize_submission_provenance


class RemoveBackgroundRequest(BaseModel):
    """Canonical request accepted by both Tools and the Wizard adapter."""

    asset_id: str | None = Field(default=None, max_length=180)
    source: str | None = Field(default=None, max_length=1200)
    source_workspace: str | None = Field(default=None, max_length=160)
    workspace: str | None = Field(default=None, max_length=160)
    instruction: str = Field(default="", max_length=2_000)
    provenance: dict[str, Any] = Field(default_factory=dict)


def _contained(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((os.path.normcase(path), os.path.normcase(root))) == os.path.normcase(root)
    except (TypeError, ValueError, OSError):
        return False


def _valid_workspace_name(value: str) -> bool:
    return bool(re.fullmatch(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)", value))


def _file_url_query_workspace(source: str | None) -> str | None:
    """Read ?workspace= from a canonical /api/v1/file/ source URL."""
    raw_source = (source or "").strip()
    if not raw_source:
        return None
    source_without_query = raw_source.split("?", 1)[0].split("#", 1)[0]
    if source_without_query.startswith("/api/v1/"):
        source_without_query = unquote(source_without_query)
    if not source_without_query.startswith("/api/v1/file/"):
        return None
    query_workspace = parse_qs(urlsplit(raw_source).query).get("workspace", [None])[0]
    if isinstance(query_workspace, str) and query_workspace.strip():
        return query_workspace.strip()
    return None


def _explicit_source_workspace(payload: RemoveBackgroundRequest) -> str | None:
    """Body source_workspace, else ?workspace= on a /api/v1/file/ source."""
    if payload.source_workspace and payload.source_workspace.strip():
        return payload.source_workspace.strip()
    return _file_url_query_workspace(payload.source)


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


def _asset_location(
    asset: Mapping[str, Any],
    *,
    source_workspace: str | None,
    destination_workspace: str,
    workspace_dir: Callable[[str], str],
    uploads_dir: Callable[[], str],
) -> tuple[str, str] | None:
    locations = asset.get("locations")
    if not isinstance(locations, list):
        return None
    candidates = [item for item in locations if isinstance(item, Mapping)]
    if source_workspace:
        candidates = [
            item for item in candidates
            if str(item.get("workspace_id") or "") == source_workspace
        ]
    else:
        candidates.sort(key=lambda item: 0 if str(item.get("workspace_id") or "") == destination_workspace else 1)
    for location in candidates:
        scope = str(location.get("workspace_id") or "").strip()
        filename = str(location.get("filename") or "").strip()
        if not scope or not filename:
            continue
        try:
            root = uploads_dir() if scope == "__uploads__" else workspace_dir(scope)
        except Exception:
            # A stale catalog location must not turn a user request into a
            # server error; the remaining exact locations may still work.
            continue
        path = _safe_image_in_root(filename, root)
        if path:
            return path, scope
    return None


def _source_from_request(
    payload: RemoveBackgroundRequest,
    *,
    destination_workspace: str,
    workspace_dir: Callable[[str], str],
    uploads_dir: Callable[[], str],
    asset_finder: Callable[[str], Mapping[str, Any] | None],
) -> tuple[str, str, str]:
    """Resolve source by canonical asset ID, then exact filename/path."""
    if payload.asset_id:
        asset = asset_finder(payload.asset_id)
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
        if payload.source and os.path.basename(payload.source.split("?", 1)[0]) != filename:
            raise HTTPException(status_code=409, detail="Source does not match asset_id")
        return path, filename, resolved_scope

    if not payload.source:
        raise HTTPException(status_code=400, detail="asset_id or source is required")
    raw_source = payload.source.strip()
    source_without_query = raw_source.split("?", 1)[0].split("#", 1)[0]
    if source_without_query.startswith("/api/v1/"):
        source_without_query = unquote(source_without_query)
    source_name = os.path.basename(source_without_query)
    virtual_candidates = {
        f"/api/v1/file/{source_name}",
        f"/api/v1/uploads/{source_name}",
    }
    is_api_path = source_without_query.startswith("/api/v1/")
    is_virtual_api_path = source_without_query in virtual_candidates
    # The UI sends a canonical filename or an API URL. Do not silently turn a
    # relative traversal path into a different filename in the root.
    if not source_name or (
        (is_api_path and not is_virtual_api_path)
        or (not is_api_path and source_without_query != source_name
            and not os.path.isabs(source_without_query))
    ):
        raise HTTPException(status_code=400, detail="Source image path is not allowed")
    # Prefer the typed field; otherwise keep the workspace identity from a
    # canonical file URL so a duplicate filename in the active workspace is
    # not used by accident. The HTTP handler already refused unknown names
    # against list_workspaces() so this cannot create a switcher entry.
    scope = _explicit_source_workspace(payload)
    if os.path.isabs(source_without_query) and not is_virtual_api_path:
        # Preserve the exact absolute source selected by the caller.  Falling
        # back to ``root / basename`` here could silently process a different
        # file when two workspaces contain the same filename.
        absolute_source = os.path.realpath(os.path.abspath(source_without_query))
        uploads_root = os.path.realpath(os.path.abspath(uploads_dir()))
        if scope == "__uploads__":
            root = uploads_root
        elif scope:
            root = os.path.realpath(os.path.abspath(workspace_dir(scope)))
        else:
            destination_root = os.path.realpath(
                os.path.abspath(workspace_dir(destination_workspace))
            )
            if _contained(absolute_source, uploads_root):
                scope = "__uploads__"
                root = uploads_root
            elif _contained(absolute_source, destination_root):
                scope = destination_workspace
                root = destination_root
            else:
                raise HTTPException(status_code=400, detail="Source image path is not allowed")
        if not _contained(absolute_source, root) or absolute_source == root:
            raise HTTPException(status_code=400, detail="Source image path is not allowed")
        if os.path.splitext(source_name)[1].casefold() not in IMAGE_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Source must be an image")
        if not os.path.isfile(absolute_source):
            raise HTTPException(status_code=404, detail="Source image not found")
        return absolute_source, source_name, scope or destination_workspace
    if is_virtual_api_path and scope:
        if source_without_query.startswith("/api/v1/uploads/") and scope != "__uploads__":
            raise HTTPException(status_code=409, detail="Upload source does not match source_workspace")
        if source_without_query.startswith("/api/v1/file/") and scope == "__uploads__":
            raise HTTPException(status_code=409, detail="Workspace source does not match source_workspace")
    if scope is None and source_without_query.startswith("/api/v1/uploads/"):
        scope = "__uploads__"
    elif scope is None and source_without_query.startswith("/api/v1/file/"):
        scope = destination_workspace
    scope = scope or destination_workspace
    if not _valid_workspace_name(scope) and scope != "__uploads__":
        raise HTTPException(status_code=400, detail="Invalid source workspace")
    root = uploads_dir() if scope == "__uploads__" else workspace_dir(scope)
    path = _safe_image_in_root(source_name, root)
    if not path:
        raise HTTPException(status_code=404, detail="Source image not found")
    return path, os.path.basename(path), scope


def create_tools_router(
    *,
    get_active_workspace: Callable[[], str],
    list_workspaces: Callable[[], Iterable[Mapping[str, Any]]],
    workspace_dir: Callable[[str], str],
    uploads_dir: Callable[[], str],
    asset_finder: Callable[[str], Mapping[str, Any] | None] | None = None,
    register_job: Callable[[dict[str, Any]], dict[str, Any]],
    start_remove_background: Callable[[dict[str, Any]], None],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/tools", tags=["Tools"])

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
                # Workspace registries can retain a stale entry while its
                # output directory is being removed.  Asset lookup should
                # continue over the healthy roots instead of failing the
                # whole Tools request.
                continue
            result.append({"workspace_id": name, "path": path})
            seen.add(name)
        result.append({"workspace_id": "__uploads__", "path": uploads_dir()})
        return result

    def find_source_asset(asset_id: str) -> Mapping[str, Any] | None:
        if asset_finder is not None:
            return asset_finder(asset_id)
        return find_asset(roots(), asset_id)

    @router.post("/remove-background")
    def remove_background(payload: RemoveBackgroundRequest):
        destination_workspace = str(payload.workspace or get_active_workspace() or "default").strip()
        if not _valid_workspace_name(destination_workspace):
            raise HTTPException(status_code=400, detail="Invalid workspace")
        requested_source_workspace = _explicit_source_workspace(payload)
        if requested_source_workspace and requested_source_workspace != "__uploads__" and not _valid_workspace_name(requested_source_workspace):
            raise HTTPException(status_code=400, detail="Invalid source workspace")
        if requested_source_workspace and requested_source_workspace != "__uploads__":
            known_workspaces = {
                str(item.get("name") or "").strip()
                for item in list_workspaces()
                if isinstance(item, Mapping)
            }
            if requested_source_workspace not in known_workspaces:
                raise HTTPException(status_code=404, detail="Source workspace not found")
        try:
            output_dir = workspace_dir(destination_workspace)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid workspace") from exc
        try:
            source_path, source_filename, source_workspace = _source_from_request(
                payload,
                destination_workspace=destination_workspace,
                workspace_dir=workspace_dir,
                uploads_dir=uploads_dir,
                asset_finder=find_source_asset,
            )
        except HTTPException:
            raise
        source_asset_id = payload.asset_id or (
            "asset_unmanaged_"
            + uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"hocuspocus:unmanaged:{source_workspace}:{source_filename}",
            ).hex
        )
        provenance = normalize_submission_provenance(payload.provenance)
        provenance["capability"] = "remove_background"
        job_id = uuid.uuid4().hex[:8]
        job = {
            "id": job_id,
            "status": "queued",
            "progress": 0,
            "step": 0,
            "total_steps": 0,
            "phase": "",
            "message": "Queued (background removal)",
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "params": {
                "source": source_filename,
                "source_asset_id": source_asset_id,
                "source_filename": source_filename,
                "source_workspace": source_workspace,
                "instruction": payload.instruction.strip(),
                "model": "u2net",
                "model_type": "rembg-u2net",
                "provider": "local",
                "generation_mode": "image",
                "capability": "remove_background",
                "_non_durable_tool": "remove_background",
                "_source_path": source_path,
                "_uploads_root": uploads_dir(),
                "_workspace_root": workspace_dir(source_workspace) if source_workspace != "__uploads__" else output_dir,
                "_destination_workspace_root": output_dir,
            },
            "output_files": [],
            "error": None,
            "workspace": destination_workspace,
            "out_dir": output_dir,
            "provenance": provenance,
        }
        accepted = register_job(job)
        start_remove_background(accepted)
        return {
            "job_id": accepted.get("id") or job_id,
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

    return router


__all__ = ["RemoveBackgroundRequest", "create_tools_router"]
