# Validación local

`bash scripts/validate_local.sh` is provider-free. It never loads models,
reserves a GPU, or calls external providers. It does **not** install Python or
npm packages; missing tools fail closed.

The script prints `mode`, `HEAD` and the exact code-health `base` SHA, and
keeps a log under `logs/local-validation/` (gitignored).

## Fast mode (default)

```bash
bash scripts/validate_local.sh
```

This is the compatible pre-push command. It runs:

- Python contracts: `tests/test_tools_upscale_contract.py` and
  `tests/test_architecture_contracts.py`
- Code-health ratchet against the exact PR base (`BASE_SHA` or `origin/main`)
- UI tests, lint, and build
- Simulated browser E2E

A PASS here is **not** CI-equivalent. The final line says so.

If the ratchet base cannot be resolved, the command exits non-zero. It never
skips `scripts/check_code_health_pr_base.sh`. Analyzer or worktree failures
are failures. Ratchet output is shown, not discarded.

## Full mode (CI-equivalent)

```bash
bash scripts/validate_local.sh --full
```

Adds the remaining CI-safe checks, still without installing dependencies or
running GPU/provider work:

- `scripts/verify_clean_repo.py`
- `scripts/check_dependency_contract.py`
- `scripts/check_documentation_links.py`
- `scripts/check_brand_contract.py`
- `python -m compileall` on `app/services`, `app/launch.py`, `scripts`
- the full safe pytest suite (`tests/`)
- the same ratchet as fast mode
- UI tests, lint, build **and** `npm run budget`
- simulated E2E

A budget failure fails `--full`. Unknown arguments fail closed.

## Base SHA

GitHub compares a pull request with the current base commit. Locally:

- `BASE_SHA=<sha>` reproduces a specific PR base
- `BASE_REF` defaults to `origin/main`
- `HEAD_SHA` defaults to `git rev-parse HEAD`

CI calls the same helper (`scripts/check_code_health_pr_base.sh`) with
`BASE_SHA` from the PR base or, on push, the previous branch tip. The
measuring job has `contents: read` only; the report goes to the job
summary and an artifact, not a PR comment.

The committed dashboard `scripts/code_health_baseline.json` is not used to
decide whether the current PR may pass.

CPU dependencies for `--full` match CI's Python job plus a local UI
`node_modules` and Playwright Chromium. ffmpeg is required by some media
unit tests. This environment is not identical to GitHub runners (no `apt-get`
or `pip install` inside the wrapper). If a required tool is missing, record
it; do not treat mocks as a full run.

## Smoke de medios reales (sólo manual)

No se ejecuta en GitHub Actions ni forma parte de la rutina anterior. Para
generar de verdad una canción con ACE-Step local y continuar el flujo de
videoclip:

```bash
RUN_GPU_TESTS=1 \
HOCUSPOCUS_SMOKE_BASE_URL=http://127.0.0.1:42003 \
HOCUSPOCUS_SMOKE_WORKSPACE=nightly-real-ace \
HOCUSPOCUS_SMOKE_CONFIRM=GENERATE_REAL_MEDIA \
bash scripts/run_real_media_smoke.sh
```

El wrapper fuerza `RUN_EXTERNAL_PROVIDER_TESTS=0`; cualquier ejecución real
requiere la confirmación explícita. Los artefactos y tiempos deben anotarse en
`comunicaciones/review.md` (fuera de Git).
