"""Regression tests for malformed Comic Director provider responses."""

from __future__ import annotations

import ast
import copy
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)


def _load_functions(*names: str):
    source = Path(__file__).parents[1].joinpath("app", "_launch_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [
        copy.deepcopy(node)
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {"json": json}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "_launch_runtime.py", "exec"), namespace)
    return tuple(namespace[name] for name in names)


(
    _repair_comic_text_encoding,
    _parse_comic_director_json,
    _generate_comic_director_json,
) = _load_functions(
    "_repair_comic_text_encoding",
    "_parse_comic_director_json",
    "_generate_comic_director_json",
)


class TestComicDirectorJsonRecovery(unittest.TestCase):
    def test_one_item_object_array_is_unwrapped_without_regeneration(self):
        parsed = _parse_comic_director_json('[{"title":"Recovered"}]', "story bible")
        self.assertEqual(parsed, {"title": "Recovered"})

    def test_unusable_non_object_response_is_retried_once(self):
        override = {
            "model": "MiniMax-M2.7",
            "base_url": "https://api.minimax.io/v1",
            "api_key": "configured-secret",
        }
        with patch(
            "services.llm_service.generate_openai_compatible",
            side_effect=['"not an object"', '{"title":"Recovered"}'],
        ) as generate:
            parsed = _generate_comic_director_json(
                prompt="Create the story bible.",
                system_prompt="Return JSON only.",
                schema={"type": "object"},
                max_new_tokens=1400,
                stage="the story bible",
                llm_override=override,
            )

        self.assertEqual(parsed, {"title": "Recovered"})
        self.assertEqual(generate.call_count, 2)
        retry_prompt = generate.call_args_list[1].kwargs["prompt"]
        self.assertIn("JSON CORRECTION RETRY", retry_prompt)
        self.assertIn("PREVIOUS RESPONSE TO REPAIR", retry_prompt)
        self.assertIn('"not an object"', retry_prompt)


if __name__ == "__main__":
    unittest.main()
