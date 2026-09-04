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

echo '[local] UI tests, lint and build'
(cd "$UI" && npm test && npm run lint -- --max-warnings=0 && npm run build)

echo '[local] simulated browser E2E'
(cd "$UI" && npm run test:e2e)

echo '[local] complete (no GPU or external provider calls)'
