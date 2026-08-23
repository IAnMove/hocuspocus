from __future__ import annotations

import os
import sys
import unittest

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services import character_sheet  # noqa: E402


class CharacterSheetDescribeTests(unittest.TestCase):
    def test_formats_keep_ignore_lines_in_picture_order(self):
        prompt = character_sheet.format_a_prompt([
            {"keep": "the bald head, beard and black coat", "ignore": "the cafe background"},
            {"keep": "the silver shield on the back", "ignore": "the other person"},
        ])
        self.assertEqual(
            prompt,
            "<Picture 1> - keep the bald head, beard and black coat. Ignore the cafe background.\n"
            "<Picture 2> - keep the silver shield on the back. Ignore the other person.",
        )

    def test_describe_calls_minimax_with_images_and_does_not_need_a_user_prompt(self):
        captured = {}

        def complete(system, user, paths):
            captured["system"] = system
            captured["user"] = user
            captured["paths"] = paths
            return '{"pictures":[{"keep":"a clay dwarf with a red hood","ignore":"the forest background"}]}'

        prompt = character_sheet.describe_character_sheet(
            kind="character",
            image_paths=["/tmp/dwarf.png"],
            complete=complete,
        )
        self.assertIn("<Picture 1> - keep a clay dwarf with a red hood.", prompt)
        self.assertIn("Ignore the forest background.", prompt)
        self.assertIn("dwarf.png", captured["paths"][0])
        self.assertIn("Subject type: character.", captured["user"])
        self.assertNotIn("360", captured["user"])

    def test_prose_fallback_still_becomes_a_picture_line(self):
        pictures = character_sheet.pictures_from_response(
            "A green hat elf in purple armor.",
            kind="character",
            roles=["subject"],
        )
        self.assertEqual(pictures[0]["keep"], "A green hat elf in purple armor.")

    def test_json_fences_are_stripped(self):
        pictures = character_sheet.pictures_from_response(
            '```json\n{"pictures":[{"keep":"a round shield","ignore":"hands"}]}\n```',
            kind="object",
            roles=["subject"],
        )
        self.assertEqual(pictures[0]["keep"], "a round shield")
        self.assertEqual(pictures[0]["ignore"], "hands")


class CharacterSheetRouteTests(unittest.TestCase):
    def test_launch_runtime_exposes_describe_refs_without_loading_local_llm(self):
        launch = os.path.join(os.path.dirname(__file__), "..", "app", "_launch_runtime.py")
        with open(launch, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('@api.post("/api/v1/characters/describe-refs")', source)
        self.assertIn("Does not load the local LLM", source)
        self.assertIn('model_id="MiniMax-M3"', source)
        self.assertNotIn("_ensure_llm_loaded()", source.split("describe_character_refs")[1].split("return {")[0])
