# GitHub branch protection (inspection and proposed apply)

Inspected: 2026-09-05. Token `IAnMove` (repository admin). This file does
**not** apply rulesets. Until an admin applies the payloads below and a
read-only re-check confirms them, protection is **prepared**, not active
for the missing pieces.

## What exists today

| Surface | Fact |
|---|---|
| Workflow `CI` | Runs on `push`/`pull_request` to `main`, `development`, `dev`. No `paths` / `paths-ignore` filters. |
| Job `CI required` | Aggregator. `if: always()`. Fails unless the three deterministic jobs are `success`. Cancelled/skipped/missing ≠ success. |
| Check names emitted | `Clean-repo guard + Python checks`, `UI tests + lint + type-check + build`, `UI E2E boot (Chromium + simulated API)`, `CI required` |
| Required on GitHub? | **No.** A job named `CI required` is not a branch rule. PRs can merge without it. |
| Ruleset `Protect main` (id `22330118`) | Active on `~DEFAULT_BRANCH` (`main`). Rules: no deletion, no force-push, PR required, **0** approving reviews. **No required status checks.** `bypass_actors: []`, `current_user_can_bypass: never` for this token. |
| `development` | `protected: false`. No ruleset. Direct push, force-push and deletion are possible with write access. |
| Legacy branch protection API | 403 for this token. Rulesets are the live mechanism. |
| Org rulesets | None visible (`IAnMove` is a user namespace). |
| Auto-merge | `allow_auto_merge: false`. |
| Admin / residual bypass | Only collaborator: `IAnMove` (`admin`). An admin can still edit or delete the ruleset. That is the remaining owner bypass. |
| Actions permissions | Workflow default `contents: read`. Measuring jobs have no `pull-requests: write`. Comment jobs are same-repo only and must run publisher scripts from the **base** tree. |

Do not require human approving reviews. Do not treat `Analyze pull request`
as a required technical check.

The single GitHub required context should be **`CI required`** (the job
name), not the workflow name `CI`. The three named jobs are its inputs.

## Proposed remote change (authorization required)

Do not apply from an implementer session. After apply, re-read the rulesets
and record bypasses.

### 1. Update ruleset 22330118 `Protect main`

Keep deletion, non-fast-forward, pull_request with 0 reviews. Add:

```json
{
  "type": "required_status_checks",
  "parameters": {
    "strict_required_status_checks_policy": true,
    "do_not_enforce_on_create": false,
    "required_status_checks": [
      { "context": "CI required" }
    ]
  }
}
```

`strict_required_status_checks_policy: true` means the required check must
run on the current HEAD of the PR, not an older SHA.

### 2. Create ruleset `Protect development`

```json
{
  "name": "Protect development",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/development"],
      "exclude": []
    }
  },
  "bypass_actors": [],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "allowed_merge_methods": ["merge"]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "do_not_enforce_on_create": false,
        "required_status_checks": [
          { "context": "CI required" }
        ]
      }
    }
  ]
}
```

Merge method `merge` only on `development` matches the integration policy
(no squash of the integration line). `main` may keep merge/squash/rebase
until a release policy tightens it.

### 3. Do not enable

- Required human approvals
- Auto-merge / merge queue
- Making `Independent QA` a required check (publisher identity is not proven)
- Bypass for the implementer token
- Changing secrets

## Verification after apply (read-only)

```bash
gh api repos/IAnMove/hocuspocus/rulesets
gh api repos/IAnMove/hocuspocus/rulesets/<id>
gh api repos/IAnMove/hocuspocus/rules/branches/main
gh api repos/IAnMove/hocuspocus/rules/branches/development
gh api repos/IAnMove/hocuspocus/branches/main --jq .protected
gh api repos/IAnMove/hocuspocus/branches/development --jq .protected
```

Confirm:

- `CI required` appears as a required status check on both branches
- deletion and non-fast-forward remain
- `required_approving_review_count` is 0
- `bypass_actors` is still empty
- a PR with a failing `CI required` cannot be merged through the UI
- a direct push to `development` is rejected

Until those reads succeed, say **prepared**, not **protección activa**.
