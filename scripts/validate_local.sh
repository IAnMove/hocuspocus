#!/usr/bin/env bash
set -euo pipefail

# Fast, provider-free pre-push validation. Real media generation is never
# included here; run scripts/nightly_wizard_validation.sh explicitly for that.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
UI="${ROOT}/ui"

echo '[local] Python contracts'
"$PYTHON" -m pytest -q \
  "$ROOT/tests/test_tools_upscale_contract.py" \
  "$ROOT/tests/test_architecture_contracts.py"

echo '[local] code-health ratchet against the exact PR base'
# GitHub compares a pull request with the current base commit, not with the
# branch fork point. Prefer an explicitly supplied SHA (the CI contract), then
# the fetched base ref, and only use merge-base as an offline fallback.
BASE_SHA="${BASE_SHA:-}"
if [[ -z "$BASE_SHA" ]]; then
  BASE_REF="${BASE_REF:-origin/main}"
  BASE_SHA="$(git -C "$ROOT" rev-parse --verify "$BASE_REF^{commit}" 2>/dev/null || true)"
fi
if [[ -z "$BASE_SHA" ]]; then
  BASE_SHA="$(git -C "$ROOT" merge-base HEAD origin/main 2>/dev/null || true)"
fi
if [[ -n "$BASE_SHA" ]]; then
  BASE_SHA="$BASE_SHA" PYTHON="$PYTHON" "$ROOT/scripts/check_code_health_pr_base.sh" >/dev/null
fi

echo '[local] UI tests, lint and build'
(cd "$UI" && npm test && npm run lint -- --max-warnings=0 && npm run build)

echo '[local] simulated browser E2E'
(cd "$UI" && npm run test:e2e)

echo '[local] complete (no GPU or external provider calls)'
