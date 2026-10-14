"""Background audio-analysis jobs.

The registry is the kernel job registry (``_jobs``), the same dict the full
server already uses. ``_audio_analysis_jobs_lock`` is the one lock those
entries had in the launch module. Launch assigns ``_publish_generic_legacy_task``
onto this module after that publisher exists; until then a publish does nothing.
"""
from __future__ import annotations

import copy
import threading
import time
import traceback

from services import resource_scheduler
from services.job_lifecycle import snapshot_job


# Bound to the kernel registry by create_audio_router. The publisher is
# filled in by the launch module after _publish_generic_legacy_task exists.
_jobs = None
_publish_generic_legacy_task = None

_AUDIO_ANALYSIS_STEPS = {
    "loading_audio": 1,
    "detecting_beats": 2,
    "identifying_sections": 3,
    "loading_vocal_model": 4,
    "extracting_vocals": 5,
    "loading_transcription_model": 5,
    "transcribing": 6,
    "aligning_lyrics": 7,
    "loading_diarization_model": 7,
    "identifying_speakers": 8,
    "finalizing": 9,
}
_AUDIO_ANALYSIS_ACTIVE = {"queued", "waiting_resource", "running", "cancelling"}
_AUDIO_ANALYSIS_TERMINAL = {"completed", "failed", "cancelled"}
_audio_analysis_jobs_lock = threading.RLock()


def _publish_audio_analysis_job(job: dict) -> dict | None:
    publisher = globals().get("_publish_generic_legacy_task")
    if not callable(publisher):
        return None
    try:
        return publisher(copy.deepcopy(job), "audio-analysis")
    except Exception as exc:
        print(f"[Task registry] Could not publish audio analysis {job.get('id')}: {exc}")
        return None

def _audio_analysis_job_update(job_id: str, **patch) -> dict | None:
    with _audio_analysis_jobs_lock:
        job = _jobs.get(job_id)
        if not job or not job_id.startswith("audio-analysis-"):
            return None
        current_status = str(job.get("status") or "queued")
        if current_status in _AUDIO_ANALYSIS_TERMINAL:
            return snapshot_job(job)
        requested_status = str(patch.get("status") or "")
        if job.get("_cancel_requested") and requested_status not in {
            "cancelled", "cancelling",
        }:
            if requested_status in {"completed", "failed"}:
                patch = {
                    **patch,
                    "status": "cancelled",
                    "phase": "cancelled",
                    "message": "Cancelled",
                    "error": None,
                    "result": None,
                    "progress": 0,
                    "acquired_resources": [],
                    "finished_at": patch.get("finished_at") or time.time(),
                }
            else:
                # A late progress callback must not overwrite a visible
                # cancelling state or reactivate a task cancelled in queue.
                return snapshot_job(job)
        job.update(patch)
        job["updated_at"] = time.time()
        snapshot = snapshot_job(job)
    _publish_audio_analysis_job(snapshot)
    return snapshot

def _run_audio_analysis_job(job_id: str, body: dict) -> None:
    """Run one serialized audio-analysis job with reconnectable progress."""
    with _audio_analysis_jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return
    from services import audio_analysis

    lane = (
        resource_scheduler.local_gpu_lane(0)
        if body.get("transcribe", False)
        else resource_scheduler.cpu_lane("audio")
    )

    def cancelled() -> bool:
        with _audio_analysis_jobs_lock:
            return bool((_jobs.get(job_id) or {}).get("_cancel_requested"))

    if cancelled() or str(job.get("status") or "") in _AUDIO_ANALYSIS_TERMINAL:
        return

    _audio_analysis_job_update(
        job_id,
        status="waiting_resource",
        phase="waiting_resource",
        message=("Waiting for local GPU 0" if body.get("transcribe", False)
                 else "Waiting for audio CPU worker"),
        acquired_resources=[],
    )
    try:
        lease = resource_scheduler.coordinator.acquire(
            lane,
            task_id=str(job.get("task_id") or job_id),
            description="Audio analysis",
            cancelled=cancelled,
        )
        with lease:
            if cancelled():
                _audio_analysis_job_update(
                    job_id, status="cancelled", phase="cancelled",
                    message="Cancelled", progress=0, finished_at=time.time(),
                    acquired_resources=[],
                )
                return
            _audio_analysis_job_update(
                job_id, status="running", phase="loading_audio",
                message="Loading audio…", started_at=time.time(),
                acquired_resources=[lane.key],
            )

            def report(step: str, detail: str) -> None:
                if cancelled():
                    raise RuntimeError("Audio analysis cancelled")
                if not step:
                    return
                current = _AUDIO_ANALYSIS_STEPS.get(step, job.get("step", 1))
                _audio_analysis_job_update(
                    job_id,
                    phase=step,
                    message=f"{detail}…" if detail else step.replace("_", " ").capitalize(),
                    step=current,
                    total_steps=10,
                    progress=int((current / 10) * 100),
                )

            audio_analysis.set_progress_callback(report)
            try:
                result = audio_analysis.analyze(
                    audio_path=body["audio_path"],
                    transcribe=body.get("transcribe", False),
                    extract_vocals_for_transcription=body.get("extract_vocals", True),
                    lyrics_hint=body.get("lyrics_hint") or None,
                )
                if cancelled():
                    _audio_analysis_job_update(
                        job_id, status="cancelled", phase="cancelled",
                        message="Cancelled", progress=0, result=None,
                        finished_at=time.time(), acquired_resources=[],
                    )
                else:
                    _audio_analysis_job_update(
                        job_id,
                        status="completed",
                        phase="completed",
                        message="Audio analysis complete",
                        progress=100,
                        step=10,
                        total_steps=10,
                        result=result,
                        finished_at=time.time(),
                        acquired_resources=[],
                    )
            except Exception as exc:
                if cancelled():
                    _audio_analysis_job_update(
                        job_id,
                        status="cancelled",
                        phase="cancelled",
                        message="Cancelled",
                        error=None,
                        progress=0,
                        finished_at=time.time(),
                        acquired_resources=[],
                    )
                else:
                    traceback.print_exc()
                    _audio_analysis_job_update(
                        job_id,
                        status="failed",
                        phase="failed",
                        message=f"Audio analysis failed: {exc}",
                        error=str(exc),
                        finished_at=time.time(),
                        acquired_resources=[],
                    )
            finally:
                audio_analysis.set_progress_callback(None)
                audio_analysis.clear_progress()
    except resource_scheduler.ResourceAcquireCancelled:
        _audio_analysis_job_update(
            job_id, status="cancelled", phase="cancelled",
            message="Cancelled", progress=0, finished_at=time.time(),
            acquired_resources=[],
        )
    except Exception as exc:
        traceback.print_exc()
        _audio_analysis_job_update(
            job_id,
            status="cancelled" if cancelled() else "failed",
            phase="cancelled" if cancelled() else "failed",
            message=("Cancelled" if cancelled()
                     else f"Audio analysis failed before it started: {exc}"),
            error=None if cancelled() else str(exc),
            result=None,
            acquired_resources=[],
            finished_at=time.time(),
        )
