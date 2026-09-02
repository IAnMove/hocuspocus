import unittest

from app.services.generation_provenance import normalize_submission_provenance


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


if __name__ == "__main__":
    unittest.main()
