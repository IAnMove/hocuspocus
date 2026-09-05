"""Tests for durable Story Lab workspace persistence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.services.story_library import (
    MAX_STORY_PROJECTS,
    StoryLibraryRevisionConflict,
    attach_story_song_candidate,
    normalize_story_library,
    delete_story_project,
    patch_story_project,
    read_story_library,
    story_library_path,
    write_story_library,
)


class TestStoryLibrary(unittest.TestCase):
    def test_missing_library_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                read_story_library(directory),
                {"version": 2, "revision": 0, "activeId": "", "projects": {}},
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
            }, base_revision=0)
            self.assertEqual(saved["revision"], 1)
            self.assertEqual(saved["activeId"], "nara")
            self.assertEqual(read_story_library(directory), saved)
            self.assertFalse(list(Path(directory).glob("*.tmp")))

    def test_two_writes_from_the_same_revision_never_lose_the_first(self):
        with tempfile.TemporaryDirectory() as directory:
            first = write_story_library(directory, {
                "version": 2,
                "activeId": "first",
                "projects": {"first": {"id": "first", "title": "First tab"}},
            }, base_revision=0)

            with self.assertRaises(StoryLibraryRevisionConflict) as raised:
                write_story_library(directory, {
                    "version": 2,
                    "activeId": "second",
                    "projects": {"second": {"id": "second", "title": "Stale tab"}},
                }, base_revision=0)

            self.assertEqual(raised.exception.expected, 0)
            self.assertEqual(raised.exception.current, 1)
            self.assertEqual(read_story_library(directory), first)

    def test_current_revision_advances_monotonically(self):
        with tempfile.TemporaryDirectory() as directory:
            first = write_story_library(directory, {
                "projects": {"story": {"id": "story", "title": "Draft 1"}},
            }, base_revision=0)
            second = write_story_library(directory, {
                "projects": {"story": {"id": "story", "title": "Draft 2"}},
            }, base_revision=first["revision"])
            self.assertEqual((first["revision"], second["revision"]), (1, 2))
            self.assertEqual(read_story_library(directory)["projects"]["story"]["title"], "Draft 2")

    def test_incremental_project_patch_preserves_unrelated_stories(self):
        with tempfile.TemporaryDirectory() as directory:
            initial = write_story_library(directory, {
                "activeId": "one",
                "projects": {
                    "one": {"id": "one", "title": "One"},
                    "two": {"id": "two", "title": "Two"},
                },
            }, base_revision=0)
            patched = patch_story_project(
                directory,
                "one",
                {"id": "one", "title": "One updated"},
                base_revision=initial["revision"],
            )
            self.assertEqual(patched["revision"], 2)
            self.assertEqual(patched["projects"]["one"]["title"], "One updated")
            self.assertEqual(patched["projects"]["two"]["title"], "Two")

            deleted = delete_story_project(
                directory,
                "one",
                base_revision=patched["revision"],
            )
            self.assertEqual(deleted["revision"], 3)
            self.assertEqual(deleted["activeId"], "two")
            self.assertEqual(list(deleted["projects"]), ["two"])

    def test_invalid_existing_json_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(story_library_path(directory)).write_text("{broken", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                read_story_library(directory)

    def test_attach_story_song_candidate_patches_pending_row(self):
        with tempfile.TemporaryDirectory() as directory:
            initial = write_story_library(directory, {
                "activeId": "story-a",
                "projects": {
                    "story-a": {
                        "id": "story-a",
                        "title": "Workspace A",
                        "music": {
                            "cues": [{
                                "id": "cue-a",
                                "title": "Theme",
                                "candidates": [{
                                    "id": "song-a",
                                    "status": "pending",
                                    "source": "",
                                    "name": "",
                                }],
                            }],
                        },
                    },
                },
            }, base_revision=0)
            saved = attach_story_song_candidate(
                directory,
                project_id="story-a",
                cue_id="cue-a",
                candidate_id="song-a",
                source="/api/v1/file/theme.wav?workspace=a",
                filename="theme.wav",
                status="ready",
                base_revision=initial["revision"],
                task_id="task-1",
            )
            candidate = saved["projects"]["story-a"]["music"]["cues"][0]["candidates"][0]
            self.assertEqual(saved["revision"], 2)
            self.assertEqual(candidate["id"], "song-a")
            self.assertEqual(candidate["status"], "ready")
            self.assertEqual(candidate["name"], "theme.wav")
            self.assertEqual(candidate["provenance"]["candidateId"], "song-a")
            self.assertEqual(
                saved["projects"]["story-a"]["music"]["cues"][0]["selectedCandidateId"],
                "song-a",
            )

    def test_attach_story_song_candidate_can_leave_selection_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            initial = write_story_library(directory, {
                "projects": {
                    "story-a": {
                        "id": "story-a",
                        "music": {
                            "cues": [{
                                "id": "cue-a",
                                "selectedCandidateId": "song-keep",
                                "candidates": [
                                    {"id": "song-keep", "status": "ready"},
                                    {"id": "song-a", "status": "pending"},
                                ],
                            }],
                        },
                    },
                },
            }, base_revision=0)
            saved = attach_story_song_candidate(
                directory,
                project_id="story-a",
                cue_id="cue-a",
                candidate_id="song-a",
                source="/api/v1/file/theme.wav",
                filename="theme.wav",
                status="ready",
                base_revision=initial["revision"],
                update_selection=False,
            )
            cue = saved["projects"]["story-a"]["music"]["cues"][0]
            self.assertEqual(cue["selectedCandidateId"], "song-keep")
            self.assertEqual(cue["candidates"][1]["status"], "ready")

    def test_attach_story_song_candidate_cas_conflict_keeps_pending_row(self):
        with tempfile.TemporaryDirectory() as directory:
            first = write_story_library(directory, {
                "projects": {
                    "story-a": {
                        "id": "story-a",
                        "music": {
                            "cues": [{
                                "id": "cue-a",
                                "candidates": [{"id": "song-a", "status": "pending", "source": ""}],
                            }],
                        },
                    },
                },
            }, base_revision=0)
            attach_story_song_candidate(
                directory,
                project_id="story-a",
                cue_id="cue-a",
                candidate_id="song-a",
                source="/api/v1/file/theme.wav",
                filename="theme.wav",
                base_revision=first["revision"],
            )
            with self.assertRaises(StoryLibraryRevisionConflict):
                attach_story_song_candidate(
                    directory,
                    project_id="story-a",
                    cue_id="cue-a",
                    candidate_id="song-a",
                    source="/api/v1/file/other.wav",
                    filename="other.wav",
                    base_revision=first["revision"],
                )
            candidate = read_story_library(directory)["projects"]["story-a"]["music"]["cues"][0]["candidates"][0]
            self.assertEqual(candidate["name"], "theme.wav")
            self.assertEqual(candidate["id"], "song-a")

    def test_attach_story_song_candidate_is_isolated_by_workspace_dir(self):
        with tempfile.TemporaryDirectory() as workspace_a, tempfile.TemporaryDirectory() as workspace_b:
            write_story_library(workspace_a, {
                "projects": {
                    "story-a": {
                        "id": "story-a",
                        "music": {
                            "cues": [{
                                "id": "cue-a",
                                "candidates": [{"id": "song-a", "status": "pending", "source": ""}],
                            }],
                        },
                    },
                },
            }, base_revision=0)
            write_story_library(workspace_b, {
                "projects": {
                    "story-b": {
                        "id": "story-b",
                        "music": {
                            "cues": [{
                                "id": "cue-b",
                                "candidates": [{"id": "song-b", "status": "pending", "source": ""}],
                            }],
                        },
                    },
                },
            }, base_revision=0)
            with self.assertRaises(KeyError):
                attach_story_song_candidate(
                    workspace_b,
                    project_id="story-a",
                    cue_id="cue-a",
                    candidate_id="song-a",
                    source="/api/v1/file/stolen.wav",
                    filename="stolen.wav",
                    base_revision=1,
                )
            self.assertEqual(
                read_story_library(workspace_a)["projects"]["story-a"]["music"]["cues"][0]["candidates"][0]["source"],
                "",
            )

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
