"""Rig routes shared by the full server and the core server.

The job runner is ``rig_service`` on both. The core server injects the UniRig
gate and the engine filter; the full server leaves those out.
"""
from __future__ import annotations

import os
import traceback
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request


def create_rig_router(
    *,
    resolve_input_path: Callable[..., str | None],
    workspace_dir: Callable[..., str],
    get_active_workspace: Callable[[], str],
    safe_join: Callable[..., str | None],
    publish_task: Callable[..., Any] | None,
    engine_gate: Callable[[dict], None] | None = None,
    filter_engines: Callable[[list], list] | None = None,
) -> APIRouter:
    """The four ``/api/v1/rig`` routes, in the full server's order."""
    router = APIRouter()

    @router.get("/api/v1/rig/capabilities")
    def rig_capabilities():
        from services import rig_service
        payload = rig_service.capabilities()
        if filter_engines is not None:
            payload["engines"] = filter_engines(payload["engines"])
        return payload

    @router.post("/api/v1/rig/generate")
    async def generate_rig(request: Request):
        from services import rig_service
        from services.generation_provenance import normalize_submission_provenance
        body = await request.json()
        if engine_gate is not None:
            engine_gate(body)
        raw_provenance, trusted = body.pop("provenance", None), getattr(request, "trusted_tool", None)
        # A UI rig keeps its historical "rig" origin; an agent or Wizard request carries who asked.
        provenance = normalize_submission_provenance(raw_provenance, trusted_tool=trusted) if raw_provenance or trusted else None
        workspace = body.get("workspace") if "workspace" in body else get_active_workspace()
        workspace_dir(workspace)
        source_name = str(body.get("source") or "").strip()
        if not source_name:
            raise HTTPException(status_code=400, detail="source is required (a generated .glb output name)")
        if not source_name.lower().endswith(".glb"):
            raise HTTPException(status_code=400, detail="Rigging currently supports GLB sources only")
        source_path = safe_join(workspace_dir(workspace), source_name)
        if not source_path or not os.path.isfile(source_path):
            # Also accept absolute/upload paths through the shared 3D resolver.
            source_path = resolve_input_path(source_name, workspace)
        if not source_path or not os.path.isfile(source_path):
            raise HTTPException(status_code=400, detail="Source 3D model not found")
        try:
            job = rig_service.start_job(
                body=body,
                source_path=source_path,
                output_dir=workspace_dir(workspace),
                workspace=workspace,
                provenance=provenance,
            )
            if publish_task is not None:
                publish_task(job, "rig")
            return job
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/rig/status/{job_id}")
    def rig_job_status(job_id: str):
        from services import rig_service
        job = rig_service.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Rig job not found")
        if publish_task is not None:
            publish_task(job, "rig")
        return job

    @router.post("/api/v1/rig/jobs/{job_id}/cancel")
    def cancel_rig_job(job_id: str):
        from services import rig_service
        job = rig_service.cancel_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Rig job not found")
        if publish_task is not None:
            publish_task(job, "rig")
        return job

    # Launch's task cancel and rig commands call these by name.
    globals()["generate_rig"] = generate_rig
    globals()["rig_job_status"] = rig_job_status
    globals()["cancel_rig_job"] = cancel_rig_job
    return router
