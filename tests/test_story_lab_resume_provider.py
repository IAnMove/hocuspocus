"""Regression tests for durable Story Lab resume provider selection."""

from __future__ import annotations

import ast
import copy
import unittest
from pathlib import Path


def _load_function(name: str):
    source = Path(__file__).parents[1].joinpath("app", "launch.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    namespace = {"copy": copy}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "launch.py", "exec"), namespace)
    return namespace[name]


_story_resume_request = _load_function("_story_resume_request")


class TestStoryLabResumeProvider(unittest.TestCase):
    def test_resume_uses_the_current_explicit_writing_profile(self):
        request = {
            "writingProvider": "maestro",
            "writingModel": "deepseek-v4-pro",
            "writingBaseUrl": "https://api.deepseek.com",
            "project": {
                "provider": {
                    "writingProvider": "maestro",
                    "writingModel": "deepseek-v4-pro",
                    "imageProvider": "minimax",
                },
            },
        }

        resumed = _story_resume_request(request, {
            "writingProvider": "minimax",
            "writingModel": "MiniMax-M2.7-highspeed",
            "writingBaseUrl": "https://api.minimax.io/v1",
        })

        self.assertEqual(resumed["writingProvider"], "minimax")
        self.assertEqual(resumed["writingModel"], "MiniMax-M2.7-highspeed")
        self.assertEqual(
            resumed["project"]["provider"]["writingProvider"],
            "minimax",
        )
        self.assertEqual(request["writingProvider"], "maestro")

    def test_resume_without_an_override_preserves_the_checkpoint(self):
        request = {"writingProvider": "maestro", "project": {}}

        resumed = _story_resume_request(request, None)

        self.assertEqual(resumed, request)
        self.assertIsNot(resumed, request)


if __name__ == "__main__":
    unittest.main()
