"""MiniMax Music job store shared by the full server and the core server.

Each server binds its workspace, services map and Activity publisher once.
The HTTP router reads this store. It does not keep a second copy of the jobs.
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
import traceback
import uuid
from types import SimpleNamespace
from typing import Any, Callable

from services import resource_scheduler


_minimax_music_jobs: dict[str, dict] = {}
_minimax_music_jobs_lock = threading.RLock()
_MINIMAX_MUSIC_TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def _minimax_music_checkpoint_dir(workspace: str | None = None) -> str:
    path = os.path.join(_workspace_dir(workspace), ".minimax-music-jobs")
    os.makedirs(path, exist_ok=True)
    return path


def _minimax_music_checkpoint_path(job_id: str, workspace: str) -> str | None:
    if not re.fullmatch(r"minimax-music-[a-f0-9]{12}", str(job_id or "")):
        return None
    return os.path.join(_minimax_music_checkpoint_dir(workspace), f"{job_id}.json")


def _persist_minimax_music_job(job: dict) -> None:
    path = _minimax_music_checkpoint_path(
        str(job.get("jobId") or ""), str(job.get("workspace") or "default"),
    )
    if not path:
        return
    temporary = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        try:
            if os.path.isfile(temporary):
                os.remove(temporary)
        except OSError:
            pass


def _public_minimax_music_job(job: dict) -> dict:
    return {
        key: copy.deepcopy(value)
        for key, value in job.items()
        if key not in {"request", "_cancel_requested"}
    }


def _publish_minimax_music_job(job: dict) -> None:
    publisher = globals().get("_publish_generic_legacy_task")
    if not callable(publisher):
        return
    try:
        publisher(copy.deepcopy(job), "minimax-music")
        for child in job.get("children") or []:
            if isinstance(child, dict):
                publisher(copy.deepcopy(child), "minimax-music-candidate")
    except Exception as exc:
        print(f"[Task registry] Could not publish MiniMax Music {job.get('jobId')}: {exc}")


def _minimax_music_job_update(job_id: str, **patch) -> dict | None:
    with _minimax_music_jobs_lock:
        job = _minimax_music_jobs.get(job_id)
        if job is None:
            return None
        requested_status = str(patch.get("status") or "")
        if (
            job.get("_cancel_requested")
            and requested_status in {
                "created", "queued", "waiting_resource", "running",
            }
        ):
            return copy.deepcopy(job)
        if (
            str(job.get("status") or "") in _MINIMAX_MUSIC_TERMINAL
            and requested_status
            and requested_status not in _MINIMAX_MUSIC_TERMINAL
        ):
            return copy.deepcopy(job)
        job.update(patch)
        job["updatedAt"] = time.time()
        snapshot = copy.deepcopy(job)
        _persist_minimax_music_job(snapshot)
    _publish_minimax_music_job(snapshot)
    return snapshot


def _minimax_music_child_update(job_id: str, child_index: int, **patch) -> dict | None:
    with _minimax_music_jobs_lock:
        job = _minimax_music_jobs.get(job_id)
        children = job.get("children") if isinstance(job, dict) else None
        if not isinstance(children, list) or not 0 <= child_index < len(children):
            return None
        child = children[child_index]
        requested_status = str(patch.get("status") or "")
        if (
            job.get("_cancel_requested")
            and requested_status in {
                "created", "queued", "waiting_resource", "running",
            }
        ):
            return copy.deepcopy(job)
        if (
            str(child.get("status") or "") in _MINIMAX_MUSIC_TERMINAL
            and requested_status
            and requested_status not in _MINIMAX_MUSIC_TERMINAL
        ):
            return copy.deepcopy(job)
        child.update(patch)
        child["updatedAt"] = time.time()
        job["updatedAt"] = child["updatedAt"]
        snapshot = copy.deepcopy(job)
        _persist_minimax_music_job(snapshot)
    _publish_minimax_music_job(snapshot)
    return snapshot


def _minimax_music_claim_candidate(
    job_id: str,
    child_index: int,
    lane_key: str,
) -> dict | None:
    """Atomically commit one candidate before entering the provider call."""
    with _minimax_music_jobs_lock:
        job = _minimax_music_jobs.get(job_id)
        children = job.get("children") if isinstance(job, dict) else None
        if (
            not isinstance(children, list)
            or not 0 <= child_index < len(children)
            or job.get("_cancel_requested")
            or str(job.get("status") or "") in _MINIMAX_MUSIC_TERMINAL
        ):
            return None
        now = time.time()
        child = children[child_index]
        child.update(
            status="running",
            phase="requesting",
            message=(
                f"MiniMax is generating candidate {child_index + 1}/"
                f"{len(children)}…"
            ),
            startedAt=child.get("startedAt") or now,
            acquired_resources=[lane_key],
            updatedAt=now,
        )
        job.update(
            status="running",
            phase="requesting",
            message=(
                f"MiniMax is generating candidate {child_index + 1}/"
                f"{len(children)}…"
            ),
            startedAt=job.get("startedAt") or now,
            acquired_resources=[],
            updatedAt=now,
        )
        snapshot = copy.deepcopy(job)
        _persist_minimax_music_job(snapshot)
    _publish_minimax_music_job(snapshot)
    return snapshot


def _load_minimax_music_job(job_id: str) -> dict | None:
    with _minimax_music_jobs_lock:
        cached = _minimax_music_jobs.get(job_id)
        if cached is not None:
            return copy.deepcopy(cached)
    for item in _list_workspaces():
        path = _minimax_music_checkpoint_path(job_id, item["name"])
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                job = json.load(handle)
            if not isinstance(job, dict):
                continue
            if str(job.get("status") or "") not in _MINIMAX_MUSIC_TERMINAL:
                now = time.time()
                job.update(
                    status="interrupted",
                    phase="interrupted",
                    message=(
                        "HocusPocus Lab restarted while MiniMax Music was active. "
                        "Existing outputs were preserved; start a new request only after checking them."
                    ),
                    error="Provider completion is unknown after restart",
                    finishedAt=now,
                    updatedAt=now,
                )
                for child in job.get("children") or []:
                    if str(child.get("status") or "") not in _MINIMAX_MUSIC_TERMINAL:
                        child.update(
                            status="interrupted", phase="interrupted",
                            message="Provider completion is unknown after restart",
                            finishedAt=now, updatedAt=now,
                        )
                _persist_minimax_music_job(job)
            with _minimax_music_jobs_lock:
                _minimax_music_jobs[job_id] = job
            _publish_minimax_music_job(job)
            return copy.deepcopy(job)
        except Exception as exc:
            print(f"[MiniMax Music] Could not restore {job_id}: {exc}")
    return None


def _finish_unstarted_music_children(job_id: str, start_index: int, message: str) -> None:
    with _minimax_music_jobs_lock:
        job = _minimax_music_jobs.get(job_id)
        children = job.get("children") if isinstance(job, dict) else []
        indices = [
            index for index in range(start_index, len(children))
            if str(children[index].get("status") or "") not in _MINIMAX_MUSIC_TERMINAL
        ]
    for index in indices:
        _minimax_music_child_update(
            job_id, index, status="cancelled", phase="cancelled",
            message=message, finishedAt=time.time(), acquired_resources=[],
        )


def _finalize_reserved_music_attempt(
    workspace, generation_id, filename, cancelled, duration_seconds=None,
) -> None:
    token = str(generation_id or "").strip()
    audio = str(filename or "").strip()
    if not token or not audio:
        return
    try:
        from services.music_finalization import finalize_reserved_music
        finalize_reserved_music(
            workspace_dir=_workspace_dir(workspace),
            generation_id=token,
            audio_filename=audio,
            cancel_check=cancelled,
            reported_duration_seconds=duration_seconds,
        )
    except Exception:
        traceback.print_exc()


def _run_minimax_music_job(job_id: str) -> None:
    from services import minimax_music_service

    with _minimax_music_jobs_lock:
        initial = copy.deepcopy(_minimax_music_jobs.get(job_id) or {})
    if not initial:
        return
    request_body = initial.get("request") if isinstance(initial.get("request"), dict) else {}
    workspace = str(initial.get("workspace") or "default")
    count = max(1, min(3, int(initial.get("total") or 1)))
    lane = resource_scheduler.remote_lane("minimax", minimax_music_service.API_URL)

    def cancelled() -> bool:
        with _minimax_music_jobs_lock:
            return bool(
                (_minimax_music_jobs.get(job_id) or {}).get("_cancel_requested")
            )

    for index in range(count):
        if cancelled():
            _finish_unstarted_music_children(
                job_id, index, "Cancelled before this candidate started",
            )
            _minimax_music_job_update(
                job_id, status="cancelled", phase="cancelled",
                message="MiniMax Music generation cancelled",
                finishedAt=time.time(), acquired_resources=[],
            )
            return
        child = initial["children"][index]
        child_task_id = str(child["taskId"])
        _minimax_music_child_update(
            job_id, index, status="waiting_resource", phase="waiting_resource",
            message=f"Waiting for MiniMax API · candidate {index + 1}/{count}",
            acquired_resources=[],
        )
        _minimax_music_job_update(
            job_id, status="waiting_resource", phase="waiting_resource",
            message=f"Waiting for MiniMax API · candidate {index + 1}/{count}",
            acquired_resources=[],
        )
        try:
            with resource_scheduler.coordinator.acquire(
                lane,
                task_id=child_task_id,
                description=f"MiniMax Music candidate {index + 1}/{count}",
                cancelled=cancelled,
            ):
                claimed = _minimax_music_claim_candidate(
                    job_id, index, lane.key,
                )
                if claimed is None:
                    raise resource_scheduler.ResourceAcquireCancelled(
                        f"MiniMax Music job {job_id} was cancelled"
                    )
                result = minimax_music_service.generate_candidates(
                    api_key=str(
                        __import__("services.provider_profile", fromlist=["resolve_minimax_key"]).resolve_minimax_key(
                            wgp.server_config.get("services") or {}, "music",
                        )
                    ),
                    prompt=str(request_body.get("prompt") or ""),
                    lyrics=str(request_body.get("lyrics") or ""),
                    count=1,
                    output_dir=_workspace_dir(workspace),
                    instrumental=bool(request_body.get("instrumental")),
                    model=str(request_body.get("model") or ""),
                    reference_audio_path=request_body.get("reference_audio_path"),
                    task_id=child_task_id,
                    root_task_id=str(initial.get("rootTaskId") or initial.get("taskId")),
                    cancelled=cancelled,
                )[0]
            candidate = {
                **result,
                "source": f"/api/v1/file/{result['filename']}",
                "taskId": result.get("task_id") or child_task_id,
                "rootTaskId": (
                    result.get("root_task_id")
                    or initial.get("rootTaskId")
                    or initial.get("taskId")
                ),
            }
            with _minimax_music_jobs_lock:
                live = _minimax_music_jobs.get(job_id) or {}
                results = list(live.get("candidates") or [])
                outputs = list(live.get("output_files") or [])
            results.append(candidate)
            if result["filename"] not in outputs:
                outputs.append(result["filename"])
            try:
                _finalize_reserved_music_attempt(
                    workspace,
                    initial.get("generationId"),
                    result.get("filename"),
                    cancelled,
                    result.get("duration_seconds"),
                )
            except Exception:
                traceback.print_exc()
            _minimax_music_child_update(
                job_id, index, status="completed", phase="completed",
                message=f"Candidate {index + 1}/{count} generated",
                current=1, total=1, progress=100,
                output_files=[result["filename"]], result=candidate,
                acquired_resources=[], finishedAt=time.time(),
            )
            _minimax_music_job_update(
                job_id, current=index + 1, progress=((index + 1) / count) * 100,
                candidates=results, output_files=outputs,
            )
            if cancelled():
                _finish_unstarted_music_children(
                    job_id, index + 1,
                    "Cancelled before this candidate started",
                )
                _minimax_music_job_update(
                    job_id, status="cancelled", phase="cancelled",
                    message=(
                        "Cancellation completed at a safe provider boundary; "
                        f"{len(results)} generated candidate(s) were preserved"
                    ),
                    result={"candidates": results}, finishedAt=time.time(),
                    acquired_resources=[],
                )
                return
        except resource_scheduler.ResourceAcquireCancelled:
            _finish_unstarted_music_children(
                job_id, index, "Cancelled before this candidate started",
            )
            _minimax_music_job_update(
                job_id, status="cancelled", phase="cancelled",
                message="MiniMax Music generation cancelled",
                finishedAt=time.time(), acquired_resources=[],
            )
            return
        except minimax_music_service.MiniMaxMusicError as exc:
            _minimax_music_child_update(
                job_id, index, status="failed", phase="failed",
                message=str(exc), error=str(exc), statusCode=exc.status_code,
                acquired_resources=[], finishedAt=time.time(),
            )
            _finish_unstarted_music_children(
                job_id, index + 1, "Not started because an earlier candidate failed",
            )
            _minimax_music_job_update(
                job_id, status="failed", phase="failed", message=str(exc),
                error=str(exc), statusCode=exc.status_code,
                finishedAt=time.time(), acquired_resources=[],
            )
            return
        except Exception as exc:
            traceback.print_exc()
            _minimax_music_child_update(
                job_id, index, status="failed", phase="failed",
                message=f"MiniMax Music failed: {exc}", error=str(exc),
                acquired_resources=[], finishedAt=time.time(),
            )
            _finish_unstarted_music_children(
                job_id, index + 1, "Not started because an earlier candidate failed",
            )
            _minimax_music_job_update(
                job_id, status="failed", phase="failed",
                message=f"MiniMax Music failed: {exc}", error=str(exc),
                finishedAt=time.time(), acquired_resources=[],
            )
            return

    with _minimax_music_jobs_lock:
        results = list((_minimax_music_jobs.get(job_id) or {}).get("candidates") or [])
    _minimax_music_job_update(
        job_id, status="completed", phase="completed",
        message=f"Generated {len(results)} MiniMax Music candidate(s)",
        current=count, total=count, progress=100,
        result={"candidates": results}, finishedAt=time.time(),
        acquired_resources=[],
    )


def bind_story_music_jobs(
    *,
    workspace_dir: Callable[..., str],
    list_workspaces: Callable[[], list],
    wgp_module: Any,
    publish_legacy_task: Callable[..., Any] | None = None,
):
    """Install one server's workspace, services map and Activity publisher."""
    global _workspace_dir, _list_workspaces, wgp, _publish_generic_legacy_task
    _workspace_dir = workspace_dir
    _list_workspaces = list_workspaces
    wgp = wgp_module
    # The moved body reads this name; launch binds its generic publisher and core its own.
    _publish_generic_legacy_task = publish_legacy_task
    return SimpleNamespace(
        workspace_dir=workspace_dir,
        load_minimax_music_job=_load_minimax_music_job,
        persist_minimax_music_job=_persist_minimax_music_job,
        publish_minimax_music_job=_publish_minimax_music_job,
        public_minimax_music_job=_public_minimax_music_job,
        run_minimax_music_job=_run_minimax_music_job,
        minimax_music_jobs=_minimax_music_jobs,
        minimax_music_jobs_lock=_minimax_music_jobs_lock,
        minimax_music_terminal=_MINIMAX_MUSIC_TERMINAL,
        finish_unstarted_music_children=_finish_unstarted_music_children,
        minimax_music_job_update=_minimax_music_job_update,
    )
