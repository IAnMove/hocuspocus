#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export RUN_EXTERNAL_PROVIDER_TESTS="${RUN_EXTERNAL_PROVIDER_TESTS:-0}"
export RUN_GPU_TESTS="${RUN_GPU_TESTS:-0}"
cd "$ROOT"
exec node "$ROOT/scripts/nightly_wizard_report.mjs" "$@"
