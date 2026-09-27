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

    def test_release_budget_selection_requires_same_repository_metadata(self):
        import os
        import subprocess

        workflow = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        for field in ('base', 'head'):
            self.assertIn(f'github.event.pull_request.{field}.repo.full_name', workflow)
        wrapper = (ROOT / 'scripts/check_code_health_pr_base.sh').read_text(encoding='utf-8')
        condition = wrapper.split('RELEASE_INTEGRATION=false\n', 1)[1].split('; then', 1)[0]
        command = condition + '; then exit 0; else exit 1; fi'
        metadata = {
            'BASE_BRANCH': 'main', 'SOURCE_BRANCH': 'development',
            'GITHUB_REPOSITORY': 'owner/project',
            'BASE_REPOSITORY': 'owner/project', 'SOURCE_REPOSITORY': 'owner/project',
        }
        cases = [({}, 0), ({'SOURCE_REPOSITORY': 'fork/project'}, 1),
                 ({'BASE_REPOSITORY': ''}, 1), ({'GITHUB_REPOSITORY': ''}, 1),
                 ({'SOURCE_BRANCH': 'feature'}, 1), ({'BASE_BRANCH': 'development'}, 1)]
        for changed, expected in cases:
            with self.subTest(changed=changed):
                result = subprocess.run(['bash', '-c', command], env={**os.environ, **metadata, **changed})
                self.assertEqual(result.returncode, expected)

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

    def test_main_push_verification_fetches_complete_development_history_first(self):
        wrapper = (ROOT / 'scripts/check_code_health_pr_base.sh').read_text(encoding='utf-8')
        push = wrapper.split('elif [[ "${GITHUB_EVENT_NAME:-}" == "push"', 1)[1]
        self.assertIn('"${GITHUB_REF:-}" == "refs/heads/main"', push)
        self.assertIn('"${EVENT_REPOSITORY:-}" == "$GITHUB_REPOSITORY"', push)
        self.assertIn('"${GITHUB_SHA:-}" == "$HEAD_SHA"', push)
        self.assertIn('"$HEAD_SHA" == "$(git -C "$ROOT" rev-parse HEAD)"', push)
        self.assertLess(push.index('--unshallow'), push.index('main_push_source'))
        self.assertLess(
            push.index('refs/heads/development:refs/remotes/origin/development'),
            push.index('main_push_source'),
        )

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

    def test_ui_validation_runs_after_ratchet_failure_without_masking_failures(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        ui = text[text.index('  ui-check:'):text.index('  ui-e2e:')]
        self.assertIn('name: Install UI deps\n        id: ui-deps', ui)
        for name in ('UI tests', 'Lint with zero warnings', 'Type-check, build and bundle budget'):
            self.assertIn(
                f"name: {name}\n        if: ${{{{ !cancelled() && steps.ui-deps.outcome == 'success' }}}}",
                ui,
            )
        self.assertNotIn('continue-on-error:', ui)
        self.assertIn('exit "$STATUS"', ui)

    def test_ci_required_aggregates_existing_job_names(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        self.assertIn('name: Clean-repo guard + Python checks', text)
        self.assertIn('name: Python tests A', text)
        self.assertIn('name: Python tests B', text)
        self.assertIn('name: UI tests + lint + type-check + build', text)
        self.assertIn('name: UI E2E boot (Chromium + simulated API)', text)
        self.assertIn('name: CI required', text)
        self.assertIn('if: always()', text)
        dependencies = 'needs: [guard, python-tests-a, python-tests-b, ui-check, ui-e2e, ui-speech-windows]'
        self.assertIn(dependencies, text)
        self.assertNotIn('code-health-comment', text.split(dependencies, 1)[1][:200])
        self.assertNotIn('independent-qa', text.split(dependencies, 1)[1][:200])
        self.assertNotIn('Independent QA', text.split(dependencies, 1)[1][:400])
        self.assertIn('Python tests A=${{ needs.python-tests-a.result }}', text)
        self.assertIn('Python tests B=${{ needs.python-tests-b.result }}', text)
        self.assertIn('Speech E2E Windows (real H.264 + AAC)=${{ needs.ui-speech-windows.result }}', text)
        windows = text.split('  ui-speech-windows:', 1)[1].split('  code-health-comment:', 1)[0]
        self.assertIn('HOCUSPOCUS_REQUIRE_SPEECH_AAC: "1"', windows)
        self.assertIn('playwright install chromium msedge', windows)
        self.assertIn('scene3d-speech.spec.ts scene3d-media-screen.spec.ts', windows)

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
        self.assertIn('AUTHORIZATION: basic', review)
        self.assertNotIn('AUTHORIZATION: bearer', review)
        self.assertNotIn('git fetch --no-tags origin "${HEAD_SHA}"', review)

    def test_protection_doc_does_not_claim_required_checks_are_active(self):
        text = (ROOT / 'docs/development/GITHUB_PROTECTION.md').read_text(encoding='utf-8')
        self.assertIn('prepared', text.lower())
        self.assertIn('22330118', text)
        self.assertIn('{ "context": "CI required" }', text)
        self.assertIn('say **prepared**, not **protección activa**', text)

    def test_qa_publisher_checkouts_pr_base_not_merge_ref(self):
        text = (ROOT / '.github/workflows/qa-evidence.yml').read_text(encoding='utf-8')
        self.assertIn('github.event.pull_request.base.sha || github.sha', text)
        self.assertNotIn('ref: ${{ github.sha }}', text)
        self.assertIn('publisher not on PR base yet', text)


if __name__ == '__main__':
    unittest.main()
