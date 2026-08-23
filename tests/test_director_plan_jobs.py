"""Durable restart/resume regressions for bounded Director planning."""

from __future__ import annotations

import json
import re

import pytest

from app.services.director.planners.music_video import MusicVideoPlanner
from app.services.director_plan_jobs import (
    DirectorPlanJobStore,
    build_director_plan_failure_detail,
    claim_director_plan_job,
    release_director_plan_job,
)


def _shot(index: int) -> dict:
    return {
        "clip_index": index,
        "scene_goal": f"Durable narrative beat {index}",
        "scene_type": "narrative",
        "subjects_on_screen": [],
        "environment": "A coherent neon transit hub",
        "visual_style": "cinematic retro future",
        "lighting": "soft cyan practical light",
        "mood": "determined",
        "action_beats": ["The performer crosses the platform"],
        "camera_plan": {
            "framing": "medium shot",
            "movement": "slow tracking move",
            "movement_intensity": "subtle",
        },
        "ending_beat": "The train doors open",
        "image_source": "original",
        "image_prompt": f"A complete static first frame at the transit hub for clip {index}.",
        "visual_changes": ["The train arrives"],
        "video_prompt": f"The camera tracks the performer as the train arrives for clip {index}.",
        "keyframe_prompts": [],
        "window_prompts": [],
    }


def _requested_indices(prompt: str) -> list[int]:
    match = re.search(r"Requested clip indexes: ([0-9, ]+)", prompt)
    assert match is not None
    return [int(value) for value in match.group(1).split(", ")]


def _clips(count: int) -> list[dict]:
    return [
        {"start": index * 4, "end": (index + 1) * 4, "label": "verse", "beat_count": 8}
        for index in range(count)
    ]


def test_restart_after_third_batch_resumes_without_recalling_completed_indexes(tmp_path):
    store = DirectorPlanJobStore(str(tmp_path))
    job = store.create(
        {"scene_description": "A durable city performance"},
        workspace="default",
        skill_type="music_video",
        total=41,
    )
    first_calls: list[list[int]] = []

    def first_generate(**kwargs):
        requested = _requested_indices(kwargs["prompt"])
        first_calls.append(requested)
        return json.dumps([_shot(index) for index in requested])

    class SimulatedRestart(RuntimeError):
        pass

    def first_checkpoint(event: dict):
        if event["event"] == "call_started":
            store.begin_call(
                job["jobId"],
                indices=event["indices"],
                phase=event["phase"],
            )
            return
        saved = store.record_batch(
            job["jobId"],
            indices=event["indices"],
            shot_plans=event["shot_plans"],
        )
        if len(saved["completedBatches"]) == 3:
            raise SimulatedRestart("process stopped after durable batch 3")

    with pytest.raises(SimulatedRestart):
        MusicVideoPlanner(llm_generate=first_generate).plan(
            clips=_clips(41),
            scene_description="A durable city performance",
            bpm=120,
            batch_checkpoint=first_checkpoint,
        )

    assert first_calls == [
        list(range(1, 9)),
        list(range(9, 17)),
        list(range(17, 25)),
    ]

    # A new store instance represents a recreated backend service.
    restarted_store = DirectorPlanJobStore(str(tmp_path))
    recovered = restarted_store.load(job["jobId"])
    assert recovered is not None
    assert recovered["completedIndices"] == list(range(1, 25))
    second_calls: list[list[int]] = []

    def second_generate(**kwargs):
        requested = _requested_indices(kwargs["prompt"])
        second_calls.append(requested)
        return json.dumps([_shot(index) for index in requested])

    def second_checkpoint(event: dict):
        if event["event"] == "call_started":
            restarted_store.begin_call(
                job["jobId"],
                indices=event["indices"],
                phase=event["phase"],
            )
        else:
            restarted_store.record_batch(
                job["jobId"],
                indices=event["indices"],
                shot_plans=event["shot_plans"],
            )

    plan = MusicVideoPlanner(llm_generate=second_generate).plan(
        clips=_clips(41),
        scene_description="A durable city performance",
        bpm=120,
        completed_shot_plans=recovered["completedShotPlans"],
        batch_checkpoint=second_checkpoint,
    )

    assert second_calls == [
        list(range(25, 33)),
        list(range(33, 41)),
        [41],
    ]
    assert len(plan.shots) == 41
    assert [shot.scene_goal for shot in plan.shots] == [
        f"Durable narrative beat {index}" for index in range(1, 42)
    ]
    completed = restarted_store.load(job["jobId"])
    assert completed is not None
    assert completed["completedIndices"] == list(range(1, 42))
    assert completed["calls"] == 6
    assert restarted_store.public_snapshot(completed)["missingIndices"] == []


def test_checkpoint_never_overwrites_a_completed_clip(tmp_path):
    store = DirectorPlanJobStore(str(tmp_path))
    job = store.create({}, workspace="default", skill_type="music_video", total=1)
    store.record_batch(job["jobId"], indices=[1], shot_plans=[_shot(1)])
    conflicting = _shot(1)
    conflicting["scene_goal"] = "Conflicting replacement"

    with pytest.raises(ValueError, match="overwrite clip index 1"):
        store.record_batch(job["jobId"], indices=[1], shot_plans=[conflicting])

    reloaded = store.load(job["jobId"])
    assert reloaded is not None
    assert reloaded["completedShotPlans"][0]["scene_goal"] == "Durable narrative beat 1"
    assert "request" not in store.public_snapshot(reloaded)


def test_failure_contract_preserves_partial_batches_and_exposes_resume_action(tmp_path):
    store = DirectorPlanJobStore(str(tmp_path))
    job = store.create(
        {"scene_description": "A recoverable plan"},
        workspace="project with spaces",
        skill_type="music_video",
        total=10,
    )
    partial = store.record_batch(
        job["jobId"],
        indices=list(range(1, 9)),
        shot_plans=[_shot(index) for index in range(1, 9)],
    )
    failed = store.update(
        job["jobId"],
        status="failed",
        phase="failed",
        message="Music-video planning stopped; completed batches are recoverable",
        error="Provider stopped during the final batch",
    )

    detail = build_director_plan_failure_detail(failed)

    assert partial["completedIndices"] == list(range(1, 9))
    assert detail["code"] == "director_plan_incomplete"
    assert detail["message"] == "Provider stopped during the final batch"
    assert detail["job"]["completedIndices"] == list(range(1, 9))
    assert detail["job"]["missingIndices"] == [9, 10]
    assert detail["job"]["completedBatches"][0]["indices"] == list(range(1, 9))
    assert detail["resume"] == {
        "action": "resume_missing",
        "method": "POST",
        "path": (
            f"/api/v1/director/v2/plan/jobs/{job['jobId']}/resume"
            "?workspace=project%20with%20spaces"
        ),
    }
    assert detail["imagesQueued"] is False
    assert "request" not in detail["job"]


def test_job_ids_cannot_escape_the_workspace(tmp_path):
    store = DirectorPlanJobStore(str(tmp_path))
    with pytest.raises(ValueError, match="Invalid Director plan job id"):
        store.load("../outside")


def test_live_job_claim_is_atomic_but_releasable_for_restart_resume():
    job_id = "director-plan-atomic-claim"
    release_director_plan_job(job_id)
    assert claim_director_plan_job(job_id) is True
    assert claim_director_plan_job(job_id) is False
    release_director_plan_job(job_id)
    assert claim_director_plan_job(job_id) is True
    release_director_plan_job(job_id)
