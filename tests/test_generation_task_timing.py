"""Tests for per-panel generation timing."""

from __future__ import annotations

import unittest

from app.shared.utils.generation_timing import GenerationTaskTimer


class _Clock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        return self.value


class TestGenerationTaskTiming(unittest.TestCase):
    def test_total_and_phase_times_are_separated_per_panel(self):
        clock = _Clock()
        timer = GenerationTaskTimer(3, 24, "panel prompt", clock=clock)
        timer.phase("Preparando textos 1–4 de 24")
        clock.value += 2.5
        timer.phase("Diffusion 1/8")
        clock.value += 7.25

        metric = timer.finish("completed")

        self.assertEqual(metric["panel_no"], 3)
        self.assertEqual(metric["panel_total"], 24)
        self.assertEqual(metric["total_seconds"], 9.75)
        self.assertEqual(
            metric["phase_timings"],
            [
                {"phase": "Preparando textos 1–4 de 24", "seconds": 2.5},
                {"phase": "Diffusion #/#", "seconds": 7.25},
            ],
        )


if __name__ == "__main__":
    unittest.main()
