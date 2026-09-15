"""MiniMax Music jobs for the core/remote profile. Local ACE-Step stays 409."""
from __future__ import annotations

import copy
import threading
import time
import uuid
from typing import Any

from services import core_workspace as core
from services.minimax_music_service import ALLOWED_MODELS, COVER_MODELS, MiniMaxMusicError, generate_candidates
from services.music_submission import classify_music_route
from services.provider_profile import resolve_minimax_key

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_TERMINAL = {"completed", "failed", "cancelled"}


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy({key: value for key, value in job.items() if key not in {"request", "_cancel_requested"}})


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return _public(job) if job else None


def cancel_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        if str(job.get("status") or "") in _TERMINAL:
            return _public(job)
        job["_cancel_requested"] = True
        if str(job.get("status") or "") in {"queued", "waiting_resource"}:
            job.update(status="cancelled", phase="cancelled", message="Cancelled before the provider call")
        else:
            job.update(status="cancelling", phase="cancelling", message="Cancellation requested")
        return _public(job)


def _patch(job_id: str, **fields: Any) -> None:
    with _LOCK:
        current = _JOBS.get(job_id)
        if current:
            current.update(fields)


def _candidate_count(body: dict[str, Any]) -> int:
    try:
        return max(1, min(3, int(body.get("count") or 2)))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("MiniMax Music candidate count must be an integer from 1 to 3") from exc


def _validated_request(body: dict[str, Any], workspace: str) -> dict[str, Any]:
    from routers.system_capabilities import require_capability_http
    from services import execution_mode

    model = str(body.get("model") or "music-3.0").strip()
    try:
        route = classify_music_route(model)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    if route != "remote_minimax":
        require_capability_http("local_audio_ai")
    if model not in ALLOWED_MODELS:
        raise ValueError(f"Unsupported MiniMax Music model: {model}")
    execution_mode.validate_remote_provider(workspace, "minimax-music")
    count = _candidate_count(body)
    prompt = str(body.get("prompt") or "").strip()[:300]
    lyrics = str(body.get("lyrics") or "").strip()[:3500]
    instrumental = bool(body.get("instrumental"))
    if not prompt:
        raise ValueError("A music style prompt is required")
    if model not in COVER_MODELS and not instrumental and not lyrics:
        raise ValueError("Lyrics are required for a vocal song")
    reference_audio_path = None
    if model in COVER_MODELS:
        from services import core_editor
        reference_audio_path = core_editor.resolve_media(str(body.get("reference_audio_filename") or ""), workspace)
    return {
        "prompt": prompt, "lyrics": lyrics, "instrumental": instrumental,
        "model": model, "reference_audio_path": reference_audio_path, "count": count,
    }


def start_job(body: dict[str, Any], *, workspace: str) -> dict[str, Any]:
    request = _validated_request(body, workspace)
    job_id = f"minimax-music-{uuid.uuid4().hex[:12]}"
    now = time.time()
    job = {
        "jobId": job_id, "taskId": f"task-{job_id}", "rootTaskId": f"task-{job_id}",
        "workspace": workspace, "status": "queued", "phase": "queued",
        "message": f"{request['count']} MiniMax Music candidate(s) queued",
        "current": 0, "total": request["count"], "progress": 0,
        "provider": "minimax", "model": request["model"], "candidates": [],
        "result": None, "error": None, "createdAt": now, "updatedAt": now,
        "_cancel_requested": False, "request": request,
    }
    with _LOCK:
        _JOBS[job_id] = job
        initial = _public(job)
    threading.Thread(target=_run, args=(job_id,), daemon=True, name=job_id).start()
    return initial


def _fail(job_id: str, message: str, **extra: Any) -> None:
    _patch(job_id, status="failed", phase="failed", message=message, error=message, **extra)


def _run(job_id: str) -> None:
    def cancelled() -> bool:
        with _LOCK:
            return bool((_JOBS.get(job_id) or {}).get("_cancel_requested"))

    with _LOCK:
        job = copy.deepcopy(_JOBS.get(job_id) or {})
    request = job.get("request") or {}
    try:
        _patch(job_id, status="running", phase="running", message="Calling MiniMax Music")
        results = generate_candidates(
            api_key=resolve_minimax_key(core.services_raw(), "music"),
            prompt=str(request.get("prompt") or ""), lyrics=str(request.get("lyrics") or ""),
            count=int(request.get("count") or 1),
            output_dir=core.workspace_dir(str(job.get("workspace") or "default")),
            instrumental=bool(request.get("instrumental")),
            model=str(request.get("model") or "music-3.0"),
            reference_audio_path=request.get("reference_audio_path"),
            task_id=str(job.get("taskId") or ""), root_task_id=str(job.get("rootTaskId") or ""),
            cancelled=cancelled,
        )
        _patch(
            job_id, status="completed", phase="completed", progress=100,
            current=len(results), total=len(results),
            message=f"Generated {len(results)} MiniMax Music candidate(s)",
            candidates=results, result={"candidates": results},
        )
    except MiniMaxMusicError as exc:
        _fail(job_id, str(exc), statusCode=exc.status_code)
    except Exception as exc:
        _fail(job_id, str(exc))
