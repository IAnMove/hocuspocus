import unittest

from app.services.generation_provenance import (
    normalize_submission_provenance,
    resolve_generation_location,
)


class GenerationSubmissionProvenanceTests(unittest.TestCase):
    def test_normalizes_browser_owned_fields_without_accepting_runtime_ids(self):
        value = normalize_submission_provenance({
            "actor": "wizard",
            "tool": "spoofed",
            "capability": "start_generation",
            "workspace_id": "collection-7",
            "output_folder": "not-browser-owned",
            "command": {
                "command_id": "command-1",
                "workflow_id": "workflow-2",
                "run_id": "run-3",
                "task_id": "spoofed-task",
                "job_id": "spoofed-job",
                "pipeline_id": "spoofed-pipeline",
            },
        })
        self.assertEqual(value["actor"], "wizard")
        self.assertEqual(value["tool"], "studio")
        self.assertEqual(value["capability"], "start_generation")
        self.assertEqual(value["workspace_id"], "collection-7")
        self.assertEqual(value["command"], {
            "command_id": "command-1",
            "workflow_id": "workflow-2",
            "run_id": "run-3",
        })
        self.assertNotIn("output_folder", value)

    def test_invalid_or_missing_actor_remains_unknown(self):
        self.assertEqual(normalize_submission_provenance(None)["actor"], "unknown")
        self.assertEqual(
            normalize_submission_provenance({"actor": "administrator"})["actor"],
            "unknown",
        )

    def test_preserves_story_object_references_but_not_runtime_ids(self):
        value = normalize_submission_provenance({
            "actor": "wizard",
            "capability": "generate_story_song",
            "workspace_id": "music-night",
            "project_id": "story-1",
            "production_id": "production-1",
            "cue_id": "cue-1",
            "candidate_id": "candidate-1",
            "song_version": "2",
            "command": {"task_id": "spoofed-task", "pipeline_id": "spoofed-pipeline"},
        })
        self.assertEqual(value["project_id"], "story-1")
        self.assertEqual(value["production_id"], "production-1")
        self.assertEqual(value["cue_id"], "cue-1")
        self.assertEqual(value["candidate_id"], "candidate-1")
        self.assertEqual(value["song_version"], "2")
        self.assertNotIn("task_id", value["command"])
        self.assertNotIn("pipeline_id", value["command"])

    def test_physical_output_folder_does_not_invent_workspace_collection(self):
        """A Story output folder is usable without a collection record."""
        value = normalize_submission_provenance({
            "actor": "wizard",
            "output_folder": "e2e_wizard",
            "project_id": "story-1",
        })
        self.assertNotIn("workspace_id", value)
        self.assertNotIn("output_folder", value)
        self.assertEqual(
            resolve_generation_location(output_folder="e2e_wizard"),
            {"workspace_id": None, "output_folder": "e2e_wizard"},
        )


if __name__ == "__main__":
    unittest.main()
