# Developer workflow

The owner writes in Spanish. Code, commits and this command guide stay in English.
Run the tools with the app interpreter and an empty `CUDA_VISIBLE_DEVICES`. On this
workstation that interpreter is
`/mnt/extras/pinokio/api/hocuspocus-development/app/env/bin/python` (`$PY` below).

## Commands

Run `gates.py --quick` while iterating. It skips characterization and the code-health
ratchet. Run the full `gates.py` once before the PR. Add `--ui` only when UI files changed
(tsc, i18n, unreachable, eslint on the changed files, `npm run test`). It never installs
or builds.

```bash
$PY scripts/dev/gates.py --quick
$PY scripts/dev/gates.py
$PY scripts/dev/gates.py --ui
```

One line per gate: `PASS`, `FAIL` or `SKIP`, the name and the seconds. A failure lists
the first five test ids (or the first error line) and the log in `.dev-gates/`. Exit
code 1 on any failure. Raw pytest output stays in the log. Changed files that
`scripts/select_local_tests.py` cannot map are not expanded to the full suite.

When `origin/development` moves, merge it and resolve the usual conflicts:

```bash
$PY scripts/dev/merge_prep.py --ref origin/development
$PY scripts/dev/merge_prep.py --ref origin/development --commit
```

CHANGELOG keeps both paragraphs, the branch first, with no duplicate. `scripts/ci_test_groups.json`
keeps the ref, re-adds this branch's new tests, recomputes both weights and appends one
dated sentence. Fixtures are regenerated and staged. Any other conflict is listed and
left untouched (exit 2). A file-count gap over 5 or a weight ratio over 1.25 fails (exit 1).

```bash
$PY scripts/dev/architecture_map.py
$PY scripts/dev/architecture_map.py --check
```

Regenerate the map after a router, service package or UI slice is added. `--check` reports
drift. It is not a CI job. The Story Lab graph is `docs/development/ARCHITECTURE_MAP.md`.

## Rules on one screen

- `app/_launch_runtime.py` and `app/core_runtime.py` only compose: imports, `include_router`, `bind(...)`. Ceilings in `scripts/size_ceilings.json` only go down. Do not grow those files.
- Logic lives in `app/services/*`, HTTP routes in `app/routers/*`, the shared kernel in `app/services/kernel/*`. A service never imports a router. A new file stays ≤ 1200 lines. A new function stays at complexity ≤ 25.
- What a module needs from launch comes through one keyword-only `bind(**names)`. No proxies, no copy of `globals()`, no `sys.modules` lookups.
- `ui/src/stores/useStore.ts` only composes slices. UI tests are node:test via tsx, not vitest (`cd ui && npm run test`, `npm run i18n:check`, `npm run unreachable:check`).
- `app/wgp.py` and `app/models/**` are upstream WanGP. Do not edit them except a minimal patch named in the PR.
- Work in a worktree. The live checkout is read-only except `git fetch`. Never touch ports 42003, 42042, 42072 or 42080. Never `rm` (use `git rm`). Never `pkill -f`. Never `npm install`, `npm ci` or `npm run build` on the live `ui/`.
- A new `tests/test_*.py` goes in exactly one group in `scripts/ci_test_groups.json`. The file-count gap stays ≤ 5. Weights equal `pytest --collect-only -q -p no:cacheprovider` on the group paths (count `::`). Add a dated sentence to `weight_note`.
- Never hand-edit fixtures. Run `scripts/architecture_contracts.py --write`.
- Goldens must not embed external-binary output, versions or absolute paths. A behaviour fix needs a test that failed first.
- PR base is `development`. Merge commits, never rebase. No `Co-Authored-By` trailer and no "Generated with" footer.
- Before the PR, also run the four guards (`verify_clean_repo.py`, `check_dependency_contract.py`, `check_documentation_links.py`, `check_brand_contract.py`) and, after committing, `BASE_REF=origin/development PYTHON=$PY bash scripts/check_code_health_pr_base.sh`. The full suite is once per PR: `CUDA_VISIBLE_DEVICES= nice -n 10 $PY -m pytest -q -p no:cacheprovider`.
