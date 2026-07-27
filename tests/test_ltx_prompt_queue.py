"""Tests for LTX prompt lookahead scheduling."""

from __future__ import annotations

import unittest

from app.shared.utils.ltx_prompt_queue import prefetch_next_ltx_prompt


def _task(prompt: str, model: str = "ltx2_22B_distilled_1_1"):
    return {"prompt": prompt, "params": {"model_type": model}}


class TestLTXPromptQueue(unittest.TestCase):
    def test_next_compatible_prompt_is_attached_to_first_task(self):
        queue = [_task("first"), _task("second"), _task("third")]

        count = prefetch_next_ltx_prompt(queue)

        self.assertEqual(count, 1)
        self.assertEqual(
            queue[0]["params"]["ltx2_prefetch_prompts"],
            ["second"],
        )
        self.assertNotIn("ltx2_prefetch_prompts", queue[1]["params"])

    def test_other_models_are_left_untouched(self):
        queue = [_task("first", "wan_2_2"), _task("second", "wan_2_2")]

        count = prefetch_next_ltx_prompt(queue)

        self.assertEqual(count, 0)
        self.assertNotIn("ltx2_prefetch_prompts", queue[0]["params"])


if __name__ == "__main__":
    unittest.main()
