"""Director pipeline restart recovery: finished media and interrupted repair.

Collections stay on ``services.director_pipeline`` so tests that rebind
``_pipelines`` / ``_pipeline_repairs`` keep a single registry.
"""
from __future__ import annotations

import json
import os
import time
import uuid

from services.director.pipeline_locks import _pipeline_host


def _normalize_interrupted_repair(state: dict, pid: str) -> bool:
    """Mark a persisted active repair interrupted when its worker is gone.

    Browser reloads leave the non-daemon worker registered, so they continue
    normally.  A Maestro process restart removes the registry; changing the
    saved status makes that distinction visible and leaves Repair available as
    an idempotent resume-from-disk operation.
    """
    host = _pipeline_host()
    repair = state.get("repair")
    if not isinstance(repair, dict):
        return False
    if repair.get("status") not in host._REPAIR_ACTIVE_STATUSES:
        return False
    operation_id = repair.get("operation_id")
    with host._pipeline_lock:
        control = host._pipeline_repairs.get(pid)
        worker_present = bool(
            control
            and control.get("operation_id") == operation_id
        )
    if worker_present:
        return False

    now = time.time()
    repair.update({
        "status": "interrupted",
        "phase": "interrupted",
        "clip_index": None,
        "message": "Repair was interrupted when HocusPocus Lab stopped. Start Repair again to continue.",
        "error": "HocusPocus Lab stopped before the repair finished.",
        "updated_at": now,
        "completed_at": now,
    })
    return True


def mark_stale_running_pipeline(data: dict, pid: str) -> bool:
    """A ``running`` checkpoint with no in-memory pipeline crashed on restart."""
    host = _pipeline_host()
    if data.get("status") != "running":
        return False
    with host._pipeline_lock:
        present = pid in host._pipelines
    if present:
        return False
    data["status"] = "crashed"
    return True


def _reconcile_pipeline_state_file(filepath: str, data: dict) -> dict:
    """Promote a timed-out checkpoint when its generation actually finished."""
    host = _pipeline_host()
    data = host._ensure_h3_segment_state(data, os.path.dirname(filepath))
    pid = str(data.get("pipeline_id") or "")
    clips = data.get("clips") if isinstance(data.get("clips"), list) else []
    if not pid or not clips:
        return data
    recovered = host._pipeline_media_for_job(pid, os.path.dirname(filepath), len(clips))
    if not recovered:
        return data

    already_reconciled = (
        data.get("status") == "completed"
        and recovered["final"] in (data.get("output_files") or [])
        and all(
            clip.get("video_filename") == recovered["clips"][index]
            for index, clip in enumerate(clips)
        )
    )
    if already_reconciled:
        return data

    for index, clip in enumerate(clips):
        clip["video_filename"] = recovered["clips"][index]
    data["status"] = "completed"
    data["output_files"] = [recovered["final"]]
    data["completed_at"] = max(
        float(data.get("completed_at") or 0),
        float(recovered["created_at"] or 0),
    )
    data["recovered_at"] = time.time()
    data["recovery_note"] = (
        "Recovered completed generation outputs after the Director supervisor "
        "timed out."
    )

    temp_path = f"{filepath}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, default=str)
        os.replace(temp_path, filepath)
        print(
            f"[Pipeline {pid}] Recovered {len(clips)} clip videos and final "
            f"movie {recovered['final']} from job {recovered['job_id']}"
        )
    finally:
        try:
            if os.path.isfile(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
    return data
