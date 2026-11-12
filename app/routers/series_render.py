"""Series render HTTP routes for the full server.

The core server has no Series render routes, so only the full server mounts
this router. Handlers stay module-level so a move keeps the launch function
name. This module does not import WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import copy
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException

from services.series_render_jobs import (
    _active_series_render_for_episode,
    _load_series_render_job,
    _reconcile_series_render_job,
    _run_series_render_job,
    _series_render_active_jobs,
    _series_render_candidates,
    _series_render_jobs,
    _series_render_jobs_lock,
    _series_render_store,
    _series_render_update,
)

# Injected by _bind_series_render_runtime. None until the full server binds them.
_series_library_workspace = None
_series_library_lock = None
_read_series_workspace = None
_write_series_workspace = None
_series_project_or_404 = None
_workspace_dir = None
_series_iso_now = None
_jobs = None
_request_generation_cancel = None
_reset_canonical_task_for_resume = None
_publish_series_task = None


def start_series_episode_render(series_id: str, episode_id: str, body: dict):
    from services.series_production import is_series_generated_shot
    from services.series_library import append_shot_render_attempt, series_for_episode_snapshot
    from services.series_reference_router import route_shot_references
    from services.series_render import (
        apply_series_h3_model_settings, apply_series_shot_duration, model_for_manifest,
        normalize_series_resolution, quantize_h3_frames, series_dialogue_preflight_issues,
        shot_generation_prompt, shot_render_settings,
    )

    workspace = _series_library_workspace(body.get("workspace"))
    from services.production_shot_regeneration import guard_shared_regeneration
    if body.get("shared_review") is not None:
        guard_shared_regeneration(_workspace_dir(workspace), workspace, body,
                                  f"/api/v1/series/{series_id}/episodes/{episode_id}/render/start")
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = copy.deepcopy(_series_project_or_404(library, series_id))
        episode = series.get("episodesById", {}).get(episode_id)
        if not isinstance(episode, dict):
            raise HTTPException(status_code=404, detail="Series episode not found")
        active_job = _active_series_render_for_episode(workspace, series_id, episode_id)
        if active_job:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Series episode already has active render {active_job.get('jobId')}; "
                    "resume or cancel that queue instead of creating duplicate attempts"
                ),
            )
        routing_series = series_for_episode_snapshot(series, episode)
        try:
            candidates = _series_render_candidates(episode, body)
            candidates = [shot for shot in candidates if is_series_generated_shot(series, shot)]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not candidates:
            raise HTTPException(status_code=400, detail="No permitted unapproved generated-video shots match this request. Prepare animation shots in their editor or import a completed take.")
        if any(bool(shot.get("dialogueBeats")) for shot in candidates) and not series.get(
            "bestEffortLipSyncAcknowledged"
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Dialogue rendering is blocked until best-effort native lip sync is acknowledged. "
                    "Use ‘I understand · enable dialogue rendering’ in Shots or enable it in Series setup."
                ),
            )
        for shot in candidates:
            apply_series_shot_duration(routing_series, shot)
        dialogue_issues = [
            (shot.get("order"), issue)
            for shot in candidates
            for issue in series_dialogue_preflight_issues(shot, routing_series)
        ]
        if dialogue_issues:
            summary = "; ".join(
                f"shot {order}: {issue}" for order, issue in dialogue_issues[:8]
            )
            if len(dialogue_issues) > 8:
                summary += f"; and {len(dialogue_issues) - 8} more"
            raise HTTPException(
                status_code=400,
                detail=f"Fix dialogue timing/format before rendering: {summary}",
            )
        provider = routing_series.get("provider") if isinstance(routing_series.get("provider"), dict) else {}
        provider_settings = provider.get("videoSettings") if isinstance(provider.get("videoSettings"), dict) else {}
        settings = {**copy.deepcopy(provider_settings), **(
            copy.deepcopy(body.get("settings")) if isinstance(body.get("settings"), dict) else {}
        )}
        resolution, orientation = normalize_series_resolution(
            settings.get("resolution"), settings.get("orientation"),
            provider.get("videoModel") or "minimax_h3",
        )
        settings["resolution"] = resolution
        settings["orientation"] = orientation
        settings["numInferenceSteps"] = max(1, min(50, int(settings.get("numInferenceSteps") or 20)))
        settings["guidanceScale"] = float(settings.get("guidanceScale") or 1)
        settings["flowShift"] = float(settings.get("flowShift") or 12)
        settings["audioShift"] = float(settings.get("audioShift") or 3)
        settings["modelProfile"] = str(settings.get("modelProfile") or "quality")
        settings["fps"] = 24
        try:
            base_seed = int(body.get("seed")) if body.get("seed") is not None else int(uuid.uuid4().hex[:8], 16)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Seed must be an integer") from exc
        items = []
        candidate_ids = {item["id"] for item in candidates}
        for shot_index, shot in enumerate(episode.get("shots", [])):
            if not isinstance(shot, dict) or shot.get("id") not in candidate_ids:
                continue
            manifest = route_shot_references(routing_series, episode, shot, body.get("capabilities"))
            if manifest.get("errors"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Shot {shot.get('order')} reference routing must be fixed: {'; '.join(manifest['errors'])}",
                )
            model = model_for_manifest(str(provider.get("videoModel") or "minimax_h3"), manifest)
            retry_count = len(shot.get("attempts", []))
            apply_series_shot_duration(routing_series, shot)
            duration_contract = shot.get("dialogueDuration") \
                if isinstance(shot.get("dialogueDuration"), dict) else {}
            shot_settings = apply_series_h3_model_settings(model, {
                **shot_render_settings(settings, shot),
                "requestedDurationSeconds": float(shot.get("durationSeconds") or 0),
                "dialogueDuration": copy.deepcopy(duration_contract),
                "videoLengthFrames": int(duration_contract.get("effectiveFrames"))
                if duration_contract.get("effectiveFrames") is not None
                else quantize_h3_frames(
                    shot.get("durationSeconds"), reference_mode=manifest.get("strategy") == "references",
                ),
            })
            updated_shot, attempt = append_shot_render_attempt(
                shot, manifest=manifest, model=model, settings=shot_settings,
                seed=(base_seed + int(shot.get("order") or shot_index)) & 0x7FFFFFFF,
                retry_count=retry_count, prompt=shot_generation_prompt(
                    routing_series, shot, manifest,
                ),
            )
            episode["shots"][shot_index] = updated_shot
            items.append({
                "shotId": shot["id"], "attemptId": attempt["id"], "status": "queued",
                "childJobId": None, "providerTaskId": None,
                "requestPayloadHash": None, "outputAssetIds": [], "retryCount": retry_count,
                "createdAt": time.time(), "updatedAt": time.time(), "error": None,
            })
        now_iso = _series_iso_now()
        from services.production_generation_link import attach_episode
        from services.production_project_link import LinkError
        try:
            registered = attach_episode(_workspace_dir(workspace), workspace, episode, body)
        except LinkError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        episode["status"] = "rendering"
        episode["updatedAt"] = now_iso
        series["episodesById"][episode_id] = episode
        series["revision"] = int(series.get("revision") or 1) + 1
        series["updatedAt"] = now_iso
        library["seriesById"][series_id] = series
        _write_series_workspace(workspace, library)
        # Persist the episode attempts and their owning job before releasing
        # the library lock. A concurrent start therefore observes this queue
        # and cannot append a second set of attempts for the same episode.
        job_id = f"series-render-{uuid.uuid4().hex[:12]}"
        task_id = f"task-series-render-{job_id}"
        now = time.time()
        job = {
            "jobId": job_id, "kind": "render", "workspace": workspace,
            "productionId": registered["production_id"],
            "seriesId": series_id, "episodeId": episode_id, "status": "queued",
            "stage": "queued", "current": 0, "total": len(items), "items": items,
            "activeShotId": None, "message": "Series shot render queued.",
            "settings": settings, "model": str(provider.get("videoModel") or "minimax_h3"),
            "seed": base_seed, "outputAssetIds": [], "retryCount": 0,
            "createdAt": now, "updatedAt": now, "error": None,
            "taskId": task_id, "rootTaskId": task_id,
        }
        with _series_render_jobs_lock:
            _series_render_jobs[job_id] = job
            _series_render_store(workspace).save(job)
    publisher = globals().get("_publish_series_task")
    task = publisher(job, "series-render") if callable(publisher) else None
    if isinstance(task, dict):
        job["taskId"] = task.get("id")
        job["rootTaskId"] = task.get("root_id") or task.get("id")
        with _series_render_jobs_lock:
            _series_render_jobs[job_id] = copy.deepcopy(job)
            _series_render_store(workspace).save(job)
    threading.Thread(
        target=_run_series_render_job, args=(job_id,),
        name=f"series-render-{job_id[-6:]}", daemon=False,
    ).start()
    return {key: job[key] for key in (
        "jobId", "taskId", "rootTaskId", "workspace", "seriesId", "episodeId",
        "status", "stage", "current",
        "total", "message", "settings", "seed", "createdAt",
    )}

def get_series_render_job(job_id: str):
    job = _load_series_render_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Series render job not found")
    return {key: job.get(key) for key in (
        "jobId", "workspace", "seriesId", "episodeId", "status", "stage", "current", "total",
        "items", "activeShotId", "message", "settings", "model", "seed", "error",
        "createdAt", "updatedAt", "finishedAt",
        "taskId", "rootTaskId",
    )}

def cancel_series_render_job(job_id: str):
    job = _load_series_render_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Series render job not found")
    if job.get("status") in {"completed", "failed", "cancelled"}:
        return {"jobId": job_id, "status": job.get("status"), "message": job.get("message")}
    cancelled_at = _series_iso_now()
    with _series_render_jobs_lock:
        worker_active = job_id in _series_render_active_jobs
    active_child = next((
        str(item.get("childJobId")) for item in job.get("items", [])
        if item.get("status") == "running" and item.get("childJobId")
    ), "")
    # A persisted child id can outlive its process after an app restart. Only
    # defer cancellation when there is an in-memory worker that can actually
    # reach a safe boundary; otherwise settle the orphaned checkpoint now.
    active_child_known = bool(active_child and active_child in _jobs)
    deferred = bool(worker_active or active_child_known)
    items = copy.deepcopy(job.get("items") or [])
    cancellable = {"queued", "running"}
    for item in items:
        if item.get("status") in cancellable:
            item.update({
                "status": (
                    "cancelling"
                    if deferred and item.get("status") == "running"
                    else "cancelled"
                ),
                "completedAt": (
                    None
                    if deferred and item.get("status") == "running"
                    else cancelled_at
                ),
                "error": "Cancellation requested", "updatedAt": time.time(),
            })
    updated_job = _series_render_update(
        job_id,
        items=items,
        status="cancelling" if deferred else "cancelled",
        stage="cancelling" if deferred else "cancelled",
        activeShotId=job.get("activeShotId") if deferred else None,
        finishedAt=None if deferred else time.time(),
        message=(
            "Series render cancellation requested; waiting for the active "
            "model thread to reach a safe boundary."
            if deferred else
            "Series render cancelled before model execution."
        ),
    ) or job
    # Persist cancellation for every queued/running attempt too. This keeps
    # recovery honest and guarantees resume appends a fresh attempt instead
    # of rewriting the immutable request metadata of an interrupted one.
    from services.series_library import update_shot_render_attempt
    with _series_library_lock:
        library = _read_series_workspace(str(job["workspace"]))
        series = copy.deepcopy(_series_project_or_404(library, str(job["seriesId"])))
        episode = series.get("episodesById", {}).get(str(job["episodeId"]))
        if isinstance(episode, dict):
            changed = False
            for item in items:
                if item.get("status") != "cancelled":
                    continue
                shot_index = next((
                    index for index, shot in enumerate(episode.get("shots", []))
                    if isinstance(shot, dict) and shot.get("id") == item.get("shotId")
                ), None)
                if shot_index is None:
                    continue
                try:
                    episode["shots"][shot_index] = update_shot_render_attempt(
                        episode["shots"][shot_index], str(item.get("attemptId")),
                        status="cancelled", completedAt=cancelled_at,
                        error="Cancelled by user",
                    )
                    changed = True
                except ValueError:
                    continue
            if changed:
                episode["updatedAt"] = cancelled_at
                series["episodesById"][episode["id"]] = episode
                series["revision"] = int(series.get("revision") or 1) + 1
                series["updatedAt"] = cancelled_at
                library["seriesById"][series["id"]] = series
                _write_series_workspace(str(job["workspace"]), library)
    if active_child and active_child in _jobs:
        _request_generation_cancel(active_child)
    return {
        "jobId": job_id,
        "status": updated_job.get("status"),
        "message": updated_job.get("message") or (
            "Cancellation requested; the active model thread may take a "
            "moment to release."
        ),
    }

def list_series_render_recovery(workspace: str | None = None):
    target_workspace = _series_library_workspace(workspace)
    jobs = [_reconcile_series_render_job(job) for job in _series_render_store(target_workspace).recoverable()]
    return {"jobs": [{key: job.get(key) for key in (
        "jobId", "seriesId", "episodeId", "status", "stage", "current", "total",
        "activeShotId", "message", "error", "createdAt", "updatedAt",
    )} for job in jobs]}

def resume_series_render_job(job_id: str):
    from services.series_library import append_shot_render_attempt, update_shot_render_attempt

    job = _load_series_render_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Series render job not found")
    with _series_render_jobs_lock:
        if job_id in _series_render_active_jobs:
            return {"jobId": job_id, "status": job.get("status"), "message": "Series render is already running."}
    items = copy.deepcopy(job.get("items") or [])
    # A local diffusion process cannot resume mid-step. On explicit recovery,
    # Interrupted/failed/cancelled items get a new append-only attempt;
    # completed items remain untouched and truly queued items retain theirs.
    with _series_library_lock:
        library = _read_series_workspace(str(job["workspace"]))
        series = copy.deepcopy(_series_project_or_404(library, str(job["seriesId"])))
        episode = series.get("episodesById", {}).get(str(job["episodeId"]))
        if not isinstance(episode, dict):
            raise HTTPException(status_code=404, detail="Series episode not found")
        changed = False
        for item_index, item in enumerate(items):
            if item.get("status") in {"completed", "queued"}:
                continue
            shot_index = next((
                index for index, shot in enumerate(episode.get("shots", []))
                if isinstance(shot, dict) and shot.get("id") == item.get("shotId")
            ), None)
            if shot_index is None:
                continue
            shot = episode["shots"][shot_index]
            previous = next((
                value for value in shot.get("attempts", []) if value.get("id") == item.get("attemptId")
            ), None)
            if not isinstance(previous, dict):
                continue
            if previous.get("status") in {"queued", "running"}:
                shot = update_shot_render_attempt(
                    shot, str(previous["id"]), status="cancelled",
                    completedAt=_series_iso_now(), error="Interrupted before recovery",
                )
            resumed_shot, attempt = append_shot_render_attempt(
                shot, manifest=previous.get("referenceManifest") or {},
                model=str(previous.get("model") or job.get("model") or "minimax_h3"),
                settings=previous.get("settings") or job.get("settings") or {},
                seed=previous.get("seed"), retry_count=int(previous.get("retryCount") or 0) + 1,
                prompt=str(previous.get("prompt") or shot.get("prompt") or ""),
            )
            episode["shots"][shot_index] = resumed_shot
            items[item_index] = {
                **item, "attemptId": attempt["id"], "status": "queued", "childJobId": None,
                "providerTaskId": None, "requestPayloadHash": None, "outputAssetIds": [],
                "retryCount": attempt["retryCount"], "error": None, "updatedAt": time.time(),
            }
            changed = True
        if changed:
            now_iso = _series_iso_now()
            episode["updatedAt"] = now_iso
            series["episodesById"][episode["id"]] = episode
            series["revision"] = int(series.get("revision") or 1) + 1
            series["updatedAt"] = now_iso
            library["seriesById"][series["id"]] = series
            _write_series_workspace(str(job["workspace"]), library)
        # Publish the resumed checkpoint before releasing the same lock used
        # by deletion, closing the terminal-job resume/delete race.
        _reset_canonical_task_for_resume(
            str(job.get("workspace") or "default"),
            str(job.get("taskId") or f"task-series-render-{job_id}"),
        )
        _series_render_update(
            job_id, items=items, status="queued", stage="queued", error=None, finishedAt=None,
            message="Resuming Series render; completed shots will be reused.",
        )
    threading.Thread(
        target=_run_series_render_job, args=(job_id,),
        name=f"series-render-{job_id[-6:]}", daemon=False,
    ).start()
    return {"jobId": job_id, "status": "queued", "message": "Series render resumed."}

def discard_series_render_job(job_id: str):
    job = _load_series_render_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Series render job not found")
    with _series_render_jobs_lock:
        if job_id in _series_render_active_jobs:
            raise HTTPException(status_code=409, detail="Cancel the active render before discarding its checkpoint")
        _series_render_store(str(job["workspace"])).discard(job_id)
        _series_render_jobs.pop(job_id, None)
    return {"discarded": True, "jobId": job_id, "outputsPreserved": True}

def _bind_series_render_runtime(
    *,
    resolve_workspace,
    library_lock,
    read_library,
    write_library,
    project_or_404,
    workspace_dir,
    list_workspaces,
    iso_now,
    jobs,
    new_generation_job,
    request_generation_cancel,
    run_generation,
    is_legacy_h3_model,
    is_minimax_h3_model,
    release_legacy_h3,
    release_h3,
    publish_task,
    reset_task,
) -> None:
    """Point both render modules at one server's library lock, queue and task hooks."""
    global _series_library_workspace, _series_library_lock
    global _read_series_workspace, _write_series_workspace, _series_project_or_404
    global _workspace_dir, _series_iso_now, _jobs, _request_generation_cancel
    global _reset_canonical_task_for_resume, _publish_series_task
    import services.series_render_jobs as render_jobs

    _series_library_workspace = resolve_workspace
    _series_library_lock = library_lock
    _read_series_workspace = read_library
    _write_series_workspace = write_library
    _series_project_or_404 = project_or_404
    _workspace_dir = workspace_dir
    _series_iso_now = iso_now
    _jobs = jobs
    _request_generation_cancel = request_generation_cancel
    _reset_canonical_task_for_resume = reset_task
    _publish_series_task = publish_task
    render_jobs._workspace_dir = workspace_dir
    render_jobs._list_workspaces = list_workspaces
    render_jobs._series_library_lock = library_lock
    render_jobs._read_series_workspace = read_library
    render_jobs._write_series_workspace = write_library
    render_jobs._series_project_or_404 = project_or_404
    render_jobs._series_iso_now = iso_now
    render_jobs._publish_series_task = publish_task
    render_jobs._new_generation_job = new_generation_job
    render_jobs._jobs = jobs
    render_jobs._request_generation_cancel = request_generation_cancel
    render_jobs._run_generation = run_generation
    render_jobs._is_legacy_h3_model = is_legacy_h3_model
    render_jobs._is_minimax_h3_model = is_minimax_h3_model
    render_jobs._release_legacy_h3_when_queue_allows = release_legacy_h3
    render_jobs._release_h3_when_queue_allows = release_h3
    render_jobs._cancel_series_render_job = cancel_series_render_job


def create_series_render_router() -> APIRouter:
    """The six Series render routes, in the order the full server used to register them."""
    router = APIRouter()
    router.add_api_route(
        "/api/v1/series/{series_id}/episodes/{episode_id}/render/start",
        start_series_episode_render, methods=["POST"],
    )
    router.add_api_route("/api/v1/series/render/jobs/{job_id}", get_series_render_job, methods=["GET"])
    router.add_api_route("/api/v1/series/render/jobs/{job_id}/cancel", cancel_series_render_job, methods=["POST"])
    router.add_api_route("/api/v1/series/render/recovery", list_series_render_recovery, methods=["GET"])
    router.add_api_route("/api/v1/series/render/jobs/{job_id}/resume", resume_series_render_job, methods=["POST"])
    router.add_api_route("/api/v1/series/render/jobs/{job_id}", discard_series_render_job, methods=["DELETE"])
    return router
