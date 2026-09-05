"""Finalize a reserved music attempt without the browser.

Bytes land first. Manifest and Story candidate publish are separate. A
metadata failure keeps the audio and records repair_pending. Does not
import FastAPI, WanGP or launch. Does not call providers or load models.
"""
from __future__ import annotations

import os
import shutil
import wave
from pathlib import Path
from typing import Any, Callable, Mapping

from .asset_manifest import publish_generation_sidecar
from .generation_record import build_generation_record
from .music_submission import MusicSubmissionError, MusicSubmissionStore
from .story_library import (
    StoryLibraryRevisionConflict,
    attach_story_song_candidate,
    read_story_library,
)


STAGES = ("bytes", "manifest", "candidate")
TERMINAL_SKIP = frozenset({"cancelled"})


class MusicFinalizationError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class MusicFinalizationCancelled(MusicFinalizationError):
    def __init__(self, message: str = "Music finalization cancelled before bytes"):
        super().__init__(message, status_code=409)


def _measure_wav_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            frames = handle.getnframes()
        if rate <= 0:
            return None
        return round(frames / float(rate), 3)
    except (OSError, wave.Error):
        return None


def _coerce_duration(value: Any) -> float | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return round(seconds, 3)


def _publication(record: Mapping[str, Any]) -> dict[str, Any]:
    value = record.get("publication")
    return dict(value) if isinstance(value, Mapping) else {}


def _should_select(library: Mapping[str, Any], spec: Mapping[str, Any]) -> bool:
    project_id = str(spec.get("project_id") or "")
    cue_id = str(spec.get("cue_id") or "")
    candidate_id = str(spec.get("candidate_id") or "")
    project = (library.get("projects") or {}).get(project_id) or {}
    music = project.get("music") if isinstance(project, Mapping) else {}
    for cue in (music.get("cues") or []) if isinstance(music, Mapping) else []:
        if not isinstance(cue, Mapping):
            continue
        if str(cue.get("id") or "") != cue_id:
            continue
        selected = str(cue.get("selectedCandidateId") or "").strip()
        if not selected or selected == candidate_id:
            return True
        return False
    return True


def reconcile_reserved_music(workspace_dir: str, generation_id: str) -> dict[str, Any] | None:
    """Describe interrupted work without starting inference."""
    store = MusicSubmissionStore(workspace_dir)
    record = store.get_by_generation_id(generation_id)
    if record is None:
        return None
    publication = _publication(record)
    audio = publication.get("audio_filename")
    path = Path(workspace_dir) / audio if audio else None
    bytes_present = bool(path and path.is_file())
    return {
        "generation_id": record.get("generation_id"),
        "status": record.get("status"),
        "stage": publication.get("stage") or "reserved",
        "bytes_present": bytes_present,
        "repair_pending": publication.get("stage") == "repair_pending",
        "needs_inference": not bytes_present and record.get("status") not in TERMINAL_SKIP,
    }


def _mark_repair(store: MusicSubmissionStore, record: dict[str, Any], message: str) -> dict[str, Any]:
    publication = _publication(record)
    publication["stage"] = "repair_pending"
    publication["repair_error"] = message[:500]
    record = dict(record)
    record["publication"] = publication
    record["status"] = "repair_pending"
    return store.replace(record)


def _stage_bytes(
    store: MusicSubmissionStore,
    record: dict[str, Any],
    *,
    workspace_dir: str,
    audio_path: str | os.PathLike[str] | None,
    audio_filename: str | None,
    cancel_check: Callable[[], bool] | None,
    reported_duration_seconds: float | None = None,
) -> tuple[dict[str, Any], Path]:
    spec = record.get("spec") if isinstance(record.get("spec"), Mapping) else {}
    publication = _publication(record)
    source = Path(audio_path) if audio_path else None
    filename = str(audio_filename or publication.get("audio_filename") or (source.name if source else "")).strip()
    if not filename or "/" in filename or "\\" in filename:
        raise MusicFinalizationError("audio_filename must be a portable file name")
    destination = Path(workspace_dir) / filename
    if source and source.is_file() and source.resolve() != destination.resolve():
        if cancel_check and cancel_check() and not destination.is_file():
            raise MusicFinalizationCancelled()
        shutil.copyfile(source, destination)
    if not destination.is_file():
        raise MusicFinalizationError(f"Audio bytes are missing: {filename}", 409)
    measured = _measure_wav_seconds(destination)
    if measured is None:
        measured = _coerce_duration(reported_duration_seconds)
        if measured is None:
            measured = _coerce_duration(publication.get("measured_duration_seconds"))
    publication.update({
        "stage": "bytes",
        "audio_filename": filename,
        "measured_duration_seconds": measured,
        "requested_duration_seconds": spec.get("duration_seconds"),
        "visible_version": publication.get("visible_version") or 1,
    })
    record = dict(record)
    record["publication"] = publication
    record["status"] = "bytes_ready"
    return store.replace(record), destination


def _stage_manifest(store: MusicSubmissionStore, record: dict[str, Any], destination: Path) -> dict[str, Any]:
    spec = record.get("spec") if isinstance(record.get("spec"), Mapping) else {}
    publication = _publication(record)
    sidecar = {
        "job_id": record.get("job_id"),
        "task_id": record.get("task_id"),
        "generation_id": record.get("generation_id"),
        "candidate_id": record.get("candidate_id"),
        "params": {
            "prompt": spec.get("prompt"),
            "lyrics": spec.get("lyrics"),
            "model": spec.get("model"),
            "requested_duration_seconds": publication.get("requested_duration_seconds"),
            "measured_duration_seconds": publication.get("measured_duration_seconds"),
        },
    }
    try:
        written = publish_generation_sidecar(
            destination,
            sidecar,
            output_folder=spec.get("output_folder"),
            workspace_id=spec.get("workspace_id"),
            project={"id": spec.get("project_id"), "kind": "story"} if spec.get("project_id") else None,
            tool="story_lab",
            actor="unknown",
            capability="generate_story_song",
        )
    except Exception as exc:
        return _mark_repair(store, record, str(exc))
    generation = build_generation_record(
        generation_id=str(record.get("generation_id")),
        product="story_lab",
        output_folder=spec.get("output_folder"),
        workspace_id=spec.get("workspace_id"),
        project_id=spec.get("project_id"),
        cue_id=spec.get("cue_id"),
        candidate_id=record.get("candidate_id"),
        song_version=str(publication.get("visible_version") or 1),
        prompt_full=spec.get("prompt"),
        prompt_original=spec.get("lyrics"),
        model={"id": spec.get("model")},
        status="completed",
        links={"task_id": record.get("task_id"), "job_id": record.get("job_id")},
        result={
            "kind": "complete",
            "filename": publication.get("audio_filename"),
            "duration_seconds": publication.get("measured_duration_seconds"),
        },
        capability="generate_story_song",
    )
    publication["generation_record"] = {
        "generation_id": generation.get("generation_id"),
        "asset_id": generation.get("asset_id"),
        "song_version": generation.get("song_version"),
    }
    publication["sidecar"] = str(written)
    publication["stage"] = "manifest"
    record = dict(record)
    record["publication"] = publication
    return store.replace(record)


def _attach_candidate_row(workspace_dir: str, record: Mapping[str, Any], *, select: bool, revision: int) -> None:
    spec = record.get("spec") if isinstance(record.get("spec"), Mapping) else {}
    publication = _publication(record)
    filename = str(publication.get("audio_filename") or "")
    attach_story_song_candidate(
        workspace_dir,
        project_id=str(spec.get("project_id") or ""),
        cue_id=str(spec.get("cue_id") or ""),
        candidate_id=str(record.get("candidate_id") or ""),
        source=f"/api/v1/file/{filename}",
        filename=filename,
        status="ready",
        base_revision=revision,
        duration_seconds=publication.get("measured_duration_seconds"),
        task_id=str(record.get("task_id") or ""),
        root_task_id=str(record.get("task_id") or ""),
        job_id=str(record.get("job_id") or ""),
        update_selection=select,
    )


def _stage_candidate(store: MusicSubmissionStore, record: dict[str, Any], workspace_dir: str) -> dict[str, Any]:
    spec = record.get("spec") if isinstance(record.get("spec"), Mapping) else {}
    library = read_story_library(workspace_dir)
    select = _should_select(library, {**spec, "candidate_id": record.get("candidate_id")})
    revision = spec.get("library_revision")
    if revision is None:
        revision = library.get("revision") or 0
    try:
        _attach_candidate_row(workspace_dir, record, select=select, revision=int(revision))
    except StoryLibraryRevisionConflict:
        latest = read_story_library(workspace_dir)
        _attach_candidate_row(
            workspace_dir, record, select=select, revision=int(latest.get("revision") or 0),
        )
    publication = _publication(record)
    publication["stage"] = "candidate"
    record = dict(record)
    record["publication"] = publication
    record["status"] = "published"
    return store.replace(record)


def finalize_reserved_music(
    *,
    workspace_dir: str,
    generation_id: str,
    audio_path: str | os.PathLike[str] | None = None,
    audio_filename: str | None = None,
    cancel_check: Callable[[], bool] | None = None,
    fail_after: str | None = None,
    reported_duration_seconds: float | None = None,
) -> dict[str, Any]:
    """Publish reserved IDs to disk + Story. Safe to repeat."""
    store = MusicSubmissionStore(workspace_dir)
    record = store.get_by_generation_id(generation_id)
    if record is None:
        raise MusicFinalizationError(f"Unknown music generation {generation_id}", 404)
    publication = _publication(record)
    if str(record.get("status") or "") in TERMINAL_SKIP and not publication.get("audio_filename"):
        raise MusicFinalizationCancelled()
    if cancel_check and cancel_check() and not publication.get("audio_filename") and not audio_filename and not audio_path:
        record = dict(record)
        record["status"] = "cancelled"
        return store.replace(record)
    if publication.get("stage") == "candidate" and publication.get("audio_filename"):
        return record
    record, destination = _stage_bytes(
        store, record,
        workspace_dir=workspace_dir,
        audio_path=audio_path,
        audio_filename=audio_filename,
        cancel_check=cancel_check,
        reported_duration_seconds=reported_duration_seconds,
    )
    if fail_after == "bytes":
        raise MusicFinalizationError("injected failure after bytes", 500)
    record = _stage_manifest(store, record, destination)
    if record.get("status") == "repair_pending":
        return record
    if fail_after == "manifest":
        return _mark_repair(store, record, "injected failure after manifest")
    if fail_after == "candidate":
        return _mark_repair(store, record, "injected failure after manifest before candidate")
    return _stage_candidate(store, record, workspace_dir)
