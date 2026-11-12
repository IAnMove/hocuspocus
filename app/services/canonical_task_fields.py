"""Canonical task field helpers.

These functions moved verbatim out of ``app/_launch_runtime.py``. ``bind`` receives
the full server's objects once, after those names exist. This module imports the
standard library only. It does not import WanGP, a router or ``_launch_runtime``.
"""
from __future__ import annotations

import math
import os
import time
from datetime import datetime

# Injected by bind(); None until the full server binds them.
_is_durable_generation_job = None
_local_gpu_lane = None
_public_generation_details = None
_task_registry = None
_workspace_dir = None


def bind(**names):
    """Take the full server's objects this module uses (one call from the full server)."""
    global _is_durable_generation_job, _local_gpu_lane, _public_generation_details, _task_registry, _workspace_dir
    _is_durable_generation_job = names["_is_durable_generation_job"]
    _local_gpu_lane = names["_local_gpu_lane"]
    _public_generation_details = names["_public_generation_details"]
    _task_registry = names["_task_registry"]
    _workspace_dir = names["_workspace_dir"]


def _task_legacy_id(record: dict) -> str:
    return str(record.get("jobId") or record.get("job_id") or record.get("id") or "")


def _task_status(value: object) -> str:
    from services.canonical_task_helpers import task_status
    return task_status(value)


def _task_timestamp(record: dict, *keys: str) -> float | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return None


def _canonical_legacy_progress(current: object, total: object, progress: object) -> float:
    """Convert legacy counters/percentages to the canonical 0..1 scale."""
    try:
        total_value = float(total)
    except (TypeError, ValueError):
        total_value = 0.0
    if math.isfinite(total_value) and total_value > 0:
        try:
            current_value = float(current)
        except (TypeError, ValueError):
            current_value = 0.0
        value = current_value / total_value if math.isfinite(current_value) else 0.0
    else:
        try:
            percent_value = float(progress)
        except (TypeError, ValueError):
            percent_value = 0.0
        value = percent_value / 100.0 if math.isfinite(percent_value) else 0.0
    return max(0.0, min(1.0, value))


def _upsert_canonical_task(
    workspace: str,
    task_id: str,
    *,
    event_exclude_fields: set[str] | frozenset[str] | None = None,
    **fields,
) -> dict:
    from services.canonical_task_helpers import upsert_canonical_task
    return upsert_canonical_task(
        _task_registry(workspace),
        workspace,
        task_id,
        event_exclude_fields=event_exclude_fields,
        **fields,
    )


def _generation_task_fields(job: dict) -> dict:
    from services.activity_media import activity_reference_images
    legacy_id = str(job.get("id") or "")
    workspace = str(job.get("workspace") or "default")
    details = _public_generation_details(job.get("params"))
    mode = str(details.get("generation_mode") or "generation")
    model_type = str(details.get("model_type") or "")
    is_remote = model_type.startswith("minimax:")
    task_id = f"task-generation-{legacy_id}"
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    owner_id = str(params.get("_director_pipeline_id") or "")
    provenance = job.get("provenance") if isinstance(job.get("provenance"), dict) else {}
    command = provenance.get("command") if isinstance(provenance.get("command"), dict) else {}
    from services.generation_provenance import task_fields_from_provenance
    from services.generation_memory import performance_fields

    task_identity = task_fields_from_provenance(
        provenance,
        pipeline_id=owner_id if owner_id and not owner_id.startswith("series:") else None,
    )
    task_metadata = {
        "adapter": "generation", "generation_details": details,
        "display_prompt": details.get("prompt", ""),
        "reference_images": activity_reference_images(params, workspace,
            uploads_dir=os.path.join(os.getcwd(), "uploads"), workspace_dir=_workspace_dir(workspace)),
        "inference_started_at": job.get("inference_started_at"),
        "inference_start_step": job.get("inference_start_step"),
        "owner_pipeline_id": owner_id,
        "actor": provenance.get("actor") or "unknown",
        "tool": provenance.get("tool") or "studio",
        "capability": provenance.get("capability"),
        "command_id": command.get("command_id"),
        "workflow_id": command.get("workflow_id"),
        "run_id": command.get("run_id"),
        "output_name_requested": params.get("output_filename") or params.get("output_name") or None,
    }
    task_metadata.update(task_identity.pop("metadata", {}))
    task_metadata.update(performance_fields(job.get("performance")))
    if owner_id.startswith("series:"):
        series_job_id = owner_id.split(":", 1)[1]
        parent_task_id = f"task-series-render-{series_job_id}"
    elif owner_id:
        parent_task_id = f"task-director-{owner_id}"
    else:
        parent_task_id = None
    root_task_id = parent_task_id or task_id
    status = _task_status(job.get("status"))
    current = int(job.get("step") or 0)
    total = int(job.get("total_steps") or 0)
    error = job.get("error")
    if status in {"completed", "failed", "cancelled", "interrupted"}:
        acquired_resources = []
    elif "acquired_resources" in job:
        acquired_resources = list(job.get("acquired_resources") or [])
    else:
        # Compatibility for older in-memory tool jobs. Newly-created jobs
        # always carry the field, which lets planning remain visibly distinct
        # from actual GPU ownership.
        acquired_resources = (
            [] if status in {"created", "queued", "waiting_resource"}
            else ["remote:https://api.minimax.io" if is_remote else _local_gpu_lane.key]
        )
    task_title = {
        "image": "Image generation", "video": "Video generation",
        "audio": "Audio generation", "music": "Music generation",
        "model3d": "3D generation", "avatar": "Video edit",
    }.get(mode, "Generation job")
    if str(provenance.get("capability") or "") == "remove_background":
        task_title = "Tools · Remove background"
    elif str(provenance.get("capability") or "") in {"upscale", "tools.upscale"}:
        task_title = "Tools · Upscale"
    elif str(provenance.get("capability") or "") == "revoice":
        task_title = "Tools · Revoice"
    return dict(
        workspace=workspace,
        id=task_id,
        root_id=root_task_id,
        parent_id=parent_task_id,
        kind=mode,
        workflow="generation",
        title=task_title,
        status=status,
        phase=str(job.get("phase") or status),
        message=str(job.get("message") or status.replace("_", " ").title()),
        current=current,
        total=total,
        progress=_canonical_legacy_progress(current, total, job.get("progress")),
        created_at=_task_timestamp(job, "created_at") or time.time(),
        started_at=_task_timestamp(job, "started_at"),
        completed_at=_task_timestamp(job, "finished_at"),
        provider="minimax" if is_remote else "local",
        model=str(details.get("model_name") or model_type),
        server_origin="https://api.minimax.io" if is_remote else "local",
        resource_requirements=["remote:https://api.minimax.io" if is_remote else "local_gpu:0"],
        acquired_resources=acquired_resources,
        backend_job_id=legacy_id,
        cancelable=(
            status in {"created", "queued", "waiting_resource", "running"}
            and str(job.get("status") or "").lower() != "cancelling"
        ),
        recoverable=_is_durable_generation_job(job),
        error=({"message": str(error), "retryable": True} if error else None),
        result_refs=list(job.get("output_files") or []),
        **task_identity,
        metadata=task_metadata,
    )
