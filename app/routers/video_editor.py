"""Video Editor HTTP surface extracted from the launch runtime.

The launcher injects workspace and path primitives so this module never
imports WanGP, Gradio, model weights, or ``_launch_runtime``.
"""

from __future__ import annotations

import copy
import os
import re
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from services import resource_scheduler
from services.asset_manifest import publish_generation_sidecar
from services.media_refs import parse_media_ref
from services.media_thumbnails import ensure_media_thumbnail
from services.video_editor import (
    build_source_provenance_manifest,
    extract_frame,
    normalise_time_card_text,
    probe_audio,
    probe_media,
    render_project,
)


_VIDEO_EDITOR_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_VIDEO_EDITOR_FFMPEG_LANE = resource_scheduler.cpu_lane("ffmpeg")
_VIDEO_EDITOR_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}
_VIDEO_EDITOR_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
SUPPORTED_TRANSITIONS = frozenset({
    "none",
    "crossfade",
    "fade-black",
    "wipe-left",
    "slide-left",
    "slide-right",
    "circle-open",
    "dissolve",
    "pixelize",
    "blur",
    "zoom-in",
    "later-clock",
    "later-tropical",
    "later-cinematic",
})
CLIP_SIDECAR_KEYS = frozenset({
    "name",
    "source",
    "trim_start",
    "trim_end",
    "volume",
    "muted",
    "fit",
    "transition",
    "transition_duration",
    "transition_text",
    "transition_text_size",
})
SOUNDTRACK_SIDECAR_KEYS = frozenset({
    "name", "source", "trim_start", "trim_end", "volume", "loop",
})
TASK_ID_PATTERN = re.compile(r"task-[A-Za-z0-9_-]{1,180}")

_video_editor_jobs: dict[str, dict] = {}
_video_editor_jobs_lock = threading.RLock()


class _Runtime:
    workspace_dir: Callable[..., str] | None = None
    get_active_workspace: Callable[[], str] | None = None
    resolve_input_path: Callable[..., str | None] | None = None
    publish_legacy_task: Callable[..., Any] | None = None
    thumbnail_cache_dir: str = ""


_runtime = _Runtime()


def _bind_video_editor_runtime(
    *,
    workspace_dir: Callable[..., str],
    get_active_workspace: Callable[[], str],
    resolve_input_path: Callable[..., str | None],
    publish_legacy_task: Callable[..., Any] | None,
    thumbnail_cache_dir: str,
) -> None:
    _runtime.workspace_dir = workspace_dir
    _runtime.get_active_workspace = get_active_workspace
    _runtime.resolve_input_path = resolve_input_path
    _runtime.publish_legacy_task = publish_legacy_task
    _runtime.thumbnail_cache_dir = thumbnail_cache_dir


def reset_video_editor_jobs() -> None:
    with _video_editor_jobs_lock:
        _video_editor_jobs.clear()


def list_video_editor_jobs() -> list[dict]:
    """Snapshot editor jobs for Activity's canonical sync."""
    with _video_editor_jobs_lock:
        return [copy.deepcopy(job) for job in _video_editor_jobs.values()]


def _public_video_editor_job(job: dict) -> dict:
    """Return a stable API snapshot without worker-only coordination flags."""
    return {
        key: copy.deepcopy(value)
        for key, value in job.items()
        if not key.startswith("_")
    }


def _publish_video_editor_job(snapshot: dict) -> dict | None:
    """Publish every editor mutation immediately to task SSE."""
    publisher = _runtime.publish_legacy_task
    if not callable(publisher):
        return None
    return publisher(snapshot, "video-editor")


def _video_editor_job_snapshot(job_id: str) -> dict | None:
    with _video_editor_jobs_lock:
        job = _video_editor_jobs.get(job_id)
        return copy.deepcopy(job) if job is not None else None


def _cancelled_status_patch(job: dict) -> dict[str, Any]:
    return {
        "status": "cancelled",
        "phase": "cancelled",
        "message": "Cancelled at the FFmpeg safe boundary",
        "error": None,
        "result": None,
        "filename": None,
        "url": None,
        "output_files": [],
        "acquired_resources": [],
        "cancel_mode": job.get("cancel_mode") or "deferred",
        "safe_boundary": job.get("safe_boundary") or "after_current_ffmpeg_render",
        "finished_at": time.time(),
    }


def _cancelling_status_patch(owns_lane: bool) -> dict[str, Any]:
    return {
        "status": "cancelling",
        "phase": "cancelling",
        "message": (
            "Cancellation deferred to a safe boundary; "
            "waiting for FFmpeg to finish…"
            if owns_lane else
            "FFmpeg safe boundary reached; cleaning up cancellation…"
        ),
        "cancel_mode": "deferred",
        "safe_boundary": "after_current_ffmpeg_render",
    }


def _absorb_cancel_into_changes(job: dict, changes: dict[str, Any]) -> dict[str, Any]:
    """Make cancellation terminally absorbing for in-flight mutations."""
    if not job.get("_cancel_requested"):
        return changes
    requested_status = str(changes.get("status") or "")
    if requested_status in {"completed", "failed"}:
        changes.update(_cancelled_status_patch(job))
        return changes
    if requested_status in {"cancelled", "cancelling"}:
        return changes
    owns_lane = bool(changes.get("acquired_resources", job.get("acquired_resources") or []))
    changes.update(_cancelling_status_patch(owns_lane))
    return changes


def _video_editor_job_update(job_id: str, **changes) -> dict:
    """Atomically mutate a job while making cancellation terminally absorbing."""
    should_publish = False
    with _video_editor_jobs_lock:
        job = _video_editor_jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if str(job.get("status") or "") in _VIDEO_EDITOR_TERMINAL:
            snapshot = copy.deepcopy(job)
        else:
            job.update(_absorb_cancel_into_changes(job, changes))
            job["updated_at"] = time.time()
            snapshot = copy.deepcopy(job)
            should_publish = True
        if should_publish:
            _publish_video_editor_job(snapshot)
    return snapshot


def _register_video_editor_job(job: dict) -> dict:
    """Reserve legacy and canonical identities before starting any worker."""
    job_id = str(job["job_id"])
    with _video_editor_jobs_lock:
        _video_editor_jobs[job_id] = job
        snapshot = copy.deepcopy(job)
        try:
            _publish_video_editor_job(snapshot)
        except Exception:
            if _video_editor_jobs.get(job_id) is job:
                _video_editor_jobs.pop(job_id, None)
            raise
    return snapshot


def _video_editor_cancel_requested(job_id: str) -> bool:
    with _video_editor_jobs_lock:
        job = _video_editor_jobs.get(job_id)
        return job is None or bool(job.get("_cancel_requested"))


def _remove_video_editor_output_bundle(output_path: str) -> None:
    """Remove an incomplete/cancelled MP4 and its metadata sidecar."""
    for candidate in (output_path, os.path.splitext(output_path)[0] + ".meta.json"):
        try:
            if os.path.isfile(candidate):
                os.remove(candidate)
        except OSError:
            pass


def _finish_video_editor_cancelled(
    job_id: str,
    output_path: str,
    *,
    message: str = "Cancelled before FFmpeg started",
    cancel_mode: str = "immediate",
    safe_boundary: str = "before_ffmpeg",
) -> dict:
    """Finish cancellation only after the worker no longer owns its lane."""
    _remove_video_editor_output_bundle(output_path)
    changes = {
        "status": "cancelled",
        "phase": "cancelled",
        "message": message,
        "cancel_mode": cancel_mode,
        "safe_boundary": safe_boundary,
        "error": None,
        "result": None,
        "filename": None,
        "url": None,
        "output_files": [],
        "acquired_resources": [],
        "finished_at": time.time(),
        "_worker_active": False,
    }
    if cancel_mode == "immediate":
        changes["progress"] = 0
        changes["current"] = 0
    return _video_editor_job_update(job_id, **changes)


def _resolve_video_editor_source(source: str, workspace: str | None = None) -> str:
    """Resolve an editor reference without allowing access outside Maestro."""
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Video source is missing")
    path, workspace = parse_media_ref(source, workspace)
    resolved = _runtime.resolve_input_path(path, workspace)
    if not resolved or not os.path.isfile(resolved):
        raise ValueError(f"Video source could not be found: {os.path.basename(path) or path}")
    suffix = os.path.splitext(resolved)[1].lower()
    if suffix not in _VIDEO_EDITOR_EXTENSIONS:
        raise ValueError(f"Unsupported video format: {suffix or 'unknown'}")
    return resolved


def _resolve_video_editor_audio_source(source: str, workspace: str | None = None) -> str:
    """Resolve a soundtrack reference using the same workspace boundary."""
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Audio source is missing")
    path, workspace = parse_media_ref(source, workspace)
    resolved = _runtime.resolve_input_path(path, workspace)
    if not resolved or not os.path.isfile(resolved):
        raise ValueError(f"Audio source could not be found: {os.path.basename(path) or path}")
    suffix = os.path.splitext(resolved)[1].lower()
    if suffix not in _VIDEO_EDITOR_AUDIO_EXTENSIONS:
        raise ValueError(f"Unsupported audio format: {suffix or 'unknown'}")
    return resolved


def _raise_http(exc: Exception, *, failed: str):
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail=f"{failed}: {exc}") from exc


def _probe_video_editor_source(body: dict) -> dict:
    try:
        resolved = _resolve_video_editor_source(body.get("source", ""), body.get("workspace"))
        return probe_media(resolved)
    except Exception as exc:
        _raise_http(exc, failed="Could not inspect video")
        raise


def _probe_video_editor_audio_source(body: dict) -> dict:
    try:
        resolved = _resolve_video_editor_audio_source(
            body.get("source", ""), body.get("workspace"),
        )
        return probe_audio(resolved)
    except Exception as exc:
        _raise_http(exc, failed="Could not inspect audio")
        raise


def _serve_video_editor_thumbnail(source: str) -> FileResponse:
    try:
        resolved = _resolve_video_editor_source(source)
        thumbnail = ensure_media_thumbnail(
            resolved, _runtime.thumbnail_cache_dir, is_video=True,
        )
    except Exception as exc:
        _raise_http(exc, failed="Could not create thumbnail")
        raise
    return FileResponse(
        thumbnail,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


def _write_video_editor_screenshot_sidecar(output_path, sidecar, workspace_id):
    publish_generation_sidecar(
        output_path, sidecar, workspace_id=workspace_id, tool="video-editor-screenshot",
    )


def _write_video_editor_export_sidecar(output_path, sidecar, workspace_id):
    publish_generation_sidecar(
        output_path, sidecar, workspace_id=workspace_id, tool="video-editor",
    )


def _safe_media_stem(value: Any, fallback: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or fallback)).strip("_")
    return safe[:60] or fallback


def _unique_workspace_file(out_dir: str, stem: str, ext: str) -> tuple[str, str]:
    output_name = f"{stem}{ext}"
    output_path = os.path.join(out_dir, output_name)
    suffix = 2
    while os.path.exists(output_path):
        output_name = f"{stem}_{suffix}{ext}"
        output_path = os.path.join(out_dir, output_name)
        suffix += 1
    return output_name, output_path


def _capture_video_editor_frame(body: dict) -> dict:
    try:
        resolved = _resolve_video_editor_source(body.get("source", ""), body.get("workspace"))
        requested_time = float(body.get("time") or 0)
    except HTTPException:
        raise
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    safe_name = _safe_media_stem(body.get("name") or "video_frame", "video_frame")
    timestamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
    out_dir = _runtime.workspace_dir()
    os.makedirs(out_dir, exist_ok=True)
    output_name, output_path = _unique_workspace_file(
        out_dir, f"{timestamp}_{safe_name}_frame", ".png",
    )
    try:
        result = extract_frame(resolved, output_path, requested_time)
        sidecar = {
            "params": {
                "video_editor_screenshot": {
                    "version": 1,
                    "source": str(body.get("source") or ""),
                    "source_name": os.path.basename(resolved),
                    "time": result["time"],
                    "width": result["width"],
                    "height": result["height"],
                },
                "source": "video_editor_screenshot",
            },
            "generation_mode": "image",
            "created_at": time.time(),
        }
        _write_video_editor_screenshot_sidecar(output_path, sidecar, body.get("workspace"))
        return {"filename": output_name, "url": f"/api/v1/file/{output_name}", **result}
    except Exception as exc:
        try:
            if os.path.isfile(output_path):
                os.remove(output_path)
        except OSError:
            pass
        raise HTTPException(
            status_code=500, detail=f"Could not capture video frame: {exc}",
        ) from exc


def _video_editor_task_identity(body: dict, job_id: str) -> tuple[str, str, str | None]:
    """Accept an optional caller hierarchy without allowing malformed task IDs."""
    supplied_task_id = str(body.get("task_id") or "").strip()
    supplied_root_id = str(body.get("root_task_id") or "").strip()
    supplied_parent_id = str(body.get("parent_task_id") or "").strip()
    for label, value in (
        ("task_id", supplied_task_id),
        ("root_task_id", supplied_root_id),
        ("parent_task_id", supplied_parent_id),
    ):
        if value and not TASK_ID_PATTERN.fullmatch(value):
            raise HTTPException(status_code=400, detail=f"Invalid {label}")
    task_id = supplied_task_id or f"task-video-editor-{job_id}"
    root_task_id = supplied_root_id or supplied_parent_id or task_id
    return task_id, root_task_id, supplied_parent_id or None


def _parse_export_geometry(body: dict) -> tuple[int, int, int]:
    try:
        width = int(body.get("width") or 1280)
        height = int(body.get("height") or 720)
        fps = int(body.get("fps") or 30)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid export settings") from exc
    odd_or_tiny = width < 240 or height < 240 or width % 2 or height % 2
    if odd_or_tiny or width > 3840 or height > 3840:
        raise HTTPException(status_code=400, detail="Invalid output resolution")
    if fps not in (24, 25, 30, 50, 60):
        raise HTTPException(status_code=400, detail="Unsupported frame rate")
    return width, height, fps


def _clean_export_clip(index: int, clip: Any) -> dict:
    if not isinstance(clip, dict):
        raise HTTPException(status_code=400, detail=f"Clip {index + 1} is invalid")
    transition = str(clip.get("transition") or "none")
    if transition not in SUPPORTED_TRANSITIONS:
        raise HTTPException(
            status_code=400, detail=f"Clip {index + 1} has an unsupported transition",
        )
    try:
        transition_duration = float(clip.get("transition_duration") or 0.4)
        transition_text_size = float(clip.get("transition_text_size") or 100)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"Clip {index + 1} has invalid transition settings",
        ) from exc
    if transition_duration < 0.05 or transition_duration > 5:
        raise HTTPException(
            status_code=400, detail="Transition duration must be between 0.05 and 5 seconds",
        )
    if transition_text_size < 50 or transition_text_size > 160:
        raise HTTPException(
            status_code=400, detail="Transition text size must be between 50% and 160%",
        )
    clean_clip = dict(clip)
    clean_clip.update({
        "transition": transition,
        "transition_duration": transition_duration,
        "transition_text": normalise_time_card_text(clip.get("transition_text")),
        "transition_text_size": transition_text_size,
    })
    return clean_clip


def _parse_soundtrack_levels(soundtrack: dict) -> tuple[float, float, float]:
    try:
        trim_start = max(0.0, float(soundtrack.get("trim_start") or 0))
        trim_end = max(0.0, float(soundtrack.get("trim_end") or 0))
        raw_volume = soundtrack.get("volume")
        volume = float(raw_volume if raw_volume is not None else 1)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid soundtrack settings") from exc
    return trim_start, trim_end, volume


def _clean_export_soundtrack(soundtrack: Any) -> dict | None:
    if soundtrack is None:
        return None
    if not isinstance(soundtrack, dict):
        raise HTTPException(status_code=400, detail="The soundtrack must be an object")
    trim_start, trim_end, volume = _parse_soundtrack_levels(soundtrack)
    if trim_end and trim_end <= trim_start:
        raise HTTPException(status_code=400, detail="Soundtrack trim_end must be after trim_start")
    if volume < 0 or volume > 2:
        raise HTTPException(status_code=400, detail="Soundtrack volume must be between 0 and 2")
    clean = {
        "name": str(soundtrack.get("name") or "soundtrack")[:300],
        "source": str(soundtrack.get("source") or ""),
        "trim_start": trim_start,
        "trim_end": trim_end,
        "volume": volume,
        "loop": bool(soundtrack.get("loop")),
    }
    if not clean["source"].strip():
        raise HTTPException(status_code=400, detail="Soundtrack source is missing")
    return clean


def _allocate_export_output(body: dict) -> tuple[Any, str, str]:
    workspace = body.get("workspace") if body.get("workspace") is not None else _runtime.get_active_workspace()
    out_dir = _runtime.workspace_dir(workspace)
    safe_name = _safe_media_stem(body.get("name"), "edited_video")
    timestamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
    os.makedirs(out_dir, exist_ok=True)
    _output_name, output_path = _unique_workspace_file(
        out_dir, f"{timestamp}_{safe_name}", ".mp4",
    )
    return workspace, out_dir, output_path


def _queued_export_job(
    job_id: str,
    task_id: str,
    root_task_id: str,
    parent_task_id: str | None,
    workspace: Any,
) -> dict:
    now = time.time()
    lane = _VIDEO_EDITOR_FFMPEG_LANE.key
    return {
        "job_id": job_id,
        "task_id": task_id,
        "root_task_id": root_task_id,
        "parent_task_id": parent_task_id,
        "workspace": workspace,
        "status": "queued",
        "phase": "queued",
        "progress": 0,
        "current": 0,
        "total": 100,
        "message": "Waiting to export…",
        "filename": None,
        "url": None,
        "output_files": [],
        "result": None,
        "error": None,
        "provider": "local",
        "model": "FFmpeg",
        "server_origin": "local",
        "resource_lane": lane,
        "resource_requirements": [lane],
        "acquired_resources": [],
        "created_at": now,
        "queued_at": now,
        "updated_at": now,
        "_cancel_requested": False,
        "_resource_acquired": False,
        "_worker_active": True,
    }


def _clip_sidecar(clip: dict) -> dict:
    return {key: value for key, value in clip.items() if key in CLIP_SIDECAR_KEYS}


def _soundtrack_sidecar(soundtrack: Any) -> dict | None:
    if not isinstance(soundtrack, dict):
        return None
    payload = {
        key: value for key, value in soundtrack.items() if key in SOUNDTRACK_SIDECAR_KEYS
    }
    return payload or None


def _export_sidecar_payload(
    body: dict,
    resolved_clips: list[dict],
    job_id: str,
    task_id: str,
    root_task_id: str,
    workspace: str,
) -> dict:
    return {
        "params": {
            "video_editor": {
                "version": 2,
                "width": int(body["width"]),
                "height": int(body["height"]),
                "fps": int(body["fps"]),
                "clips": [_clip_sidecar(clip) for clip in body["clips"]],
                "source_manifest": build_source_provenance_manifest(resolved_clips),
                "soundtrack": _soundtrack_sidecar(body.get("soundtrack")),
            },
            "source": "video_editor",
        },
        "generation_mode": "video",
        "job_id": job_id,
        "task_id": task_id,
        "root_task_id": root_task_id,
        "workspace": workspace,
        "created_at": time.time(),
    }


def _deferred_cancel_finish(job_id: str, output_path: str, started: bool) -> dict:
    return _finish_video_editor_cancelled(
        job_id,
        output_path,
        message=(
            "Cancelled after FFmpeg reached a safe boundary"
            if started else "Cancelled before FFmpeg started"
        ),
        cancel_mode="deferred" if started else "immediate",
        safe_boundary=(
            "after_current_ffmpeg_render" if started else "before_ffmpeg"
        ),
    )


def _make_export_report(job_id: str):
    def report(progress: int, message: str) -> None:
        bounded = max(0, min(int(progress), 100))
        if _video_editor_cancel_requested(job_id):
            _video_editor_job_update(
                job_id,
                status="cancelling",
                phase="cancelling",
                progress=bounded,
                current=bounded,
                message=(
                    "Cancellation deferred to a safe boundary; "
                    f"FFmpeg is finishing: {message}"
                ),
                cancel_mode="deferred",
                safe_boundary="after_current_ffmpeg_render",
            )
            raise resource_scheduler.ResourceAcquireCancelled(
                f"Video editor export {job_id} reached an FFmpeg safe boundary"
            )
        _video_editor_job_update(
            job_id,
            status="running",
            phase="rendering",
            progress=bounded,
            current=bounded,
            message=message,
        )

    return report


def _resolve_export_media(job_id: str, body: dict, workspace: str):
    resolved_clips = []
    for clip in body["clips"]:
        if _video_editor_cancel_requested(job_id):
            return None
        if not isinstance(clip, dict):
            raise ValueError("Every timeline entry must be a clip object")
        resolved = dict(clip)
        resolved["resolved_path"] = _resolve_video_editor_source(
            str(clip.get("source") or ""), workspace,
        )
        resolved_clips.append(resolved)

    resolved_soundtrack = None
    soundtrack = body.get("soundtrack")
    if soundtrack is not None:
        if not isinstance(soundtrack, dict):
            raise ValueError("The soundtrack must be an object")
        resolved_soundtrack = dict(soundtrack)
        resolved_soundtrack["resolved_path"] = _resolve_video_editor_audio_source(
            str(soundtrack.get("source") or ""), workspace,
        )
    if _video_editor_cancel_requested(job_id):
        return None
    return resolved_clips, resolved_soundtrack


def _render_export_on_lane(
    job_id: str,
    task_id: str,
    body: dict,
    resolved_clips: list[dict],
    resolved_soundtrack: dict | None,
    output_path: str,
    report,
):
    _video_editor_job_update(
        job_id,
        status="waiting_resource",
        phase="waiting_resource",
        message="Waiting for the local FFmpeg lane…",
        acquired_resources=[],
    )
    try:
        with resource_scheduler.coordinator.acquire(
            _VIDEO_EDITOR_FFMPEG_LANE,
            task_id=task_id,
            description="Video editor export",
            cancelled=lambda: _video_editor_cancel_requested(job_id),
        ):
            started = _video_editor_job_update(
                job_id,
                status="running",
                phase="rendering",
                message="Preparing video export with FFmpeg…",
                started_at=time.time(),
                acquired_resources=[_VIDEO_EDITOR_FFMPEG_LANE.key],
                _resource_acquired=True,
            )
            started_status = str(started.get("status") or "")
            if _video_editor_cancel_requested(job_id) or started_status in _VIDEO_EDITOR_TERMINAL:
                raise resource_scheduler.ResourceAcquireCancelled(
                    f"Video editor export {job_id} was cancelled before FFmpeg started"
                )
            return render_project(
                resolved_clips,
                output_path,
                width=int(body["width"]),
                height=int(body["height"]),
                fps=int(body["fps"]),
                soundtrack=resolved_soundtrack,
                progress=report,
            )
    except resource_scheduler.ResourceAcquireCancelled:
        current = _video_editor_job_snapshot(job_id) or {}
        _deferred_cancel_finish(job_id, output_path, bool(current.get("started_at")))
        return None


def _finalize_completed_export(
    job_id: str,
    body: dict,
    resolved_clips: list[dict],
    output_path: str,
    result: dict,
    workspace: str,
    task_id: str,
    root_task_id: str,
) -> None:
    if _video_editor_cancel_requested(job_id):
        _deferred_cancel_finish(job_id, output_path, True)
        return
    saving = _video_editor_job_update(
        job_id,
        status="running",
        phase="saving",
        message="Saving video metadata…",
        acquired_resources=[],
        _resource_acquired=False,
    )
    if _video_editor_cancel_requested(job_id) or str(saving.get("status") or "") == "cancelling":
        _deferred_cancel_finish(job_id, output_path, True)
        return
    output_name = os.path.basename(output_path)
    sidecar = _export_sidecar_payload(
        body, resolved_clips, job_id, task_id, root_task_id, workspace,
    )
    _write_video_editor_export_sidecar(output_path, sidecar, workspace)
    completed = _video_editor_job_update(
        job_id,
        status="completed",
        phase="completed",
        progress=100,
        current=100,
        message="Video export complete",
        filename=output_name,
        url=f"/api/v1/file/{output_name}",
        output_files=[output_name],
        result=result,
        error=None,
        acquired_resources=[],
        finished_at=time.time(),
        _worker_active=False,
    )
    if str(completed.get("status") or "") == "cancelled":
        _remove_video_editor_output_bundle(output_path)


def _fail_export_worker(job_id: str, output_path: str, exc: Exception) -> None:
    if _video_editor_cancel_requested(job_id):
        current = _video_editor_job_snapshot(job_id) or {}
        _deferred_cancel_finish(job_id, output_path, bool(current.get("started_at")))
        return
    traceback.print_exception(type(exc), exc, exc.__traceback__)
    _remove_video_editor_output_bundle(output_path)
    _video_editor_job_update(
        job_id,
        status="failed",
        phase="failed",
        error=str(exc),
        message=f"Export failed: {exc}",
        output_files=[],
        acquired_resources=[],
        finished_at=time.time(),
        _resource_acquired=False,
        _worker_active=False,
    )


def _run_video_editor_export(job_id: str, body: dict, out_dir: str, output_path: str) -> None:
    job = _video_editor_job_snapshot(job_id)
    if job is None or str(job.get("status") or "") in _VIDEO_EDITOR_TERMINAL:
        return
    workspace = str(job["workspace"])
    task_id = str(job["task_id"])
    try:
        _video_editor_job_update(
            job_id,
            status="queued",
            phase="validating_sources",
            progress=1,
            current=1,
            message="Validating source clips…",
        )
        resolved = _resolve_export_media(job_id, body, workspace)
        if resolved is None:
            _finish_video_editor_cancelled(job_id, output_path)
            return
        resolved_clips, resolved_soundtrack = resolved
        result = _render_export_on_lane(
            job_id, task_id, body, resolved_clips, resolved_soundtrack,
            output_path, _make_export_report(job_id),
        )
        if result is None:
            return
        _finalize_completed_export(
            job_id, body, resolved_clips, output_path, result,
            workspace, task_id, str(job["root_task_id"]),
        )
    except Exception as exc:
        _fail_export_worker(job_id, output_path, exc)


def _start_video_editor_export(body: dict) -> dict:
    clips = body.get("clips")
    if not isinstance(clips, list) or not clips:
        raise HTTPException(status_code=400, detail="Add at least one video clip")
    if len(clips) > 100:
        raise HTTPException(status_code=400, detail="A project can contain at most 100 clips")
    width, height, fps = _parse_export_geometry(body)
    clean_clips = [_clean_export_clip(index, clip) for index, clip in enumerate(clips)]
    clean_soundtrack = _clean_export_soundtrack(body.get("soundtrack"))
    workspace, out_dir, output_path = _allocate_export_output(body)
    clean_body = dict(body)
    clean_body.update({
        "width": width, "height": height, "fps": fps,
        "clips": clean_clips, "soundtrack": clean_soundtrack,
    })
    job_id = f"video-edit-{uuid.uuid4().hex[:12]}"
    task_id, root_task_id, parent_task_id = _video_editor_task_identity(body, job_id)
    job = _queued_export_job(job_id, task_id, root_task_id, parent_task_id, workspace)
    try:
        snapshot = _register_video_editor_job(job)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not queue video export: {exc}") from exc
    worker = threading.Thread(
        target=_run_video_editor_export,
        args=(job_id, clean_body, out_dir, output_path),
        daemon=True,
        name=f"maestro-{job_id}",
    )
    try:
        worker.start()
    except Exception as exc:
        _video_editor_job_update(
            job_id,
            status="failed",
            phase="failed",
            error=str(exc),
            message=f"Could not start video export worker: {exc}",
            acquired_resources=[],
            finished_at=time.time(),
            _worker_active=False,
        )
        raise HTTPException(status_code=500, detail=f"Could not start video export: {exc}") from exc
    return _public_video_editor_job(snapshot)


def get_video_editor_export(job_id: str) -> dict:
    job = _video_editor_job_snapshot(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Video editor export job not found")
    return _public_video_editor_job(job)


_lookup_export_job = get_video_editor_export


def cancel_video_editor_export(job_id: str) -> dict:
    """Cancel before FFmpeg, or defer cancellation to its safe boundary."""
    now = time.time()
    with _video_editor_jobs_lock:
        job = _video_editor_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Video editor export job not found")
        if str(job.get("status") or "") in _VIDEO_EDITOR_TERMINAL:
            snapshot = copy.deepcopy(job)
            should_publish = False
        else:
            job["_cancel_requested"] = True
            job["cancel_requested_at"] = now
            if str(job.get("status") or "") in {"queued", "waiting_resource"}:
                job.update({
                    "status": "cancelled",
                    "phase": "cancelled",
                    "message": "Cancelled before FFmpeg started",
                    "cancel_mode": "immediate",
                    "safe_boundary": "before_ffmpeg",
                    "error": None,
                    "result": None,
                    "filename": None,
                    "url": None,
                    "output_files": [],
                    "acquired_resources": [],
                    "progress": 0,
                    "current": 0,
                    "finished_at": now,
                })
            else:
                owns_lane = bool(job.get("acquired_resources"))
                job.update(_cancelling_status_patch(owns_lane))
            job["updated_at"] = now
            snapshot = copy.deepcopy(job)
            should_publish = True
        if should_publish:
            _publish_video_editor_job(snapshot)
    return _public_video_editor_job(snapshot)


_cancel_export_job = cancel_video_editor_export


def create_video_editor_router(
    *,
    workspace_dir: Callable[..., str],
    get_active_workspace: Callable[[], str],
    resolve_input_path: Callable[..., str | None],
    publish_legacy_task: Callable[..., Any] | None,
    thumbnail_cache_dir: str,
) -> APIRouter:
    """Probe, thumbnail, screenshot and export queue at the original ordinals."""
    _bind_video_editor_runtime(
        workspace_dir=workspace_dir,
        get_active_workspace=get_active_workspace,
        resolve_input_path=resolve_input_path,
        publish_legacy_task=publish_legacy_task,
        thumbnail_cache_dir=thumbnail_cache_dir,
    )
    router = APIRouter()

    @router.post("/api/v1/video-editor/probe")
    def probe_video_editor_source(body: dict):
        """Read duration, dimensions, frame rate and audio presence for one clip."""
        return _probe_video_editor_source(body)

    @router.post("/api/v1/video-editor/probe-audio")
    def probe_video_editor_audio_source(body: dict):
        """Read duration for one workspace soundtrack without requiring video."""
        return _probe_video_editor_audio_source(body)

    @router.get("/api/v1/video-editor/thumbnail")
    def serve_video_editor_thumbnail(source: str):
        """Return a static preview for an uploaded or workspace editor source."""
        return _serve_video_editor_thumbnail(source)

    @router.post("/api/v1/video-editor/screenshot")
    def capture_video_editor_frame(body: dict):
        """Save the current source-video frame as a reusable Maestro image output."""
        return _capture_video_editor_frame(body)

    @router.post("/api/v1/video-editor/export", status_code=202)
    def start_video_editor_export(body: dict):
        """Queue a non-blocking FFmpeg export for uploaded and/or Maestro clips."""
        return _start_video_editor_export(body)

    return router


def create_video_editor_jobs_router() -> APIRouter:
    """Status and cancel routes that follow the comic animatic ordinal."""
    router = APIRouter()

    @router.get("/api/v1/video-editor/export/{job_id}")
    def get_video_editor_export(job_id: str):
        return _lookup_export_job(job_id)

    @router.post("/api/v1/video-editor/export/{job_id}/cancel")
    def cancel_video_editor_export(job_id: str):
        """Cancel before FFmpeg, or defer cancellation to its safe boundary."""
        return _cancel_export_job(job_id)

    return router


__all__ = [
    "cancel_video_editor_export",
    "create_video_editor_jobs_router",
    "create_video_editor_router",
    "get_video_editor_export",
    "list_video_editor_jobs",
    "reset_video_editor_jobs",
    "_VIDEO_EDITOR_FFMPEG_LANE",
    "_VIDEO_EDITOR_TERMINAL",
    "_finish_video_editor_cancelled",
    "_public_video_editor_job",
    "_register_video_editor_job",
    "_remove_video_editor_output_bundle",
    "_video_editor_cancel_requested",
    "_video_editor_job_snapshot",
    "_video_editor_job_update",
    "_video_editor_task_identity",
]
