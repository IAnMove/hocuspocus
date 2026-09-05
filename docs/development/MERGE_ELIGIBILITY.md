# Merge eligibility (simulation only)

Status: P7 simulation. This script **never merges**. It never talks to GitHub.
Execute mode and auto-merge stay disabled. Remote rulesets stay unapplied.
Activation needs a separate authorization and a different adapter identity
from the component that evaluates PRs.

## Command

```bash
python scripts/evaluate_merge_eligibility.py --snapshot path/to/snapshot.json
```

- Exit `0`: the snapshot **would** be eligible. `would_merge` is still `false`.
- Exit `1`: not eligible. Reasons are listed.
- Exit `2`: infrastructure (missing file, invalid JSON, insufficient token).

A simulation is not a merge. CI green is not independent QA. Cursor of an
older SHA is not review of the current HEAD. Silence is not approval.

## What the snapshot must prove

The current HEAD, not an earlier commit:

1. Required checks all `success`: `Clean-repo guard + Python checks`,
   `UI tests + lint + type-check + build`,
   `UI E2E boot (Chromium + simulated API)`, `CI required`.
   Cancelled, skipped, missing or failed is not success.
2. Cursor state `reviewed_at_head` on that exact HEAD.
3. Independent QA evidence `pass` on that exact HEAD
   (`python scripts/verify_qa_evidence.py`).
4. No open blocking findings.
5. Mergeable, not a draft, base `development` or `main`.
6. Files stay in the low-risk simulate scope. Product code (`app/`, `ui/src/`),
   launchers, workflows, outputs, and the merge/QA gate itself are out of
   scope until a later authorization. Musical execution risk waits on P5.
7. The adapter must not be able to change branch protections.
8. A duplicate event must not produce a second merge action.
9. A new HEAD or base invalidates eligibility.

## What this delivery does not do

- It does not call `gh pr merge` or the GitHub merge API.
- It does not enable GitHub auto-merge or a merge queue.
- It does not apply rulesets or store admin credentials.
- `mode: execute` is always rejected.

Schema: [merge-eligibility.schema.json](merge-eligibility.schema.json).
Pilot fixtures live in `tests/test_merge_eligibility.py`: three eligible
snapshots and the seeded ineligible cases (cancelled CI, missing review, head
advanced, duplicate event, insufficient token, own-gate change).
