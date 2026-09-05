# Wizard nightly validation

The Wizard nightly runner is deliberately safe by default: it does not enable
GPU generation or external provider calls. Run it from the repository root:

```bash
scripts/nightly_wizard_validation.sh
```

PowerShell:

```powershell
scripts/nightly_wizard_validation.ps1
```

The default coverage is `NIGHTLY_LEVELS=1,2,4,5,6`. A reduced diagnostic run can
select levels explicitly, for example `NIGHTLY_LEVELS=1,2`. Selecting an
unknown level is a configuration failure; selecting a documented but missing
level produces `INCOMPLETE`, never a false pass.

## Levels

| Level | State | Coverage |
| --- | --- | --- |
| 1 | Implemented | Diff hygiene, ESLint, TypeScript, build, bundle budget, docs, brand and runner contracts |
| 2 | Implemented | Wizard action, schema and capability unit tests |
| 3 | Missing | Browser-level interaction tests |
| 4 | Implemented | Complete frontend test suite |
| 5 | Implemented | Durable workflow reload, retry, export-recovery, rhythm-grid and synthetic 120 BPM timing suite |
| 6 | Implemented | Complete Python backend test suite |
| 7 | Missing | Presentation anchors, accessibility and reduced-motion suite |
| 8 | Missing/opt-in | Real song → Video3D → MP4 smoke workflow |

Level 8 never runs merely because it was selected. It additionally requires
`RUN_GPU_TESTS=1` and/or `RUN_EXTERNAL_PROVIDER_TESTS=1`. Until the real smoke
workflow is implemented, enabling it fails truthfully instead of pretending
coverage exists.

## Result states

- `PASS`: every requested implemented job passed.
- `PASS_WITH_BASELINE`: no regression occurred, but exact known failures were
  observed. The process exits zero, while those tests remain
  `expected_failure` and JUnit records them as skipped—not passed.
- `REGRESSION`: a new or unclassified failure occurred.
- `INCOMPLETE`: a requested level is intentionally missing or was skipped.
- `INFRASTRUCTURE FAILURE`: a timeout, interruption, unreadable log, missing
  diagnostics, or runner/configuration failure occurred. An empty job list is
  not a pass.

Classification prefers the process exit code and a structured runner summary
(`# tests` / `ℹ tests` and `# fail` / `ℹ fail`). Fixture or mock logs that
merely contain the word `failed` are not a suite failure. If the runner
cannot determine the result, it reports not evaluable /
`INFRASTRUCTURE FAILURE` and never invents `PASS`. A green CI job is not
real media generation.

Baseline matching requires both the exact test title and its expected file. A
different failure in a baseline file is therefore a regression. Keep
[`scripts/nightly_baseline.json`](../../scripts/nightly_baseline.json) narrow
and remove entries as soon as their tests are repaired.

## Artifacts

Every execution writes `artifacts/nightly/<timestamp>/` with:

- one log per executed job;
- `failures/` copies for failures, skips and expected failures;
- `results.json`, including requested, executed and missing levels;
- `junit.xml`, preserving expected failures as skipped cases;
- `summary.md`, suitable for morning review.

The runner waits for each log stream to finish before classifying or copying
it, so failure artifacts contain the complete process tail.

The Python suite runs one `tests/test_*.py` file at a time and appends each
result immediately to `backend-tests.log`. The per-file timeout defaults to
three minutes and can be changed with `NIGHTLY_PYTEST_FILE_TIMEOUT_MS`; one
hung file can therefore be named and timed out without losing earlier output.
For a diagnostic subset, `NIGHTLY_PYTEST_FILES` accepts a comma-separated list
of exact discovered paths such as `tests/test_video_editor_soundtrack.py`.

Restricted sandboxes may forbid the IPC socket or child processes used by the
Node/tsx test runner. Empty test output and the known `listen EPERM ... tsx`
failure are reported as `INFRASTRUCTURE FAILURE`; they are never accepted as a
pass. Run the shell/PowerShell wrapper in the normal Pinokio environment for
the unattended overnight battery.
