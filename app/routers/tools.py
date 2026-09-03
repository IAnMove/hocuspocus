"""HTTP boundary for standalone image tools."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from fastapi import APIRouter

from services.asset_catalog import find_asset
from services.generation_provenance import normalize_submission_provenance
from shared.tools.background_removal_job import build_background_removal_job
from shared.tools.background_removal_request import (
    RemoveBackgroundRequest,
    destination_context,
    job_response,
    resolve_source,
)


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
        destination_workspace, output_dir = destination_context(
            payload,
            get_active_workspace=get_active_workspace,
            list_workspaces=list_workspaces,
            workspace_dir=workspace_dir,
        )
        source_path, source_filename, source_workspace = resolve_source(
            payload,
            destination_workspace=destination_workspace,
            workspace_dir=workspace_dir,
            uploads_dir=uploads_dir,
            asset_finder=find_source_asset,
        )
        source_asset_id = payload.asset_id or (
            "asset_unmanaged_"
            + uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"hocuspocus:unmanaged:{source_workspace}:{source_filename}",
            ).hex
        )
        # Capability must be present before normalize: the Tools panel only
        # sends `{actor: user}`, and a later stamp would leave tool=studio.
        provenance = normalize_submission_provenance({
            **payload.provenance,
            "capability": "remove_background",
        })
        job_id = uuid.uuid4().hex[:8]
        source_root = output_dir if source_workspace == "__uploads__" else workspace_dir(source_workspace)
        job = build_background_removal_job(
            job_id=job_id,
            workspace=destination_workspace,
            output_dir=output_dir,
            source_path=source_path,
            source_filename=source_filename,
            source_workspace=source_workspace,
            source_asset_id=source_asset_id,
            uploads_root=uploads_dir(),
            source_root=source_root,
            provenance=provenance,
            instruction=payload.instruction.strip(),
        )
        accepted = register_job(job)
        start_remove_background(accepted)
        return job_response(
            accepted,
            fallback_id=job_id,
            source_asset_id=source_asset_id,
            source_filename=source_filename,
        )

    return router


__all__ = ["RemoveBackgroundRequest", "create_tools_router"]
