"""Tests for durable Wizard conversation persistence."""

from __future__ import annotations

import tempfile
import unittest

from services.wizard_conversations import (
    WizardConversationRevisionConflict,
    reconstruct_cards,
    read_conversation,
    write_conversation,
)


class TestWizardConversations(unittest.TestCase):
    def test_round_trip_keeps_execution_key_and_job_link(self):
        with tempfile.TemporaryDirectory() as directory:
            saved = write_conversation(
                directory,
                {
                    "version": 1,
                    "revision": 0,
                    "messages": [{
                        "id": "msg-1",
                        "role": "assistant",
                        "text": "He encolado la exportación.",
                        "createdAt": 1,
                        "executionKey": "default|export_video_editor|edit-1|{}",
                        "cards": [{
                            "id": "card-1",
                            "state": "queued",
                            "message": "Exportando",
                            "executionKey": "default|export_video_editor|edit-1|{}",
                            "taskId": "export-99",
                            "recoverable": True,
                            "target": {"kind": "video_editor", "id": "edit-1", "title": "edit-1"},
                            "controls": {
                                "open": True, "cancel": True, "resume": False,
                                "viewErrors": False, "retryPending": False,
                            },
                        }],
                        "jobLinks": [{"taskId": "export-99", "pipelineId": ""}],
                    }],
                    "executions": [],
                },
                base_revision=0,
            )
            loaded = read_conversation(directory)
            self.assertEqual(loaded["revision"], 1)
            self.assertEqual(loaded["messages"][0]["executionKey"], "default|export_video_editor|edit-1|{}")
            self.assertEqual(loaded["messages"][0]["cards"][0]["taskId"], "export-99")
            cards = reconstruct_cards(loaded)
            self.assertEqual(cards[0]["taskId"], "export-99")
            self.assertEqual(cards[0]["state"], "queued")
            self.assertEqual(saved["revision"], 1)

    def test_conflict_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            write_conversation(directory, {"revision": 0, "messages": []}, base_revision=0)
            with self.assertRaises(WizardConversationRevisionConflict):
                write_conversation(directory, {"revision": 0, "messages": []}, base_revision=0)


if __name__ == "__main__":
    unittest.main()
