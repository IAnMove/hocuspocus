"""Regression tests for Story Lab's LLM-authored music plan."""

from __future__ import annotations

import ast
import copy
import re
import unittest
from pathlib import Path


def _load_functions(*names: str):
    source = Path(__file__).parents[1].joinpath("app", "launch.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {"copy": copy, "re": re}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "launch.py", "exec"), namespace)
    return tuple(namespace[name] for name in names)


_story_lab_schema, _story_id_token, _normalize_story_stage_ids, _story_stage_problem = _load_functions(
    "_story_lab_schema",
    "_story_id_token",
    "_normalize_story_stage_ids",
    "_story_stage_problem",
)


def cue(cue_id, kind, target, *, instrumental=True):
    return {
        "id": cue_id,
        "kind": kind,
        "targetId": target,
        "title": f"Theme for {target}",
        "purpose": "Express this part of the story.",
        "referenceSong": "Example Track — Example Artist",
        "brief": "An original cue grounded in the Story bible.",
        "style": "cinematic, evolving, memorable motif",
        "lyrics": "" if instrumental else "[Verse]\nAn original line",
        "instrumental": instrumental,
        "durationSeconds": 90,
    }


class TestStoryLabMusicPlan(unittest.TestCase):
    def setUp(self):
        self.project = {
            "characters": [
                {"id": "nara", "name": "Nara"},
                {"id": "vigil", "name": "Vigil"},
            ],
        }
        self.result = {"music": {"cues": [
            cue("world-theme", "world", "world"),
            cue("nara-theme", "character", "Nara"),
            cue("vigil-theme", "character", "vigil"),
            cue("story-one", "story", "story-1", instrumental=False),
            cue("story-two", "story", "story-2", instrumental=False),
            cue("story-three", "story", "story-3", instrumental=False),
        ]}}

    def test_music_schema_requires_editable_reference_and_generation_fields(self):
        item = _story_lab_schema("music")["properties"]["music"]["properties"]["cues"]["items"]
        self.assertIn("referenceSong", item["required"])
        self.assertIn("style", item["required"])
        self.assertIn("lyrics", item["required"])

    def test_character_names_are_normalized_to_stable_ids(self):
        normalized = _normalize_story_stage_ids(self.result, "music", self.project)
        self.assertEqual(normalized["music"]["cues"][1]["targetId"], "nara")
        self.assertIsNone(_story_stage_problem(normalized, "music", self.project))

    def test_requires_one_world_one_per_character_and_three_story_songs(self):
        invalid = copy.deepcopy(self.result)
        invalid["music"]["cues"].pop()
        self.assertIn("exactly", _story_stage_problem(invalid, "music", self.project))


if __name__ == "__main__":
    unittest.main()
