"""Model-free coverage for reserved music finalization."""
from __future__ import annotations

import wave
from pathlib import Path

import pytest

from app.services.music_finalization import (
    MusicFinalizationCancelled,
    MusicFinalizationError,
    finalize_reserved_music,
    reconcile_reserved_music,
)
from app.services.music_submission import submit_music_generation
from app.services.story_library import read_story_library, write_story_library


def _wav(path: Path, *, seconds: float = 0.25, rate: int = 8000) -> Path:
    frames = int(rate * seconds)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)
    return path


def _library(tmp_path: Path, **candidate_fields):
    candidate = {"id": "song-1", "status": "pending", "source": "", "name": ""}
    candidate.update(candidate_fields)
    write_story_library(
        str(tmp_path),
        {
            "version": 2,
            "revision": 0,
            "activeId": "story-1",
            "projects": {
                "story-1": {
                    "id": "story-1",
                    "title": "Night Choir",
                    "music": {
                        "cues": [{
                            "id": "cue-1",
                            "title": "Opening",
                            "candidates": [candidate],
                        }],
                    },
                },
            },
        },
        base_revision=0,
    )


def _submit(tmp_path: Path, **overrides):
    request = {
        "prompt": "cinematic dream pop",
        "lyrics": "[Verse]\nLa noche canta",
        "model": "music-3.0",
        "count": 1,
        "output_folder": "night-shift",
        "idempotency_key": "cmd-final-1",
        "project_id": "story-1",
        "cue_id": "cue-1",
        "candidate_id": "song-1",
    }
    request.update(overrides)
    return submit_music_generation(workspace_dir=str(tmp_path), request=request)


def test_finalize_writes_bytes_manifest_and_correct_candidate(tmp_path: Path):
    _library(tmp_path)
    reserved = _submit(tmp_path)
    audio = _wav(tmp_path / "opening.wav")
    published = finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=reserved["generation_id"],
        audio_path=audio,
    )
    assert published["status"] == "published"
    assert published["publication"]["stage"] == "candidate"
    assert published["publication"]["measured_duration_seconds"] == 0.25
    assert published["publication"]["requested_duration_seconds"] is None
    assert published["publication"]["visible_version"] == 1
    library = read_story_library(str(tmp_path))
    cue = library["projects"]["story-1"]["music"]["cues"][0]
    assert cue["candidates"][0]["id"] == "song-1"
    assert cue["candidates"][0]["status"] == "ready"
    assert cue["candidates"][0]["name"] == "opening.wav"
    assert cue["selectedCandidateId"] == "song-1"
    assert (tmp_path / "opening.wav").is_file()
    sidecar = Path(published["publication"]["sidecar"])
    assert sidecar.is_file()


def test_finalize_is_idempotent_and_does_not_duplicate(tmp_path: Path):
    _library(tmp_path)
    reserved = _submit(tmp_path)
    audio = _wav(tmp_path / "opening.wav")
    first = finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=reserved["generation_id"],
        audio_path=audio,
    )
    second = finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=reserved["generation_id"],
        audio_path=audio,
    )
    assert first["publication"]["audio_filename"] == second["publication"]["audio_filename"]
    library = read_story_library(str(tmp_path))
    assert len(library["projects"]["story-1"]["music"]["cues"][0]["candidates"]) == 1


def test_metadata_failure_keeps_bytes_and_marks_repair(tmp_path: Path):
    _library(tmp_path)
    reserved = _submit(tmp_path)
    audio = _wav(tmp_path / "opening.wav")
    broken = finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=reserved["generation_id"],
        audio_path=audio,
        fail_after="manifest",
    )
    assert broken["status"] == "repair_pending"
    assert (tmp_path / "opening.wav").is_file()
    library = read_story_library(str(tmp_path))
    assert library["projects"]["story-1"]["music"]["cues"][0]["candidates"][0]["status"] == "pending"
    recovered = finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=reserved["generation_id"],
        audio_filename="opening.wav",
    )
    assert recovered["status"] == "published"
    assert recovered["publication"]["stage"] == "candidate"


def test_injected_crash_after_bytes_is_reconcilable_without_inference(tmp_path: Path):
    _library(tmp_path)
    reserved = _submit(tmp_path)
    audio = _wav(tmp_path / "opening.wav")
    with pytest.raises(MusicFinalizationError, match="after bytes"):
        finalize_reserved_music(
            workspace_dir=str(tmp_path),
            generation_id=reserved["generation_id"],
            audio_path=audio,
            fail_after="bytes",
        )
    report = reconcile_reserved_music(str(tmp_path), reserved["generation_id"])
    assert report["bytes_present"] is True
    assert report["needs_inference"] is False
    assert report["stage"] == "bytes"


def test_cancel_before_bytes_does_not_publish(tmp_path: Path):
    _library(tmp_path)
    reserved = _submit(tmp_path)
    cancelled = finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=reserved["generation_id"],
        cancel_check=lambda: True,
    )
    assert cancelled["status"] == "cancelled"
    library = read_story_library(str(tmp_path))
    assert library["projects"]["story-1"]["music"]["cues"][0]["candidates"][0]["status"] == "pending"


def test_does_not_steal_a_selection_the_user_changed(tmp_path: Path):
    _library(tmp_path)
    library = read_story_library(str(tmp_path))
    project = library["projects"]["story-1"]
    project["music"]["cues"][0]["candidates"].append({
        "id": "song-keep",
        "status": "ready",
        "source": "/api/v1/file/keep.wav",
        "name": "keep.wav",
    })
    project["music"]["cues"][0]["selectedCandidateId"] = "song-keep"
    write_story_library(str(tmp_path), library, base_revision=library["revision"])
    reserved = _submit(tmp_path)
    audio = _wav(tmp_path / "opening.wav")
    finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=reserved["generation_id"],
        audio_path=audio,
    )
    cue = read_story_library(str(tmp_path))["projects"]["story-1"]["music"]["cues"][0]
    assert cue["selectedCandidateId"] == "song-keep"
    by_id = {row["id"]: row for row in cue["candidates"]}
    assert by_id["song-1"]["status"] == "ready"


def test_two_generations_of_the_same_cue_keep_distinct_rows(tmp_path: Path):
    _library(tmp_path)
    library = read_story_library(str(tmp_path))
    library["projects"]["story-1"]["music"]["cues"][0]["candidates"].append({
        "id": "song-2", "status": "pending", "source": "", "name": "",
    })
    write_story_library(str(tmp_path), library, base_revision=library["revision"])
    first = _submit(tmp_path, idempotency_key="cmd-a", candidate_id="song-1")
    second = _submit(tmp_path, idempotency_key="cmd-b", candidate_id="song-2")
    finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=first["generation_id"],
        audio_path=_wav(tmp_path / "one.wav"),
    )
    finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=second["generation_id"],
        audio_path=_wav(tmp_path / "two.wav"),
    )
    cue = read_story_library(str(tmp_path))["projects"]["story-1"]["music"]["cues"][0]
    names = {row["id"]: row["name"] for row in cue["candidates"]}
    assert names["song-1"] == "one.wav"
    assert names["song-2"] == "two.wav"
    assert first["generation_id"] != second["generation_id"]


def test_unknown_generation_fails_closed(tmp_path: Path):
    with pytest.raises(MusicFinalizationError, match="Unknown"):
        finalize_reserved_music(workspace_dir=str(tmp_path), generation_id="gen-missing")


def test_non_wav_keeps_worker_reported_duration(tmp_path: Path):
    _library(tmp_path)
    reserved = _submit(tmp_path)
    audio = tmp_path / "opening.mp3"
    audio.write_bytes(b"ID3" + b"\x00" * 32)
    published = finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=reserved["generation_id"],
        audio_path=audio,
        reported_duration_seconds=61.5,
    )
    assert published["publication"]["measured_duration_seconds"] == 61.5
    cue = read_story_library(str(tmp_path))["projects"]["story-1"]["music"]["cues"][0]
    assert cue["candidates"][0]["durationSeconds"] == 61.5


def test_wav_measurement_wins_over_reported_duration(tmp_path: Path):
    _library(tmp_path)
    reserved = _submit(tmp_path)
    published = finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=reserved["generation_id"],
        audio_path=_wav(tmp_path / "opening.wav"),
        reported_duration_seconds=99,
    )
    assert published["publication"]["measured_duration_seconds"] == 0.25
