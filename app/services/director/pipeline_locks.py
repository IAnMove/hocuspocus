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


def _claim_pipeline_operation_locked(pid: str) -> bool:
    """Reserve a terminal pipeline while ``_pipeline_lock`` is held."""
    host = _pipeline_host()
    if (
        pid in host._pipeline_threads
        or bool(host._pipeline_child_jobs.get(pid))
        or pid in host._pipeline_starting
        or pid in host._pipeline_operations
        or pid in host._pipeline_deleting
        or host._pipelines.get(pid, {}).get("status") in {
            "queued", "planning", "running", "paused",
        }
    ):
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
