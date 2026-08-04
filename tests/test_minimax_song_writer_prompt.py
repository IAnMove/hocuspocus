"""Focused tests for the MiniMax-specific LLM song-writing contract."""

from __future__ import annotations

import ast
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
    namespace = {"re": re}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "launch.py", "exec"), namespace)
    return tuple(namespace[name] for name in names)


_minimax_song_request_prompt, _normalize_minimax_song_output, _parse_song_output, _parse_lyria_output = _load_functions(
    "_minimax_song_request_prompt",
    "_normalize_minimax_song_output",
    "_parse_song_output",
    "_parse_lyria_output",
)


class TestMiniMaxSongWriterPrompt(unittest.TestCase):
    def test_builds_labelled_reference_style_lyrics_and_story_inputs(self):
        prompt = _minimax_song_request_prompt({
            "model": "music-3.0",
            "reference_song": "Example — Artist",
            "style_direction": "Cinematic indie folk with intimate vocals",
            "lyrics_direction": "A chorus about choosing hope",
            "story_context": "Nara crosses the ruined observatory at dawn.",
            "language": "Spanish",
            "duration_seconds": 120,
        }, "Write an original song", False)

        self.assertIn("REFERENCE SONG (analysis input only", prompt)
        self.assertIn("DESIRED STYLE", prompt)
        self.assertIn("DESIRED LYRICS OR STRUCTURE", prompt)
        self.assertIn("STORY CONTEXT", prompt)
        self.assertIn("LYRICS LANGUAGE: Spanish", prompt)
        self.assertIn("TARGET DURATION: approximately 120 seconds", prompt)

    def test_normalizes_provider_limits_by_mode(self):
        style, lyrics = _normalize_minimax_song_output(
            "Cinematic   folk, " + ("warm strings " * 40),
            "new lyric " * 500,
            False,
            "music-cover",
        )
        self.assertLessEqual(len(style), 300)
        self.assertNotIn("  ", style)
        self.assertLessEqual(len(lyrics), 1000)

        instrumental_style, instrumental_lyrics = _normalize_minimax_song_output(
            "Ambient electronic, soft pads, slow build",
            "[Instrumental]",
            True,
            "music-3.0",
        )
        self.assertEqual(instrumental_style, "Ambient electronic, soft pads, slow build")
        self.assertEqual(instrumental_lyrics, "")

    def test_separates_minimax_lyrics_from_optional_timed_lyria_prompt(self):
        raw = """[STYLE]
Indie folk, hopeful, acoustic guitar, warm alto, mid-tempo
[LYRICS]
[Verse]
We carry light across the plain

[Chorus]
The sky remembers rain
[LYRIA]
Sky Seed: Composition Breakdown
[0:00 - 0:12] Intro: Intensity: 3/10. Warm acoustic guitar.
[0:12 - 0:42] Verse: Intensity: 4/10. Lyrics: \"We carry light across the plain\".
"""
        style, lyrics = _parse_song_output(raw, False)

        self.assertEqual(style, "Indie folk, hopeful, acoustic guitar, warm alto, mid-tempo")
        self.assertNotIn("[LYRIA]", lyrics)
        self.assertIn("[Chorus]", lyrics)
        self.assertIn("[0:00 - 0:12]", _parse_lyria_output(raw))


if __name__ == "__main__":
    unittest.main()
