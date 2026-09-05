# Integration and release branches

Decision: 2026-09-05. `development` is the integration base; `main` is the published
Pinokio line. This policy does not itself configure remote rulesets or release jobs.
Workflow branch filters include both lines; existing `dev` coverage is retained
during transition, but new work must not use that ambiguous legacy name.

## Ordinary agent work

1. Read local AGENTS instructions when present, CONTRIBUTING, SLICE_QUEUE and the
   assigned acceptance criteria. Inspect branches, PRs and ownership before editing.
2. Fetch origin and create an isolated feature/fix worktree from origin/development.
   Never switch the branch in another agent's shared checkout or carry untracked
   outputs into a new PR.
3. Compare the change against development. For local validation pass explicit
   `BASE_REF=origin/development` (or exact fetched base SHA via BASE_SHA where
   supported). Older wrappers default to main; their migration is a separate owned
   task, not permission to skip ratchet.
4. Run relevant checks and independent technical review/QA on the actual head.
   Open PR with explicit `--base development`; do not rely on the default branch.
5. Respect dependencies and at most one PR per hotspot. A green open PR is not a
   merged dependency. No auto-merge is enabled by this document. Simulated
   eligibility is `python scripts/evaluate_merge_eligibility.py`; a
   would-merge result is not a merge.

Human review is functional and brief, not exhaustive code review. Agents and
deterministic checks supply technical review/QA. A human merge click is operational
and must not be recorded as technical approval. Missing technical evidence remains
pending; heuristics or silence from a reviewer are not evidence of success.

## Release from development to main

1. Prepare one small release PR from development to main, with notes, known
   limitations and a bounded functional/local smoke checklist.
2. Briefly freeze integration while testing the candidate. Record source head, base
   and tested integration SHA. CI simulation proves software contracts, not actual
   model execution. Image/audio/video generation smoke remains explicit local work.
3. Any head/base change invalidates affected evidence. Publish only the tested
   candidate combination; never test A and promote a later B without revalidation.
4. Use a merge commit between permanent branches (not squash/rebase) to preserve
   ancestry. Verify the final tree and post-merge checks before tagging the exact
   released commit. Release/publishing requires separate authorization.
5. Synchronize main back to development as necessary using an explicit PR when
   it introduces history or fixes not yet present. Do not force reset development
   as a routine release operation.

No third permanent release branch is required. A release tag identifies a version;
main advancing is still distribution-impacting if Pinokio follows that branch.
Changing the installer/updater or adding preview channels is a separate task.

## Urgent hotfix

Branch from origin/main only for an explicitly scoped published-version hotfix.
Validate and open the PR to main. Carry the accepted fix back to development
immediately through a checked PR; do not leave integration without a shipped fix.
Git rollback does not undo data migrations: backup/recovery are separate evidence.

## Transition checklist

- [ ] Record previous development tip and preserve its history before realignment.
- [ ] Confirm development is based on the selected current remote main SHA.
- [ ] Merge branch-filter/policy PR into development after its own CI/review.
- [ ] Coordinate open PRs with owners; retarget ordinary PRs only with authorization,
  inspect changed diff and rerun checks. No blind bulk retarget.
- [ ] Configure protections for both branches separately when authorized; verify
  emitted check names and GitHub sources before making them required.
- [ ] Adapt local validation defaults in its existing owned PR; until then use an
  explicit base. Do not mix integration base with historical metric baseline.
- [ ] Verify installation/update distribution behavior before the first release.

Remote configuration, merges and real generation are not claimed complete by a
committed checklist. Mutable transition evidence belongs in the PR/handoff.

## Handoff prompt for Grok

```text
HocusPocus now integrates ordinary work in development; main is the published line.
Fetch origin, read CONTRIBUTING.md, docs/development/BRANCHING.md and SLICE_QUEUE.md,
plus any local AGENTS.md instructions. Create feature/fix work in isolated worktrees
from origin/development; open PRs with --base development. Use the actual PR base
for ratchet (explicit BASE_REF or BASE_SHA while wrappers are transitioning).
Preserve ownership and untracked files. Historical main examples in phase plans do
not override this branch policy. Before retargeting existing PRs, coordinate with
their owner and obtain authorization; review the new diff and rerun checks.
Do not merge, change protections or publish unless separately authorized. Release
PRs go development → main with exact-candidate evidence and required local smoke.
CI green, independent review, merge and real model validation are separate states.
```
