"""Unit tests for the repo PR review agent."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest


_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

from analyze_pr import (  # noqa: E402
    COMMENT_MARKER,
    FileDiff,
    analyze_files,
    parse_unified_diff,
    render_markdown,
)


SAMPLE_DIFF = """\
diff --git a/app/services/story_lab.py b/app/services/story_lab.py
index 111..222 100644
--- a/app/services/story_lab.py
+++ b/app/services/story_lab.py
@@ -1,3 +1,6 @@
 def plan():
-    return {}
+    api_key = "sk-abcdefghijklmnopqrstuvwxyz123456"
+    eval("plan()")
+    return {"ok": True}
diff --git a/ui/src/App.tsx b/ui/src/App.tsx
index 333..444 100644
--- a/ui/src/App.tsx
+++ b/ui/src/App.tsx
@@ -1,2 +1,3 @@
 export function App() {
+  return <div>hello</div>
 }
"""


class TestParseUnifiedDiff(unittest.TestCase):
    def test_parses_added_and_removed_lines(self):
        files = parse_unified_diff(SAMPLE_DIFF)
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0].path, "app/services/story_lab.py")
        self.assertEqual(files[0].status, "modified")
        self.assertTrue(any("api_key" in line for line in files[0].added))
        self.assertEqual(files[1].path, "ui/src/App.tsx")

    def test_parses_added_file(self):
        diff = """\
diff --git a/docs/new.md b/docs/new.md
new file mode 100644
index 000..111
--- /dev/null
+++ b/docs/new.md
@@ -0,0 +1,2 @@
+hello
+world
"""
        files = parse_unified_diff(diff)
        self.assertEqual(files[0].status, "added")
        self.assertEqual(files[0].path, "docs/new.md")
        self.assertEqual(files[0].added, ["hello", "world"])

    def test_parses_deleted_file(self):
        diff = """\
diff --git a/docs/old.md b/docs/old.md
deleted file mode 100644
index 111..000
--- a/docs/old.md
+++ /dev/null
@@ -1 +0,0 @@
-gone
"""
        files = parse_unified_diff(diff)
        self.assertEqual(files[0].status, "deleted")
        self.assertEqual(files[0].path, "docs/old.md")


class TestAnalyzeFiles(unittest.TestCase):
    def test_flags_secret_eval_missing_tests_and_ui(self):
        review = analyze_files(parse_unified_diff(SAMPLE_DIFF))
        titles = {f.title for f in review.findings}
        self.assertIn("Possible secret in added lines", titles)
        self.assertIn("Dangerous dynamic execution", titles)
        self.assertIn("Product Python changed without tests", titles)
        self.assertIn("UI changed — rebuild before merge", titles)
        self.assertEqual(review.risk, "high")
        self.assertIn("backend services", review.areas)
        self.assertIn("React UI", review.areas)

    def test_flags_never_publish_weight(self):
        review = analyze_files([
            FileDiff(
                path="app/ckpts/wan.safetensors",
                status="added",
                added=["binary"],
            ),
            FileDiff(
                path="app/loras/style.civitai.json",
                status="added",
                added=["{}"],
            ),
        ])
        titles = {f.title for f in review.findings}
        self.assertIn("Model weight or checkpoint committed", titles)
        self.assertIn("Never-publish artifact in the diff", titles)
        self.assertEqual(review.risk, "high")

    def test_flags_telemetry(self):
        review = analyze_files([
            FileDiff(
                path="app/launch.py",
                status="modified",
                added=["sentry.init(dsn='https://example')"],
            ),
        ])
        self.assertTrue(any(f.title == "Local-first policy risk" for f in review.findings))

    def test_task_generation_ids_are_not_token_shaped_secrets(self):
        review = analyze_files([
            FileDiff(
                path="ui/tests/agentActions.test.mjs",
                status="modified",
                added=[
                    "taskId: `task-generation-job-studio-${generationCalls}`",
                    "assert.equal(first[1].report.taskId, 'task-generation-job-studio-1')",
                ],
            ),
        ])
        self.assertFalse(any(f.title == "Possible secret in added lines" for f in review.findings))

    def test_docs_only_is_low_risk(self):
        review = analyze_files([
            FileDiff(path="README.md", status="modified", added=["# note"], removed=[]),
        ])
        self.assertEqual(review.risk, "low")
        self.assertFalse(any(f.severity == "high" for f in review.findings))

    def test_python_change_with_tests_skips_missing_test_finding(self):
        review = analyze_files([
            FileDiff(
                path="app/services/story_lab.py",
                status="modified",
                added=["return 1"],
            ),
            FileDiff(
                path="tests/test_story_lab.py",
                status="modified",
                added=["assert True"],
            ),
        ])
        titles = {f.title for f in review.findings}
        self.assertNotIn("Product Python changed without tests", titles)


class TestRenderMarkdown(unittest.TestCase):
    def test_includes_marker_risk_and_checklist(self):
        review = analyze_files(parse_unified_diff(SAMPLE_DIFF))
        markdown = render_markdown(review)
        self.assertIn(COMMENT_MARKER, markdown)
        self.assertIn("**Risk:** high", markdown)
        self.assertIn("CONTRIBUTING checklist", markdown)
        self.assertIn("verify_clean_repo.py", markdown)


if __name__ == "__main__":
    unittest.main()
