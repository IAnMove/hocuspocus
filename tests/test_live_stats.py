import tempfile
import unittest
from pathlib import Path

from app.services import live_stats


class RuntimeIdentityTests(unittest.TestCase):
    def test_identity_changes_when_ui_bundle_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("first build", encoding="utf-8")
            first = live_stats.get_runtime_identity(tmp)

            index.write_text("second build", encoding="utf-8")
            second = live_stats.get_runtime_identity(tmp)

        self.assertEqual(first["instance_id"], second["instance_id"])
        self.assertNotEqual(first["ui_build_id"], second["ui_build_id"])

    def test_missing_bundle_has_stable_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity = live_stats.get_runtime_identity(tmp)

        self.assertEqual(identity["ui_build_id"], "missing")
        self.assertTrue(identity["instance_id"])


if __name__ == "__main__":
    unittest.main()
