"""Series render jobs for the full server.

The job dictionary, the active-job set and their lock stay here. The Series
library lock, the workspace helpers and the generation-queue callables are
injected by the full server and are the same objects the rest of the server
uses. A render still claims the GPU slot by handing a child job to
``_run_generation``. This module does not import WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import time
import uuid

from services import workspace_busy
from services.job_lifecycle import snapshot_job

_series_render_jobs: dict[str, dict] = {}
_series_render_jobs_lock = threading.RLock()
_series_render_active_jobs: set[str] = set()
INTERRUPTED = "The server restarted during this render; resume to continue"


def busy_jobs(workspace: str, workspace_dir: str) -> list[dict]:
    """Series render coordinators that are running now (``services.workspace_busy`` probe).

    The claim set is the proof of life; the child generation jobs are also in the queue, but the
    coordinator is alive between them.
    """
    with _series_render_jobs_lock:
        return workspace_busy.claimed(_series_render_active_jobs, _series_render_jobs)

# Injected by _bind_series_render_runtime. None until the full server binds them.
_workspace_dir = None
_list_workspaces = None
_series_library_lock = None
_read_series_workspace = None
_write_series_workspace = None
_series_project_or_404 = None
_series_iso_now = None
_publish_series_task = None
_new_generation_job = None
_jobs = None
_request_generation_cancel = None
_run_generation = None
_is_legacy_h3_model = None
_is_minimax_h3_model = None
_release_legacy_h3_when_queue_allows = None
_release_h3_when_queue_allows = None
_cancel_series_render_job = None


def _clip_name(shot_id: str, child_job_id: str) -> str:
    """The file stem a render asks WanGP for: only ``[A-Za-z0-9_-]``, unique to this child job.

    WanGP names an unnamed clip after its prompt (spaces and brackets stay) and adds ``(2)`` when a name is taken;
    ``validate_series_asset_uri`` accepts neither, so the finished clip was registered as a failure.
    Like ``series_native_render``, a Series render names its outputs."""
    shot = re.sub(r"[^A-Za-z0-9_-]+", "_", str(shot_id)).strip("_")[:60] or "shot"
    return f"series-{shot}-{child_job_id}"


def _series_render_store(workspace: str):
    from services.series_jobs import SeriesJobStore

    return SeriesJobStore(_workspace_dir(workspace), "render")


def _reconcile_series_render_job(job: dict) -> dict:
    """A checkpoint that says running without a worker in this process was cut by a restart: interrupted, once.

    A render this process started is in ``_series_render_jobs`` and, while it works, in ``_series_render_active_jobs``;
    anything else read from disk is dead. Its running items become ``interrupted`` (not ``queued``): a resume
    (``routers.series_render.resume_series_render_job``) gives those a new attempt instead of reusing a dead child."""
    job_id = str(job.get("jobId") or "")
    if job.get("status") != "running":
        return job
    with _series_render_jobs_lock:
        if job_id in _series_render_active_jobs or job_id in _series_render_jobs:
            return job
    settled = copy.deepcopy(job)
    for item in settled.get("items") or []:
        if isinstance(item, dict) and item.get("status") == "running":
            item["status"] = "interrupted"
    now = time.time()
    settled.update(status="interrupted", stage="interrupted", activeShotId=None, message=INTERRUPTED,
                   finishedAt=now, updatedAt=now)
    _series_render_store(str(settled.get("workspace") or "default")).save(settled)
    return settled

def _active_series_render_for_episode(
    workspace: str, series_id: str, episode_id: str,
) -> dict | None:
    """Return the one queue that owns an episode, including after restart."""
    active_statuses = {"queued", "running", "cancelling"}
    with _series_render_jobs_lock:
        cached = [copy.deepcopy(job) for job in _series_render_jobs.values()]
    try:
        persisted = [_reconcile_series_render_job(job) for job in _series_render_store(workspace).list()]
    except (OSError, ValueError, json.JSONDecodeError):
        persisted = []
    by_id = {
        str(job.get("jobId")): job
        for job in [*persisted, *cached]
        if isinstance(job, dict) and job.get("jobId")
    }
    return next((
        job for job in by_id.values()
        if job.get("workspace") == workspace
        and job.get("seriesId") == series_id
        and job.get("episodeId") == episode_id
        and job.get("status") in active_statuses
    ), None)

def _load_series_render_job(job_id: str) -> dict | None:
    with _series_render_jobs_lock:
        cached = _series_render_jobs.get(job_id)
        if cached:
            return copy.deepcopy(cached)
    for item in _list_workspaces():
        try:
            job = _series_render_store(item["name"]).load(job_id)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if job:
            job = _reconcile_series_render_job(job)
            with _series_render_jobs_lock:
                _series_render_jobs[job_id] = job
            return copy.deepcopy(job)
    return None

def _series_render_update(job_id: str, **patch) -> dict | None:
    with _series_render_jobs_lock:
        job = _series_render_jobs.get(job_id)
        if not job:
            return None
        if (
            job.get("status") == "cancelling"
            and patch.get("status") not in {"cancelling", "cancelled"}
        ):
            return copy.deepcopy(job)
        job.update(copy.deepcopy(patch))
        job["updatedAt"] = time.time()
        snapshot = copy.deepcopy(job)
        _series_render_store(str(job["workspace"])).save(snapshot)
        if snapshot.get("productionId") and "status" in patch:
            from services.production_project_link import note_production_status
            note_production_status(_workspace_dir(snapshot["workspace"]), snapshot["productionId"], snapshot["status"])
        publisher = globals().get("_publish_series_task")
        if callable(publisher):
            try:
                publisher(snapshot, "series-render")
            except Exception as exc:
                print(f"[Task registry] Could not publish Series render {job_id}: {exc}")
        return snapshot

def _series_render_update_item(job_id: str, item_index: int, **patch) -> dict | None:
    with _series_render_jobs_lock:
        job = _series_render_jobs.get(job_id)
        if not job:
            return None
        items = job.get("items") if isinstance(job.get("items"), list) else []
        if item_index < 0 or item_index >= len(items):
            return None
        items[item_index].update(copy.deepcopy(patch))
        job["items"] = items
        job["current"] = sum(1 for item in items if item.get("status") == "completed")
        job["updatedAt"] = time.time()
        snapshot = copy.deepcopy(job)
        _series_render_store(str(job["workspace"])).save(snapshot)
        return snapshot

def _series_asset_local_path(workspace: str, asset: dict) -> str:
    from services.series_asset_path import series_asset_local_path

    return series_asset_local_path(
        workspace,
        asset,
        workspace_dir=_workspace_dir,
        remote_purpose="local H3 rendering",
        on_missing="raise",
    )

def _series_render_context(job: dict, item: dict) -> tuple[dict, dict, dict, dict]:
    from services.series_library import series_for_episode_snapshot
    from services.series_production import series_shot_method
    workspace = str(job["workspace"])
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = _series_project_or_404(library, str(job["seriesId"]))
        episode = series.get("episodesById", {}).get(str(job["episodeId"]))
        if not isinstance(episode, dict):
            raise ValueError("Series episode no longer exists")
        shot = next((
            value for value in episode.get("shots", [])
            if isinstance(value, dict) and value.get("id") == item.get("shotId")
        ), None)
        if not isinstance(shot, dict):
            raise ValueError("Series shot no longer exists")
        if series_shot_method(series, shot) != "generated_video":
            raise ValueError("This shot no longer permits model video generation")
        attempt = next((
            value for value in shot.get("attempts", [])
            if isinstance(value, dict) and value.get("id") == item.get("attemptId")
        ), None)
        if not isinstance(attempt, dict):
            raise ValueError("Series render attempt no longer exists")
        frozen_series = series_for_episode_snapshot(series, episode)
        return frozen_series, copy.deepcopy(episode), copy.deepcopy(shot), copy.deepcopy(attempt)

def _series_patch_attempt(
    job: dict,
    item: dict,
    patch: dict,
    *,
    output_assets: list[dict] | None = None,
) -> dict:
    from services.series_library import update_shot_render_attempt

    workspace = str(job["workspace"])
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = copy.deepcopy(_series_project_or_404(library, str(job["seriesId"])))
        episode = series.get("episodesById", {}).get(str(job["episodeId"]))
        if not isinstance(episode, dict):
            raise ValueError("Series episode no longer exists")
        shot_index = next((
            index for index, value in enumerate(episode.get("shots", []))
            if isinstance(value, dict) and value.get("id") == item.get("shotId")
        ), None)
        if shot_index is None:
            raise ValueError("Series shot no longer exists")
        episode["shots"][shot_index] = update_shot_render_attempt(
            episode["shots"][shot_index], str(item["attemptId"]), **patch,
        )
        for asset in output_assets or []:
            series.setdefault("assets", {})[asset["id"]] = copy.deepcopy(asset)
        now = _series_iso_now()
        episode["updatedAt"] = now
        series["updatedAt"] = now
        series["revision"] = int(series.get("revision") or 1) + 1
        library["seriesById"][series["id"]] = series
        stored = _write_series_workspace(workspace, library)
        return stored["seriesById"][series["id"]]["episodesById"][episode["id"]]["shots"][shot_index]

def _series_settle_episode_render_status(job: dict) -> str:
    """Leave an episode in a truthful terminal state after a render job settles."""
    workspace = str(job["workspace"])
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = copy.deepcopy(_series_project_or_404(library, str(job["seriesId"])))
        episode = series.get("episodesById", {}).get(str(job["episodeId"]))
        if not isinstance(episode, dict):
            raise ValueError("Series episode no longer exists")
        shots = [item for item in episode.get("shots", []) if isinstance(item, dict)]
        all_rendered = bool(shots) and all(
            any(
                isinstance(attempt, dict)
                and attempt.get("status") == "completed"
                and bool(attempt.get("outputAssetIds"))
                for attempt in shot.get("attempts", [])
            )
            for shot in shots
        )
        status = "completed" if all_rendered else "shot_plan"
        if episode.get("status") == status:
            return status
        now = _series_iso_now()
        episode["status"] = status
        episode["updatedAt"] = now
        series["updatedAt"] = now
        series["revision"] = int(series.get("revision") or 1) + 1
        library["seriesById"][series["id"]] = series
        _write_series_workspace(workspace, library)
        return status

def _run_series_render_job_inner(job_id: str) -> None:
    from services.series_render import build_h3_generation_params

    job = _load_series_render_job(job_id)
    if not job:
        return
    items = job.get("items") if isinstance(job.get("items"), list) else []
    any_failed = False
    try:
        for item_index, item in enumerate(items):
            latest = _load_series_render_job(job_id)
            if not latest or latest.get("status") in {"cancelling", "cancelled"}:
                return
            current_item = latest.get("items", [])[item_index]
            if current_item.get("status") == "completed":
                continue
            series, _episode, shot, attempt = _series_render_context(latest, current_item)
            submitted_at = _series_iso_now()
            _series_patch_attempt(
                latest, current_item,
                {"status": "running", "submittedAt": submitted_at, "error": ""},
            )
            _series_render_update_item(
                job_id, item_index, status="running", submittedAt=submitted_at, error=None,
            )
            _series_render_update(
                job_id, status="running", stage="rendering", activeShotId=current_item["shotId"],
                message=f"Rendering shot {item_index + 1}/{len(items)}…",
            )
            latest = _load_series_render_job(job_id) or latest
            if latest.get("status") in {"cancelling", "cancelled"}:
                completed_at = _series_iso_now()
                _series_patch_attempt(
                    latest,
                    current_item,
                    {
                        "status": "cancelled",
                        "completedAt": completed_at,
                        "error": "Cancelled by user",
                    },
                )
                _series_render_update_item(
                    job_id,
                    item_index,
                    status="cancelled",
                    completedAt=completed_at,
                    error="Cancelled by user",
                )
                return
            started = time.time()
            child_job_id = ""
            try:
                assets = series.get("assets") if isinstance(series.get("assets"), dict) else {}
                resolved = {}
                for reference in attempt.get("referenceManifest", {}).get("selected", []):
                    if not isinstance(reference, dict):
                        continue
                    asset_id = str(reference.get("assetId") or "")
                    asset = assets.get(asset_id)
                    if not isinstance(asset, dict):
                        raise ValueError(f"Routed Series asset no longer exists: {asset_id}")
                    resolved[asset_id] = _series_asset_local_path(str(latest["workspace"]), asset)
                params = build_h3_generation_params(series, shot, attempt, resolved)
                params["_director_pipeline_id"] = f"series:{job_id}"
                cancellation_check = _load_series_render_job(job_id) or latest
                if cancellation_check.get("status") in {"cancelling", "cancelled"}:
                    raise RuntimeError("Cancelled by user before model execution")
                request_hash = "sha256:" + hashlib.sha256(
                    json.dumps(params, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
                child_job_id = f"sr{uuid.uuid4().hex[:10]}"
                params["output_filename"] = _clip_name(current_item["shotId"], child_job_id)
                child = _new_generation_job(
                    params, str(latest["workspace"]), job_id=child_job_id,
                )
                _jobs[child_job_id] = child
                _series_render_update_item(
                    job_id, item_index, childJobId=child_job_id,
                    requestPayloadHash=request_hash,
                )
                cancellation_check = _load_series_render_job(job_id) or latest
                if cancellation_check.get("status") in {"cancelling", "cancelled"}:
                    _request_generation_cancel(child_job_id)
                    raise RuntimeError("Cancelled by user before model execution")
                _series_patch_attempt(
                    latest, current_item,
                    {"providerTaskId": child_job_id, "requestPayloadHash": request_hash},
                )
                _run_generation(child_job_id)
                child_result = snapshot_job(_jobs[child_job_id])
                if child_result.get("status") != "completed" or not child_result.get("output_files"):
                    raise RuntimeError(child_result.get("error") or "H3 returned no video output")
                completed_at = _series_iso_now()
                elapsed_ms = max(0, round((time.time() - started) * 1000))
                output_asset_ids = []
                output_assets = []
                for output_index, filename in enumerate(child_result["output_files"]):
                    basename = os.path.basename(str(filename))
                    asset_id = f"asset_{attempt['id']}_{output_index + 1}"
                    output_asset_ids.append(asset_id)
                    output_assets.append({
                        "id": asset_id, "workspaceId": latest["workspace"], "kind": "video",
                        "uri": f"outputs/{basename}", "ownerType": "attempt", "ownerId": attempt["id"],
                        "isDerivedThumbnail": False,
                        "metadata": {
                            "seriesId": latest["seriesId"], "episodeId": latest["episodeId"],
                            "shotId": current_item["shotId"], "attemptId": attempt["id"],
                            "prompt": attempt.get("prompt"), "negativePrompt": attempt.get("negativePrompt"),
                            "model": params["model_type"], "seed": params["seed"],
                            "settings": attempt.get("settings"),
                            "referenceManifest": attempt.get("referenceManifest"),
                            "createdAt": attempt.get("createdAt"), "submittedAt": submitted_at,
                            "completedAt": completed_at, "elapsedMs": elapsed_ms,
                            "generationJobId": child_job_id, "requestPayloadHash": request_hash,
                            "taskId": child_result.get("task_id"),
                            "rootTaskId": (
                                child_result.get("root_task_id")
                                or child_result.get("task_id")
                            ),
                        },
                    })
                _series_patch_attempt(
                    latest, current_item,
                    {
                        "status": "completed", "completedAt": completed_at,
                        "elapsedMs": elapsed_ms, "outputAssetIds": output_asset_ids,
                        "providerTaskId": child_job_id, "requestPayloadHash": request_hash, "error": "",
                    },
                    output_assets=output_assets,
                )
                _series_render_update_item(
                    job_id, item_index, status="completed", completedAt=completed_at,
                    elapsedMs=elapsed_ms, outputAssetIds=output_asset_ids, error=None,
                )
            except Exception as exc:
                any_failed = True
                error = str(exc)
                completed_at = _series_iso_now()
                elapsed_ms = max(0, round((time.time() - started) * 1000))
                current = _load_series_render_job(job_id)
                if current and current.get("status") in {"cancelling", "cancelled"}:
                    try:
                        _series_patch_attempt(
                            current, current["items"][item_index],
                            {"status": "cancelled", "completedAt": completed_at, "elapsedMs": elapsed_ms, "error": "Cancelled"},
                        )
                    except Exception:
                        pass
                    return
                try:
                    _series_patch_attempt(
                        current or latest, (current or latest)["items"][item_index],
                        {"status": "failed", "completedAt": completed_at, "elapsedMs": elapsed_ms, "error": error},
                    )
                except Exception as patch_exc:
                    error = f"{error}; could not persist attempt state: {patch_exc}"
                _series_render_update_item(
                    job_id, item_index, status="failed", completedAt=completed_at,
                    elapsedMs=elapsed_ms, error=error, childJobId=child_job_id,
                )
        latest = _load_series_render_job(job_id) or job
        if latest.get("status") in {"cancelling", "cancelled"}:
            return
        finished = time.time()
        failures = [item for item in latest.get("items", []) if item.get("status") == "failed"]
        _series_render_update(
            job_id,
            status="failed" if failures or any_failed else "completed",
            stage="completed", activeShotId=None, finishedAt=finished,
            error=(f"{len(failures)} shot(s) failed; completed attempts were preserved." if failures else None),
            message=(
                "Render finished with failures. Retry only failed shots when ready."
                if failures else "All requested Series shots completed."
            ),
        )
        _series_settle_episode_render_status(latest)
    except Exception as exc:
        _series_render_update(
            job_id, status="failed", error=str(exc), finishedAt=time.time(),
            message="Series render stopped. Completed attempts were preserved.",
        )
        try:
            _series_settle_episode_render_status(job)
        except Exception:
            pass

def _run_series_render_job(job_id: str) -> None:
    with _series_render_jobs_lock:
        if job_id in _series_render_active_jobs:
            return
        _series_render_active_jobs.add(job_id)
    try:
        _run_series_render_job_inner(job_id)
    finally:
        with _series_render_jobs_lock:
            _series_render_active_jobs.discard(job_id)
        settling = _load_series_render_job(job_id) or {}
        if settling.get("status") == "cancelling":
            settled_items = copy.deepcopy(settling.get("items") or [])
            for item in settled_items:
                if item.get("status") in {"queued", "running", "cancelling"}:
                    item.update({
                        "status": "cancelled",
                        "completedAt": item.get("completedAt") or _series_iso_now(),
                        "error": item.get("error") or "Cancelled by user",
                        "updatedAt": time.time(),
                    })
            _series_render_update(
                job_id,
                items=settled_items,
                status="cancelled",
                stage="cancelled",
                activeShotId=None,
                finishedAt=time.time(),
                message=(
                    "Series render cancelled after the active model thread "
                    "reached a safe boundary. Completed attempts remain available."
                ),
            )
        # Series deliberately marks child generations as one Director-like
        # group so H3 stays warm between adjacent shots. Once the parent job
        # settles, restore the ordinary idle-release policy; otherwise the
        # isolated ConvRot process can retain roughly 50 GB of host RAM forever.
        finished = _load_series_render_job(job_id) or {}
        model_type = str(finished.get("model") or "")
        if _is_legacy_h3_model(model_type):
            _release_legacy_h3_when_queue_allows(job_id)
        elif _is_minimax_h3_model(model_type):
            _release_h3_when_queue_allows(job_id)

def _series_render_candidates(episode: dict, body: dict) -> list[dict]:
    shots = [item for item in episode.get("shots", []) if isinstance(item, dict)]
    mode = str(body.get("mode") or "missing")
    selected_ids = {str(item) for item in body.get("shotIds", []) if isinstance(item, str)}
    if mode == "selected":
        shots = [item for item in shots if item.get("id") in selected_ids]
        if not shots:
            raise ValueError("Select at least one Series shot")
        # Append a new alternative in the same slot while retaining the older
        # approved cut until the user explicitly approves the replacement.
        return shots
    elif mode == "failed":
        shots = [
            item for item in shots
            if item.get("attempts") and item["attempts"][-1].get("status") == "failed"
        ]
    elif mode == "all":
        pass
    elif mode == "missing":
        shots = [item for item in shots if not item.get("approvedAttemptId")]
    else:
        raise ValueError("Render mode must be selected, failed, missing, or all")
    # Bulk generation never spends compute on approved shots. Only explicit
    # per-slot regeneration may append an alternative attempt.
    return [item for item in shots if not item.get("approvedAttemptId")]

def _series_render_job_for_task(workspace: str, task_id: str) -> dict | None:
    """The in-memory render job whose canonical task id is ``task_id``."""
    with _series_render_jobs_lock:
        jobs = [copy.deepcopy(job) for job in _series_render_jobs.values()]
    wanted = str(task_id or "")
    for job in jobs:
        if str(job.get("workspace") or "default") != workspace:
            continue
        job_id = str(job.get("jobId") or "")
        if str(job.get("taskId") or "") == wanted or f"task-series-render-{job_id}" == wanted:
            return job
    return None


class SeriesRenderTaskAdapter:
    """What Series render offers the canonical task registry.

    The full server still publishes and cancels from its own aggregator.
    Registering this adapter is the hook; pointing the aggregator at it is later.
    """

    def list(self, workspace: str) -> list[dict]:
        if not callable(_publish_series_task):
            return []
        with _series_render_jobs_lock:
            jobs = [
                copy.deepcopy(job)
                for job in _series_render_jobs.values()
                if str(job.get("workspace") or "default") == workspace
            ]
        records = []
        for job in jobs:
            record = _publish_series_task(job, "series-render")
            if isinstance(record, dict):
                records.append(record)
        return records

    def snapshot(self, workspace: str, task_id: str) -> dict | None:
        job = _series_render_job_for_task(workspace, task_id)
        if job is None or not callable(_publish_series_task):
            return None
        record = _publish_series_task(job, "series-render")
        return record if isinstance(record, dict) else None

    def cancel(self, workspace: str, task_id: str) -> dict | None:
        job = _series_render_job_for_task(workspace, task_id)
        if job is None or not callable(_cancel_series_render_job):
            return None
        return _cancel_series_render_job(str(job["jobId"]))


series_render_task_adapter = SeriesRenderTaskAdapter()
