"""The clean-repo guard keeps personal generation sessions out of scripts/."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

import verify_clean_repo  # noqa: E402


def _boundary_label(path: str) -> str | None:
    for pattern, label in verify_clean_repo.FORBIDDEN_TRACKED_PATTERNS:
        if pattern.search(path):
            return label
    return None


class TestPersonalSessionBoundary(unittest.TestCase):
    def test_session_files_under_scripts_are_forbidden(self):
        for path in (
            "scripts/hobbit_mv.log",
            "scripts/watch_generation.log",
            "scripts/orc_song.json",
            "scripts/vader_friday_kernel_pipeline.json",
            "scripts/overnight_moria_concat.txt",
            "scripts/joke_clips.json",
            "scripts/joke_round_portrait_rest_jobs.json",
        ):
            with self.subTest(path=path):
                self.assertIsNotNone(_boundary_label(path), path)

    def test_repo_tooling_in_scripts_is_allowed(self):
        for path in (
            "scripts/ci_test_groups.json",
            "scripts/code_health_baseline.json",
            "scripts/code_health_exceptions.json",
            "scripts/nightly_baseline.json",
            "scripts/verify_clean_repo.py",
            "scripts/tests/nightly_wizard_smoke.test.mjs",
            "scripts/ci-python-requirements.txt",
            "logs/api/latest.log",
            "docs/development/CODE_HEALTH.md",
        ):
            with self.subTest(path=path):
                self.assertIsNone(_boundary_label(path), path)

    def test_gitignore_covers_the_same_patterns(self):
        gitignore = (_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for pattern in (
            "scripts/*.log",
            "scripts/*_song.json",
            "scripts/*_pipeline.json",
            "scripts/*_concat.txt",
            "scripts/joke_*.json",
        ):
            self.assertIn(pattern, gitignore)

    def test_no_tracked_file_crosses_the_boundary(self):
        result = subprocess.run(
            ["git", "-C", str(_ROOT), "ls-files", "-z", "scripts"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        )
        tracked = [path for path in result.stdout.split("\0") if path]
        self.assertTrue(tracked)
        leaked = [path for path in tracked if _boundary_label(path)]
        self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()
