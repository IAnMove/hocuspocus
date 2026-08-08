"""Tests for durable Story Lab workspace persistence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.services.story_library import (
    MAX_STORY_PROJECTS,
    normalize_story_library,
    read_story_library,
    story_library_path,
    write_story_library,
)


class TestStoryLibrary(unittest.TestCase):
    def test_missing_library_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                read_story_library(directory),
                {"version": 2, "activeId": "", "projects": {}},
            )

    def test_round_trip_is_atomic_and_repairs_active_id(self):
        with tempfile.TemporaryDirectory() as directory:
            saved = write_story_library(directory, {
                "version": 2,
                "activeId": "missing",
                "projects": {
                    "nara": {"id": "nara", "title": "The Last Seed"},
                    "kael": {"id": "kael", "title": "The Guardian"},
                },
            })
            self.assertEqual(saved["activeId"], "nara")
            self.assertEqual(read_story_library(directory), saved)
            self.assertFalse(list(Path(directory).glob("*.tmp")))

    def test_invalid_existing_json_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(story_library_path(directory)).write_text("{broken", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                read_story_library(directory)

    def test_project_limit_is_enforced(self):
        value = {
            "projects": {
                f"story-{index}": {"id": f"story-{index}"}
                for index in range(MAX_STORY_PROJECTS + 1)
            },
        }
        with self.assertRaisesRegex(ValueError, "limited"):
            normalize_story_library(value)


if __name__ == "__main__":
    unittest.main()
