"""Canonical task publishers.

These functions moved verbatim out of ``app/_launch_runtime.py``. ``bind`` receives
the full server's objects once, after those names exist. This module imports the
standard library, the resource scheduler and the canonical task field helpers.
It does not import WanGP, a router or ``_launch_runtime``.
"""
from __future__ import annotations

import time

from services import resource_scheduler
from services.canonical_task_fields import (
    _canonical_legacy_progress,
    _generation_task_fields,
    _task_legacy_id,
    _task_status,
    _task_timestamp,
    _upsert_canonical_task,
)

# Injected by bind(); None until the full server binds it.
_task_registry = None


def bind(**names):
    """Take the full server's objects this module uses (one call from the full server)."""
    global _task_registry
    _task_registry = names["_task_registry"]


def _publish_generation_sidecar_for_studio_job(
    job: dict,
    output_path: str,
    sidecar: dict,
    *,
    tool: str = "studio",
) -> None:
    """Publish one Studio result with its initiating command and real location."""
    from services.asset_manifest import publish_generation_job_sidecar
    publish_generation_job_sidecar(
        job,
        output_path,
        sidecar,
        job_id_key="id",
        output_folder=job.get("workspace"),
        tool=tool,
    )

def _publish_moved_studio_task(record, adapter):
    """Activity publish stays the launch function, which is defined further down."""
    publisher = globals().get("_publish_generic_legacy_task")
    if callable(publisher):
        publisher(record, adapter)

def _publish_generation_task(job: dict) -> dict:
    fields = _generation_task_fields(job)
    workspace, task_id = fields.pop("workspace"), fields.pop("id")
    return _upsert_canonical_task(workspace, task_id, **fields)

def _observe_generation_job_state(record: dict) -> None:
    """Forward atomic lifecycle changes to the canonical task event stream."""
    job = dict(record)
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    if not str(params.get("model_type") or "").strip():
        return
    _publish_generation_task(job)

def _publish_series_task(job: dict, adapter: str) -> dict:
    legacy_id = _task_legacy_id(job)
    workspace = str(job.get("workspace") or "default")
    is_render = adapter == "series-render"
    is_known = job.get("bootstrapKnownSeries") is True
    status = _task_status(job.get("status"))
    provider = job.get("provider") if isinstance(job.get("provider"), dict) else {}
    request_body = job.get("request") if isinstance(job.get("request"), dict) else {}
    model = str(job.get("model") or request_body.get("writingModel") or provider.get("videoModel") or "")
    provider_name = str(request_body.get("writingProvider") or "local")
    server = "local" if is_render else str(request_body.get("writingBaseUrl") or "")
    lane = (
        resource_scheduler.local_gpu_lane(0)
        if is_render
        else resource_scheduler.llm_lane(
            provider_name,
            base_url=server,
            device=str(request_body.get("writingDevice") or "cpu"),
        )
    )
    task_id = f"task-{adapter}-{legacy_id}"
    return _upsert_canonical_task(
        workspace,
        task_id,
        root_id=task_id,
        kind="video" if is_render else "llm-planning",
        workflow=adapter,
        title=("Series Lab · Video generation" if is_render else
               "Series Lab · Known-series bible" if is_known else
               "Series Lab · Canon" if job.get("jobType") == "canon" else
               "Series Lab · Episode planning"),
        status=status,
        phase=str(job.get("stage") or status),
        message=str(job.get("message") or "Series Lab is working…"),
        detail=str(job.get("validationError") or ""),
        current=int(job.get("current") or 0),
        total=int(job.get("total") or 0),
        created_at=_task_timestamp(job, "createdAt") or time.time(),
        completed_at=_task_timestamp(job, "finishedAt"),
        provider="local" if is_render else provider_name,
        model=model,
        server_origin=server,
        resource_requirements=[lane.key],
        # Parent workflows span parsing/checkpoint phases as well as provider
        # calls. Only observable child operations publish an acquired lease;
        # inferring one from the parent's broad "running" state is misleading.
        acquired_resources=[],
        attempt=max(1, int(job.get("retryCount") or job.get("validationAttempt") or 0) + 1),
        project_id=str(job.get("seriesId") or ""),
        entity_type="episode",
        entity_id=str(job.get("episodeId") or ""),
        backend_job_id=legacy_id,
        cancelable=status in {"created", "queued", "waiting_resource", "running"},
        resumable=True,
        recoverable=True,
        error=({"message": str(job.get("error")), "retryable": True} if job.get("error") else None),
        result_refs=list(job.get("outputAssetIds") or []),
        metadata={"adapter": adapter, "settings": job.get("settings") or {}},
    )

def _publish_series_assembly_task(job: dict) -> dict:
    """Publish persisted Series Assembly checkpoints to canonical Activity."""
    legacy_id = _task_legacy_id(job)
    if not legacy_id:
        return {}
    workspace = str(job.get("workspace") or "default")
    raw_status = str(job.get("status") or "queued")
    status = "running" if raw_status == "cancelling" else _task_status(raw_status)
    task_id = str(job.get("taskId") or f"task-series-assembly-{legacy_id}")
    return _upsert_canonical_task(
        workspace, task_id,
        root_id=task_id,
        kind="assembly", workflow="series-assembly",
        title="Series Lab · Episode assembly",
        status=status, phase=str(job.get("stage") or status),
        message=str(job.get("message") or "Joining approved Series clips…"),
        current=int(job.get("current") or 0), total=int(job.get("total") or 0),
        created_at=_task_timestamp(job, "createdAt") or time.time(),
        started_at=_task_timestamp(job, "startedAt"),
        completed_at=_task_timestamp(job, "finishedAt"),
        provider="local", model="FFmpeg", server_origin="local",
        resource_requirements=["cpu:ffmpeg"],
        acquired_resources=["cpu:ffmpeg"] if status == "running" else [],
        project_id=str(job.get("seriesId") or ""), entity_type="episode",
        entity_id=str(job.get("episodeId") or ""), backend_job_id=legacy_id,
        cancelable=status in {"created", "queued", "waiting_resource", "running"},
        resumable=status in {"failed", "cancelled", "interrupted"},
        recoverable=True,
        error=({"message": str(job.get("error")), "retryable": True}
               if job.get("error") else None),
        result_refs=[str(job["assetId"])] if job.get("assetId") else [],
        metadata={"adapter": "series-assembly"},
    )

_GENERIC_TASK_CONFIG = {
    "story-plan": ("Story Lab planning", "llm-planning", True),
    "comic-plan": ("Comic planning", "llm-planning", True),
    "video-editor": ("Video editor", "ffmpeg", False),
    "model3d": ("3D generation", "model3d", False),
    "rig": ("Character rigging", "rig", False),
    "minimax-image": ("MiniMax Image-01", "image", False),
    "audio-analysis": ("Audio analysis", "audio-analysis", False),
    "minimax-music": ("MiniMax Music", "music", False),
    "minimax-music-candidate": ("MiniMax Music candidate", "music", False),
}

def _publish_generic_legacy_task(record: dict, adapter: str) -> dict | None:
    legacy_id = _task_legacy_id(record)
    if not legacy_id:
        return None
    workspace = str(record.get("workspace") or "default")
    title, kind, resumable = _GENERIC_TASK_CONFIG.get(adapter, (adapter.replace("-", " ").title(), adapter, False))
    status = _task_status(record.get("status"))
    phase = str(record.get("stage") or record.get("phase") or record.get("status") or status)
    task_id = str(
        record.get("task_id")
        or record.get("taskId")
        or f"task-{adapter}-{legacy_id}"
    )
    root_task_id = str(
        record.get("root_task_id")
        or record.get("rootTaskId")
        or task_id
    )
    parent_task_id = str(
        record.get("parent_task_id")
        or record.get("parentTaskId")
        or ""
    ) or None
    request_body = record.get("request") if isinstance(record.get("request"), dict) else {}
    provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    command = provenance.get("command") if isinstance(provenance.get("command"), dict) else {}
    provider = str(
        record.get("provider")
        or request_body.get("writingProvider")
        or "local"
    )
    model = str(record.get("model") or record.get("model_id") or record.get("modelId") or "")
    explicit_lane = str(record.get("resource_lane") or "").strip()
    if explicit_lane:
        lane_key = explicit_lane
    elif adapter == "model3d":
        lane_key = resource_scheduler.local_gpu_lane(0).key
    elif adapter == "rig":
        lane_key = (
            resource_scheduler.local_gpu_lane(0).key
            if str(record.get("engine") or request_body.get("engine") or "").lower() == "unirig"
            else resource_scheduler.cpu_lane("rig").key
        )
    elif adapter in {"story-plan", "comic-plan"}:
        lane_key = resource_scheduler.llm_lane(
            provider,
            base_url=str(
                record.get("writingBaseUrl")
                or request_body.get("writingBaseUrl")
                or ""
            ),
            device=str(
                record.get("writingDevice")
                or request_body.get("writingDevice")
                or "cpu"
            ),
        ).key
    elif adapter == "video-editor":
        lane_key = resource_scheduler.cpu_lane("ffmpeg").key
    else:
        lane_key = resource_scheduler.cpu_lane(adapter).key
    current = int(record.get("current") or record.get("step") or 0)
    total = int(record.get("total") or record.get("total_steps") or 0)
    return _upsert_canonical_task(
        workspace, task_id,
        root_id=root_task_id, parent_id=parent_task_id,
        kind=kind, workflow=adapter, title=title,
        status=status, phase=phase,
        message=str(record.get("message") or phase.replace("_", " ").title()),
        current=current,
        total=total,
        progress=_canonical_legacy_progress(current, total, record.get("progress")),
        detail_current=int(record.get("detailCurrent") or 0),
        detail_total=int(record.get("detailTotal") or 0),
        created_at=_task_timestamp(record, "createdAt", "created_at") or time.time(),
        started_at=_task_timestamp(record, "startedAt", "started_at"),
        completed_at=_task_timestamp(record, "finishedAt", "finished_at"),
        provider=provider, model=model,
        server_origin=str(record.get("server_origin") or record.get("writingBaseUrl") or "local"),
        resource_requirements=[lane_key],
        acquired_resources=list(record.get("acquired_resources") or []),
        backend_job_id=legacy_id,
        cancelable=(status in {"created", "queued", "waiting_resource", "running"}
                    and str(record.get("status") or "").lower() != "cancelling"
                    and adapter != "comic-plan"),
        resumable=resumable, recoverable=resumable,
        error=({"message": str(record.get("error")), "retryable": resumable} if record.get("error") else None),
        result_refs=list(record.get("output_files") or (
            [record["output"]] if record.get("output") else
            [record["filename"]] if record.get("filename") else []
        )),
        metadata={
            "adapter": adapter,
            "cancel_mode": record.get("cancel_mode"),
            "safe_boundary": record.get("safe_boundary"),
            "actor": provenance.get("actor") or "unknown",
            "tool": provenance.get("tool") or adapter,
            "capability": provenance.get("capability"),
            "command_id": (
                command.get("command_id")
                or record.get("commandId")
                or record.get("command_id")
            ),
            "workflow_id": command.get("workflow_id"),
            "run_id": command.get("run_id"),
            "generation_id": record.get("generationId") or record.get("generation_id"),
            "candidate_id": record.get("candidateId") or record.get("candidate_id"),
            "idempotency_key": record.get("idempotencyKey") or record.get("idempotency_key"),
        },
    )

def _publish_director_task(pipeline: dict, workspace: str) -> dict | None:
    pipeline_id = str(pipeline.get("id") or pipeline.get("pipeline_id") or "")
    if not pipeline_id:
        return None
    progress = pipeline.get("progress") if isinstance(pipeline.get("progress"), dict) else {}
    details = pipeline.get("generation_details") if isinstance(pipeline.get("generation_details"), dict) else {}
    snapshot = pipeline.get("_params_snapshot") if isinstance(pipeline.get("_params_snapshot"), dict) else {}
    params = pipeline.get("params") if isinstance(pipeline.get("params"), dict) else {}
    provenance = pipeline.get("provenance") if isinstance(pipeline.get("provenance"), dict) else {}
    if not provenance:
        provenance = snapshot.get("provenance") if isinstance(snapshot.get("provenance"), dict) else {}
    if not provenance:
        provenance = params.get("provenance") if isinstance(params.get("provenance"), dict) else {}
    from services.generation_provenance import task_fields_from_provenance

    task_identity = task_fields_from_provenance(
        provenance,
        pipeline_id=pipeline_id,
    )
    canonical_pipeline_id = task_identity.pop("pipeline_id", pipeline_id)
    schedule = pipeline.get("resource_schedule") if isinstance(pipeline.get("resource_schedule"), dict) else {}
    schedule_lanes = schedule.get("lanes") if isinstance(schedule.get("lanes"), dict) else {}
    resource_requirements = list(dict.fromkeys(
        str(lane.get("key") or "")
        for lane in schedule_lanes.values()
        if isinstance(lane, dict) and str(lane.get("key") or "")
    ))
    command = provenance.get("command") if isinstance(provenance.get("command"), dict) else {}
    task_metadata = {
        "adapter": "director", "generation_details": details,
        "resource_schedule": schedule,
        "actor": provenance.get("actor") or "unknown",
        "tool": provenance.get("tool") or "director",
        "capability": provenance.get("capability"),
        "command_id": command.get("command_id"),
        "workflow_id": command.get("workflow_id"),
        "run_id": command.get("run_id"),
    }
    task_metadata.update(task_identity.pop("metadata", {}))
    raw_status = str(pipeline.get("status") or "").strip().lower()
    status = {
        "crashed": "interrupted",
        "preview_ready": "completed",
    }.get(raw_status, _task_status(raw_status))
    task_id = f"task-director-{pipeline_id}"
    # Director checkpoints survive Activity dismissal.  Do not recreate a
    # terminal card on every snapshot just because its source JSON still
    # exists; an explicit resume creates a new task event and makes it visible
    # again.
    if status in {"completed", "failed", "cancelled", "interrupted"}:
        try:
            if _task_registry(workspace).is_dismissed(task_id):
                return None
        except Exception:
            # A task registry failure must not hide the underlying pipeline.
            pass
    completed_at = _task_timestamp(
        pipeline,
        "finished_at",
        "_completed_at",
        "completed_at",
    )
    if completed_at is None and status in {
        "completed", "failed", "cancelled", "interrupted",
    }:
        completed_at = _task_timestamp(pipeline, "updated_at")
    return _upsert_canonical_task(
        workspace, task_id,
        root_id=task_id, kind="director", workflow="director",
        title="Music video" if pipeline.get("pipeline_type") == "music_video" else "Director pipeline",
        status=status, phase=str(pipeline.get("phase") or status),
        message=str(pipeline.get("error") or progress.get("message") or "Director is working…"),
        current=int(progress.get("current") or progress.get("step") or 0),
        total=int(progress.get("total") or progress.get("total_steps") or 0),
        detail_current=int(progress.get("detail_current") or 0),
        detail_total=int(progress.get("detail_total") or 0),
        created_at=_task_timestamp(pipeline, "created_at") or time.time(),
        started_at=_task_timestamp(pipeline, "phase_started_at", "created_at"),
        completed_at=completed_at,
        provider=str(details.get("text_provider") or ""),
        model=str(details.get("text_model") or details.get("video_model_name") or ""),
        server_origin=str(details.get("text_server") or ""),
        resource_requirements=resource_requirements,
        pipeline_id=canonical_pipeline_id, backend_job_id=pipeline_id,
        cancelable=status in {"created", "queued", "waiting_resource", "running"},
        resumable=True, recoverable=True,
        error=({"message": str(pipeline.get("error")), "retryable": True} if pipeline.get("error") else None),
        result_refs=list(pipeline.get("output_files") or []),
        **task_identity,
        metadata=task_metadata,
    )
