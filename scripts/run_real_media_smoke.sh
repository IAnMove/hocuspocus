#!/usr/bin/env bash
set -euo pipefail

if [[ "${HOCUSPOCUS_SMOKE_CONFIRM:-}" != "GENERATE_REAL_MEDIA" ]]; then
  echo 'Refusing real media generation. Set HOCUSPOCUS_SMOKE_CONFIRM=GENERATE_REAL_MEDIA.' >&2
  exit 2
fi
if [[ "${RUN_GPU_TESTS:-0}" != "1" ]]; then
  echo 'Refusing real media generation. Set RUN_GPU_TESTS=1.' >&2
  exit 2
fi

# Level 8 is deliberately local for music: ACE-Step, never MiniMax Music.
export RUN_EXTERNAL_PROVIDER_TESTS=0
export NIGHTLY_LEVELS=8
export NIGHTLY_MEDIA_SCOPE="${NIGHTLY_MEDIA_SCOPE:-all}"
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/scripts/nightly_wizard_validation.sh" "$@"
