#!/usr/bin/env bash
set -euo pipefail

# Provider-free local validation.
# Default (no args): fast pre-push checks. Not CI-equivalent.
# --full: CI-equivalent suite (guards, all safe pytest, UI, budget, E2E).
# Real media generation is never included; use scripts/run_real_media_smoke.sh.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI="${ROOT}/ui"
LOG_DIR="${VALIDATE_LOCAL_LOG_DIR:-$ROOT/logs/local-validation}"
MODE="fast"

usage() {
  cat >&2 <<'EOF'
Usage: bash scripts/validate_local.sh [--full]

  (default)  Fast pre-push checks: architecture/upscale contracts, code-health
             ratchet vs PR base, UI tests, lint, build, simulated E2E.
             PASS here is not CI-equivalent.

  --full     CI-equivalent local validation: clean-repo/docs/brand/deps guards,
             compileall, the full safe Python suite, ratchet, UI tests, lint,
             types/build, bundle budget, simulated E2E.

Neither mode installs packages, downloads models, uses a GPU, or calls
external providers. Unknown arguments fail closed.
EOF
  exit 2
}

for arg in "$@"; do
  case "$arg" in
    --full) MODE="full" ;;
    -h|--help) usage ;;
    *)
      echo "[local] unknown argument: $arg" >&2
      usage
      ;;
  esac
done

if [[ -n "${PYTHON:-}" && ! -x "$PYTHON" ]]; then
  PYTHON=""
fi
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/app/env/bin/python" ]]; then
    PYTHON="$ROOT/app/env/bin/python"
  else
    PYTHON="$(command -v python3 || command -v python || true)"
  fi
fi
if [[ -z "$PYTHON" ]]; then
  echo '[local] no usable Python interpreter found' >&2
  exit 2
fi

require_cmd() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "[local] required command not found: $name" >&2
    exit 2
  fi
}

require_cmd git
require_cmd npm

HEAD_SHA="${HEAD_SHA:-$(git -C "$ROOT" rev-parse --verify HEAD 2>/dev/null || true)}"
if [[ -z "$HEAD_SHA" ]]; then
  echo '[local] cannot resolve HEAD commit' >&2
  exit 2
fi

BASE_SHA="${BASE_SHA:-}"
if [[ -z "$BASE_SHA" ]]; then
  BASE_REF="${BASE_REF:-origin/main}"
  BASE_SHA="$(git -C "$ROOT" rev-parse --verify "$BASE_REF^{commit}" 2>/dev/null || true)"
fi
if [[ -z "$BASE_SHA" ]]; then
  echo '[local] cannot resolve code-health base: set BASE_SHA or fetch origin/main' >&2
  echo '[local] refusing to skip the ratchet' >&2
  exit 2
fi

mkdir -p "$LOG_DIR"
RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ 2>/dev/null || echo local)"
LOG_FILE="${LOG_DIR}/${MODE}-${RUN_STAMP}.log"

log() {
  printf '%s\n' "$*" | tee -a "$LOG_FILE"
}

run_step() {
  local label="$1"
  shift
  log "[local] start: $label"
  if ! "$@" 2>&1 | tee -a "$LOG_FILE"; then
    log "[local] FAIL: $label"
    log "[local] see $LOG_FILE"
    return 1
  fi
  log "[local] ok: $label"
}

run_ui() {
  local label="$1"
  shift
  # Inherit the current PATH (nvm/Pinokio/direnv). Do not use a login shell.
  run_step "$label" bash -c 'cd "$1" && shift && "$@"' bash "$UI" "$@"
}

if [[ "$MODE" == "full" ]]; then
  log "[local] mode=full (CI-equivalent; no GPU or providers)"
else
  log "[local] mode=fast (not CI-equivalent; pass --full for the complete suite)"
fi
log "[local] HEAD=$HEAD_SHA"
log "[local] base=$BASE_SHA"
log "[local] python=$PYTHON"

if [[ "$MODE" == "full" ]]; then
  run_step "clean-repo guard" "$PYTHON" "$ROOT/scripts/verify_clean_repo.py"
  run_step "dependency contract" "$PYTHON" "$ROOT/scripts/check_dependency_contract.py"
  run_step "documentation links" "$PYTHON" "$ROOT/scripts/check_documentation_links.py"
  run_step "brand contract" "$PYTHON" "$ROOT/scripts/check_brand_contract.py"
  run_step "python compileall" "$PYTHON" -m compileall -q "$ROOT/app/services" "$ROOT/app/launch.py" "$ROOT/scripts"
  run_step "python suite" "$PYTHON" -m pytest -q "$ROOT/tests"
else
  run_step "python contracts (upscale + architecture)" "$PYTHON" -m pytest -q \
    "$ROOT/tests/test_tools_upscale_contract.py" \
    "$ROOT/tests/test_architecture_contracts.py"
fi

log "[local] code-health ratchet vs $BASE_SHA"
if ! BASE_SHA="$BASE_SHA" PYTHON="$PYTHON" HEAD_SHA="$HEAD_SHA" \
    "$ROOT/scripts/check_code_health_pr_base.sh" | tee -a "$LOG_FILE"; then
  log "[local] FAIL: code-health ratchet"
  exit 1
fi
log "[local] ok: code-health ratchet"

run_ui "ui tests" npm test
run_ui "ui lint" npm run lint -- --max-warnings=0
if [[ "$MODE" == "full" ]]; then
  run_ui "ui build + budget" npm run build && run_ui "ui budget" npm run budget
else
  run_ui "ui build" npm run build
fi
run_ui "simulated browser e2e" npm run test:e2e

if [[ "$MODE" == "full" ]]; then
  log "[local] full checks passed (CI-equivalent; no GPU or external provider calls)"
else
  log "[local] fast checks passed (not CI-equivalent; run bash scripts/validate_local.sh --full)"
fi
