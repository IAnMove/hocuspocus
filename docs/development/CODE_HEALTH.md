# Code-health ratchet

`scripts/code_health.py` measures only first-party production code. It includes
the HocusPocus Python runtime, services and routers plus `ui/src` TypeScript
and JavaScript. Markdown, JSON catalogs, tests and vendored models are
excluded. Test LOC is reported separately because adding tests is not a
production-code regression.

CI prints a table in the job summary and upserts the same table as a PR
comment (`<!-- code-health-report -->`) so every pull request shows the
current hotspots and the delta versus the committed baseline.

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

CI compares the result with the committed baseline:

```bash
python scripts/code_health.py --check
```

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
