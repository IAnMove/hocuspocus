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
        ui = text[text.index('  ui-check:'):text.index('  ui-e2e:')]
        comment = text[text.index('  code-health-comment:'):text.index('  ci-required:')]
        self.assertNotIn('pull-requests: write', ui)
        self.assertNotIn('GH_TOKEN', ui)
        self.assertIn('pull-requests: write', comment)
        self.assertIn('GH_TOKEN', comment)
        self.assertIn('scripts/publish_pr_markdown.py', comment)
        self.assertIn(
            'github.event.pull_request.head.repo.full_name == github.repository',
            comment,
        )
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
        self.assertNotIn('code-health-comment', text.split('needs: [guard, ui-check, ui-e2e]', 1)[1][:200])

    def test_agent_qa_policy_still_lists_ci_required(self):
        text = (ROOT / 'docs/development/AGENT_QA_POLICY.md').read_text(encoding='utf-8')
        self.assertIn('`CI required`', text)
        self.assertIn('python scripts/verify_qa_evidence.py', text)
        self.assertIn('Do not enable auto-merge', text)
        self.assertIn('python scripts/evaluate_merge_eligibility.py', text)
        self.assertIn('GITHUB_PROTECTION.md', text)
        self.assertIn('prepared', text.lower())

    def test_ci_has_no_path_filters_that_skip_required_jobs(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        header = text.split('jobs:', 1)[0]
        self.assertNotIn('paths:', header)
        self.assertNotIn('paths-ignore:', header)
        self.assertIn('if: always()', text[text.index('  ci-required:'):])

    def test_write_jobs_run_publisher_scripts_from_pr_base(self):
        ci = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        comment = ci[ci.index('  code-health-comment:'):ci.index('  ci-required:')]
        self.assertIn('github.event.pull_request.base.sha', comment)
        self.assertIn('persist-credentials: false', comment)
        review = (ROOT / '.github/workflows/pr-review.yml').read_text(encoding='utf-8')
        self.assertIn('github.event.pull_request.base.sha || github.sha', review)
        self.assertIn('persist-credentials: false', review)
        self.assertIn('pull/${PR_NUMBER}/head:refs/remotes/origin/pr-head', review)
        self.assertNotIn('git fetch --no-tags origin "${HEAD_SHA}"', review)

    def test_protection_doc_does_not_claim_required_checks_are_active(self):
        text = (ROOT / 'docs/development/GITHUB_PROTECTION.md').read_text(encoding='utf-8')
        self.assertIn('prepared', text.lower())
        self.assertIn('22330118', text)
        self.assertIn('{ "context": "CI required" }', text)
        self.assertIn('say **prepared**, not **protección activa**', text)


if __name__ == '__main__':
    unittest.main()
