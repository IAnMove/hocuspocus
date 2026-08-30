"""Tests for durable Wizard workflow checkpoint persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.wizard_workflows import (
    WizardWorkflowRevisionConflict,
    read_workflows,
    write_workflows,
)


class TestWizardWorkflows(unittest.TestCase):
    def test_round_trip_preserves_correlation_and_redacts_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            saved = write_workflows(
                directory,
                {
                    "version": 1,
                    "revision": 0,
                    "workflows": [{
                        "workflowId": "workflow-1",
                        "type": "create_rhythmic_3d_video",
                        "workspace": "default",
                        "userRequest": "Create a rhythmic video",
                        "state": "waiting",
                        "currentStep": 0,
                        "steps": [{
                            "stepId": "song",
                            "kind": "generate_song",
                            "state": "waiting",
                            "input": {"prompt": "synthwave", "api_key": "secret"},
                            "taskId": "task-song-1",
                            "pipelineId": "pipeline-1",
                            "outputRefs": ["song.wav"],
                            "attempts": 1,
                        }],
                        "inputSnapshot": {"prompt": "synthwave", "access_token": "secret"},
                        "resolvedEntityIds": {"scene": "scene-1"},
                        "taskIds": ["task-song-1"],
                        "pipelineIds": ["pipeline-1"],
                        "outputRefs": ["song.wav"],
                        "confirmationScope": ["generate", "export"],
                        "processedEventIds": [40],
                        "createdAt": 1,
                        "updatedAt": 2,
                    }],
                },
                base_revision=0,
            )
            loaded = read_workflows(directory)
            workflow = loaded["workflows"][0]
            self.assertEqual(saved["revision"], 1)
            self.assertEqual(workflow["steps"][0]["taskId"], "task-song-1")
            self.assertEqual(workflow["pipelineIds"], ["pipeline-1"])
            self.assertEqual(workflow["resolvedEntityIds"]["scene"], "scene-1")
            self.assertEqual(workflow["steps"][0]["input"]["api_key"], "[REDACTED]")
            self.assertEqual(workflow["inputSnapshot"]["access_token"], "[REDACTED]")

    def test_conflict_does_not_overwrite_newer_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            write_workflows(directory, {"revision": 0, "workflows": []}, base_revision=0)
            with self.assertRaises(WizardWorkflowRevisionConflict):
                write_workflows(directory, {"revision": 0, "workflows": []}, base_revision=0)
            self.assertEqual(read_workflows(directory)["revision"], 1)

    def test_runtime_exposes_workspace_scoped_get_and_put_endpoints(self):
        source = (Path(__file__).parents[1] / "app" / "_launch_runtime.py").read_text(encoding="utf-8")
        self.assertIn('@api.get("/api/v1/wizard/workflows")', source)
        self.assertIn('@api.put("/api/v1/wizard/workflows")', source)
        self.assertIn('"wizard_workflow_revision_conflict"', source)


if __name__ == "__main__":
    unittest.main()
