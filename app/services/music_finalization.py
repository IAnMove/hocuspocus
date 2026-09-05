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


def finalize_reserved_music(
    *,
    workspace_dir: str,
    generation_id: str,
    audio_path: str | os.PathLike[str] | None = None,
    audio_filename: str | None = None,
    cancel_check: Callable[[], bool] | None = None,
    fail_after: str | None = None,
) -> dict[str, Any]:
    """Publish reserved IDs to disk + Story. Safe to repeat."""
    store = MusicSubmissionStore(workspace_dir)
    record = store.get_by_generation_id(generation_id)
    if record is None:
        raise MusicFinalizationError(f"Unknown music generation {generation_id}", 404)
    if str(record.get("status") or "") in TERMINAL_SKIP and not _publication(record).get("audio_filename"):
        raise MusicFinalizationCancelled()
    if cancel_check and cancel_check() and not _publication(record).get("audio_filename") and not audio_filename and not audio_path:
        record = dict(record)
        record["status"] = "cancelled"
        return store.replace(record)

    spec = record.get("spec") if isinstance(record.get("spec"), Mapping) else {}
    publication = _publication(record)
    if publication.get("stage") == "candidate" and publication.get("audio_filename"):
        return record

    root = Path(workspace_dir)
    source = Path(audio_path) if audio_path else None
    filename = str(audio_filename or publication.get("audio_filename") or (source.name if source else "")).strip()
    if not filename or "/" in filename or "\\" in filename:
        raise MusicFinalizationError("audio_filename must be a portable file name")
    destination = root / filename
    if source and source.is_file() and source.resolve() != destination.resolve():
        if cancel_check and cancel_check() and not destination.is_file():
            raise MusicFinalizationCancelled()
        shutil.copyfile(source, destination)
    if not destination.is_file():
        raise MusicFinalizationError(f"Audio bytes are missing: {filename}", 409)

    measured = _measure_wav_seconds(destination)
    requested = spec.get("duration_seconds")
    publication.update({
        "stage": "bytes",
        "audio_filename": filename,
        "measured_duration_seconds": measured,
        "requested_duration_seconds": requested,
        "visible_version": publication.get("visible_version") or 1,
    })
    record = dict(record)
    record["publication"] = publication
    record["status"] = "bytes_ready"
    record = store.replace(record)
    if fail_after == "bytes":
        raise MusicFinalizationError("injected failure after bytes", 500)

    sidecar = {
        "job_id": record.get("job_id"),
        "task_id": record.get("task_id"),
        "generation_id": record.get("generation_id"),
        "candidate_id": record.get("candidate_id"),
        "params": {
            "prompt": spec.get("prompt"),
            "lyrics": spec.get("lyrics"),
            "model": spec.get("model"),
            "requested_duration_seconds": requested,
            "measured_duration_seconds": measured,
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
        publication["stage"] = "repair_pending"
        publication["repair_error"] = str(exc)[:500]
        record["publication"] = publication
        record["status"] = "repair_pending"
        return store.replace(record)

    if fail_after == "manifest":
        publication["stage"] = "repair_pending"
        publication["repair_error"] = "injected failure after manifest"
        record["publication"] = publication
        record["status"] = "repair_pending"
        return store.replace(record)

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
        result={"kind": "complete", "filename": filename, "duration_seconds": measured},
        capability="generate_story_song",
    )
    publication["generation_record"] = {
        "generation_id": generation.get("generation_id"),
        "asset_id": generation.get("asset_id"),
        "song_version": generation.get("song_version"),
    }
    publication["sidecar"] = str(written)
    publication["stage"] = "manifest"
    record["publication"] = publication
    record = store.replace(record)
    if fail_after == "candidate":
        publication["stage"] = "repair_pending"
        publication["repair_error"] = "injected failure after manifest before candidate"
        record["publication"] = publication
        record["status"] = "repair_pending"
        return store.replace(record)

    library = read_story_library(workspace_dir)
    select = _should_select(library, {**spec, "candidate_id": record.get("candidate_id")})
    revision = spec.get("library_revision")
    if revision is None:
        revision = library.get("revision") or 0
    try:
        attach_story_song_candidate(
            workspace_dir,
            project_id=str(spec.get("project_id") or ""),
            cue_id=str(spec.get("cue_id") or ""),
            candidate_id=str(record.get("candidate_id") or ""),
            source=f"/api/v1/file/{filename}",
            filename=filename,
            status="ready",
            base_revision=int(revision),
            duration_seconds=measured,
            task_id=str(record.get("task_id") or ""),
            root_task_id=str(record.get("task_id") or ""),
            job_id=str(record.get("job_id") or ""),
            update_selection=select,
        )
    except StoryLibraryRevisionConflict:
        latest = read_story_library(workspace_dir)
        attach_story_song_candidate(
            workspace_dir,
            project_id=str(spec.get("project_id") or ""),
            cue_id=str(spec.get("cue_id") or ""),
            candidate_id=str(record.get("candidate_id") or ""),
            source=f"/api/v1/file/{filename}",
            filename=filename,
            status="ready",
            base_revision=int(latest.get("revision") or 0),
            duration_seconds=measured,
            task_id=str(record.get("task_id") or ""),
            root_task_id=str(record.get("task_id") or ""),
            job_id=str(record.get("job_id") or ""),
            update_selection=select,
        )
    publication["stage"] = "candidate"
    record["publication"] = publication
    record["status"] = "published"
    return store.replace(record)
