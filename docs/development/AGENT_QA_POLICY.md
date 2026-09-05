# Agent QA policy (minimum)

Status: P0 policy plus P2 `CI required`, P6 evidence validator, and P7
merge-eligibility **simulation**. Remote GitHub protection is **not**
applied by this file. That needs a separate admin authorization.

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

The workflow already emits these names. They were not removed. If GitHub
does not list `CI required` yet, it still belongs here; do not drop it.

1. `Clean-repo guard + Python checks`
2. `UI tests + lint + type-check + build`
3. `UI E2E boot (Chromium + simulated API)`
4. `CI required`

`CI required` is the aggregator from P2: cancelled, skipped or failed
dependencies are not success. Do not require human approval reviews that
will not be performed. Do not treat Analyze pull request as a required
technical review.

Independent review uses
`python scripts/verify_qa_evidence.py` and
[QA_ACCEPTANCE.md](QA_ACCEPTANCE.md). That validator is **not** a required
GitHub check yet.

## Remote configuration (prepared, not executed)

Ask an admin to apply, then verify in read-only:

- PRs required to update `main` / `development`
- the four checks above required, including `CI required`
- no force-push / no deleting those branches
- bypass limited to repository owners; record that owners can still bypass
- credentials for applying rulesets stay off the implementer agent

`CI required` already exists in `.github/workflows/ci.yml`. After P6, require
the verified QA check only when its publisher identity is proven. Do not
apply that ruleset in this file.

A follow-up PR of this initiative must not apply the ruleset itself.

## Evidence states (keep them separate)

designed / implemented / commit / PR / CI of the current HEAD /
independent agent review of the current HEAD / Cursor of the current HEAD /
merged / real media validation.

A simulation is not real generation. A skipped check is not a pass.
An implementer-written JSON is not independent review.
