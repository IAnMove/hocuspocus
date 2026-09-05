# Agent QA policy (minimum)

Status: documentary P0. Remote GitHub protection is **not** applied by this
PR. That needs a separate admin authorization.

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

## Required checks (names as of this tree)

Until `ci-required` exists (P2) and a verified QA check exists (P6), the
normal integration path should require exactly these GitHub check names:

1. `Clean-repo guard + Python checks`
2. `UI tests + lint + type-check + build`
3. `UI E2E boot (Chromium + simulated API)`

Do not require human approval reviews that will not be performed.
Do not treat Analyze pull request as a required technical review.

## Remote configuration (prepared, not executed)

Ask an admin to apply, then verify in read-only:

- PRs required to update `main`
- the three checks above required
- no force-push / no deleting `main`
- bypass limited to repository owners; record that owners can still bypass
- credentials for applying rulesets stay off the implementer agent

After P2 lands and `ci-required` is observed on a real PR, add that check
without dropping coverage. After P6, require the verified QA check only when
its publisher identity is proven.

A follow-up PR of this initiative must not apply the ruleset itself.

## Evidence states (keep them separate)

designed / implemented / commit / PR / CI of the current HEAD /
independent agent review of the current HEAD / Cursor of the current HEAD /
merged / real media validation.

A simulation is not real generation. A skipped check is not a pass.
An implementer-written JSON is not independent review.
