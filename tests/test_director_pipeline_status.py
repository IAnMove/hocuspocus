"""Regressions for reconnecting Director status polling after restarts."""

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


class TestDirectorPipelineStatusReconnect(unittest.TestCase):
    def setUp(self):
        self.previous_wgp = pipeline._wgp

    def tearDown(self):
        pipeline._pipelines.pop("deadbeef", None)
        pipeline._wgp = self.previous_wgp

    def test_saved_running_state_is_reported_as_failed_instead_of_404(self):
        with tempfile.TemporaryDirectory() as output_dir:
            state_path = os.path.join(
                output_dir,
                "_director_pipeline_deadbeef.json",
            )
            with open(state_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "pipeline_id": "deadbeef",
                    "status": "running",
                    "clips": [{
                        "video_prompt": "A saved shot.",
                        "start_image_filename": "",
                        "video_filename": "clip.mp4",
                    }],
                    "output_files": ["clip.mp4"],
                }, handle)

            status = pipeline.get_pipeline_status("deadbeef", output_dir)

        self.assertIsNotNone(status)
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["phase"], "failed")
        self.assertTrue(status["recovered_from_disk"])
        self.assertEqual(status["progress"]["current"], 1)
        self.assertEqual(status["progress"]["total"], 1)

    def test_live_pipeline_wins_over_saved_fallback(self):
        live = {
            "id": "deadbeef",
            "status": "running",
            "phase": "generating_video",
        }
        pipeline._pipelines["deadbeef"] = live

        with tempfile.TemporaryDirectory() as output_dir:
            status = pipeline.get_pipeline_status("deadbeef", output_dir)

        self.assertEqual(status, live)
        self.assertIsNot(status, live)

    def test_live_pipeline_reports_the_exact_frozen_models_and_recipe(self):
        class FakeWgp:
            @staticmethod
            def get_model_def(model_type):
                return {
                    "minimax_h3_legacy": {"name": "H3 Legacy ConvRot"},
                }.get(model_type, {})

        pipeline._wgp = FakeWgp()
        pipeline._pipelines["deadbeef"] = {
            "id": "deadbeef",
            "status": "running",
            "phase": "generating_video",
            "clip_plans": [{"video_prompt": "shot"}] * 3,
            "params": {
                "pipeline_type": "music_video",
                "writing_provider": "minimax",
                "writing_model": "MiniMax-M3",
                "image_model": "minimax:image-01",
                "image_params": {"resolution": "1280x720", "num_inference_steps": 8},
                "video_model": "minimax_h3_legacy",
                "video_params": {
                    "resolution": "960x544",
                    "num_inference_steps": 20,
                    "h3_model_profile": "quality",
                    "flow_shift": 12,
                    "h3_audio_shift": 3,
                    "minimax_h3_turbo_mode": False,
                },
            },
        }

        status = pipeline.get_pipeline_status("deadbeef", "/unused")
        details = status["generation_details"]

        self.assertEqual(details["video_model_type"], "minimax_h3_legacy")
        self.assertEqual(details["video_model_name"], "H3 Legacy ConvRot")
        self.assertEqual(details["video_resolution"], "960x544")
        self.assertEqual(details["video_steps"], 20)
        self.assertEqual(details["clip_count"], 3)
        self.assertFalse(details["turbo"])

    def test_planning_details_count_presegmented_shots_before_llm_returns(self):
        details = pipeline._public_pipeline_generation_details({
            "pipeline_type": "music_video",
            "writing_provider": "minimax",
            "writing_model": "MiniMax-M2.7-highspeed",
            "planned_clips": [{"start": 0, "end": 5}] * 21,
        })

        self.assertEqual(details["clip_count"], 21)
        message = pipeline._director_planning_progress_message(
            {
                "writing_provider": "minimax",
                "writing_model": "MiniMax-M2.7-highspeed",
            },
            "music_video",
            21,
        )
        self.assertIn("21 timed song segments", message)
        self.assertIn("video generation have not started", message)

    def test_recent_pipeline_feed_keeps_terminal_memory_states(self):
        pipeline_ids = ["terminaldone", "terminalfail", "terminalstop"]
        statuses = ["completed", "failed", "cancelled"]
        now = 1234.0
        for index, (pipeline_id, status) in enumerate(
            zip(pipeline_ids, statuses)
        ):
            pipeline._pipelines[pipeline_id] = {
                "id": pipeline_id,
                "workspace": "default",
                "status": status,
                "phase": status,
                "created_at": now + index,
                "updated_at": now + index + 10,
                "_completed_at": now + index + 10,
                "progress": {
                    "current": 1,
                    "total": 1,
                    "message": status,
                },
                "clip_plans": [{"video_prompt": "shot"}],
                "output_files": [f"{pipeline_id}.mp4"],
                "params": {
                    "pipeline_type": "music_video",
                    "video_model": "minimax_h3_legacy",
                },
            }

        try:
            with tempfile.TemporaryDirectory() as output_dir:
                recent = pipeline.list_recent_pipelines(
                    output_dir,
                    "default",
                )
        finally:
            for pipeline_id in pipeline_ids:
                pipeline._pipelines.pop(pipeline_id, None)

        by_id = {item["id"]: item for item in recent}
        self.assertEqual(
            {pipeline_id: by_id[pipeline_id]["status"] for pipeline_id in pipeline_ids},
            dict(zip(pipeline_ids, statuses)),
        )
        self.assertNotIn("params", by_id["terminaldone"])
        self.assertEqual(
            by_id["terminaldone"]["generation_details"]["video_model_type"],
            "minimax_h3_legacy",
        )

    def test_recent_pipeline_feed_recovers_terminal_checkpoint(self):
        with tempfile.TemporaryDirectory() as output_dir:
            state_path = os.path.join(
                output_dir,
                "_director_pipeline_savedfinal.json",
            )
            with open(state_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "pipeline_id": "savedfinal",
                    "workspace": "default",
                    "status": "failed",
                    "phase": "failed",
                    "created_at": 100.0,
                    "updated_at": 120.0,
                    "completed_at": 120.0,
                    "error": "render failed",
                    "progress": {
                        "current": 1,
                        "total": 2,
                        "message": "render failed",
                    },
                    "pipeline_type": "music_video",
                    "video_model": "minimax_h3_legacy",
                    "clips": [{"video_filename": "clip-1.mp4"}, {}],
                    "output_files": ["clip-1.mp4"],
                    "_params_snapshot": {
                        "pipeline_type": "music_video",
                        "video_model": "minimax_h3_legacy",
                        "video_params": {"resolution": "960x544"},
                    },
                }, handle)

            recent = pipeline.list_recent_pipelines(
                output_dir,
                "default",
            )

        saved = next(item for item in recent if item["id"] == "savedfinal")
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["completed_at"], 120.0)
        self.assertEqual(saved["error"], "render failed")
        self.assertEqual(saved["output_files"], ["clip-1.mp4"])
        self.assertEqual(
            saved["generation_details"]["video_resolution"],
            "960x544",
        )


if __name__ == "__main__":
    unittest.main()
