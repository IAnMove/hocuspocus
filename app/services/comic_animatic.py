"""Comic animatic worker for the full server.

Moved verbatim from the full server. The comics router receives
``_run_comic_animatic`` by injection, as it did when this worker lived in
the launch runtime. This module does not import WanGP, ``_launch_runtime``
or a router. The path resolver and the video-editor callables are injected.
"""
from __future__ import annotations

import os
import time
import traceback

from services import resource_scheduler

# Injected by bind_comic_animatic. None until the full server binds them.
_resolve_model3d_input_path = None
_VIDEO_EDITOR_FFMPEG_LANE = None
_VIDEO_EDITOR_TERMINAL = None
_finish_video_editor_cancelled = None
_remove_video_editor_output_bundle = None
_video_editor_cancel_requested = None
_video_editor_job_snapshot = None
_video_editor_job_update = None


_COMIC_ANIMATIC_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _resolve_comic_animatic_image(source: str, workspace: str | None = None) -> str:
    """Resolve a captured panel image using Maestro's existing safe path rules."""
    from urllib.parse import unquote

    decoded = unquote(str(source or "").strip())
    resolved = _resolve_model3d_input_path(decoded, workspace)
    if not resolved or not os.path.isfile(resolved):
        raise ValueError(f"Comic panel image could not be found: {os.path.basename(decoded)}")
    if os.path.splitext(resolved)[1].lower() not in _COMIC_ANIMATIC_IMAGE_EXTENSIONS:
        raise ValueError("Comic animatics require PNG, JPEG or WebP panel images")
    return resolved


def _write_comic_animatic_sidecar(output_path, sidecar, workspace_id):
    from services.asset_manifest import publish_generation_sidecar

    publish_generation_sidecar(
        output_path,
        sidecar,
        workspace_id=workspace_id,
        tool="comic-animatic",
    )


def _run_comic_animatic(job_id: str, body: dict, output_path: str) -> None:
    from services.video_editor import render_comic_animatic

    job = _video_editor_job_snapshot(job_id)
    if job is None or str(job.get("status") or "") in _VIDEO_EDITOR_TERMINAL:
        return
    workspace = str(job["workspace"])
    task_id = str(job["task_id"])

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
            # The callback runs only between blocking FFmpeg subprocesses.
            raise resource_scheduler.ResourceAcquireCancelled(
                f"Comic animatic {job_id} reached an FFmpeg safe boundary"
            )
        else:
            _video_editor_job_update(
                job_id,
                status="running",
                phase="rendering",
                progress=bounded,
                current=bounded,
                message=message,
            )

    try:
        _video_editor_job_update(
            job_id,
            status="queued",
            phase="validating_sources",
            progress=1,
            current=1,
            message="Validating comic panels…",
        )
        panels = []
        for panel in body["panels"]:
            if _video_editor_cancel_requested(job_id):
                _finish_video_editor_cancelled(job_id, output_path)
                return
            if not isinstance(panel, dict):
                raise ValueError("Every animatic panel must be an object")
            resolved = dict(panel)
            resolved["resolved_path"] = _resolve_comic_animatic_image(
                panel.get("source", ""), workspace,
            )
            panels.append(resolved)

        if _video_editor_cancel_requested(job_id):
            _finish_video_editor_cancelled(job_id, output_path)
            return
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
                description="Comic animatic render",
                cancelled=lambda: _video_editor_cancel_requested(job_id),
            ):
                started = _video_editor_job_update(
                    job_id,
                    status="running",
                    phase="rendering",
                    message="Animating comic panels with FFmpeg…",
                    started_at=time.time(),
                    acquired_resources=[_VIDEO_EDITOR_FFMPEG_LANE.key],
                    _resource_acquired=True,
                )
                if (
                    _video_editor_cancel_requested(job_id)
                    or str(started.get("status") or "") in _VIDEO_EDITOR_TERMINAL
                ):
                    raise resource_scheduler.ResourceAcquireCancelled(
                        f"Comic animatic {job_id} was cancelled before FFmpeg started"
                    )
                result = render_comic_animatic(
                    panels,
                    output_path,
                    width=body["width"],
                    height=body["height"],
                    fps=body["fps"],
                    transition=body["transition"],
                    transition_duration=body["transition_duration"],
                    progress=report,
                )
        except resource_scheduler.ResourceAcquireCancelled:
            current = _video_editor_job_snapshot(job_id) or {}
            deferred = bool(current.get("started_at"))
            _finish_video_editor_cancelled(
                job_id,
                output_path,
                message=(
                    "Cancelled after FFmpeg reached a safe boundary"
                    if deferred else "Cancelled before FFmpeg started"
                ),
                cancel_mode="deferred" if deferred else "immediate",
                safe_boundary=(
                    "after_current_ffmpeg_render" if deferred else "before_ffmpeg"
                ),
            )
            return

        if _video_editor_cancel_requested(job_id):
            _finish_video_editor_cancelled(
                job_id,
                output_path,
                message="Cancelled after FFmpeg reached a safe boundary",
                cancel_mode="deferred",
                safe_boundary="after_current_ffmpeg_render",
            )
            return
        saving = _video_editor_job_update(
            job_id,
            status="running",
            phase="saving",
            message="Saving animatic metadata…",
            acquired_resources=[],
            _resource_acquired=False,
        )
        if (
            _video_editor_cancel_requested(job_id)
            or str(saving.get("status") or "") == "cancelling"
        ):
            _finish_video_editor_cancelled(
                job_id,
                output_path,
                message="Cancelled after FFmpeg reached a safe boundary",
                cancel_mode="deferred",
                safe_boundary="after_current_ffmpeg_render",
            )
            return

        output_name = os.path.basename(output_path)
        sidecar = {
            "params": {
                "source": "comic_animatic",
                "comic_animatic": {
                    "version": 1,
                    "comic_id": body.get("comic_id"),
                    "comic_title": body.get("comic_title"),
                    "width": body["width"], "height": body["height"], "fps": body["fps"],
                    "transition": body["transition"],
                    "transition_duration": body["transition_duration"],
                    "panels": [{key: value for key, value in panel.items() if key != "resolved_path"} for panel in panels],
                },
            },
            "generation_mode": "video",
            "job_id": job_id,
            "task_id": task_id,
            "root_task_id": str(job["root_task_id"]),
            "workspace": workspace,
            "created_at": time.time(),
        }
        _write_comic_animatic_sidecar(output_path, sidecar, workspace)
        completed = _video_editor_job_update(
            job_id,
            status="completed",
            phase="completed",
            progress=100,
            current=100,
            message="Comic animatic complete",
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
    except Exception as exc:
        if _video_editor_cancel_requested(job_id):
            current = _video_editor_job_snapshot(job_id) or {}
            deferred = bool(current.get("started_at"))
            _finish_video_editor_cancelled(
                job_id,
                output_path,
                message=(
                    "Cancelled after FFmpeg reached a safe boundary"
                    if deferred else "Cancelled before FFmpeg started"
                ),
                cancel_mode="deferred" if deferred else "immediate",
                safe_boundary=(
                    "after_current_ffmpeg_render" if deferred else "before_ffmpeg"
                ),
            )
            return
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        _remove_video_editor_output_bundle(output_path)
        _video_editor_job_update(
            job_id,
            status="failed",
            phase="failed",
            error=str(exc),
            message=f"Animatic failed: {exc}",
            output_files=[],
            acquired_resources=[],
            finished_at=time.time(),
            _resource_acquired=False,
            _worker_active=False,
        )


def bind_comic_animatic(
    *,
    resolve_model3d_input_path,
    video_editor_ffmpeg_lane,
    video_editor_terminal,
    finish_video_editor_cancelled,
    remove_video_editor_output_bundle,
    video_editor_cancel_requested,
    video_editor_job_snapshot,
    video_editor_job_update,
) -> None:
    """Install the full server's path resolver and video-editor callables."""
    global _resolve_model3d_input_path
    global _VIDEO_EDITOR_FFMPEG_LANE, _VIDEO_EDITOR_TERMINAL
    global _finish_video_editor_cancelled, _remove_video_editor_output_bundle
    global _video_editor_cancel_requested
    global _video_editor_job_snapshot, _video_editor_job_update
    _resolve_model3d_input_path = resolve_model3d_input_path
    _VIDEO_EDITOR_FFMPEG_LANE = video_editor_ffmpeg_lane
    _VIDEO_EDITOR_TERMINAL = video_editor_terminal
    _finish_video_editor_cancelled = finish_video_editor_cancelled
    _remove_video_editor_output_bundle = remove_video_editor_output_bundle
    _video_editor_cancel_requested = video_editor_cancel_requested
    _video_editor_job_snapshot = video_editor_job_snapshot
    _video_editor_job_update = video_editor_job_update
