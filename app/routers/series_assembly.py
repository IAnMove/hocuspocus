"""Ordered Series episode assembly API.

The launcher supplies its workspace and media primitives so this module can
own the job lifecycle without importing the large ``launch`` module or WanGP.
"""

from __future__ import annotations

import copy
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


class SeriesAssemblyStartRequest(BaseModel):
    """Stable request contract for starting one episode assembly."""

    model_config = ConfigDict(extra="forbid")

    workspace: str | None = Field(default=None, min_length=1, max_length=200)


class SeriesAssemblyJobResponse(BaseModel):
    """Public, persisted-safe view of an episode assembly job."""

    model_config = ConfigDict(extra="forbid")

    jobId: str
    workspace: str
    seriesId: str
    episodeId: str
    status: Literal["queued", "running", "completed", "failed"]
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

    def store(workspace: str) -> SeriesJobStore:
        return SeriesJobStore(workspace_dir(workspace), "assembly")

    def load(job_id: str) -> dict[str, Any] | None:
        with jobs_lock:
            cached = jobs.get(job_id)
            if cached:
                return copy.deepcopy(cached)
        for workspace in list_workspaces():
            name = workspace.get("name") if isinstance(workspace, dict) else None
            if not isinstance(name, str) or not name:
                continue
            try:
                saved = store(name).load(job_id)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if saved:
                with jobs_lock:
                    jobs[job_id] = saved
                return copy.deepcopy(saved)
        return None

    def update(job_id: str, **patch: Any) -> dict[str, Any] | None:
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return None
            job.update(copy.deepcopy(patch))
            job["updatedAt"] = time.time()
            snapshot = copy.deepcopy(job)
            store(str(job["workspace"])).save(snapshot)
            return snapshot

    def persisted_active_job(workspace: str, series_id: str, episode_id: str) -> dict[str, Any] | None:
        active_statuses = {"queued", "running"}
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
            "status": "failed",
            "stage": "failed",
            "message": "The previous assembly process was interrupted; it can be started again.",
            "error": "Assembly process interrupted before completion",
            "updatedAt": time.time(),
            "finishedAt": time.time(),
        })
        store(str(stale["workspace"])).save(stale)

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
        output_path = ""
        try:
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
            if not concatenate_clips(clip_paths, output_path):
                raise RuntimeError("ffmpeg could not join the approved Series clips")
            if not os.path.isfile(output_path):
                raise RuntimeError("Series assembly finished without an output file")

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
                    and value.get("status") in {"queued", "running"}
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
        threading.Thread(
            target=run,
            args=(job_id,),
            name=f"series-assembly-{job_id[-6:]}",
            daemon=True,
        ).start()
        return _public_job(job)

    @router.get(
        "/api/v1/series/assembly/jobs/{job_id}",
        response_model=SeriesAssemblyJobResponse,
    )
    def status(job_id: str):
        job = load(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Series assembly job not found")
        return _public_job(job)

    return router
