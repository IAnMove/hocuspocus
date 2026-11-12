"""Claim and exclusive-delete locks for Director pipeline mutations.

Collections stay on ``services.director_pipeline`` so callers and tests that
rebind ``_pipeline_threads`` (and related globals) keep a single mutex.
"""
from __future__ import annotations

import sys
from functools import wraps


def _pipeline_host():
    host = sys.modules.get("services.director_pipeline")
    if host is None:
        from services import director_pipeline as host
    return host


class PipelineBusyError(RuntimeError):
    """Raised when a Dashboard mutation conflicts with active pipeline work."""


_ACTIVE_STATUSES = frozenset({"queued", "planning", "running", "paused"})
_LIVE_JOB_STATUSES = frozenset({"queued", "running", "cancelling"})
_CLIP_OPERATION_NAMES = frozenset({
    "_rerun_clip_video_guarded",
    "rerun_clip_image",
    "update_clip_prompts",
    "select_clip_video_attempt",
})
_OPERATION_LABELS = {
    "_rerun_clip_video_guarded": "rerun-video",
    "rerun_clip_image": "rerun-image",
    "rejoin_clips": "rejoin",
    "update_clip_prompts": "prompt edit",
    "select_clip_video_attempt": "video selection",
}


def _operation_labels(host):
    labels = getattr(host, "_pipeline_operation_labels", None)
    if labels is None:
        labels = {}
        host._pipeline_operation_labels = labels
    return labels


def _job_record_is_live(job) -> bool:
    """A child lease is live only while that job can still write."""
    if not isinstance(job, dict):
        return False
    return str(job.get("status") or "") in _LIVE_JOB_STATUSES


def _forget_dead_thread_locked(pid: str) -> None:
    """Drop a worker entry whose thread has already exited."""
    host = _pipeline_host()
    thread = host._pipeline_threads.get(pid)
    if thread is None:
        return
    # ident is None until Thread.start(); that slot is a worker being published.
    if thread.ident is not None and not thread.is_alive():
        host._pipeline_threads.pop(pid, None)


def _forget_finished_children_locked(pid: str) -> None:
    """Drop child ids whose jobs have finished or disappeared."""
    host = _pipeline_host()
    children = host._pipeline_child_jobs.get(pid)
    if not children:
        return
    jobs = host._jobs or {}
    finished = [
        job_id for job_id in list(children)
        if not _job_record_is_live(jobs.get(job_id))
    ]
    for job_id in finished:
        children.discard(job_id)
    if not children:
        host._pipeline_child_jobs.pop(pid, None)


def _release_stale_pipeline_leases_locked(pid: str) -> None:
    """Clear registry leftovers that no longer protect a writer."""
    _forget_dead_thread_locked(pid)
    _forget_finished_children_locked(pid)


def _job_stage(job: dict) -> str:
    for key in ("phase", "message", "status"):
        text = str(job.get(key) or "").strip()
        if text:
            return text
    return "running"


def _live_work_reason_locked(pid: str) -> str | None:
    """Why ``pid`` must refuse an edit, or None when it is idle.

    A completed, failed or cancelled run with no live job is idle even if a
    finished child id or an exited worker thread is still in the registry.
    A cancelling job whose worker has not acknowledged stays live.
    """
    host = _pipeline_host()
    _release_stale_pipeline_leases_locked(pid)
    if pid in host._pipeline_deleting:
        return "delete is in progress"
    if pid in host._pipeline_starting:
        return "start is in stage starting"
    if pid in host._pipeline_threads:
        pipeline = host._pipelines.get(pid) or {}
        stage = pipeline.get("phase") or pipeline.get("status") or "running"
        return f"worker is in stage {stage}"
    children = host._pipeline_child_jobs.get(pid) or set()
    if children:
        job_id = next(iter(children))
        job = (host._jobs or {}).get(job_id) or {}
        return f"job {job_id} is running ({_job_stage(job)})"
    repair = host._pipeline_repairs.get(pid)
    if isinstance(repair, dict):
        snapshot = repair.get("snapshot") if isinstance(repair.get("snapshot"), dict) else {}
        stage = snapshot.get("phase") or snapshot.get("status") or "repair"
        return f"repair is in stage {stage}"
    if pid in host._pipeline_operations:
        label = _operation_labels(host).get(pid) or "an edit"
        return f"{label} is running"
    pipeline = host._pipelines.get(pid) or {}
    status = pipeline.get("status")
    if status in _ACTIVE_STATUSES:
        stage = pipeline.get("phase") or status
        return f"stage {stage} is running"
    return None


def _pipeline_is_busy_locked(pid: str) -> bool:
    """True when a live save can still replace ``_director_pipeline_{pid}.json``."""
    return _live_work_reason_locked(pid) is not None


def _pipeline_busy_detail_locked(pid: str) -> str:
    reason = _live_work_reason_locked(pid)
    if not reason:
        return "Pipeline is still active; try again shortly."
    return f"Pipeline is still active: {reason}."


def _pipeline_busy_detail(pid: str) -> str:
    host = _pipeline_host()
    with host._pipeline_lock:
        return _pipeline_busy_detail_locked(pid)


def _exclusive_operation_label(function_name: str, args: tuple) -> str:
    base = _OPERATION_LABELS.get(
        function_name, function_name.replace("_", " "),
    )
    if args and function_name in _CLIP_OPERATION_NAMES:
        return f"{base} clip {args[0]}"
    return base


def _same_production(pid: str, pipeline: dict, production_id: str) -> bool:
    if production_id in {
        pid,
        pipeline.get("id"),
        pipeline.get("pipeline_id"),
        pipeline.get("production_id"),
    }:
        return True
    from services.production_run import pipeline_matches_production

    return pipeline_matches_production(pipeline, production_id)


def director_holds_production(production_id: str) -> bool:
    """True when shared catalog edits would be wiped by the next pipeline save.

    ``_save_pipeline_state_locked`` rebuilds ``clips`` and writes
    ``selected_video_filename: None``. Catalog select/undo/reexport persist
    that field on the same file, so they must wait until the worker is idle.
    """
    if not production_id:
        return False
    host = _pipeline_host()
    with host._pipeline_lock:
        if _pipeline_is_busy_locked(production_id):
            return True
        for pid, pipeline in host._pipelines.items():
            if not isinstance(pipeline, dict) or not _same_production(pid, pipeline, production_id):
                continue
            if _pipeline_is_busy_locked(pid):
                return True
    return False


def _claim_pipeline_operation_locked(pid: str, label: str | None = None) -> bool:
    """Reserve a terminal pipeline while ``_pipeline_lock`` is held."""
    host = _pipeline_host()
    if _pipeline_is_busy_locked(pid):
        return False
    host._pipeline_operations.add(pid)
    labels = _operation_labels(host)
    if label:
        labels[pid] = label
    else:
        labels.pop(pid, None)
    return True


def _claim_pipeline_operation(pid: str, label: str | None = None) -> bool:
    """Reserve a terminal pipeline for one Dashboard mutation."""
    host = _pipeline_host()
    with host._pipeline_lock:
        return _claim_pipeline_operation_locked(pid, label=label)


def _release_pipeline_operation(pid: str) -> None:
    host = _pipeline_host()
    with host._pipeline_lock:
        host._pipeline_operations.discard(pid)
        labels = getattr(host, "_pipeline_operation_labels", None)
        if labels is not None:
            labels.pop(pid, None)


def _claim_pipeline_delete(pid: str) -> bool:
    """Reserve deletion before taking the state-file lock."""
    host = _pipeline_host()
    with host._pipeline_lock:
        if _pipeline_is_busy_locked(pid):
            return False
        host._pipeline_deleting.add(pid)
        return True


def _release_pipeline_delete(pid: str) -> None:
    host = _pipeline_host()
    with host._pipeline_lock:
        host._pipeline_deleting.discard(pid)


def _exclusive_pipeline_operation(function):
    """Keep delete/resume/live saves away from a Dashboard media mutation."""
    @wraps(function)
    def wrapped(out_dir: str, pid: str, *args, **kwargs):
        label = kwargs.pop("_operation_label", None) or _exclusive_operation_label(
            function.__name__, args,
        )
        if not _claim_pipeline_operation(pid, label=label):
            raise PipelineBusyError(_pipeline_busy_detail(pid))
        try:
            return function(out_dir, pid, *args, **kwargs)
        finally:
            _release_pipeline_operation(pid)
    return wrapped
