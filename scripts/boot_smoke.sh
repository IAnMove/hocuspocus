#!/usr/bin/env bash
# Boot one worktree's server on a free port, isolated from the live install, and smoke-test it.
#
#   scripts/boot_smoke.sh <worktree> [--port N] [--list scripts/boot_smoke/<slice>.txt] [--core] [--cpu]
#
# A local pre-merge check for refactor PRs. It needs the GPU host (real WanGP
# import), so CI does not run it. Details: python3 scripts/boot_smoke.py --help
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -z "${PYTHON:-}" || ! -x "${PYTHON}" ]]; then
  PYTHON="$(command -v python3 || command -v python)"
fi
exec "$PYTHON" "$ROOT/scripts/boot_smoke.py" "$@"
