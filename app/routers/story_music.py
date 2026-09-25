"""Story MiniMax Music job HTTP surface extracted from the launch runtime.

The launcher supplies workspace and job primitives so this module never
imports WanGP, Gradio, model weights, or ``_launch_runtime``. Studio music
commands stay in ``studio_music_commands``.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from services import execution_mode


_get_active_workspace: Callable[[], str]
_workspace_dir: Callable[..., str]
_story_cover_reference_path: Callable[[str, str], str | None]
_load_minimax_music_job: Callable[[str], dict | None]
_persist_minimax_music_job: Callable[[dict], None]
_publish_minimax_music_job: Callable[[dict], None]
_public_minimax_music_job: Callable[[dict], dict]
_run_minimax_music_job: Callable[[str], None]
_minimax_music_jobs: dict[str, dict]
_minimax_music_jobs_lock: threading.RLock
_MINIMAX_MUSIC_TERMINAL: set[str]
_finish_unstarted_music_children: Callable[..., None]
_minimax_music_job_update: Callable[..., Any]
wgp: Any


def _bind_story_music_runtime(
    *,
    get_active_workspace: Callable[[], str],
    workspace_dir: Callable[..., str],
    story_cover_reference_path: Callable[[str, str], str | None],
    load_minimax_music_job: Callable[[str], dict | None],
    persist_minimax_music_job: Callable[[dict], None],
    publish_minimax_music_job: Callable[[dict], None],
    public_minimax_music_job: Callable[[dict], dict],
    run_minimax_music_job: Callable[[str], None],
    minimax_music_jobs: dict[str, dict],
    minimax_music_jobs_lock: threading.RLock,
    minimax_music_terminal: set[str],
    finish_unstarted_music_children: Callable[..., None],
    minimax_music_job_update: Callable[..., Any],
    wgp_module: Any,
) -> None:
    """Install launcher primitives under the names the handlers already use."""
    global _get_active_workspace, _workspace_dir, _story_cover_reference_path
    global _load_minimax_music_job, _persist_minimax_music_job
    global _publish_minimax_music_job, _public_minimax_music_job
    global _run_minimax_music_job, _minimax_music_jobs, _minimax_music_jobs_lock
    global _MINIMAX_MUSIC_TERMINAL, _finish_unstarted_music_children
    global _minimax_music_job_update, wgp
    _get_active_workspace = get_active_workspace
    _workspace_dir = workspace_dir
    _story_cover_reference_path = story_cover_reference_path
    _load_minimax_music_job = load_minimax_music_job
    _persist_minimax_music_job = persist_minimax_music_job
    _publish_minimax_music_job = publish_minimax_music_job
    _public_minimax_music_job = public_minimax_music_job
    _run_minimax_music_job = run_minimax_music_job
    _minimax_music_jobs = minimax_music_jobs
    _minimax_music_jobs_lock = minimax_music_jobs_lock
    _MINIMAX_MUSIC_TERMINAL = minimax_music_terminal
    _finish_unstarted_music_children = finish_unstarted_music_children
    _minimax_music_job_update = minimax_music_job_update
    wgp = wgp_module


def _reserve_story_music_submission(body: dict, workspace: str):
    """Persist command/task/candidate IDs before the MiniMax worker starts."""
    from services.music_submission import (
        MusicSubmissionConflict,
        MusicSubmissionError,
        submit_music_generation,
    )

    try:
        return submit_music_generation(
            workspace_dir=_workspace_dir(workspace),
            request={**body, "output_folder": workspace, "workspace": workspace},
        )
    except MusicSubmissionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MusicSubmissionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def start_story_music_candidates_job(body: dict):
    """Start observable MiniMax Music generation and return immediately."""
    from services import minimax_music_service

    workspace = body.get("workspace") if "workspace" in body else _get_active_workspace()
    _workspace_dir(workspace)
    try:
        execution_mode.validate_remote_provider(workspace, "minimax-music")
    except execution_mode.ExecutionModeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    model = str(body.get("model") or "music-3.0").strip()
    if model not in minimax_music_service.ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail=f"Unsupported MiniMax Music model: {model}")
    try:
        count = max(1, min(3, int(body.get("count") or 2)))
    except (TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(
            status_code=400,
            detail="MiniMax Music candidate count must be an integer from 1 to 3",
        ) from exc
    prompt = str(body.get("prompt") or "").strip()[:300]
    lyrics = str(body.get("lyrics") or "").strip()[:3500]
    instrumental = bool(body.get("instrumental"))
    if not prompt:
        raise HTTPException(status_code=400, detail="A music style prompt is required")
    if model not in minimax_music_service.COVER_MODELS and not instrumental and not lyrics:
        raise HTTPException(status_code=400, detail="Lyrics are required for a vocal song")
    reference_audio_path = None
    if model in minimax_music_service.COVER_MODELS:
        reference_audio_path = _story_cover_reference_path(
            str(body.get("reference_audio_filename") or ""),
            workspace,
        )
        if not reference_audio_path:
            raise HTTPException(
                status_code=400,
                detail="Upload a valid reference song before generating a cover",
            )

    reserved = _reserve_story_music_submission(body, workspace) or {}
    if reserved.get("replay"):
        existing = _load_minimax_music_job(str(reserved.get("job_id") or ""))
        if existing:
            public = _public_minimax_music_job(existing)
            public["replay"] = True
            return public
        # Reservation survived but the MiniMax job did not: start the worker
        # again with the reserved IDs instead of returning a dead 202.
    job_id = str(reserved.get("job_id") or f"minimax-music-{uuid.uuid4().hex[:12]}")
    task_id = str(reserved.get("task_id") or f"task-minimax-music-{job_id}")
    now = time.time()
    children = []
    for index in range(count):
        child_job_id = f"{job_id}-candidate-{index + 1}"
        child_task_id = f"{task_id}-candidate-{index + 1}"
        children.append({
            "jobId": child_job_id,
            "taskId": child_task_id,
            "rootTaskId": task_id,
            "parentTaskId": task_id,
            "workspace": workspace,
            "status": "queued",
            "phase": "queued",
            "message": f"MiniMax Music candidate {index + 1}/{count} queued",
            "current": 0,
            "total": 1,
            "progress": 0,
            "provider": "minimax",
            "model": model,
            "server_origin": "https://api.minimax.io",
            "resource_lane": "remote:https://api.minimax.io",
            "acquired_resources": [],
            "output_files": [],
            "result": None,
            "error": None,
            "createdAt": now,
            "updatedAt": now,
        })
    job = {
        "jobId": job_id,
        "taskId": task_id,
        "rootTaskId": task_id,
        "workspace": workspace,
        "status": "queued",
        "phase": "queued",
        "message": f"{count} MiniMax Music candidate(s) queued",
        "current": 0,
        "total": count,
        "progress": 0,
        "provider": "minimax",
        "model": model,
        "server_origin": "https://api.minimax.io",
        "resource_lane": "remote:https://api.minimax.io",
        "acquired_resources": [],
        "output_files": [],
        "candidates": [],
        "result": None,
        "error": None,
        "children": children,
        "createdAt": now,
        "updatedAt": now,
        "_cancel_requested": False,
        "request": {
            "prompt": prompt,
            "lyrics": lyrics,
            "instrumental": instrumental,
            "model": model,
            "reference_audio_path": reference_audio_path,
        },
        "generationId": reserved.get("generation_id"),
        "commandId": reserved.get("command_id"),
        "candidateId": reserved.get("candidate_id"),
        "idempotencyKey": reserved.get("idempotency_key"),
    }
    with _minimax_music_jobs_lock:
        existing_live = _minimax_music_jobs.get(job_id)
        if existing_live is not None:
            # Same reserved job_id is already in flight (concurrent replay
            # missed the checkpoint). Do not start a second worker.
            public = _public_minimax_music_job(existing_live)
            public["replay"] = True
            return public
        _minimax_music_jobs[job_id] = job
        _persist_minimax_music_job(job)
    _publish_minimax_music_job(job)
    threading.Thread(
        target=_run_minimax_music_job,
        args=(job_id,),
        name=f"minimax-music-{job_id[-6:]}",
        daemon=True,
    ).start()
    return _public_minimax_music_job(job)


def get_story_music_candidates_job(job_id: str):
    job = _load_minimax_music_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="MiniMax Music job not found")
    return _public_minimax_music_job(job)


def cancel_story_music_candidates_job(job_id: str):
    job = _load_minimax_music_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="MiniMax Music job not found")
    if str(job.get("status") or "") in _MINIMAX_MUSIC_TERMINAL:
        return _public_minimax_music_job(job)
    with _minimax_music_jobs_lock:
        live = _minimax_music_jobs[job_id]
        live["_cancel_requested"] = True
        waiting = str(live.get("status") or "") in {
            "created", "queued", "waiting_resource",
        }
    if waiting:
        _finish_unstarted_music_children(
            job_id, 0, "Cancelled before this candidate started",
        )
        updated = _minimax_music_job_update(
            job_id, status="cancelled", phase="cancelled",
            message="Cancelled before the provider call", finishedAt=time.time(),
            acquired_resources=[],
        )
    else:
        updated = _minimax_music_job_update(
            job_id, status="cancelling", phase="cancelling",
            message="Cancellation requested; waiting for the active MiniMax request…",
        )
    return _public_minimax_music_job(updated or job)


async def generate_story_music_candidates(body: dict):
    """Compatibility endpoint for older clients; new clients use durable jobs."""
    from services import minimax_music_service

    services = wgp.server_config.get("services", {})
    workspace = str(body.get("workspace") or _get_active_workspace())
    execution_mode.validate_remote_provider(workspace, "minimax-music")
    model = str(body.get("model") or "music-3.0").strip()
    reference_audio_path = None
    if model in {"music-cover", "music-cover-free"}:
        reference_audio_path = _story_cover_reference_path(
            str(body.get("reference_audio_filename") or ""),
            workspace,
        )
        if not reference_audio_path:
            raise HTTPException(status_code=400, detail="Upload a valid reference song before generating a cover")
    try:
        candidates = await asyncio.to_thread(
            minimax_music_service.generate_candidates,
            api_key=str(__import__("services.provider_profile", fromlist=["resolve_minimax_key"]).resolve_minimax_key(services, "music") or ""),
            prompt=str(body.get("prompt") or ""),
            lyrics=str(body.get("lyrics") or ""),
            count=int(body.get("count") or 2),
            output_dir=_workspace_dir(workspace),
            instrumental=bool(body.get("instrumental")),
            model=model,
            reference_audio_path=reference_audio_path,
        )
    except minimax_music_service.MiniMaxMusicError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {
        "candidates": [
            {
                **candidate,
                "source": f"/api/v1/file/{candidate['filename']}",
            }
            for candidate in candidates
        ]
    }


_start_story_music_candidates_job = start_story_music_candidates_job
_get_story_music_candidates_job = get_story_music_candidates_job
_cancel_story_music_candidates_job = cancel_story_music_candidates_job
_generate_story_music_candidates = generate_story_music_candidates


def create_story_music_router(
    *,
    get_active_workspace: Callable[[], str],
    workspace_dir: Callable[..., str],
    story_cover_reference_path: Callable[[str, str], str | None],
    load_minimax_music_job: Callable[[str], dict | None],
    persist_minimax_music_job: Callable[[dict], None],
    publish_minimax_music_job: Callable[[dict], None],
    public_minimax_music_job: Callable[[dict], dict],
    run_minimax_music_job: Callable[[str], None],
    minimax_music_jobs: dict[str, dict],
    minimax_music_jobs_lock: threading.RLock,
    minimax_music_terminal: set[str],
    finish_unstarted_music_children: Callable[..., None],
    minimax_music_job_update: Callable[..., Any],
    wgp_module: Any,
) -> APIRouter:
    """Mount Story MiniMax Music jobs without importing the launch module."""
    _bind_story_music_runtime(
        get_active_workspace=get_active_workspace,
        workspace_dir=workspace_dir,
        story_cover_reference_path=story_cover_reference_path,
        load_minimax_music_job=load_minimax_music_job,
        persist_minimax_music_job=persist_minimax_music_job,
        publish_minimax_music_job=publish_minimax_music_job,
        public_minimax_music_job=public_minimax_music_job,
        run_minimax_music_job=run_minimax_music_job,
        minimax_music_jobs=minimax_music_jobs,
        minimax_music_jobs_lock=minimax_music_jobs_lock,
        minimax_music_terminal=minimax_music_terminal,
        finish_unstarted_music_children=finish_unstarted_music_children,
        minimax_music_job_update=minimax_music_job_update,
        wgp_module=wgp_module,
    )
    router = APIRouter()

    @router.post("/api/v1/stories/music-candidates/jobs", status_code=202)
    def start_story_music_candidates_job(body: dict):
        """Start observable MiniMax Music generation and return immediately."""
        return _start_story_music_candidates_job(body)

    @router.get("/api/v1/stories/music-candidates/jobs/{job_id}")
    def get_story_music_candidates_job(job_id: str):
        return _get_story_music_candidates_job(job_id)

    @router.post("/api/v1/stories/music-candidates/jobs/{job_id}/cancel")
    def cancel_story_music_candidates_job(job_id: str):
        return _cancel_story_music_candidates_job(job_id)

    @router.post("/api/v1/stories/music-candidates")
    async def generate_story_music_candidates(body: dict):
        """Compatibility endpoint for older clients; new clients use durable jobs."""
        return await _generate_story_music_candidates(body)

    return router


__all__ = [
    "cancel_story_music_candidates_job",
    "create_story_music_router",
    "generate_story_music_candidates",
    "get_story_music_candidates_job",
    "start_story_music_candidates_job",
    "_reserve_story_music_submission",
]
