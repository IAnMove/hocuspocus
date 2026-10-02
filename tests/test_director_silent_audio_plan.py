"""A shot the planner gave no audio plan is silent; its default plan must be one the H3 prompt contract accepts."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "app"))

from services.director.h3_dialogue import validate_h3_prompt_contract  # noqa: E402
from services.director.schema import ShotPlan  # noqa: E402


def test_a_shot_with_no_audio_plan_defaults_to_a_silent_plan_anchored_on_the_video():
    plan = ShotPlan.from_dict({"shot_id": "s1", "index": 0}).audio_plan.to_dict()
    assert plan == {"mode": "ambient_only", "timing_anchor": "video", "lip_sync_critical": False}


def test_that_default_passes_the_h3_silent_generation_check():
    # Comic films give no audio plan; with the old "balanced" default every shot failed planning with
    # "silent generation requires audio_plan.timing_anchor=video" before a single frame was prepared.
    plan = ShotPlan.from_dict({"shot_id": "s1", "index": 0}).audio_plan.to_dict()
    errors = validate_h3_prompt_contract("integrated_multimodal_description: a quiet shot", [], audio_plan=plan)
    assert not [error for error in errors if "audio_plan" in error], errors


def test_balanced_means_no_anchor_but_an_audio_anchor_still_contradicts_silent_generation():
    ok = validate_h3_prompt_contract("integrated_multimodal_description: a quiet shot", [],
                                     audio_plan={"mode": "ambient_only", "timing_anchor": "balanced", "lip_sync_critical": False})
    assert not [error for error in ok if "audio_plan" in error], ok
    bad = validate_h3_prompt_contract("integrated_multimodal_description: a quiet shot", [],
                                      audio_plan={"mode": "ambient_only", "timing_anchor": "audio", "lip_sync_critical": False})
    assert any("timing_anchor=video" in error for error in bad)


def test_a_comic_shot_with_speech_still_uses_a_silent_plan_h3_preflight_accepts():
    # Prepare PRE on a comic with speech bubbles used to die here: the planner
    # set audio_plan.mode=dialogue_driven without dialogue_beats, so H3 treated
    # the shot as silent and refused "unsupported audio_plan.mode".
    from services.director.h3_dialogue import compile_h3_clip_plans
    from services.director.planners.comic_movie import ComicMoviePlanner

    def no_llm(**_kwargs):
        return "not json"

    plan = ComicMoviePlanner(
        llm_generate=no_llm,
        llm_generate_streaming=no_llm,
    ).plan(
        comic_context="A finished comic.",
        comic_shots=[{
            "page_number": 1,
            "panel_number": 1,
            "duration": 3,
            "scene_description": "Mara opens the engine room.",
            "script": "[Mara] Not alone this time.",
            "camera_move": "push-in",
            "characters": ["Mara"],
            "renderer": "ltx",
        }],
    )
    shot = plan.shots[0]
    audio = shot.audio_plan.to_dict()
    assert audio == {
        "mode": "ambient_only",
        "timing_anchor": "video",
        "lip_sync_critical": False,
    }
    assert "Not alone this time" in (shot.metadata or {}).get("dialogue", "")
    clip = {
        "video_prompt": shot.video_prompt,
        "_director_audio_plan": audio,
        "_director_dialogue_beats": [],
        "_director_subjects_on_screen": [],
        "_director_duration_sec": shot.duration_sec,
    }
    compile_h3_clip_plans([clip])
    assert clip["video_prompt"]
