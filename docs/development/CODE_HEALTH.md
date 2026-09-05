# Code-health ratchet

`scripts/code_health.py` measures only first-party production code. It includes
the HocusPocus Python runtime, services and routers plus `ui/src` TypeScript
and JavaScript. Markdown, JSON catalogs, tests and vendored models are
excluded. Test LOC is reported separately because adding tests is not a
production-code regression.

CI prints a table in the job summary and a separate write-only job upserts
the same table as a PR comment (`<!-- code-health-report -->`) so every
pull request shows the current hotspots, the 0–100 quality score and the
delta versus the PR base. The job that runs the ratchet does not get
comment permissions.

The PR table starts with a transparent quality score from 0 to 100 and its
change against the PR's exact base commit. Higher is better. The score combines
cyclomatic health (45%), concentration in the largest files (25%), oversized
file debt (20%) and modularity (10%). Component scores and their individual
deltas are shown so the total is explainable.

Each signal is linearly mapped between a healthy bound (100) and a severe
bound (0), then clamped. The current bounds are deliberately broad:

| Component | Signals (100 → 0) |
|---|---|
| Cyclomatic health | functions at complexity 15+: 2% → 12%; maximum complexity: 25 → 700 |
| File concentration | largest-file share: 5% → 25%; top-five share: 20% → 55% |
| Oversized-file debt | lines above 1,000 per hotspot: 5% → 50% of production; files at 5,000+ lines: 0.5% → 5% |
| Modularity | average file size: 250 → 800 lines; 1,000-line hotspot share: 2% → 15% of files |

Inside the components, cyclomatic ratio has 75% of its component weight and
maximum complexity 25%; the oversized-line debt has 75% and giant-file ratio
25%. The other paired signals are weighted equally.

Quick report after installing the normal UI dependencies:

```bash
python scripts/code_health.py
python scripts/code_health.py --markdown
```

`--markdown` without `--check` prints **Ratchet not evaluated.** CI uses `--check --markdown` so the PR comment shows passed or failed against the committed baseline.

The report lists physical/non-blank lines, files over 1,000 lines, and the most
complex Python and TypeScript/JavaScript functions. Python uses a classic
AST-based McCabe count. UI complexity uses ESLint's built-in `complexity` rule.
If `ui/node_modules` is absent, the normal report still works but warns that UI
complexity is unavailable.

CI compares a pull request with the exact code-health report generated from
its base commit. The committed baseline remains the repository trend
dashboard and is used when running the check outside a pull request:

```bash
python scripts/code_health.py --check
```

For a feature branch, do not use the historical-baseline command above as the
pre-PR gate. It intentionally reports accumulated trend debt and may fail even
when a change is safe relative to its pull-request base. Use:

```bash
bash scripts/check_code_health_pr_base.sh
```

The helper checks the exact `origin/main` ref by default. Set `BASE_SHA` to the
base SHA reported by GitHub (or `BASE_REF` to another fetched base ref) to
reproduce a specific pull-request comparison. `scripts/validate_local.sh`
invokes the same helper automatically. The committed baseline remains useful
for the long-term dashboard and must not be refreshed merely to make a PR
green.

The check prints deltas for production LOC, test LOC, complex functions and
every changed large-file hotspot, so a refactor's improvement is visible in
the same run. Small increases print warnings. CI fails only for a material
regression:

- production LOC grows beyond the greater of 3% or 2,000 lines;
- functions at complexity 15+ increase by more than five;
- maximum function complexity rises by more than three;
- a file's maximum complexity rises by more than five, or a new file exceeds 25;
- an existing 1,000-line hotspot exceeds its small growth allowance; or
- a new first-party file exceeds 1,200 lines.

A deliberate architectural change can refresh the snapshot, but the diff must
be reviewed like any other budget change:

```bash
python scripts/code_health.py --write-baseline
git diff -- scripts/code_health_baseline.json
```

The baseline is a ratchet, not a quality certificate. Decreasing a giant file
or a complex function is progress; moving the same code under a different name
should be reviewed rather than used to reset the baseline casually.

The aggregate score is also not a quality certificate and never replaces the
ratchet. It deliberately excludes test volume and coverage, which need their
own evidence and are too easy to game as a maintainability score.
