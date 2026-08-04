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
        "lyrics": "" if instrumental else "[Verse]\n\nAn original line\n\n[Chorus]\n\nA recurring original hook",
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

    def test_rejects_prompts_that_are_not_minimax_ready(self):
        invalid = copy.deepcopy(self.result)
        invalid["music"]["cues"][0]["style"] = "vague"
        self.assertIn("10–300", _story_stage_problem(invalid, "music", self.project))

        invalid = copy.deepcopy(self.result)
        invalid["music"]["cues"][0]["lyrics"] = "[Verse]\nThis should stay silent"
        self.assertIn("empty lyrics", _story_stage_problem(invalid, "music", self.project))

        invalid = copy.deepcopy(self.result)
        invalid["music"]["cues"][3]["lyrics"] = "Words without a supported section tag"
        self.assertIn("structural tags", _story_stage_problem(invalid, "music", self.project))

    def test_world_is_instrumental_and_story_tracks_are_vocal(self):
        invalid = _normalize_story_stage_ids(copy.deepcopy(self.result), "music", self.project)
        invalid["music"]["cues"][0]["instrumental"] = False
        invalid["music"]["cues"][0]["lyrics"] = "[Verse]\n\nA vocal world"
        self.assertIn("world ambience", _story_stage_problem(invalid, "music", self.project))

        invalid = _normalize_story_stage_ids(copy.deepcopy(self.result), "music", self.project)
        invalid["music"]["cues"][3]["instrumental"] = True
        invalid["music"]["cues"][3]["lyrics"] = ""
        self.assertIn("must include vocals", _story_stage_problem(invalid, "music", self.project))


if __name__ == "__main__":
    unittest.main()
