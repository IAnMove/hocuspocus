# Agent QA policy (minimum)

Status: P0 policy plus P2 `CI required`, P6 evidence validator, and P7
merge-eligibility **simulation**. Remote GitHub protection is **prepared**,
not fully active. See [GITHUB_PROTECTION.md](GITHUB_PROTECTION.md). Applying
or widening rulesets needs a separate admin authorization.

## Who reviews what

- **Agents** own technical review and adversarial QA. Heuristic Analyze
  (`pr-review.yml`) is not an LLM review and does not count as independent
  technical review.
- **Humans** own brief functional validation, product decisions, and
  permissions. A merge click is an operational act. It does not certify a
  human code review.
- Cursor Bugbot counts only when its comment is tied to the **current HEAD**.
  A previous commit's review does not cover a new SHA. Silence is not
  approval.

Do not enable auto-merge during this transition.
`python scripts/evaluate_merge_eligibility.py --snapshot …` only reports
whether a PR **would** be eligible. It never merges. See
[MERGE_ELIGIBILITY.md](MERGE_ELIGIBILITY.md).

## Required checks (names as of this tree)

The workflow already emits these names. They were not removed.

1. `Clean-repo guard + Python checks`
2. `UI tests + lint + type-check + build`
3. `UI E2E boot (Chromium + simulated API)`
4. `CI required`

`CI required` is the aggregator from P2: cancelled, skipped or failed
dependencies are not success. The **GitHub required context** to enforce is
the job name `CI required`, not the workflow title `CI`. A job that exists
in YAML is not a branch rule until a ruleset lists it.

Do not require human approval reviews that will not be performed. Do not
treat Analyze pull request as a required technical review.

Independent review uses
`python scripts/verify_qa_evidence.py` and
[QA_ACCEPTANCE.md](QA_ACCEPTANCE.md). That validator is **not** a required
GitHub check yet.

## Remote configuration (inspected 2026-09-05)

Verified in read-only against `IAnMove/hocuspocus`:

- Ruleset `Protect main` (`22330118`) is **active** on default branch `main`:
  PR required, no deletion, no force-push, 0 approving reviews, empty
  bypass list. **No required status checks.**
- `development` is **not** protected. Write access can push, force-push or
  delete it without a PR or CI.
- `CI required` runs on every PR to `main`/`development`/`dev` (no path
  filters) but GitHub does not require it to merge.
- Auto-merge is off. The remaining owner bypass is editing or deleting the
  ruleset (`IAnMove` is the only admin collaborator).

Exact payloads to add required `CI required` on `main` and to protect
`development` are in [GITHUB_PROTECTION.md](GITHUB_PROTECTION.md). Ask an
admin to apply them, then re-read. Until that verification, say prepared,
not active.

Do not apply rulesets from this file or from an implementer session.

## Evidence states (keep them separate)

designed / implemented / commit / PR / CI of the current HEAD /
independent agent review of the current HEAD / Cursor of the current HEAD /
merged / real media validation.

A simulation is not real generation. A skipped check is not a pass.
An implementer-written JSON is not independent review.
