#!/usr/bin/env bash
set -euo pipefail

# Fast, provider-free pre-push validation. Real media generation is never
# included here; run scripts/nightly_wizard_validation.sh explicitly for that.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/app/env/bin/python}"
UI="${ROOT}/ui"

echo '[local] Python contracts'
"$PYTHON" -m pytest -q \
  "$ROOT/tests/test_tools_upscale_contract.py" \
  "$ROOT/tests/test_architecture_contracts.py"

echo '[local] code-health ratchet against origin/main'
BASE_SHA="$(git -C "$ROOT" merge-base HEAD origin/main 2>/dev/null || true)"
if [[ -n "$BASE_SHA" ]]; then
  BASE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hocus-health.XXXXXX")"
  trap 'git -C "$ROOT" worktree remove --force "$BASE_DIR" >/dev/null 2>&1 || true' EXIT
  git -C "$ROOT" worktree add --detach "$BASE_DIR" "$BASE_SHA" >/dev/null
  ln -s "$UI/node_modules" "$BASE_DIR/ui/node_modules" 2>/dev/null || true
  (cd "$BASE_DIR" && python scripts/code_health.py --json) > "$BASE_DIR/code-health-base.json"
  "$PYTHON" "$ROOT/scripts/code_health.py" --check --baseline "$BASE_DIR/code-health-base.json" >/dev/null
  trap - EXIT
  git -C "$ROOT" worktree remove --force "$BASE_DIR" >/dev/null 2>&1 || true
fi

echo '[local] UI tests, lint and build'
(cd "$UI" && npm test && npm run lint -- --max-warnings=0 && npm run build)

echo '[local] simulated browser E2E'
(cd "$UI" && npm run test:e2e)

echo '[local] complete (no GPU or external provider calls)'
