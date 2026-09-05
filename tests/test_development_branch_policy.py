"""Cheap regression guard for the explicit branch allowlists (no GitHub writes)."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DevelopmentBranchPolicyTests(unittest.TestCase):
    def test_ci_checks_both_integration_and_release_events(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        for event in ('push', 'pull_request'):
            match = re.search(rf'^  {event}:\n    branches: \[([^\]]+)\]', text, re.M)
            self.assertIsNotNone(match, f'Missing explicit {event} branch allowlist')
            branches = {part.strip() for part in match.group(1).split(',')}
            self.assertTrue({'main', 'development'} <= branches)

    def test_auxiliary_review_includes_development(self):
        text = (ROOT / '.github/workflows/pr-review.yml').read_text(encoding='utf-8')
        match = re.search(r'^    branches: \[([^\]]+)\]', text, re.M)
        self.assertIsNotNone(match)
        self.assertIn('development', {part.strip() for part in match.group(1).split(',')})


if __name__ == '__main__':
    unittest.main()
