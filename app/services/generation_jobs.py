"""Generation job status, cancel and list.

The three handlers moved out of ``app/_launch_runtime.py`` without a body edit.
The full server calls ``bind`` once, after its registries exist, and passes the
objects these handlers read. ``_job_leftovers`` is assigned later, on this
module, because that object is built further down in the server; ``get_status``
still looks it up with ``globals().get``.
"""
from __future__ import annotations

import time

from fastapi import HTTPException

from services.job_lifecycle import generation_queue_position, request_cancel, snapshot_job

# Injected by bind(); None until the full server binds them.
_active_gen_states = None
_gen_lock = None
_jobs = None
_public_generation_details = None
_remove_persisted_generation_job = None
cancel_audio_analysis_job = None


def bind(**names):
    """Take the full server's objects these handlers use."""
    global _active_gen_states, _gen_lock, _jobs, _public_generation_details
    global _remove_persisted_generation_job, cancel_audio_analysis_job
    _active_gen_states = names["_active_gen_states"]
    _gen_lock = names["_gen_lock"]
    _jobs = names["_jobs"]
    _public_generation_details = names["_public_generation_details"]
    _remove_persisted_generation_job = names["_remove_persisted_generation_job"]
    cancel_audio_analysis_job = names["cancel_audio_analysis_job"]


def get_status(job_id: str):
    """Get generation job status."""
    if job_id not in _jobs:
        leftovers = globals().get("_job_leftovers")
        if leftovers is not None:
            found = leftovers.status_for(job_id)
            if found is not None:
                return found
        raise HTTPException(status_code=404, detail="Job not found")
    j = snapshot_job(_jobs[job_id])
    started_at = j.get("started_at")
    finished_at = j.get("finished_at")
    processing_time = (
        max(0.0, float(finished_at or time.time()) - float(started_at))
        if started_at else None
    )
    payload = {
        "job_id": j["id"],
        "task_id": j.get("task_id"),
        "root_task_id": j.get("root_task_id") or j.get("task_id"),
        "status": j["status"],
        "progress": j["progress"],
        "step": j.get("step", 0),
        "total_steps": j.get("total_steps", 0),
        "phase": j.get("phase", ""),
        "message": j["message"],
        "output_files": j["output_files"],
        "error": j["error"],
        "task_timings": j.get("task_timings", []),
        "created_at": j.get("created_at"),
        "started_at": started_at,
        "finished_at": finished_at,
        "processing_time_sec": (
            round(processing_time, 2) if processing_time is not None else None
        ),
        "queue_position": (
            generation_queue_position(_gen_lock, _jobs[job_id])
            if j.get("status") == "queued" else None
        ),
        "generation_details": _public_generation_details(j.get("params")),
        "h3_window_plan": (
            (j.get("params") or {}).get("h3_window_plan")
            if isinstance(j.get("params"), dict)
            else None
        ),
        # Present only on failed jobs that look like CUDA OOMs. UI
        # renders the OOM recovery banner when this is non-null.
        "oom_info": j.get("oom_info"),
    }
    from services.generation_output_name import status_output_fields
    from services.generation_memory import include_performance
    from services.output_names import annotate_generation_view
    payload.update(status_output_fields(
        payload.get("output_files"),
        workspace=str(j.get("workspace") or ""),
        workspace_dir=str(j.get("out_dir") or ""),
    ))
    return annotate_generation_view(include_performance(payload, j), j)


def cancel_job(job_id: str):
    """Cancel a queued or running generation job."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_id.startswith("audio-analysis-"):
        return cancel_audio_analysis_job(job_id)

    job = _jobs[job_id]
    result = request_cancel(
        job,
        job_id=job_id,
        active_states=_active_gen_states,
    )
    if result.abort_signalled:
        print(f"[Cancel] Signalling abort for job {job_id}")
    if not result.was_running and job.get("status") == "cancelled":
        _remove_persisted_generation_job(job)
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "was_running": result.was_running,
    }


def list_jobs():
    """List all active/recent jobs for reconnection after browser refresh."""
    active = []
    for job in list(_jobs.values()):
        j = snapshot_job(job)
        if j["status"] in ("queued", "waiting_resource", "running", "cancelling"):
            active.append({
                "job_id": j["id"],
                "task_id": j.get("task_id"),
                "root_task_id": j.get("root_task_id") or j.get("task_id"),
                "status": j["status"],
                "progress": j["progress"],
                "step": j.get("step", 0),
                "total_steps": j.get("total_steps", 0),
                "phase": j.get("phase", ""),
                "message": j["message"],
                "output_files": j["output_files"],
                "error": j["error"],
                "oom_info": j.get("oom_info"),
                "task_timings": j.get("task_timings", []),
                "created_at": j.get("created_at", 0),
                "started_at": j.get("started_at"),
                "finished_at": j.get("finished_at"),
                "queue_position": (
                    generation_queue_position(_gen_lock, job)
                    if j.get("status") == "queued" else None
                ),
                "generation_details": _public_generation_details(
                    j.get("params")
                ),
                # Lets a refreshed browser restore the exact H3 prompts that
                # are already driving an in-flight sliding-window job. This is
                # planning metadata only; model paths and unrelated params stay
                # private.
                "h3_window_plan": (
                    (j.get("params") or {}).get("h3_window_plan")
                    if isinstance(j.get("params"), dict)
                    else None
                ),
            })
    active.sort(key=lambda x: x["created_at"])
    return {"jobs": active}
