"""MiniMax H3 model metadata and Comfy workflow regression tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services import minimax_h3_service as h3


class TestMiniMaxH3Workflow(unittest.TestCase):
    def test_reference_duration_converts_pyav_microseconds_to_seconds(self):
        class Container:
            duration = 14_083_333
            streams = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        fake_av = SimpleNamespace(
            time_base=1_000_000,
            open=lambda _source: Container(),
        )
        with patch.dict(sys.modules, {"av": fake_av}):
            self.assertAlmostEqual(h3._probe_duration("reference.mp4"), 14.083333)

    def test_runtime_enables_fused_triton_int8_backend(self):
        command = h3._runtime_command(43123, "balanced")

        self.assertIn("--enable-triton-backend", command)
        self.assertIn("--lowvram", command)
        self.assertEqual(command[command.index("--listen") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--port") + 1], "43123")

        quality_command = h3._runtime_command(43124, "quality")
        self.assertIn("--lowvram", quality_command)

    def test_text_to_video_uses_fl2va_and_native_audio(self):
        workflow, pipeline = h3.build_workflow({
            **h3.DEFAULTS,
            "prompt": "ocean at night; audio: surf",
        }, "jobt2v")

        self.assertEqual(pipeline, "fl2va")
        self.assertEqual(
            workflow["1"]["inputs"]["unet_name"],
            h3.MODEL_PROFILES["quality"]["fl2va"],
        )
        self.assertEqual(workflow["10"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertEqual(workflow["10"]["inputs"]["prompt"].lower().count("audio:"), 1)
        self.assertEqual(workflow["27"]["inputs"]["fps"], 24.0)
        self.assertEqual(workflow["27"]["inputs"]["audio"], ["26", 0])
        self.assertEqual(workflow["28"]["inputs"]["codec"], "auto")

    def test_profile_selects_matching_convrot_pair(self):
        workflow, _ = h3.build_workflow({
            **h3.DEFAULTS,
            "prompt": "quality test",
            "h3_model_profile": "quality",
        }, "jobquality")

        profile = h3.MODEL_PROFILES["quality"]
        self.assertEqual(workflow["1"]["inputs"]["unet_name"], profile["fl2va"])
        self.assertEqual(workflow["3"]["inputs"]["clip_name"], profile["text_encoder"])
        self.assertEqual(h3.DEFAULTS["resolution"], "960x544")
        self.assertEqual(h3.DEFAULTS["video_length"], 124)
        self.assertEqual(h3.DEFAULTS["num_inference_steps"], 20)
        self.assertEqual(h3.DEFAULTS["h3_model_profile"], "quality")
        self.assertEqual(h3.DEFAULTS["h3_reference_mode"], "first_frame")

    def test_legacy_balanced_profile_no_longer_silently_uses_int4(self):
        self.assertEqual(
            h3.MODEL_PROFILES["balanced"]["ref2va"],
            h3.MODEL_PROFILES["quality"]["ref2va"],
        )

    def test_community_dit_download_uses_hub_root_and_comfy_diffusion_folder(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(h3, "COMFY_DIR", Path(tmp) / "ComfyUI"), \
                patch("huggingface_hub.hf_hub_download") as download:
            h3._ensure_models("ref2va", "quality", lambda _message: None)

        dit_call = next(
            call for call in download.call_args_list
            if call.kwargs["repo_id"] == h3.COMMUNITY_HF_REPO
            and call.kwargs["filename"].startswith("MiniMax_H3_Ref2VA")
        )
        self.assertEqual(
            dit_call.kwargs["filename"],
            h3.MODEL_PROFILES["quality"]["ref2va"],
        )
        self.assertTrue(dit_call.kwargs["local_dir"].endswith("models/diffusion_models"))

    def test_visual_only_prompt_receives_recommended_audio_direction(self):
        workflow, _ = h3.build_workflow({
            **h3.DEFAULTS,
            "prompt": "a cyclist crosses a wet city street",
        }, "jobaudiodefault")

        prompt = workflow["10"]["inputs"]["prompt"]
        self.assertIn("Audio:", prompt)
        self.assertIn("clear, audible stereo mix", prompt)

    def test_authored_audio_clause_is_not_duplicated(self):
        prompt = "A quiet beach. Audio: gentle waves and gulls."
        workflow, _ = h3.build_workflow({
            **h3.DEFAULTS,
            "prompt": prompt,
            "h3_audio_prompt": "loud machinery",
        }, "jobaudioauthored")

        self.assertEqual(workflow["10"]["inputs"]["prompt"], prompt)

    def test_comfy_sampling_progress_is_exposed_to_maestro_jobs(self):
        update = h3._comfy_progress_event(json.dumps({
            "type": "progress",
            "data": {"value": 7, "max": 20, "prompt_id": "prompt-1", "node": "20"},
        }), "prompt-1")

        self.assertEqual(update, ("MiniMax H3 sampling — step 7/20", 40, 7, 20))
        self.assertIsNone(h3._comfy_progress_event(json.dumps({
            "type": "progress",
            "data": {"value": 7, "max": 20, "prompt_id": "another-prompt"},
        }), "prompt-1"))

    def test_first_and_last_frames_are_optional_fl2va_inputs(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(h3, "INPUT_DIR", Path(tmp) / "input"):
            first = Path(tmp) / "first.png"
            last = Path(tmp) / "last.png"
            first.write_bytes(b"first")
            last.write_bytes(b"last")
            workflow, pipeline = h3.build_workflow({
                **h3.DEFAULTS,
                "prompt": "transition",
                "image_start": str(first),
                "image_end": str(last),
            }, "jobfl")

        self.assertEqual(pipeline, "fl2va")
        inputs = workflow["10"]["inputs"]
        self.assertIn("first_frame", inputs)
        self.assertIn("last_frame", inputs)

    def test_all_reference_modalities_use_ref2va(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(h3, "INPUT_DIR", Path(tmp) / "input"), \
                patch.object(h3, "_probe_duration", return_value=5.0):
            files = {}
            for name in ("picture.png", "clip.mp4", "voice.wav"):
                path = Path(tmp) / name
                path.write_bytes(name.encode())
                files[name] = str(path)
            workflow, pipeline = h3.build_workflow({
                **h3.DEFAULTS,
                "prompt": "<Picture 1>, <Video 1>, <Audio 2>",
                "image_refs": [files["picture.png"]],
                "h3_ref_videos": [files["clip.mp4"]],
                "h3_ref_audios": [files["voice.wav"]],
                "h3_ref_image_size": "max",
                "h3_reference_mode": "references",
            }, "jobref")

        self.assertEqual(pipeline, "ref2va")
        self.assertEqual(
            workflow["1"]["inputs"]["unet_name"],
            h3.MODEL_PROFILES["quality"]["ref2va"],
        )
        inputs = workflow["10"]["inputs"]
        self.assertEqual(workflow["10"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertEqual(inputs["ref_image_size"], "max")
        self.assertIn("ref_images.ref_image_0", inputs)
        self.assertIn("ref_videos.ref_video_0", inputs)
        self.assertIn("ref_video_audios.ref_video_audio_0", inputs)
        self.assertIn("ref_audios.ref_audio_0", inputs)
        self.assertNotIn("ref_image_1", inputs)

    def test_audio_only_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(h3, "INPUT_DIR", Path(tmp) / "input"):
            audio = Path(tmp) / "voice.wav"
            audio.write_bytes(b"audio")
            with self.assertRaisesRegex(ValueError, "cannot use audio alone"):
                h3.build_workflow({
                    **h3.DEFAULTS,
                    "prompt": "voice",
                    "h3_ref_audios": [str(audio)],
                    "h3_reference_mode": "references",
                }, "jobaudio")

    def test_duration_is_clamped_and_aligned_to_17k_plus_5(self):
        workflow, _ = h3.build_workflow({
            **h3.DEFAULTS,
            "prompt": "test",
            "video_length": 200,
        }, "jobduration")
        length = workflow["10"]["inputs"]["length"]
        self.assertEqual(length % 17, 5)
        self.assertGreaterEqual(length, 107)
        self.assertLessEqual(length, 362)

    def test_oversized_resolution_is_reduced_to_open_base_canvas(self):
        workflow, _ = h3.build_workflow({
            **h3.DEFAULTS,
            "prompt": "test",
            "resolution": "1920x1080",
        }, "jobcanvas")
        inputs = workflow["10"]["inputs"]
        self.assertEqual((inputs["width"], inputs["height"]), (1344, 768))

    def test_reference_duration_limit_is_enforced_before_generation(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(h3, "INPUT_DIR", Path(tmp) / "input"), \
                patch.object(h3, "_probe_duration", return_value=16.0):
            picture = Path(tmp) / "picture.png"
            video = Path(tmp) / "long.mp4"
            picture.write_bytes(b"picture")
            video.write_bytes(b"video")
            with self.assertRaisesRegex(ValueError, "must each be 2–15 seconds"):
                h3.build_workflow({
                    **h3.DEFAULTS,
                    "prompt": "test",
                    "image_refs": [str(picture)],
                    "h3_ref_videos": [str(video)],
                    "h3_reference_mode": "references",
                }, "joblong")

    def test_first_frame_mode_rejects_silent_omni_reference_mixing(self):
        with tempfile.TemporaryDirectory() as tmp:
            picture = Path(tmp) / "picture.png"
            picture.write_bytes(b"picture")
            with self.assertRaisesRegex(ValueError, "cannot also use omni references"):
                h3.build_workflow({
                    **h3.DEFAULTS,
                    "prompt": "keep the first frame",
                    "image_refs": [str(picture)],
                }, "jobmixed")

    def test_quality_profile_retries_int4_only_after_an_oom(self):
        params = {**h3.DEFAULTS, "prompt": "test"}
        updates = []
        with patch.object(
            h3,
            "_generate_impl",
            side_effect=[RuntimeError("CUDA out of memory"), ["fallback.mp4"]],
        ) as generate_impl, patch.object(h3, "stop_runtime") as stop_runtime:
            result = h3.generate(
                params,
                "jobfallback",
                "/tmp",
                lambda *args: updates.append(args),
                lambda: False,
            )

        self.assertEqual(result, ["fallback.mp4"])
        self.assertEqual(generate_impl.call_count, 2)
        self.assertEqual(stop_runtime.call_count, 2)
        self.assertEqual(params["h3_model_profile"], "low_memory")
        self.assertEqual(params["h3_model_fallback_from"], "quality")
        self.assertTrue(any("INT4 fallback" in update[0] for update in updates))

    def test_standalone_generation_always_releases_runtime(self):
        with patch.object(h3, "_generate_impl", return_value=["clip.mp4"]), \
                patch.object(h3, "stop_runtime") as stop_runtime:
            result = h3.generate(
                {**h3.DEFAULTS, "prompt": "test"},
                "jobstandalone",
                "/tmp",
                lambda *_args: None,
                lambda: False,
            )

        self.assertEqual(result, ["clip.mp4"])
        stop_runtime.assert_called_once()

    def test_director_batch_can_keep_runtime_warm(self):
        with patch.object(h3, "_generate_impl", return_value=["clip.mp4"]), \
                patch.object(h3, "stop_runtime") as stop_runtime:
            result = h3.generate(
                {**h3.DEFAULTS, "prompt": "test"},
                "jobdirector",
                "/tmp",
                lambda *_args: None,
                lambda: False,
                keep_runtime=True,
            )

        self.assertEqual(result, ["clip.mp4"])
        stop_runtime.assert_not_called()

    def test_idle_shutdown_rechecks_queue_guard_before_releasing(self):
        class FakeTimer:
            def __init__(self, _delay, callback):
                self.callback = callback
                self.daemon = False
                self.cancelled = False

            def start(self):
                pass

            def cancel(self):
                self.cancelled = True

        with patch.object(h3.threading, "Timer", FakeTimer), \
                patch.object(h3, "_stop_runtime_locked") as stop_runtime:
            h3.schedule_idle_shutdown(45, should_keep_warm=lambda: True)
            timer = h3._idle_shutdown_timer
            self.assertIsNotNone(timer)
            timer.callback()
            stop_runtime.assert_not_called()

            h3.schedule_idle_shutdown(45, should_keep_warm=lambda: False)
            timer = h3._idle_shutdown_timer
            self.assertIsNotNone(timer)
            timer.callback()
            stop_runtime.assert_called_once()

        h3.cancel_idle_shutdown()


if __name__ == "__main__":
    unittest.main()
