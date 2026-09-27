"""Story Music submit → task → generation record → asset, without a second scheduler."""
from __future__ import annotations

import wave
from pathlib import Path

from app.services.generation_record import GenerationRecordStore
from app.services.music_finalization import finalize_reserved_music
from app.services.music_submission import submit_music_generation
from app.services.story_library import write_story_library
from app.services.story_music_generation_record import (
    RECORDS_DIRNAME,
    load_story_music_generation_record,
)
from app.services.task_manager import TaskRegistry


def _request(**overrides):
    payload = {
        "prompt": "cinematic dream pop",
        "lyrics": "[Verse]\nLa noche canta",
        "model": "music-3.0",
        "count": 1,
        "output_folder": "night-shift",
        "idempotency_key": "cmd-g07-once",
    }
    payload.update(overrides)
    return payload


def _library(tmp_path: Path):
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
                            "candidates": [{"id": "song-1", "status": "pending"}],
                        }],
                    },
                },
            },
        },
        base_revision=0,
    )


def _wav(path: Path) -> Path:
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 2000)
    return path


def _store(tmp_path: Path) -> GenerationRecordStore:
    return GenerationRecordStore(tmp_path / RECORDS_DIRNAME)


def test_submit_writes_queued_record_linked_to_task_and_command(tmp_path: Path):
    reserved = submit_music_generation(workspace_dir=str(tmp_path), request=_request())
    record = load_story_music_generation_record(str(tmp_path), reserved)
    assert record is not None
    assert record["generation_id"] == reserved["generation_id"]
    assert record["status"] == "queued"
    assert record["product"] == "story_lab"
    assert record["correlations"]["task_id"] == reserved["task_id"]
    assert record["correlations"]["job_id"] == reserved["job_id"]
    assert record["correlations"]["command_id"] == reserved["command_id"]
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    task = registry.get(reserved["task_id"])
    assert task["id"] == reserved["task_id"]
    assert task["metadata"]["generation_id"] == reserved["generation_id"]
    listed = _store(tmp_path).list(output_folder="night-shift")
    assert [item["generation_id"] for item in listed] == [reserved["generation_id"]]


def test_replay_does_not_mint_a_second_generation_or_task(tmp_path: Path):
    first = submit_music_generation(workspace_dir=str(tmp_path), request=_request())
    second = submit_music_generation(workspace_dir=str(tmp_path), request=_request())
    assert second["replay"] is True
    assert second["generation_id"] == first["generation_id"]
    assert second["task_id"] == first["task_id"]
    listed = _store(tmp_path).list(output_folder="night-shift")
    assert len(listed) == 1
    assert listed[0]["generation_id"] == first["generation_id"]
    assert listed[0]["revision"] == 1


def test_retry_mints_a_child_record_and_keeps_parent(tmp_path: Path):
    first = submit_music_generation(workspace_dir=str(tmp_path), request=_request())
    retry = submit_music_generation(
        workspace_dir=str(tmp_path),
        request=_request(
            idempotency_key="cmd-g07-once:retry",
            retry=True,
            parent_generation_id=first["generation_id"],
        ),
    )
    child = load_story_music_generation_record(str(tmp_path), retry)
    parent = load_story_music_generation_record(str(tmp_path), first)
    assert child["generation_id"] != first["generation_id"]
    assert child["lineage"]["parents"][0]["generation_id"] == first["generation_id"]
    assert parent["lineage"]["derivatives"][0]["generation_id"] == retry["generation_id"]
    ids = {item["generation_id"] for item in _store(tmp_path).list(output_folder="night-shift")}
    assert ids == {first["generation_id"], retry["generation_id"]}


def test_finalize_completes_the_same_attempt_and_does_not_duplicate(tmp_path: Path):
    _library(tmp_path)
    reserved = submit_music_generation(
        workspace_dir=str(tmp_path),
        request=_request(project_id="story-1", cue_id="cue-1", candidate_id="song-1"),
    )
    audio = _wav(tmp_path / "opening.wav")
    published = finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=reserved["generation_id"],
        audio_path=audio,
    )
    again = finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=reserved["generation_id"],
        audio_path=audio,
    )
    record = load_story_music_generation_record(str(tmp_path), published)
    assert again["generation_id"] == reserved["generation_id"]
    assert record["status"] == "completed"
    assert record["generation_id"] == reserved["generation_id"]
    assert record["location"]["filename"] == "opening.wav"
    assert record["result"]["kind"] == "complete"
    listed = _store(tmp_path).list(output_folder="night-shift")
    assert len(listed) == 1


def test_cancel_before_bytes_settles_the_same_attempt(tmp_path: Path):
    reserved = submit_music_generation(workspace_dir=str(tmp_path), request=_request())
    published = finalize_reserved_music(
        workspace_dir=str(tmp_path),
        generation_id=reserved["generation_id"],
        cancel_check=lambda: True,
    )
    assert published["status"] == "cancelled"
    record = load_story_music_generation_record(str(tmp_path), published)
    assert record["status"] == "cancelled"
    assert record["generation_id"] == reserved["generation_id"]
    listed = _store(tmp_path).list(output_folder="night-shift")
    assert len(listed) == 1
