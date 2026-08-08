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

    def test_music_video_mode_requests_and_accepts_one_vocal_story_song(self):
        schema = _story_lab_schema("music", "music_video")
        cues_schema = schema["properties"]["music"]["properties"]["cues"]
        self.assertEqual(cues_schema["minItems"], 1)
        self.assertEqual(cues_schema["maxItems"], 1)

        project = {"projectType": "music_video", "characters": []}
        result = {"music": {"cues": [
            cue("main-song", "story", "story", instrumental=False),
        ]}}
        self.assertIsNone(_story_stage_problem(result, "music", project))

        result["music"]["cues"][0]["instrumental"] = True
        result["music"]["cues"][0]["lyrics"] = ""
        self.assertIn("must include vocals", _story_stage_problem(result, "music", project))

    def test_music_video_repairs_observed_vocal_song_contradictions(self):
        project = {
            "projectType": "music_video",
            "title": "Gremlins of Context",
            "characters": [],
            "creativeBrief": {
                "songStory": "The gremlins race through the labyrinth before the reset.",
                "musicStyle": "cinematic boom bap, theatrical puppet vocals, 94 BPM",
                "durationSeconds": 90,
            },
        }
        result = {"music": {"cues": [{
            "id": "intro-chaos",
            "kind": "story",
            "targetId": "story",
            "title": "Protocol Run",
            "purpose": "Drive the chase through the context labyrinth.",
            "referenceSong": "",
            "brief": "A fast theatrical rap with a recurring hook.",
            "style": "fast cinematic boom bap, distorted bass, theatrical vocals, 94 BPM",
            "lyrics": "We steal the words / We bend the rules / We race the reset",
            "instrumental": True,
            "durationSeconds": 150,
        }]}}

        normalized = _normalize_story_stage_ids(result, "music", project)
        repaired = normalized["music"]["cues"][0]

        self.assertFalse(repaired["instrumental"])
        self.assertEqual(repaired["durationSeconds"], 90)
        self.assertTrue(repaired["referenceSong"])
        self.assertTrue(repaired["lyrics"].startswith("[Verse]\n\n"))
        self.assertIn("\nWe bend the rules\n", repaired["lyrics"])
        self.assertIsNone(_story_stage_problem(normalized, "music", project))

    def test_music_video_unwraps_a_single_song_alias(self):
        project = {
            "projectType": "music_video",
            "title": "Token Run",
            "characters": [],
            "creativeBrief": {
                "songStory": "A crew steals the master token before dawn.",
                "musicStyle": "dark cinematic rap, gritty drums, ensemble vocals, 94 BPM",
                "durationSeconds": 90,
            },
        }
        result = {"music": {"song": {
            "name": "Token Run",
            "reference_song": "Original composition — No direct reference",
            "style_prompt": "dark cinematic rap, gritty drums, ensemble vocals, 94 BPM",
            "song_lyrics": {
                "verse1": ["We cross the maze", "We steal the light"],
                "chorus": ["Run with the token", "Run through the night"],
            },
            "duration_seconds": 90,
        }}}

        normalized = _normalize_story_stage_ids(result, "music", project)
        repaired = normalized["music"]["cues"][0]

        self.assertEqual(repaired["id"], "music-story-1")
        self.assertEqual(repaired["kind"], "story")
        self.assertEqual(repaired["targetId"], "story")
        self.assertIn("[Chorus]", repaired["lyrics"])
        self.assertIsNone(_story_stage_problem(normalized, "music", project))

    def test_quick_video_structure_is_compact(self):
        schema = _story_lab_schema("beats", "quick_video")
        beats = schema["properties"]["beats"]
        self.assertEqual(beats["minItems"], 3)
        self.assertEqual(beats["maxItems"], 8)


if __name__ == "__main__":
    unittest.main()
