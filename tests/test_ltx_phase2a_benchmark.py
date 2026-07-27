"""Unit tests for the Phase 2A benchmark timing parser."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.benchmark_ltx_phase2a import _adapt_reference, derive_phase_timings


class TestPhase2ABenchmarkTimings(unittest.TestCase):
    def test_derive_phase_timings_handles_two_stage_pipeline(self):
        transitions = [
            {"elapsed_seconds": 1.0, "phase": "Loading model Example", "message": ""},
            {"elapsed_seconds": 4.0, "phase": "Model loaded", "message": ""},
            {"elapsed_seconds": 5.0, "phase": "Encoding Prompt", "message": ""},
            {"elapsed_seconds": 7.0, "phase": "Denoising First Pass", "message": ""},
            {"elapsed_seconds": 11.0, "phase": "Denoising Second Pass", "message": ""},
            {"elapsed_seconds": 14.0, "phase": "VAE Decoding", "message": ""},
        ]

        result = derive_phase_timings(transitions, 20.0)

        self.assertEqual(
            result["durations_seconds"],
            {
                "model_load": 3.0,
                "text_and_prepare": 3.0,
                "stage_1": 4.0,
                "stage_2": 3.0,
                "vae_decode": 6.0,
            },
        )

    def test_derive_phase_timings_keeps_missing_phases_explicit(self):
        result = derive_phase_timings(
            [
                {
                    "elapsed_seconds": 2.0,
                    "phase": "Denoising First Pass",
                    "message": "",
                }
            ],
            5.0,
        )

        self.assertIsNone(result["durations_seconds"]["model_load"])
        self.assertEqual(result["durations_seconds"]["stage_1"], 3.0)
        self.assertIsNone(result["durations_seconds"]["stage_2"])

    def test_contain_reference_has_exact_requested_canvas(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "reference.png"
            Image.new("RGB", (64, 64), "#d9f0e5").save(source)

            result = _adapt_reference(
                source, "768x512", "contain", root
            )

            with Image.open(result) as adapted:
                self.assertEqual(adapted.size, (768, 512))
                self.assertEqual(adapted.getpixel((0, 0)), (217, 240, 229))
            self.assertTrue(
                result.is_relative_to(
                    root
                    / "app"
                    / "outputs"
                    / "benchmarks"
                    / "phase2a"
                    / "reference"
                )
            )

    def test_cover_reference_has_exact_requested_canvas(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "reference.png"
            Image.new("RGB", (64, 96), "#e66b5b").save(source)

            result = _adapt_reference(source, "512x768", "cover", root)

            with Image.open(result) as adapted:
                self.assertEqual(adapted.size, (512, 768))


if __name__ == "__main__":
    unittest.main()
