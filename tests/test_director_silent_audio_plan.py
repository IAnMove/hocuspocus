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
