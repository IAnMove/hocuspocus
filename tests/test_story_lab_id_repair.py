"""Regression tests for Story Lab character/relationship ID recovery."""

from __future__ import annotations

import ast
import copy
import re
import unittest
from pathlib import Path


def _load_functions(*names: str):
    source = Path(__file__).parents[1].joinpath("app", "_launch_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {"copy": copy, "re": re}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "_launch_runtime.py", "exec"), namespace)
    return tuple(namespace[name] for name in names)


_story_id_token, _normalize_story_stage_ids, _story_stage_problem = _load_functions(
    "_story_id_token",
    "_normalize_story_stage_ids",
    "_story_stage_problem",
)


class TestStoryLabIdRepair(unittest.TestCase):
    def test_character_ids_are_trimmed_before_downstream_stages(self):
        result = {
            "characters": [
                {"id": "nara", "name": "Nara"},
                {"id": " vigil", "name": "Vigil"},
            ],
        }
        normalized = _normalize_story_stage_ids(result, "characters", {})
        self.assertEqual(
            [character["id"] for character in normalized["characters"]],
            ["nara", "vigil"],
        )

    def test_world_location_visual_defaults_are_recovered_without_another_llm_call(self):
        result = {
            "world": {
                "locations": [{
                    "id": "archive",
                    "name": "The Archive",
                    "purpose": "Where the AI finds its first memory.",
                    "description": "A buried concrete library under a red desert.",
                }],
            },
        }

        normalized = _normalize_story_stage_ids(result, "world", {})
        location = normalized["world"]["locations"][0]

        self.assertIn("The Archive", location["visualPrompt"])
        self.assertIn("no text", location["visualPrompt"])
        self.assertIn("lettering", location["negativePrompt"])

    def test_relationship_names_and_whitespace_resolve_to_canonical_ids(self):
        project = {
            "characters": [
                {"id": "nara", "name": "Nara"},
                {"id": "vigil", "name": "Vigil"},
            ],
        }
        result = {
            "relationships": [{
                "id": " trust ",
                "fromCharacterId": " Nara ",
                "toCharacterId": "VIGIL",
                "label": "Trust",
                "dynamic": "They learn to cooperate.",
                "evolution": "Suspicion becomes hope.",
            }],
        }
        normalized = _normalize_story_stage_ids(result, "relationships", project)
        relationship = normalized["relationships"][0]
        self.assertEqual(relationship["id"], "trust")
        self.assertEqual(relationship["fromCharacterId"], "nara")
        self.assertEqual(relationship["toCharacterId"], "vigil")

    def test_only_irreparable_relationships_are_dropped(self):
        project = {
            "characters": [
                {"id": "nara", "name": "Nara"},
                {"id": "vigil", "name": "Vigil"},
            ],
        }
        result = {
            "relationships": [
                {"id": "valid", "fromCharacterId": "nara", "toCharacterId": "vigil"},
                {"id": "invented", "fromCharacterId": "nara", "toCharacterId": "ghost"},
            ],
        }
        normalized = _normalize_story_stage_ids(
            result,
            "relationships",
            project,
            drop_unknown_relationships=True,
        )
        self.assertEqual(
            [relationship["id"] for relationship in normalized["relationships"]],
            ["valid"],
        )

    def test_visual_sequence_and_plot_points_are_recovered_as_beats(self):
        result = {
            "title": "The Token Heist",
            "plot_points": [
                {"point": index + 1, "description": f"Story development {index + 1}.", "focus": f"Purpose {index + 1}"}
                for index in range(5)
            ],
            "visual_sequence_outline": [
                {"sequence": index + 1, "description": f"Visible action {index + 1}.", "mood": "tense"}
                for index in range(5)
            ],
        }

        normalized = _normalize_story_stage_ids(
            result,
            "structure",
            {"projectType": "music_video"},
        )

        self.assertEqual(len(normalized["beats"]), 5)
        self.assertEqual(normalized["beats"][0]["title"], "Purpose 1")
        self.assertEqual(normalized["beats"][0]["summary"], "Visible action 1.")
        self.assertEqual(normalized["beats"][0]["goal"], "Purpose 1")
        self.assertEqual(normalized["beats"][-1]["stage"], "resolution")
        self.assertIsNone(_story_stage_problem(
            normalized,
            "structure",
            {"projectType": "music_video"},
        ))

    def test_wrapped_structure_items_are_unwrapped_and_completed(self):
        result = {
            "beats": {
                "items": [
                    {"name": f"Scene {index + 1}", "description": f"Action {index + 1}"}
                    for index in range(4)
                ],
            },
        }

        normalized = _normalize_story_stage_ids(
            result,
            "structure",
            {"projectType": "music_video"},
        )

        self.assertEqual([beat["title"] for beat in normalized["beats"]], [
            "Scene 1", "Scene 2", "Scene 3", "Scene 4",
        ])
        self.assertTrue(all(beat["conflict"] and beat["turn"] for beat in normalized["beats"]))
        self.assertIsNone(_story_stage_problem(
            normalized,
            "structure",
            {"projectType": "music_video"},
        ))


if __name__ == "__main__":
    unittest.main()
