"""Ordered Series episode assembly API.

The launcher supplies its workspace and media primitives so this module can
own the job lifecycle without importing the large ``launch`` module or WanGP.
"""

from __future__ import annotations

import copy
import inspect
import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services.series_assembly import episode_assembly_plan
from services.series_jobs import SeriesJobStore
from services.task_manager import get_cancellation_token, get_task_registry


PUBLIC_JOB_KEYS = (
    "jobId",
    "workspace",
    "seriesId",
    "episodeId",
    "status",
    "stage",
    "current",
    "total",
    "message",
    "error",
    "assetId",
    "filename",
    "createdAt",
    "updatedAt",
    "finishedAt",
)

_ASSEMBLY_CONTROLLERS: dict[str, Callable[[str, str], dict[str, Any]]] = {}


class SeriesAssemblyStartRequest(BaseModel):
    """Stable request contract for starting one episode assembly."""

    model_config = ConfigDict(extra="forbid")

    workspace: str | None = Field(default=None, min_length=1, max_length=200)


class SeriesAssemblyActionRequest(BaseModel):
    """Workspace scope for a job mutation."""

    model_config = ConfigDict(extra="forbid")

    workspace: str | None = Field(default=None, min_length=1, max_length=200)


class SeriesAssemblyJobResponse(BaseModel):
    """Public, persisted-safe view of an episode assembly job."""

    model_config = ConfigDict(extra="forbid")

    jobId: str
    workspace: str
    seriesId: str
    episodeId: str
    status: Literal[
        "queued", "running", "cancelling", "completed", "failed",
        "cancelled", "interrupted",
    ]
    stage: str
    current: int = Field(ge=0)
    total: int = Field(ge=0)
    message: str
    error: str | None = None
    assetId: str | None = None
    filename: str | None = None
    createdAt: float | None = None
    updatedAt: float | None = None
    finishedAt: float | None = None


class SeriesAssemblyRecoveryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: list[SeriesAssemblyJobResponse]


class SeriesAssemblyDiscardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discarded: bool
    jobId: str
    outputsPreserved: bool


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: job.get(key) for key in PUBLIC_JOB_KEYS}


def create_series_assembly_router(
    *,
    resolve_workspace: Callable[[Any], str],
    workspace_dir: Callable[[str], str],
    list_workspaces: Callable[[], Iterable[dict[str, Any]]],
    library_lock: threading.RLock,
    read_library: Callable[[str], dict[str, Any]],
    write_library: Callable[[str, dict[str, Any]], dict[str, Any]],
    find_series: Callable[[dict[str, Any], str], dict[str, Any]],
    asset_local_path: Callable[[str, dict[str, Any]], str],
    available_filename: Callable[[str, str], str],
    concatenate_clips: Callable[..., bool],
    iso_now: Callable[[], str],
) -> APIRouter:
    """Build the router while keeping launcher-specific dependencies explicit."""

    router = APIRouter()
    jobs: dict[str, dict[str, Any]] = {}
    active_job_ids: set[str] = set()
    jobs_lock = threading.RLock()

    def canonical_task_id(job_id: str) -> str:
        return f"task-series-assembly-{job_id}"

    def canonical_status(job: dict[str, Any]) -> str:
        status = str(job.get("status") or "queued")
        return "running" if status == "cancelling" else status

    def publish_task(job: dict[str, Any]) -> None:
        """Mirror the durable Assembly checkpoint into Activity's registry."""
        workspace = str(job.get("workspace") or "default")
        task_id = str(job.get("taskId") or canonical_task_id(str(job.get("jobId") or "")))
        registry = get_task_registry(workspace_dir(workspace))
        status = canonical_status(job)
        fields = {
            "root_id": task_id,
            "kind": "assembly",
            "workflow": "series-assembly",
            "title": "Series Lab · Episode assembly",
            "status": status,
            "phase": str(job.get("stage") or status),
            "message": str(job.get("message") or "Joining approved Series clips…"),
            "current": int(job.get("current") or 0),
            "total": int(job.get("total") or 0),
            "created_at": float(job.get("createdAt") or time.time()),
            "started_at": float(job.get("startedAt") or 0) or None,
            "completed_at": float(job.get("finishedAt") or 0) or None,
            "provider": "local",
            "model": "FFmpeg",
            "server_origin": "local",
            "resource_requirements": ["cpu:ffmpeg"],
            "acquired_resources": ["cpu:ffmpeg"] if status == "running" else [],
            "project_id": str(job.get("seriesId") or ""),
            "entity_type": "episode",
            "entity_id": str(job.get("episodeId") or ""),
            "backend_job_id": str(job.get("jobId") or ""),
            "cancelable": status in {"created", "queued", "running"},
            "resumable": status in {"failed", "cancelled", "interrupted"},
            "recoverable": True,
            "error": ({"message": str(job.get("error")), "retryable": True}
                      if job.get("error") else None),
            "result_refs": [str(job["assetId"])] if job.get("assetId") else [],
            "metadata": {"adapter": "series-assembly"},
        }
        existing = registry.get(task_id)
        if existing is None:
            registry.create(id=task_id, workspace=workspace, **fields)
        else:
            try:
                registry.update(task_id, force=True, event_type="adapter.synced", **fields)
            except (KeyError, ValueError, OSError):
                # A terminal task can only be reopened through the explicit
                # resume endpoint; a late adapter snapshot must not resurrect it.
                pass

    def normalize_stale(job: dict[str, Any]) -> dict[str, Any]:
        """Set a checkpoint left by another process to interrupted once."""
        job_id = str(job.get("jobId") or "")
        if str(job.get("status") or "") not in {"queued", "running", "cancelling"}:
            return job
        with jobs_lock:
            if job_id in active_job_ids:
                return job
            cached = jobs.setdefault(job_id, copy.deepcopy(job))
        stale = copy.deepcopy(cached)
        now = time.time()
        stale.update({
            "status": "interrupted",
            "stage": "interrupted",
            "message": "The previous assembly process was interrupted; it can be resumed.",
            "error": "Assembly process interrupted before completion",
            "updatedAt": now,
            "finishedAt": now,
        })
        store(str(stale["workspace"])).save(stale)
        with jobs_lock:
            jobs[job_id] = stale
        publish_task(stale)
        return copy.deepcopy(stale)

    def store(workspace: str) -> SeriesJobStore:
        return SeriesJobStore(workspace_dir(workspace), "assembly")

    def load(job_id: str, workspace: str | None = None) -> dict[str, Any] | None:
        target = resolve_workspace(workspace)
        with jobs_lock:
            cached = jobs.get(job_id)
            if cached and str(cached.get("workspace") or "") == target:
                return normalize_stale(cached)
        try:
            saved = store(target).load(job_id)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not saved:
            return None
        with jobs_lock:
            jobs[job_id] = saved
        return normalize_stale(saved)

    def update(job_id: str, **patch: Any) -> dict[str, Any] | None:
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return None
            job.update(copy.deepcopy(patch))
            job["updatedAt"] = time.time()
            snapshot = copy.deepcopy(job)
            store(str(job["workspace"])).save(snapshot)
        publish_task(snapshot)
        return snapshot

    def persisted_active_job(workspace: str, series_id: str, episode_id: str) -> dict[str, Any] | None:
        active_statuses = {"queued", "running", "cancelling"}
        with jobs_lock:
            cached = list(jobs.values())
        try:
            saved = store(workspace).list()
        except (OSError, ValueError, json.JSONDecodeError):
            saved = []
        by_id = {
            str(job.get("jobId")): job
            for job in [*saved, *cached]
            if isinstance(job, dict) and job.get("jobId")
        }
        return next((
            job
            for job in by_id.values()
            if job.get("workspace") == workspace
            and job.get("seriesId") == series_id
            and job.get("episodeId") == episode_id
            and job.get("status") in active_statuses
        ), None)

    def mark_interrupted(active: dict[str, Any]) -> None:
        """Release a queued/running checkpoint left by a previous process."""

        job_id = str(active.get("jobId") or "")
        with jobs_lock:
            if job_id in active_job_ids:
                return
        stale = copy.deepcopy(active)
        stale.update({
            "status": "interrupted",
            "stage": "interrupted",
            "message": "The previous assembly process was interrupted; it can be resumed.",
            "error": "Assembly process interrupted before completion",
            "updatedAt": time.time(),
            "finishedAt": time.time(),
        })
        store(str(stale["workspace"])).save(stale)
        with jobs_lock:
            jobs[job_id] = stale
        publish_task(stale)

    def run(job_id: str) -> None:
        job = update(
            job_id,
            status="running",
            stage="joining",
            message="Joining approved clips in shot order…",
        )
        if not job:
            with jobs_lock:
                active_job_ids.discard(job_id)
            return
        task_id = str(job.get("taskId") or canonical_task_id(job_id))
        token = get_cancellation_token(workspace_dir(str(job["workspace"])), task_id)
        output_path = ""
        try:
            if token.is_cancelled():
                update(
                    job_id, status="cancelled", stage="cancelled",
                    error=None, finishedAt=time.time(),
                    message="Series episode assembly cancelled before FFmpeg started.",
                )
                return
            clip_paths = [
                asset_local_path(str(job["workspace"]), {
                    "id": item.get("assetId"),
                    "uri": item.get("uri"),
                })
                for item in job.get("clips", [])
            ]
            output_directory = workspace_dir(str(job["workspace"]))
            timestamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
            output_path = available_filename(
                output_directory,
                f"{timestamp}_{job['episodeId']}_series_assembly.mp4",
            )
            try:
                parameters = inspect.signature(concatenate_clips).parameters
                supports_abort = "abort_callback" in parameters or any(
                    value.kind == inspect.Parameter.VAR_KEYWORD
                    for value in parameters.values()
                )
            except (TypeError, ValueError):
                supports_abort = False
            joined = (
                concatenate_clips(clip_paths, output_path, abort_callback=token.is_cancelled)
                if supports_abort else concatenate_clips(clip_paths, output_path)
            )
            if token.is_cancelled():
                if output_path and os.path.isfile(output_path):
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass
                update(
                    job_id, status="cancelled", stage="cancelled",
                    error=None, finishedAt=time.time(),
                    message="Series episode assembly cancelled; no joined output was kept.",
                )
                return
            if not joined:
                raise RuntimeError("ffmpeg could not join the approved Series clips")
            if not os.path.isfile(output_path):
                raise RuntimeError("Series assembly finished without an output file")
            if token.is_cancelled():
                try:
                    os.remove(output_path)
                except OSError:
                    pass
                update(
                    job_id, status="cancelled", stage="cancelled",
                    error=None, finishedAt=time.time(),
                    message="Series episode assembly cancelled before publishing its output.",
                )
                return

            asset_id = f"asset_assembly_{uuid.uuid4().hex}"
            completed_at = iso_now()
            with library_lock:
                library = read_library(str(job["workspace"]))
                series = copy.deepcopy(find_series(library, str(job["seriesId"])))
                episode = series.get("episodesById", {}).get(str(job["episodeId"]))
                if not isinstance(episode, dict):
                    raise ValueError("Series episode no longer exists")
                series.setdefault("assets", {})[asset_id] = {
                    "id": asset_id,
                    "workspaceId": job["workspace"],
                    "kind": "video",
                    "uri": f"outputs/{os.path.basename(output_path)}",
                    "ownerType": "episode",
                    "ownerId": job["episodeId"],
                    "isDerivedThumbnail": False,
                    "metadata": {
                        "seriesId": job["seriesId"],
                        "episodeId": job["episodeId"],
                        "assemblyJobId": job_id,
                        "clipCount": len(clip_paths),
                        "orderedClipAssetIds": [
                            item.get("assetId") for item in job.get("clips", [])
                        ],
                        "createdAt": completed_at,
                    },
                }
                assembly_ids = [
                    str(value)
                    for value in episode.get("assemblyAssetIds", [])
                    if isinstance(value, str) and value
                ]
                assembly_ids.append(asset_id)
                episode["assemblyAssetIds"] = list(dict.fromkeys(assembly_ids))
                episode["latestAssemblyAssetId"] = asset_id
                episode["updatedAt"] = completed_at
                series["episodesById"][episode["id"]] = episode
                series["revision"] = int(series.get("revision") or 1) + 1
                series["updatedAt"] = completed_at
                library["seriesById"][series["id"]] = series
                if token.is_cancelled():
                    raise RuntimeError("Series assembly cancelled before library commit")
                write_library(str(job["workspace"]), library)
            update(
                job_id,
                status="completed",
                stage="completed",
                current=len(clip_paths),
                assetId=asset_id,
                filename=os.path.basename(output_path),
                finishedAt=time.time(),
                message=f"Joined {len(clip_paths)} approved clips in episode order.",
            )
        except Exception as exc:
            if token.is_cancelled():
                if output_path and os.path.isfile(output_path):
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass
                update(
                    job_id, status="cancelled", stage="cancelled",
                    error=None, finishedAt=time.time(),
                    message="Series episode assembly cancelled; approved clips were not changed.",
                )
                return
            if output_path and os.path.isfile(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            update(
                job_id,
                status="failed",
                stage="failed",
                error=str(exc),
                finishedAt=time.time(),
                message="Series episode assembly failed; approved clips were not changed.",
            )
        finally:
            with jobs_lock:
                active_job_ids.discard(job_id)

    @router.post(
        "/api/v1/series/{series_id}/episodes/{episode_id}/assembly/start",
        response_model=SeriesAssemblyJobResponse,
    )
    def start(series_id: str, episode_id: str, payload: SeriesAssemblyStartRequest):
        workspace = resolve_workspace(payload.workspace)
        with library_lock:
            library = read_library(workspace)
            series = copy.deepcopy(find_series(library, series_id))
            episode = series.get("episodesById", {}).get(episode_id)
            if not isinstance(episode, dict):
                raise HTTPException(status_code=404, detail="Series episode not found")
            try:
                clips = episode_assembly_plan(series, episode)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            # Keep validation and durable registration under the same lock as
            # Series deletion. Deletion therefore either wins first (404 here)
            # or observes this queued Assembly checkpoint and returns 409.
            active = persisted_active_job(workspace, series_id, episode_id)
            if active:
                with jobs_lock:
                    active_here = str(active.get("jobId")) in active_job_ids
                if active_here:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Episode assembly {active['jobId']} is already running",
                    )
                mark_interrupted(active)

            with jobs_lock:
                # Re-check under the mutation lock so simultaneous requests cannot
                # enqueue two assemblers for the same episode.
                active_here = next((
                    value
                    for value in jobs.values()
                    if value.get("workspace") == workspace
                    and value.get("seriesId") == series_id
                    and value.get("episodeId") == episode_id
                    and value.get("status") in {"queued", "running", "cancelling"}
                ), None)
                if active_here:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Episode assembly {active_here['jobId']} is already running",
                    )
                job_id = f"series-assembly-{uuid.uuid4().hex[:12]}"
                now = time.time()
                job = {
                    "jobId": job_id,
                    "taskId": canonical_task_id(job_id),
                    "kind": "assembly",
                    "workspace": workspace,
                    "seriesId": series_id,
                    "episodeId": episode_id,
                    "status": "queued",
                    "stage": "queued",
                    "current": 0,
                    "total": len(clips),
                    "clips": clips,
                    "message": "Episode assembly queued.",
                    "error": None,
                    "assetId": None,
                    "filename": None,
                    "createdAt": now,
                    "updatedAt": now,
                }
                jobs[job_id] = job
                active_job_ids.add(job_id)
                store(workspace).save(job)
                publish_task(job)
        threading.Thread(
            target=run,
            args=(job_id,),
            name=f"series-assembly-{job_id[-6:]}",
            daemon=True,
        ).start()
        return _public_job(job)

    def control(job_id: str, action: str, workspace: str | None = None) -> dict[str, Any]:
        target = resolve_workspace(workspace)
        job = load(job_id, target)
        if not job:
            raise HTTPException(status_code=404, detail="Series assembly job not found")
        task_id = str(job.get("taskId") or canonical_task_id(job_id))
        token = get_cancellation_token(workspace_dir(target), task_id)
        current_status = str(job.get("status") or "")
        if action == "cancel":
            if current_status in {"completed", "failed", "cancelled", "interrupted"}:
                return _public_job(job)
            token.cancel(f"Assembly {job_id} cancellation requested")
            with jobs_lock:
                active = job_id in active_job_ids
            updated = update(
                job_id,
                status="cancelling" if active else "cancelled",
                stage="cancelling" if active else "cancelled",
                finishedAt=None if active else time.time(),
                error=None,
                message=(
                    "Series assembly cancellation requested; waiting for FFmpeg to stop."
                    if active else "Series episode assembly cancelled before FFmpeg started."
                ),
            )
            return _public_job(updated or job)
        if action == "resume":
            if current_status == "completed":
                raise HTTPException(status_code=409, detail="Completed assembly jobs cannot be resumed")
            with jobs_lock:
                if job_id in active_job_ids:
                    return _public_job(job)
                token.reset()
                reopened = copy.deepcopy(job)
                now = time.time()
                reopened.update({
                    "status": "queued", "stage": "queued", "message": "Episode assembly resumed.",
                    "error": None, "finishedAt": None, "updatedAt": now,
                })
                jobs[job_id] = reopened
                active_job_ids.add(job_id)
                store(target).save(reopened)
            publish_task(reopened)
            threading.Thread(
                target=run, args=(job_id,), name=f"series-assembly-{job_id[-6:]}", daemon=True,
            ).start()
            return _public_job(reopened)
        if action == "discard":
            if current_status in {"queued", "running", "cancelling"}:
                raise HTTPException(status_code=409, detail="Cancel the active assembly before discarding its checkpoint")
            with jobs_lock:
                removed = store(target).discard(job_id)
                jobs.pop(job_id, None)
            if not removed:
                raise HTTPException(status_code=404, detail="Series assembly job not found")
            registry = get_task_registry(workspace_dir(target))
            try:
                registry.delete(task_id)
            except (KeyError, ValueError):
                pass
            return {"discarded": True, "jobId": job_id, "outputsPreserved": True}
        raise HTTPException(status_code=400, detail=f"Unsupported Assembly action: {action}")

    @router.post(
        "/api/v1/series/assembly/jobs/{job_id}/cancel",
        response_model=SeriesAssemblyJobResponse,
    )
    def cancel(job_id: str, payload: SeriesAssemblyActionRequest):
        return control(job_id, "cancel", payload.workspace)

    @router.post(
        "/api/v1/series/assembly/jobs/{job_id}/resume",
        response_model=SeriesAssemblyJobResponse,
    )
    def resume(job_id: str, payload: SeriesAssemblyActionRequest):
        return control(job_id, "resume", payload.workspace)

    @router.get(
        "/api/v1/series/assembly/recovery",
        response_model=SeriesAssemblyRecoveryResponse,
    )
    def recovery(workspace: str | None = None):
        target = resolve_workspace(workspace)
        recovered = []
        for item in store(target).recoverable():
            job = load(str(item.get("jobId") or ""), target)
            if job:
                recovered.append(_public_job(job))
        return {"jobs": recovered}

    @router.delete(
        "/api/v1/series/assembly/jobs/{job_id}",
        response_model=SeriesAssemblyDiscardResponse,
    )
    def discard(job_id: str, workspace: str | None = None):
        return control(job_id, "discard", workspace)

    @router.get(
        "/api/v1/series/assembly/jobs/{job_id}",
        response_model=SeriesAssemblyJobResponse,
    )
    def status(job_id: str, workspace: str | None = None):
        job = load(job_id, workspace)
        if not job:
            raise HTTPException(status_code=404, detail="Series assembly job not found")
        return _public_job(job)

    def controller(job_id: str, action: str) -> dict[str, Any]:
        return control(job_id, action, None)

    _ASSEMBLY_CONTROLLERS[os.path.realpath(os.path.abspath(workspace_dir(resolve_workspace(None))))] = controller

    # Normalize all process leftovers at router construction, not only when
    # the user happens to press Start. This keeps recovery visible in Activity.
    for workspace_info in list_workspaces():
        workspace_name = workspace_info.get("name") if isinstance(workspace_info, dict) else None
        if not isinstance(workspace_name, str) or not workspace_name:
            continue
        _ASSEMBLY_CONTROLLERS[os.path.realpath(os.path.abspath(workspace_dir(workspace_name)))] = (
            lambda job_id, action, target=workspace_name: control(job_id, action, target)
        )
        try:
            for persisted in store(workspace_name).list():
                normalize_stale(persisted)
        except (OSError, ValueError, json.JSONDecodeError):
            continue

    return router


def control_series_assembly_job(workspace_dir_value: str, job_id: str, action: str) -> dict[str, Any]:
    """Control Assembly from the canonical Activity adapter."""
    controller = _ASSEMBLY_CONTROLLERS.get(
        os.path.realpath(os.path.abspath(workspace_dir_value))
    )
    if controller is None:
        raise HTTPException(status_code=404, detail="Series assembly controller not found")
    return controller(job_id, action)
