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

    def test_ci_ratchet_uses_pr_base_or_push_before_and_fails_closed(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        self.assertIn(
            'github.event.pull_request.base.sha || github.event.before',
            text,
        )
        self.assertIn(
            'Cannot resolve code-health base: need pull_request.base.sha or push before',
            text,
        )
        self.assertNotIn(
            'BASE_SHA: ${{ github.event.pull_request.base.sha }}\n',
            text,
        )

    def test_ci_measures_without_pr_write_and_reuses_helper(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        self.assertRegex(text, r'(?m)^permissions:\n  contents: read\n')
        self.assertIsNone(re.search(r'(?m)^ {2,}pull-requests:\s*write\s*$', text))
        self.assertNotIn('GH_TOKEN', text)
        self.assertNotIn('--publish-pr-comment', text)
        self.assertIn('bash scripts/check_code_health_pr_base.sh', text)
        self.assertIn('scripts/ci_required.py', text)
        self.assertIn('STATUS=${PIPESTATUS[0]}', text)
        helper_at = text.index('bash scripts/check_code_health_pr_base.sh')
        summary_at = text.index('GITHUB_STEP_SUMMARY', helper_at)
        status_at = text.index('STATUS=${PIPESTATUS[0]}', helper_at)
        exit_at = text.index('exit "$STATUS"', helper_at)
        self.assertLess(status_at, summary_at)
        self.assertLess(summary_at, exit_at)

    def test_ci_cancels_only_superseded_pull_requests(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        self.assertIn(
            'github.event.pull_request.number || github.run_id',
            text,
        )
        self.assertIn(
            'cancel-in-progress: ${{ github.event_name == \'pull_request\' }}',
            text,
        )

    def test_ci_required_aggregates_existing_job_names(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        self.assertIn('name: Clean-repo guard + Python checks', text)
        self.assertIn('name: UI tests + lint + type-check + build', text)
        self.assertIn('name: UI E2E boot (Chromium + simulated API)', text)
        self.assertIn('name: CI required', text)
        self.assertIn('if: always()', text)
        self.assertIn('needs: [guard, ui-check, ui-e2e]', text)


if __name__ == '__main__':
    unittest.main()
