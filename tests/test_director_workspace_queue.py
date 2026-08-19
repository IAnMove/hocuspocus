"""Workspaces queue hydration and prompt edits for Director threads."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.abspath(os.path.join(_HERE, "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services import director_pipeline as pipeline  # noqa: E402


class TestDirectorWorkspaceQueue(unittest.TestCase):
    def test_planned_shots_become_a_visible_queue_when_clips_are_empty(self):
        hydrated = pipeline.hydrate_queue_clips({
            "pipeline_id": "song-fail",
            "status": "failed",
            "error": "Shot 9: silent visual field still contains affirmative vocal cues: habla",
            "clips": [],
            "clip_plans": [],
            "planned_clips": [
                {
                    "_director_h3_source_prompt": "Gandalf nunca habla.",
                    "duration_sec": 5.875,
                    "_director_audio_plan": {"mode": "music_driven"},
                },
                {
                    "_director_h3_source_prompt": "El MC cruza el muelle.",
                    "duration_sec": 6.5,
                },
            ],
        })

        self.assertEqual(hydrated["queue_source"], "planned")
        self.assertEqual(len(hydrated["clips"]), 2)
        self.assertEqual(hydrated["clips"][0]["video_prompt"], "Gandalf nunca habla.")
        self.assertEqual(hydrated["clips"][0]["duration_seconds"], 5.875)
        self.assertEqual(
            hydrated["clips"][0]["_director_audio_plan"],
            {"mode": "music_driven"},
        )

    def test_queue_plans_resume_from_planned_clips_after_preflight_failure(self):
        plans, planned = pipeline._queue_plans_from_saved_state({
            "clips": [],
            "clip_plans": [],
            "planned_clips": [{
                "_director_h3_source_prompt": "Gandalf never opens his mouth.",
                "_director_dialogue_beats": [],
                "duration_sec": 5.0,
            }],
        })

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["video_prompt"], "Gandalf never opens his mouth.")
        self.assertEqual(plans[0]["_director_h3_source_prompt"], "Gandalf never opens his mouth.")
        self.assertEqual(planned[0]["duration_sec"], 5.0)

    def test_prompt_edits_persist_onto_planned_clips(self):
        with tempfile.TemporaryDirectory() as output_dir:
            path = os.path.join(output_dir, "_director_pipeline_editme.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({
                    "pipeline_id": "editme",
                    "status": "failed",
                    "clips": [],
                    "clip_plans": [],
                    "planned_clips": [{
                        "_director_h3_source_prompt": "Old silent shot.",
                    }],
                }, handle)

            updated = pipeline.update_clip_prompts(
                output_dir,
                "editme",
                0,
                video_prompt="Edited closed-mouth shot.",
            )
            with open(path, encoding="utf-8") as handle:
                saved = json.loads(handle.read())

        self.assertEqual(updated["clips"][0]["video_prompt"], "Edited closed-mouth shot.")
        self.assertEqual(
            saved["planned_clips"][0]["_director_h3_source_prompt"],
            "Edited closed-mouth shot.",
        )

    def test_soundtrack_drive_toggle_persists_on_planned_clips(self):
        with tempfile.TemporaryDirectory() as output_dir:
            path = os.path.join(output_dir, "_director_pipeline_drive.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({
                    "pipeline_id": "drive",
                    "status": "completed",
                    "clips": [],
                    "clip_plans": [],
                    "planned_clips": [{
                        "_director_h3_source_prompt": "A dwarf faces camera.",
                        "_director_audio_plan": {
                            "mode": "audio_driven",
                            "lip_sync_critical": True,
                        },
                    }],
                }, handle)

            updated = pipeline.update_clip_prompts(
                output_dir,
                "drive",
                0,
                soundtrack_drive=False,
            )

        self.assertEqual(
            updated["clips"][0]["_director_audio_plan"]["mode"],
            "music_driven",
        )
        self.assertFalse(updated["clips"][0]["_director_audio_plan"]["lip_sync_critical"])
