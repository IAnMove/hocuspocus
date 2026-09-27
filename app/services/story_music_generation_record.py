"""Project Story MiniMax music attempts onto GenerationRecord v1.

TaskRegistry still owns tasks. Asset-manifest still owns published bytes.
This module is a durable projection with CAS, not a second scheduler.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .generation_record import (
    GenerationRecordError,
    GenerationRecordStore,
    attach_derivative,
    build_generation_record,
    request_cancel,
    transition_status,
)


RECORDS_DIRNAME = "generation-records"


def story_music_generation_store(workspace_dir: str | Path) -> GenerationRecordStore:
    return GenerationRecordStore(Path(workspace_dir) / RECORDS_DIRNAME)


def _spec(stored: Mapping[str, Any]) -> dict[str, Any]:
    value = stored.get("spec")
    return dict(value) if isinstance(value, Mapping) else {}


def load_story_music_generation_record(
    workspace_dir: str | Path,
    stored: Mapping[str, Any],
) -> dict[str, Any] | None:
    spec = _spec(stored)
    generation_id = str(stored.get("generation_id") or "").strip()
    folder = spec.get("output_folder")
    if not generation_id or not folder:
        return None
    try:
        return story_music_generation_store(workspace_dir).load(
            generation_id,
            workspace_id=spec.get("workspace_id"),
            output_folder=str(folder),
        )
    except GenerationRecordError:
        return None


def _build_queued(stored: Mapping[str, Any]) -> dict[str, Any]:
    spec = _spec(stored)
    parent_id = str(stored.get("parent_generation_id") or "").strip()
    generation_id = str(stored.get("generation_id") or "")
    return build_generation_record(
        generation_id=generation_id,
        asset_id=f"asset_{generation_id}" if generation_id else None,
        product="story_lab",
        output_folder=spec.get("output_folder"),
        workspace_id=spec.get("workspace_id"),
        project_id=spec.get("project_id"),
        cue_id=spec.get("cue_id"),
        candidate_id=stored.get("candidate_id"),
        prompt_full=spec.get("prompt"),
        prompt_original=spec.get("lyrics"),
        prompt_effective=spec.get("prompt"),
        model={"id": spec.get("model")},
        status="queued",
        parents=([{
            "generation_id": parent_id,
            "kind": "attempt",
        }] if parent_id else None),
        retry_count=1 if stored.get("intent") == "retry" else 0,
        correlations={
            "command_id": stored.get("command_id"),
            "task_id": stored.get("task_id"),
            "job_id": stored.get("job_id"),
        },
        capability="generate_story_song",
    )


def ensure_story_music_generation_record(
    workspace_dir: str | Path,
    stored: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Create the queued projection once. Replay loads the same generation_id."""
    existing = load_story_music_generation_record(workspace_dir, stored)
    if existing is not None:
        return existing
    try:
        record = _build_queued(stored)
    except GenerationRecordError:
        return None
    store = story_music_generation_store(workspace_dir)
    try:
        store.persist(record)
    except GenerationRecordError:
        existing = load_story_music_generation_record(workspace_dir, stored)
        if existing is not None:
            return existing
        raise
    parent_id = str(stored.get("parent_generation_id") or "").strip()
    if parent_id:
        try:
            parent = store.load(
                parent_id,
                workspace_id=record.get("workspace_id"),
                output_folder=record.get("output_folder"),
            )
            store.persist(attach_derivative(parent, record))
        except GenerationRecordError:
            pass
    return store.load(
        record["generation_id"],
        workspace_id=record.get("workspace_id"),
        output_folder=record.get("output_folder"),
    )


def complete_story_music_generation_record(
    workspace_dir: str | Path,
    stored: Mapping[str, Any],
    *,
    filename: str | None = None,
    sidecar: str | None = None,
) -> dict[str, Any] | None:
    """queued → running → completed for one reserved Story Music attempt."""
    current = load_story_music_generation_record(workspace_dir, stored)
    if current is None:
        current = ensure_story_music_generation_record(workspace_dir, stored)
    if current is None:
        return None
    if current["status"] in {"completed", "cancelled", "failed"}:
        return current
    if current["status"] == "queued":
        current = transition_status(current, "running")
    if current["status"] == "running":
        current = transition_status(current, "completed")
    if filename:
        current["location"] = {
            "filename": Path(filename).name,
            "uri": Path(filename).name,
            "sidecar": Path(sidecar).name if sidecar else None,
        }
        current["result"] = {"kind": "complete"}
    store = story_music_generation_store(workspace_dir)
    store.persist(current)
    return store.load(
        current["generation_id"],
        workspace_id=current.get("workspace_id"),
        output_folder=current.get("output_folder"),
    )


def cancel_story_music_generation_record(
    workspace_dir: str | Path,
    stored: Mapping[str, Any],
    *,
    reason: str = "cancelled",
) -> dict[str, Any] | None:
    current = load_story_music_generation_record(workspace_dir, stored)
    if current is None:
        current = ensure_story_music_generation_record(workspace_dir, stored)
    if current is None:
        return None
    cancelled = request_cancel(current, reason=reason)
    store = story_music_generation_store(workspace_dir)
    store.persist(cancelled)
    return store.load(
        cancelled["generation_id"],
        workspace_id=cancelled.get("workspace_id"),
        output_folder=cancelled.get("output_folder"),
    )
