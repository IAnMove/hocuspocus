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


def _pipeline_is_busy_locked(pid: str) -> bool:
    """True when a live save can still replace ``_director_pipeline_{pid}.json``."""
    host = _pipeline_host()
    return (
        pid in host._pipeline_threads
        or bool(host._pipeline_child_jobs.get(pid))
        or pid in host._pipeline_starting
        or pid in host._pipeline_operations
        or pid in host._pipeline_deleting
        or host._pipelines.get(pid, {}).get("status") in _ACTIVE_STATUSES
    )


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


def _claim_pipeline_operation_locked(pid: str) -> bool:
    """Reserve a terminal pipeline while ``_pipeline_lock`` is held."""
    host = _pipeline_host()
    if _pipeline_is_busy_locked(pid):
        return False
    host._pipeline_operations.add(pid)
    return True


def _claim_pipeline_operation(pid: str) -> bool:
    """Reserve a terminal pipeline for one Dashboard mutation."""
    host = _pipeline_host()
    with host._pipeline_lock:
        return _claim_pipeline_operation_locked(pid)


def _release_pipeline_operation(pid: str) -> None:
    host = _pipeline_host()
    with host._pipeline_lock:
        host._pipeline_operations.discard(pid)


def _claim_pipeline_delete(pid: str) -> bool:
    """Reserve deletion before taking the state-file lock."""
    host = _pipeline_host()
    with host._pipeline_lock:
        pipeline = host._pipelines.get(pid)
        if (
            pid in host._pipeline_threads
            or bool(host._pipeline_child_jobs.get(pid))
            or pid in host._pipeline_starting
            or pid in host._pipeline_operations
            or pid in host._pipeline_deleting
            or (
                pipeline
                and pipeline.get("status") in {
                    "queued", "planning", "running", "paused",
                }
            )
        ):
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
        if not _claim_pipeline_operation(pid):
            raise PipelineBusyError(
                "Pipeline is still active; try again shortly.",
            )
        try:
            return function(out_dir, pid, *args, **kwargs)
        finally:
            _release_pipeline_operation(pid)
    return wrapped
