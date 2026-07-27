"""Tests for LTX prompt lookahead scheduling."""

from __future__ import annotations

import unittest

from app.shared.utils.ltx_prompt_queue import schedule_ltx_prompt_windows


def _task(prompt: str, model: str = "ltx2_22B_distilled_1_1"):
    return {"prompt": prompt, "params": {"model_type": model}}


class TestLTXPromptQueue(unittest.TestCase):
    def test_first_batch_never_exceeds_four_panel_prompts(self):
        queue = [
            _task("first"),
            _task("second"),
            _task("third"),
            _task("fourth"),
            _task("fifth"),
        ]

        windows = schedule_ltx_prompt_windows(queue)

        self.assertEqual(windows, [(1, 4), (5, 5)])
        self.assertEqual(
            queue[0]["params"]["ltx2_prefetch_prompts"],
            ["second", "third", "fourth"],
        )
        self.assertNotIn("fifth", queue[0]["params"]["ltx2_prefetch_prompts"])
        self.assertNotIn("ltx2_prefetch_prompts", queue[1]["params"])

    def test_other_models_are_left_untouched(self):
        queue = [_task("first", "wan_2_2"), _task("second", "wan_2_2")]

        windows = schedule_ltx_prompt_windows(queue)

        self.assertEqual(windows, [])
        self.assertNotIn("ltx2_prefetch_prompts", queue[0]["params"])

    def test_long_comics_are_scheduled_in_consecutive_windows(self):
        queue = [_task(f"panel-{index}") for index in range(1, 11)]

        windows = schedule_ltx_prompt_windows(queue)

        self.assertEqual(windows, [(1, 4), (5, 8), (9, 10)])
        self.assertEqual(
            queue[0]["params"]["ltx2_prefetch_prompts"],
            ["panel-2", "panel-3", "panel-4"],
        )
        self.assertEqual(
            queue[4]["params"]["ltx2_prefetch_prompts"],
            ["panel-6", "panel-7", "panel-8"],
        )
        self.assertEqual(
            queue[8]["params"]["ltx2_prefetch_prompts"],
            ["panel-10"],
        )
        for index in (1, 2, 3, 5, 6, 7, 9):
            self.assertNotIn("ltx2_prefetch_prompts", queue[index]["params"])


if __name__ == "__main__":
    unittest.main()
