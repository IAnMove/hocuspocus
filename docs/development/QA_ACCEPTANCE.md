# Independent review and QA acceptance

Status: P6 validator. This is not a required GitHub check yet and does not
enable auto-merge. Remote rulesets: `Protect main` exists without required
CI; `development` is unprotected. See [GITHUB_PROTECTION.md](GITHUB_PROTECTION.md).

The implementer produces criteria and a diff. A **different** agent session
derives cases from those criteria and reviews the actual HEAD. The
conversation transcript is not evidence.

## Command

```bash
python scripts/verify_qa_evidence.py \
  --evidence path/to/evidence.json \
  --head <current-head-sha> \
  --base <current-base-sha> \
  --implementer <implementer-login> \
  --risk routine|persistence|lyrics|concurrency|permissions \
  --require-separation
```

Exit `0` only when the JSON is independent evidence of that exact HEAD.
Exit `1` is a policy reject. Exit `2` is infrastructure (missing file, invalid
JSON). Missing evidence is QA pending, never a pass.

Schema: [qa-evidence.schema.json](qa-evidence.schema.json). Policy:
[AGENT_QA_POLICY.md](AGENT_QA_POLICY.md).

## What never counts

- Implementer-written JSON claiming independence
- Heuristic Analyze (`pr-review.yml`)
- CI green, including `CI required`
- Cursor/Bugbot of a previous SHA, or silence
- A free PR comment as the approval publisher

Cursor of the **current HEAD** is a useful signal. It does not replace
executed cases.

## Risk classes

| Risk | Reviewers | Required case ids |
|---|---|---|
| `routine` | `technical_review` | at least one executed case |
| `persistence` | technical + adversarial, different agents/sessions | `cas`, `cancel`, `round_trip` |
| `lyrics` | technical + adversarial, different agents/sessions | `counterexample`, `corpus` |
| `concurrency` | technical + adversarial, different agents/sessions | `race_or_lock` |
| `permissions` | technical + adversarial, different agents/sessions | `denied_path` |

Open blocking findings reject. `fail` or `unevaluable` on a required case
rejects. Cost must set `known`; if false, explain in `note` instead of
inventing token counts.

Repair loops stay at two automatic attempts. After that, return a
reproducible block; do not ask a human to finish the technical dispute by
reading the whole diff.

The GitHub check `Independent QA` is published by
`.github/workflows/qa-evidence.yml` using `scripts/publish_qa_check.py`
from the PR **base** tree. The check identity is that Actions job
(`GITHUB_TOKEN` + current `GITHUB_RUN_ID`), not a role declared in JSON.

The file on HEAD is evidence only. The publisher **stamps** provenance from
the current Actions run (`GITHUB_RUN_ID`, trusted workflow, repository,
head/base). Claims of origin inside the JSON are ignored. Missing
`qa-evidence.json` is **pending** (neutral check named `Independent QA`;
the Actions job is `Independent QA publisher`). Never success. Fake adapter
tests prove the contract only. This check is **not** required.
