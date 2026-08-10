"""MiniMax H3 model metadata and Comfy workflow regression tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.services import minimax_h3_service as h3


class TestMiniMaxH3Workflow(unittest.TestCase):
    def test_legacy_options_publish_ref2va_image_limit(self):
        self.assertEqual(h3.MODEL_OPTIONS["max_image_refs"], 9)

    def test_portrait_start_frame_is_letterboxed_to_landscape_without_stretching(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "portrait.png"
            Image.new("RGB", (200, 400), (220, 30, 40)).save(source)
            input_dir = root / "input"

            with patch.object(h3, "INPUT_DIR", input_dir):
                workflow, pipeline = h3.build_workflow({
                    **h3.DEFAULTS,
                    "image_start": str(source),
                    "resolution": "960x544",
                    "image_fit_mode": "contain",
                }, "letterbox")

            self.assertEqual(pipeline, "fl2va")
            prepared_path = input_dir / workflow["31"]["inputs"]["image"]
            with Image.open(prepared_path) as prepared:
                self.assertEqual(prepared.size, (960, 544))
                self.assertEqual(prepared.getpixel((0, 272)), (0, 0, 0))
                center = prepared.getpixel((480, 272))
                self.assertGreater(center[0], 200)
                self.assertLess(center[1], 50)

    def test_start_frame_crop_is_explicit_and_fills_the_canvas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "portrait.png"
            Image.new("RGB", (200, 400), (20, 180, 60)).save(source)
            input_dir = root / "input"

            with patch.object(h3, "INPUT_DIR", input_dir):
                workflow, _ = h3.build_workflow({
                    **h3.DEFAULTS,
                    "image_start": str(source),
                    "resolution": "960x544",
                    "image_fit_mode": "crop",
                }, "crop")

            with Image.open(input_dir / workflow["31"]["inputs"]["image"]) as prepared:
                self.assertEqual(prepared.size, (960, 544))
                self.assertEqual(prepared.getpixel((0, 0)), (20, 180, 60))
                self.assertEqual(prepared.getpixel((959, 543)), (20, 180, 60))

    def test_legacy_source_fit_mode_maps_to_non_distorting_letterbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "wide.png"
            Image.new("RGB", (400, 100), (30, 50, 210)).save(source)
            input_dir = root / "input"

            with patch.object(h3, "INPUT_DIR", input_dir):
                workflow, _ = h3.build_workflow({
                    **h3.DEFAULTS,
                    "image_start": str(source),
                    "resolution": "544x960",
                    "image_fit_mode": "source",
                }, "legacy-source")

            with Image.open(input_dir / workflow["31"]["inputs"]["image"]) as prepared:
                self.assertEqual(prepared.size, (544, 960))
                self.assertEqual(prepared.getpixel((272, 0)), (0, 0, 0))
                self.assertEqual(prepared.getpixel((272, 480)), (30, 50, 210))

    def test_extend_video_becomes_last_frame_fl2va_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.mp4"
            source.write_bytes(b"video")

            def fake_extract(_source, destination, requested_time):
                Image.new("RGB", (1280, 720), (12, 24, 36)).save(destination)
                self.assertEqual(requested_time, 8.5)
                return {"time": 8.416667, "width": 1280, "height": 720}

            params = {
                **h3.DEFAULTS,
                "video_source": str(source),
                "h3_reference_mode": "references",
                "image_refs": ["old-reference.png"],
            }
            with patch("app.services.video_editor.probe_media", return_value={"duration": 8.5}), \
                    patch("app.services.video_editor.extract_frame", side_effect=fake_extract):
                result = h3.prepare_extend_anchor(params, "extend1", source, Path(tmp) / "cache")

            self.assertTrue(Path(result["path"]).is_file())
            self.assertEqual(result["time"], 8.416667)
            self.assertEqual(result["ignored_references"], 1)
            self.assertEqual(params["image_start"], result["path"])
            self.assertEqual(params["image_prompt_type"], "S")
            self.assertEqual(params["h3_reference_mode"], "first_frame")
            self.assertNotIn("image_refs", params)

            with patch.object(h3, "INPUT_DIR", Path(tmp) / "input"):
                workflow, pipeline = h3.build_workflow(params, "extend1")
            self.assertEqual(pipeline, "fl2va")
            self.assertIn("first_frame", workflow["10"]["inputs"])

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
        final_prompt = workflow["10"]["inputs"]["prompt"]
        self.assertEqual(final_prompt.lower().count("overall_soundscape:"), 1)
        self.assertIn("at 0.00 seconds", final_prompt)
        self.assertEqual(workflow["27"]["inputs"]["fps"], 24.0)
        self.assertEqual(workflow["27"]["inputs"]["audio"], ["26", 0])
        self.assertEqual(workflow["28"]["inputs"]["codec"], "auto")

    def test_stale_ref2va_mode_without_media_recovers_to_text_to_video(self):
        params = {
            **h3.DEFAULTS,
            "prompt": "sunrise over an empty ocean; audio: quiet surf",
            "h3_reference_mode": "references",
            "image_refs": [],
            "h3_ref_videos": [],
            "h3_ref_audios": [],
        }

        workflow, pipeline = h3.build_workflow(params, "job-stale-ref-mode")

        self.assertEqual(pipeline, "fl2va")
        self.assertEqual(params["h3_reference_mode"], "first_frame")
        self.assertNotIn("image_refs", params)
        self.assertNotIn("h3_ref_videos", params)
        self.assertNotIn("h3_ref_audios", params)
        self.assertEqual(workflow["10"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertNotIn("first_frame", workflow["10"]["inputs"])

    def test_profile_selects_matching_convrot_pair(self):
        workflow, _ = h3.build_workflow({
            **h3.DEFAULTS,
            "prompt": "quality test",
            "h3_model_profile": "quality",
        }, "jobquality")

        profile = h3.MODEL_PROFILES["quality"]
        self.assertEqual(workflow["1"]["inputs"]["unet_name"], profile["fl2va"])
        self.assertEqual(workflow["3"]["inputs"]["clip_name"], profile["text_encoder"])
        self.assertEqual(h3.MODEL_ID, "minimax_h3_legacy")
        self.assertEqual(h3.MODEL_OPTIONS["architecture"], "minimax_h3")
        self.assertEqual(
            h3.MODEL_OPTIONS["director_audio_input_mode"],
            "timeline_remux",
        )
        self.assertIsNotNone(h3.MODEL_OPTIONS["image_ref_choices"])
        self.assertEqual(h3.DEFAULTS["resolution"], "960x544")
        self.assertEqual(h3.DEFAULTS["video_length"], 124)
        self.assertEqual(h3.DEFAULTS["num_inference_steps"], 20)
        self.assertEqual(h3.DEFAULTS["h3_model_profile"], "quality")
        self.assertEqual(h3.DEFAULTS["h3_reference_mode"], "first_frame")
        self.assertEqual(
            h3.MODEL_OPTIONS["resolution_preset_order"],
            ["480p", "540p", "720p", "768p"],
        )
        self.assertEqual(
            h3.MODEL_OPTIONS["resolution_presets"]["480p"]["values"]["16:9"],
            "864x480",
        )
        self.assertEqual(
            h3.MODEL_OPTIONS["resolution_presets"]["720p"]["values"]["9:16"],
            "704x1280",
        )
        self.assertEqual(
            h3.MODEL_OPTIONS["resolution_presets"]["768p"]["values"]["16:9"],
            "1344x768",
        )

    def test_story_lab_presets_are_native_base_canvases_without_rescaling(self):
        for preset, orientation in (("480p", "16:9"), ("540p", "9:16"),
                                    ("720p", "16:9"), ("768p", "9:16")):
            resolution = h3.MODEL_OPTIONS["resolution_presets"][preset]["values"][orientation]
            params = {**h3.DEFAULTS, "prompt": "resolution test", "resolution": resolution}

            workflow, _ = h3.build_workflow(params, f"job-{preset}-{orientation}")

            width, height = (int(value) for value in resolution.split("x", 1))
            self.assertEqual(
                (workflow["10"]["inputs"]["width"], workflow["10"]["inputs"]["height"]),
                (width, height),
            )
            self.assertEqual(params["effective_resolution"], resolution)

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
        self.assertIn("overall_soundscape:", prompt)
        self.assertIn("clear, audible stereo mix", prompt)

    def test_authored_audio_clause_is_not_duplicated(self):
        prompt = "A quiet beach. Audio: gentle waves and gulls."
        workflow, _ = h3.build_workflow({
            **h3.DEFAULTS,
            "prompt": prompt,
            "h3_audio_prompt": "loud machinery",
        }, "jobaudioauthored")

        final_prompt = workflow["10"]["inputs"]["prompt"]
        self.assertIn("overall_soundscape: gentle waves and gulls.", final_prompt)
        self.assertNotIn("loud machinery", final_prompt)

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
            Image.new("RGB", (640, 360), (10, 20, 30)).save(first)
            Image.new("RGB", (640, 360), (30, 20, 10)).save(last)
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

        near_default = {**h3.DEFAULTS, "prompt": "test", "video_length": 125}
        near_workflow, _ = h3.build_workflow(near_default, "jobduration-nearest")
        self.assertEqual(near_workflow["10"]["inputs"]["length"], 124)
        self.assertEqual(near_default["requested_video_length"], 125)
        self.assertEqual(near_default["effective_video_length"], 124)
        self.assertEqual(h3.MODEL_OPTIONS["frame_alignment_mode"], "nearest")

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
        params = {
            **h3.DEFAULTS,
            "prompt": "test",
            "h3_allow_low_memory_fallback": True,
        }
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

    def test_legacy_quality_never_silently_falls_back_to_int4(self):
        params = {**h3.DEFAULTS, "prompt": "test"}
        with patch.object(
            h3,
            "_generate_impl",
            side_effect=RuntimeError("CUDA out of memory"),
        ) as generate_impl, patch.object(h3, "stop_runtime") as stop_runtime:
            with self.assertRaisesRegex(RuntimeError, "out of memory"):
                h3.generate(
                    params,
                    "jobquality",
                    "/tmp",
                    lambda *_args: None,
                    lambda: False,
                    keep_runtime=True,
                )

        generate_impl.assert_called_once()
        stop_runtime.assert_not_called()

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

    def test_idle_shutdown_default_releases_host_memory_promptly(self):
        self.assertEqual(h3.DEFAULT_IDLE_SHUTDOWN_SECONDS, 10.0)


if __name__ == "__main__":
    unittest.main()
