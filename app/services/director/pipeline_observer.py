"""Push-based Director snapshot publication.

The callback is best-effort: task observability must never stop a render.
Collections stay on ``services.director_pipeline`` so ``init(..., state_observer=)``
and tests that rebind ``_pipeline_state_observer`` keep one observer.
"""
from __future__ import annotations

import copy
from typing import Optional

from services.director.pipeline_locks import _pipeline_host


def _observer_task_ids(result) -> tuple[Optional[str], Optional[str]]:
    """Accept both TaskRegistry records and explicit observer ID payloads."""
    if not isinstance(result, dict):
        return None, None
    task_id = str(
        result.get("task_id") or result.get("id") or ""
    ).strip()
    root_task_id = str(
        result.get("root_task_id")
        or result.get("root_id")
        or task_id
        or ""
    ).strip()
    return task_id or None, root_task_id or None


def _pipeline_observer_snapshot(pipeline: dict) -> dict:
    """Build one immutable, non-sensitive snapshot for task publication."""
    host = _pipeline_host()
    snapshot = copy.deepcopy(pipeline)
    params = snapshot.pop("params", None)
    snapshot.pop("_llm_passes", None)
    snapshot["pipeline_type"] = snapshot.get("pipeline_type") or (
        params or {}
    ).get("pipeline_type", "")
    # ``params`` is intentionally omitted from observer snapshots because it
    # may contain prompts and provider details. Provenance is the portable,
    # non-sensitive identity contract needed by the task adapter, so project
    # and song-to-video references must survive that projection.
    if isinstance(params, dict) and isinstance(params.get("provenance"), dict):
        snapshot["provenance"] = copy.deepcopy(params["provenance"])
    details = host._public_pipeline_generation_details(
        params,
        len(snapshot.get("clip_plans") or []),
    )
    if details:
        snapshot["generation_details"] = details
    return snapshot


def _notify_pipeline_snapshot(
    pid: str,
    snapshot: Optional[dict] = None,
) -> Optional[dict]:
    """Publish a pipeline snapshot without holding Director's registry lock.

    The callback is deliberately best-effort: task observability must never
    stop a render.  A callback may return either the canonical TaskRegistry
    record (``id``/``root_id``) or explicit ``task_id``/``root_task_id``
    fields.  Retaining those IDs on the pipeline lets nested LLM calls attach
    themselves to the Director root from inside the background worker.
    """
    host = _pipeline_host()
    with host._pipeline_lock:
        observer = host._pipeline_state_observer
        if snapshot is None:
            pipeline = host._pipelines.get(pid)
            snapshot = copy.deepcopy(pipeline) if pipeline else None
    if observer is None or snapshot is None:
        return None

    public_snapshot = _pipeline_observer_snapshot(snapshot)
    workspace = str(public_snapshot.get("workspace") or "default")
    try:
        result = observer(public_snapshot, workspace)
    except Exception as exc:
        print(f"[Pipeline {pid}] State observer warning (non-fatal): {exc}")
        return None

    task_id, root_task_id = _observer_task_ids(result)
    if task_id or root_task_id:
        with host._pipeline_lock:
            pipeline = host._pipelines.get(pid)
            if pipeline is not None:
                if task_id:
                    pipeline["task_id"] = task_id
                if root_task_id:
                    pipeline["root_task_id"] = root_task_id
    return result if isinstance(result, dict) else None
