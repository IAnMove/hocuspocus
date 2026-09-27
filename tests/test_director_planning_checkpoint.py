"""Resumable Director planning: completed LLM steps are reused on resume."""

from __future__ import annotations

import copy
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.abspath(os.path.join(_HERE, "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services.director.planners.short_film import ShortFilmPlanner  # noqa: E402

_SCREENPLAY = """INT. PLAYROOM - DAY

BUSTER
I am the storm.
"""
_BIBLE = [{
    "character_name": "Buster",
    "personality_engine": "Tiny bravado hides nerves",
    "speech_pattern": "Short declarative lines",
    "relationship_behavior": "Talks to the room like an audience",
    "performance_direction": "low, steady, dramatic",
    "avoid": "long speeches",
}]
_TABLE_READ = [{
    "turn": 1,
    "speaker_name": "Buster",
    "original_text": "I am the storm.",
    "revised_text": "I am the storm.",
    "delivery": "low and steady",
}]


def _shot() -> dict:
    return {
        "title": "Buster walks out",
        "duration_sec": 10,
        "scene_goal": "Buster leaves the explosion",
        "narrative_role": "climax",
        "scene_type": "dialogue",
        "continuity_strategy": "independent",
        "continuity_group": "playroom_day",
        "subjects_on_screen": [{
            "visual_description": "a small fluffy brown teddy bear in aviator sunglasses",
            "character_id": "buster",
            "speaker_name": "Buster",
            "position_or_relation": "screen-center foreground, walking toward camera",
            "wardrobe": "miniature aviator sunglasses",
        }],
        "spatial_setup": "Buster walks screen-center foreground.",
        "environment": "a messy child's playroom",
        "visual_style": "cinematic macro photography",
        "lighting": "warm backlight through glitter",
        "mood": "heroic",
        "action_beats": ["Buster walks toward camera."],
        "dialogue_beats": [{
            "speaker_id": "buster",
            "spoken_text": "I am the storm.",
            "delivery": "low and steady",
            "physical_cue": "Buster visibly speaks.",
            "priority": "high",
        }],
        "camera_plan": {
            "framing": "low medium shot",
            "movement": "slow pull back",
            "movement_intensity": "subtle",
        },
        "audio_plan": {
            "mode": "dialogue_driven",
            "ambience": "settling confetti",
            "effects": [],
            "vocal_style": "natural",
            "timing_anchor": "audio",
            "lip_sync_critical": True,
        },
        "ending_beat": "Buster stops in the light.",
        "closing_blocking": "Buster stands center foreground.",
        "video_prompt": (
            "Buster speaks <d>[English] I am the storm.</d>. "
            "overall_soundscape: Settling confetti. "
            "non_diegetic_music: N/A."
        ),
        "multishot": False,
        "window_prompts": [],
    }


class _FakeLLM:
    """Answers each planner step and records which steps were called."""

    def __init__(self, fail_on: str | None = None):
        self.calls: list[str] = []
        self.fail_on = fail_on

    def __call__(self, **kwargs):
        system = kwargs["system_prompt"]
        if "character and dialogue editor" in system:
            step, answer = "voice_bible", json.dumps(_BIBLE)
        elif "acclaimed screenwriter" in system:
            step, answer = "screenplay", _SCREENPLAY
        elif "H3 CHARACTER TABLE-READ" in system:
            step, answer = "table_read", json.dumps(_TABLE_READ)
        else:
            step, answer = "shot_plan", json.dumps([_shot()])
        self.calls.append(step)
        if step == self.fail_on:
            raise RuntimeError(f"simulated {step} failure")
        return answer


def _plan(llm: _FakeLLM, checkpoint=None, sink=None, target_duration=10):
    planner = ShortFilmPlanner(llm_generate=llm, llm_generate_streaming=llm)
    return planner.plan(
        story_description="Buster the teddy bear walks away from a glitter explosion.",
        target_duration=target_duration,
        target_scenes=1,
        video_model="minimax_h3",
        shot_image_policy="prompt_only",
        fps=24,
        frames_steps=17,
        frames_minimum=124,
        frames_maximum=345,
        planning_checkpoint=checkpoint,
        planning_checkpoint_sink=sink,
    )


class PlanningCheckpointTests(unittest.TestCase):
    def test_resume_after_shot_plan_failure_reuses_earlier_steps(self):
        saved: list[dict] = []
        failing = _FakeLLM(fail_on="shot_plan")
        with self.assertRaises(RuntimeError):
            _plan(failing, sink=saved.append)
        stages = set(saved[-1]["stages"])
        self.assertTrue({"h3_voice_bible", "screenplay", "h3_dialogue_manifest"} <= stages)
        self.assertNotIn("h3_shot_dicts", stages)

        resumed = _FakeLLM()
        plan = _plan(resumed, checkpoint=copy.deepcopy(saved[-1]), sink=saved.append)

        self.assertEqual(resumed.calls, ["shot_plan"])
        self.assertEqual(
            [b.spoken_text for s in plan.shots for b in s.dialogue_beats],
            ["I am the storm."],
        )
        self.assertIn("h3_shot_dicts", saved[-1]["stages"])

    def test_completed_shot_list_skips_every_llm_step(self):
        saved: list[dict] = []
        first = _plan(_FakeLLM(), sink=saved.append)

        resumed = _FakeLLM(fail_on="voice_bible")
        plan = _plan(resumed, checkpoint=copy.deepcopy(saved[-1]))

        self.assertEqual(resumed.calls, [])
        self.assertEqual(
            [s.video_prompt for s in plan.shots],
            [s.video_prompt for s in first.shots],
        )

    def test_changed_request_ignores_saved_checkpoint(self):
        saved: list[dict] = []
        _plan(_FakeLLM(), sink=saved.append)

        fresh = _FakeLLM()
        _plan(fresh, checkpoint=copy.deepcopy(saved[-1]), target_duration=12)

        self.assertEqual(fresh.calls[:2], ["voice_bible", "screenplay"])

    def test_regenerated_step_drops_later_checkpoints(self):
        saved: list[dict] = []
        _plan(_FakeLLM(), sink=saved.append)
        partial = copy.deepcopy(saved[-1])
        del partial["stages"]["screenplay"]

        resumed_saves: list[dict] = []
        resumed = _FakeLLM()
        _plan(resumed, checkpoint=partial, sink=resumed_saves.append)

        # Voice bible is reused; everything after the regenerated screenplay reruns.
        self.assertEqual(resumed.calls[0], "screenplay")
        self.assertIn("shot_plan", resumed.calls)


if __name__ == "__main__":
    unittest.main()
