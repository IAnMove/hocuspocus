"""Series plan HTTP routes shared by the full server and the core server.

Resume and apply are separate factories so the full server can keep the shot
duration preview between them. Handlers stay module-level so a move keeps the
launch function name. This module does not import WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import copy
import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from services.series_plan_jobs import (
    _apply_series_canon_proposal,
    _load_series_plan_job,
    _prepare_edited_series_episode_proposal,
    _run_series_plan_job,
    _series_plan_active_jobs,
    _series_plan_jobs,
    _series_plan_jobs_lock,
    _series_plan_request,
    _series_plan_store,
    _series_plan_update,
)

# Injected by _bind_series_plan_runtime. None until a server binds them.
_series_library_workspace = None
_series_library_lock = None
_read_series_workspace = None
_write_series_workspace = None
_series_project_or_404 = None
_comic_writing_llm = None
_reset_canonical_task_for_resume = None
_publish_series_task = None


def start_series_canon_preparation(series_id: str, body: dict):
    workspace = _series_library_workspace(body.get("workspace"))
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = copy.deepcopy(_series_project_or_404(library, series_id))
    bootstrap_known_series = body.get("bootstrapKnownSeries") is True
    instruction = str(body.get("instruction") or "")[:8000].strip()
    if bootstrap_known_series and len(instruction) < 3:
        raise HTTPException(status_code=400, detail="Describe the known series you want to continue")
    missing = [
        label for label, value in (
            ("title", series.get("title")), ("premise", series.get("premise")),
            ("visual style", series.get("visualStyle")),
        ) if not str(value or "").strip()
    ]
    if missing and not bootstrap_known_series:
        raise HTTPException(
            status_code=400,
            detail=f"Complete Series setup before preparing canon: {', '.join(missing)}",
        )
    snapshot = copy.deepcopy(series)
    snapshot.pop("assets", None)
    snapshot["episodesById"] = {}
    request = {
        "instruction": instruction,
        "writingProvider": str(body.get("writingProvider") or series.get("provider", {}).get("writingProvider") or "maestro"),
        "writingModel": str(body.get("writingModel") or series.get("provider", {}).get("writingModel") or ""),
        "writingBaseUrl": str(body.get("writingBaseUrl") or series.get("provider", {}).get("writingBaseUrl") or ""),
        "seriesSnapshot": snapshot,
        "bootstrapKnownSeries": bootstrap_known_series,
        "autoApply": bootstrap_known_series and body.get("autoApply") is not False,
    }
    _comic_writing_llm(request)
    job_id = f"series-canon-{uuid.uuid4().hex[:12]}"
    task_id = f"task-series-plan-{job_id}"
    now = time.time()
    job = {
        "jobId": job_id, "jobType": "canon", "kind": "planning",
        "workspace": workspace, "seriesId": series_id, "episodeId": "",
        "status": "queued", "stage": "queued", "current": 0, "total": 1,
        "message": "Canon preparation queued.", "request": request,
        "sourceSeriesRevision": int(series.get("revision") or 1),
        "seriesResult": None, "result": None, "error": None,
        "generateImages": body.get("generateImages") is True,
        "bootstrapKnownSeries": bootstrap_known_series,
        "autoApply": request["autoApply"], "autoApplied": False,
        "createdAt": now, "updatedAt": now,
        "taskId": task_id, "rootTaskId": task_id,
    }
    # Revalidate and publish the durable checkpoint while deletion holds the
    # same library lock. Either deletion wins and this start returns 404, or
    # the checkpoint wins and the deletion guard observes it.
    with _series_library_lock:
        _series_project_or_404(_read_series_workspace(workspace), series_id)
        with _series_plan_jobs_lock:
            _series_plan_jobs[job_id] = job
            _series_plan_store(workspace).save(job)
    publisher = globals().get("_publish_series_task")
    task = publisher(job, "series-plan") if callable(publisher) else None
    if isinstance(task, dict):
        job["taskId"] = task.get("id")
        job["rootTaskId"] = task.get("root_id") or task.get("id")
        with _series_plan_jobs_lock:
            _series_plan_jobs[job_id] = copy.deepcopy(job)
            _series_plan_store(workspace).save(job)
    threading.Thread(target=_run_series_plan_job, args=(job_id,), daemon=True).start()
    return {key: job[key] for key in (
        "jobId", "jobType", "workspace", "seriesId", "episodeId",
        "status", "stage", "current", "total", "message", "generateImages",
        "bootstrapKnownSeries", "autoApply", "autoApplied", "taskId",
        "rootTaskId", "createdAt",
    )}

def start_series_episode_plan(series_id: str, episode_id: str, body: dict):
    from services.series_planning import planning_stages

    workspace = _series_library_workspace(body.get("workspace"))
    scope = str(body.get("scope") or "complete")
    try:
        stages = planning_stages(scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = _series_project_or_404(library, series_id)
        episode = series.get("episodesById", {}).get(episode_id)
        if not isinstance(episode, dict):
            raise HTTPException(status_code=404, detail="Series episode not found")
        if not str(episode.get("premise") or body.get("instruction") or "").strip():
            raise HTTPException(status_code=400, detail="Write an episode premise or instruction first")
        request = _series_plan_request(body, series, episode)
    # Resolve provider credentials before creating a durable job so a missing
    # key does not leave a permanently queued phantom checkpoint.
    _comic_writing_llm(request)
    job_id = f"series-plan-{uuid.uuid4().hex[:12]}"
    task_id = f"task-series-plan-{job_id}"
    now = time.time()
    job = {
        "jobId": job_id, "kind": "planning", "workspace": workspace,
        "seriesId": series_id, "episodeId": episode_id,
        "status": "queued", "stage": "queued", "current": 0, "total": len(stages),
        "message": "Episode planning queued.", "request": request,
        "sourceSeriesRevision": int(series.get("revision") or 1),
        "sourceEpisodeUpdatedAt": episode.get("updatedAt"),
        "completedStages": {}, "episodeResult": None, "result": None, "error": None,
        "createdAt": now, "updatedAt": now,
        "taskId": task_id, "rootTaskId": task_id,
    }
    # Revalidate and publish atomically with respect to Series deletion.
    with _series_library_lock:
        current_series = _series_project_or_404(_read_series_workspace(workspace), series_id)
        if not isinstance(current_series.get("episodesById", {}).get(episode_id), dict):
            raise HTTPException(status_code=404, detail="Series episode not found")
        with _series_plan_jobs_lock:
            _series_plan_jobs[job_id] = job
            _series_plan_store(workspace).save(job)
    publisher = globals().get("_publish_series_task")
    task = publisher(job, "series-plan") if callable(publisher) else None
    if isinstance(task, dict):
        job["taskId"] = task.get("id")
        job["rootTaskId"] = task.get("root_id") or task.get("id")
        with _series_plan_jobs_lock:
            _series_plan_jobs[job_id] = copy.deepcopy(job)
            _series_plan_store(workspace).save(job)
    threading.Thread(target=_run_series_plan_job, args=(job_id,), daemon=True).start()
    return {key: job[key] for key in (
        "jobId", "taskId", "rootTaskId", "workspace", "seriesId", "episodeId",
        "status", "stage", "current",
        "total", "message", "createdAt",
    )}

def get_series_episode_plan(job_id: str):
    job = _load_series_plan_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Series planning job not found")
    return {key: job.get(key) for key in (
        "jobId", "jobType", "workspace", "seriesId", "episodeId", "status", "stage", "current", "total",
        "message", "completedStages", "episodeResult", "seriesResult", "generateImages",
        "validationAttempt", "validationError",
        "bootstrapKnownSeries", "autoApply", "autoApplied", "appliedSeriesRevision", "applyError",
        "result", "error", "createdAt", "updatedAt", "finishedAt", "appliedAt",
        "taskId", "rootTaskId",
    )}

def cancel_series_episode_plan(job_id: str):
    job = _load_series_plan_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Series planning job not found")
    if job.get("status") in {"completed", "failed", "cancelled"}:
        return {"jobId": job_id, "status": job.get("status"), "message": job.get("message")}
    with _series_plan_jobs_lock:
        worker_active = job_id in _series_plan_active_jobs
    updated = _series_plan_update(
        job_id,
        status="cancelling" if worker_active else "cancelled",
        stage="cancelling" if worker_active else "cancelled",
        finishedAt=None if worker_active else time.time(),
        message=(
            "Series planning cancellation requested; aborting the active LLM "
            "response where supported, otherwise waiting for its safe boundary."
            if worker_active else
            "Series planning cancelled before an LLM call started."
        ),
    )
    return {
        "jobId": job_id,
        "status": updated.get("status"),
        "message": updated.get("message"),
    }

def resume_series_episode_plan(job_id: str, body: dict | None = None):
    job = _load_series_plan_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Series planning job not found")
    if job.get("status") == "completed":
        return {"jobId": job_id, "status": "completed", "message": job.get("message")}
    with _series_plan_jobs_lock:
        if job_id in _series_plan_active_jobs:
            return {"jobId": job_id, "status": job.get("status"), "message": "Planning is already running."}
    request = copy.deepcopy(job.get("request") or {})
    if isinstance(body, dict) and str(body.get("writingProvider") or "").strip():
        for key in ("writingProvider", "writingModel", "writingBaseUrl"):
            if key in body:
                request[key] = body[key]
        _comic_writing_llm(request)
    workspace = str(job.get("workspace") or "default")
    with _series_library_lock:
        current_series = _series_project_or_404(
            _read_series_workspace(workspace), str(job.get("seriesId") or ""),
        )
        episode_id = str(job.get("episodeId") or "")
        if episode_id and not isinstance(current_series.get("episodesById", {}).get(episode_id), dict):
            raise HTTPException(status_code=404, detail="Series episode not found")
        _reset_canonical_task_for_resume(
            workspace,
            str(job.get("taskId") or f"task-series-plan-{job_id}"),
        )
        _series_plan_update(
            job_id, request=request, status="queued", error=None, finishedAt=None,
            message="Resuming episode planning from the last completed stage…",
        )
    threading.Thread(target=_run_series_plan_job, args=(job_id,), daemon=True).start()
    return {"jobId": job_id, "status": "queued", "message": "Episode planning resumed."}

def apply_series_episode_plan(job_id: str, body: dict | None = None):
    job = _load_series_plan_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Series planning job not found")
    if job.get("jobType") == "canon":
        raise HTTPException(status_code=400, detail="Use the canon proposal apply endpoint for this job")
    if job.get("status") != "completed" or not isinstance(job.get("episodeResult"), dict):
        raise HTTPException(status_code=400, detail="Complete the planning job before applying it")
    workspace = str(job["workspace"])
    series_id = str(job["seriesId"])
    episode_id = str(job["episodeId"])
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = copy.deepcopy(_series_project_or_404(library, series_id))
        current = series.get("episodesById", {}).get(episode_id)
        if not isinstance(current, dict):
            raise HTTPException(status_code=404, detail="Series episode not found")
        if current.get("updatedAt") != job.get("sourceEpisodeUpdatedAt"):
            raise HTTPException(
                status_code=409,
                detail="The episode was edited after planning started. Review the saved proposal instead of overwriting it.",
            )
        try:
            proposed = _prepare_edited_series_episode_proposal(
                job["episodeResult"], body.get("episodeResult") if isinstance(body, dict) else None, series,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        proposed["canonSnapshot"] = copy.deepcopy(current.get("canonSnapshot"))
        proposed["canonRevisionAtCreation"] = current.get("canonRevisionAtCreation")
        proposed["createdAt"] = current.get("createdAt")
        proposed["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        # Route exact manifests now so review shows what generation will send.
        from services.series_library import series_for_episode_snapshot
        from services.series_reference_router import route_shot_references
        routing_series = series_for_episode_snapshot(series, proposed)
        for shot in proposed.get("shots", []):
            if isinstance(shot, dict):
                shot["referenceManifest"] = route_shot_references(routing_series, proposed, shot)
        series["episodesById"][episode_id] = proposed
        series["revision"] = int(series.get("revision") or 1) + 1
        series["updatedAt"] = proposed["updatedAt"]
        library["seriesById"][series_id] = series
        stored = _write_series_workspace(workspace, library)
    _series_plan_update(job_id, appliedAt=time.time(), message="Episode proposal applied for review.")
    return stored["seriesById"][series_id]["episodesById"][episode_id]

def apply_series_canon_plan(job_id: str):
    job = _load_series_plan_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Series canon planning job not found")
    proposal = job.get("seriesResult")
    if job.get("jobType") != "canon" or job.get("status") != "completed" or not isinstance(proposal, dict):
        raise HTTPException(status_code=400, detail="Complete the canon preparation job before applying it")
    applied = _apply_series_canon_proposal(job, proposal)
    _series_plan_update(job_id, appliedAt=time.time(), message="Canon proposal applied as a draft for review.")
    return applied

def list_series_plan_recovery(workspace: str | None = None):
    target_workspace = _series_library_workspace(workspace)
    jobs = _series_plan_store(target_workspace).recoverable()
    return {"jobs": [{key: job.get(key) for key in (
        "jobId", "jobType", "seriesId", "episodeId", "status", "stage", "current", "total", "generateImages",
        "bootstrapKnownSeries", "autoApply", "autoApplied",
        "message", "error", "createdAt", "updatedAt",
    )} for job in jobs]}

def discard_series_plan_job(job_id: str):
    job = _load_series_plan_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Series planning job not found")
    with _series_plan_jobs_lock:
        if job_id in _series_plan_active_jobs:
            raise HTTPException(status_code=409, detail="Cancel the active planning job before discarding it")
        _series_plan_store(str(job["workspace"])).discard(job_id)
        _series_plan_jobs.pop(job_id, None)
    return {"discarded": True, "jobId": job_id, "outputsPreserved": True}

def _bind_series_plan_runtime(
    *,
    resolve_workspace,
    library_lock,
    read_library,
    write_library,
    project_or_404,
    workspace_dir,
    list_workspaces,
    ensure_llm_loaded,
    writing_override,
    publish_task,
    reset_task,
) -> None:
    """Point both plan modules at one server's library lock and accessors."""
    global _series_library_workspace, _series_library_lock
    global _read_series_workspace, _write_series_workspace, _series_project_or_404
    global _comic_writing_llm, _reset_canonical_task_for_resume, _publish_series_task
    import services.series_plan_jobs as jobs

    _series_library_workspace = resolve_workspace
    _series_library_lock = library_lock
    _read_series_workspace = read_library
    _write_series_workspace = write_library
    _series_project_or_404 = project_or_404
    _comic_writing_llm = writing_override
    _reset_canonical_task_for_resume = reset_task
    _publish_series_task = publish_task
    jobs._workspace_dir = workspace_dir
    jobs._list_workspaces = list_workspaces
    jobs._series_library_lock = library_lock
    jobs._read_series_workspace = read_library
    jobs._write_series_workspace = write_library
    jobs._series_project_or_404 = project_or_404
    jobs._comic_writing_llm = writing_override
    jobs._ensure_llm_loaded = ensure_llm_loaded
    jobs._publish_series_task = publish_task


def create_series_plan_router() -> APIRouter:
    """Plan routes up to resume. Duration preview stays mounted between the two factories."""
    router = APIRouter()
    router.add_api_route("/api/v1/series/{series_id}/canon/prepare/start", start_series_canon_preparation, methods=["POST"])
    router.add_api_route("/api/v1/series/{series_id}/episodes/{episode_id}/plan/start", start_series_episode_plan, methods=["POST"])
    router.add_api_route("/api/v1/series/plan/jobs/{job_id}", get_series_episode_plan, methods=["GET"])
    router.add_api_route("/api/v1/series/plan/jobs/{job_id}/cancel", cancel_series_episode_plan, methods=["POST"])
    router.add_api_route("/api/v1/series/plan/jobs/{job_id}/resume", resume_series_episode_plan, methods=["POST"])
    return router


def create_series_plan_apply_router() -> APIRouter:
    """Apply, canon apply, recovery and discard. Mounted after the duration preview."""
    router = APIRouter()
    router.add_api_route("/api/v1/series/plan/jobs/{job_id}/apply", apply_series_episode_plan, methods=["POST"])
    router.add_api_route("/api/v1/series/plan/jobs/{job_id}/apply-canon", apply_series_canon_plan, methods=["POST"])
    router.add_api_route("/api/v1/series/plan/recovery", list_series_plan_recovery, methods=["GET"])
    router.add_api_route("/api/v1/series/plan/jobs/{job_id}", discard_series_plan_job, methods=["DELETE"])
    return router
