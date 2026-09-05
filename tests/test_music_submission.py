"""Model-free coverage for idempotent music submission before inference."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app.services.music_submission import (
    LOCAL_MODELS,
    REMOTE_MODELS,
    MusicSubmissionConflict,
    MusicSubmissionError,
    classify_music_route,
    public_music_job,
    spec_hash,
    spec_snapshot,
    submit_music_generation,
    verify_story_destination,
)
from app.services.story_library import write_story_library
from app.services.task_manager import TaskRegistry


def _request(**overrides):
    payload = {
        "prompt": "cinematic dream pop",
        "lyrics": "[Verse]\nLa noche canta",
        "model": "music-3.0",
        "count": 1,
        "output_folder": "night-shift",
        "idempotency_key": "cmd-same-once",
    }
    payload.update(overrides)
    return payload


def _write_library(tmp_path: Path, **project_fields):
    project = {
        "id": "story-1",
        "title": "Night Choir",
        "language": "Español",
        "music": {
            "cues": [{
                "id": "cue-1",
                "title": "Opening",
                "candidates": [{"id": "song-1", "status": "pending"}],
            }],
        },
    }
    project.update(project_fields)
    write_story_library(
        str(tmp_path),
        {"version": 2, "revision": 0, "activeId": "story-1", "projects": {"story-1": project}},
        base_revision=0,
    )


def test_inventory_keeps_local_and_remote_routes():
    assert classify_music_route("ace_step_v1_5_xl_sft_lm_4b") == "local"
    assert classify_music_route("minimax_music3") == "local"
    assert classify_music_route("music-3.0") == "remote_minimax"
    assert "music-2.6" in REMOTE_MODELS
    assert "minimax_music3" in LOCAL_MODELS
    with pytest.raises(MusicSubmissionError, match="Unsupported"):
        classify_music_route("unknown-model")


def test_same_key_and_spec_replays_without_a_second_task(tmp_path: Path):
    first = submit_music_generation(workspace_dir=str(tmp_path), request=_request())
    second = submit_music_generation(workspace_dir=str(tmp_path), request=_request())
    assert first["replay"] is False
    assert second["replay"] is True
    assert second["job_id"] == first["job_id"]
    assert second["task_id"] == first["task_id"]
    assert second["generation_id"] == first["generation_id"]
    assert second["candidate_id"] == first["candidate_id"]
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    assert registry.get(first["task_id"])["id"] == first["task_id"]


def test_same_key_different_spec_conflicts(tmp_path: Path):
    submit_music_generation(workspace_dir=str(tmp_path), request=_request())
    with pytest.raises(MusicSubmissionConflict):
        submit_music_generation(
            workspace_dir=str(tmp_path),
            request=_request(lyrics="[Verse]\nOtra letra"),
        )


def test_explicit_retry_mints_a_new_attempt_with_lineage(tmp_path: Path):
    first = submit_music_generation(workspace_dir=str(tmp_path), request=_request())
    retry = submit_music_generation(
        workspace_dir=str(tmp_path),
        request=_request(retry=True, parent_generation_id=first["generation_id"]),
    )
    assert retry["job_id"] != first["job_id"]
    assert retry["generation_id"] != first["generation_id"]
    assert retry["intent"] == "retry"
    assert retry["parent_generation_id"] == first["generation_id"]


def test_missing_project_id_is_not_resolved_by_title(tmp_path: Path):
    _write_library(tmp_path)
    with pytest.raises(MusicSubmissionError, match="was not found"):
        submit_music_generation(
            workspace_dir=str(tmp_path),
            request=_request(
                project_id="Night Choir",
                cue_id="cue-1",
                candidate_id="song-1",
            ),
        )
    accepted = submit_music_generation(
        workspace_dir=str(tmp_path),
        request=_request(
            idempotency_key="cmd-existing-ids",
            project_id="story-1",
            cue_id="cue-1",
            candidate_id="song-1",
        ),
    )
    assert accepted["spec"]["project_id"] == "story-1"


def test_stale_library_revision_conflicts(tmp_path: Path):
    _write_library(tmp_path)
    with pytest.raises(MusicSubmissionConflict, match="revision"):
        submit_music_generation(
            workspace_dir=str(tmp_path),
            request=_request(
                idempotency_key="cmd-rev",
                project_id="story-1",
                cue_id="cue-1",
                candidate_id="song-1",
                library_revision=99,
            ),
        )


def test_failure_after_reserve_still_returns_queryable_ids(tmp_path: Path):
    def boom(_record):
        raise RuntimeError("worker did not start")

    record = submit_music_generation(
        workspace_dir=str(tmp_path),
        request=_request(),
        after_persist=boom,
    )
    assert record["job_id"]
    assert record["start_error"]
    replay = submit_music_generation(workspace_dir=str(tmp_path), request=_request())
    assert replay["replay"] is True
    assert replay["job_id"] == record["job_id"]
    public = public_music_job(record)
    assert public["status"] == "queued"
    assert public["jobId"] == record["job_id"]


def test_concurrent_duplicate_posts_share_one_job(tmp_path: Path):
    results: list[dict] = []

    def worker():
        results.append(submit_music_generation(workspace_dir=str(tmp_path), request=_request()))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    job_ids = {item["job_id"] for item in results}
    assert len(job_ids) == 1
    assert sum(1 for item in results if not item["replay"]) == 1


def test_spec_hash_is_stable_and_ignores_transport_noise():
    first = spec_snapshot(_request(idempotency_key="a"))
    second = spec_snapshot(_request(idempotency_key="b"))
    assert spec_hash(first) == spec_hash(second)
    assert first["output_folder"] == "night-shift"
    assert first["workspace_id"] is None
