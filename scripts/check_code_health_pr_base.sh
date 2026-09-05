#!/usr/bin/env bash
set -euo pipefail

# Fast, explicit pre-PR check. Unlike `code_health.py --check`, this never
# compares a feature branch with the historical dashboard baseline.
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
  echo 'Cannot find a usable Python interpreter' >&2
  exit 2
fi
BASE_SHA="${BASE_SHA:-}"
BASE_REF="${BASE_REF:-origin/main}"

if [[ -z "$BASE_SHA" ]]; then
  BASE_SHA="$(git -C "$ROOT" rev-parse --verify "$BASE_REF^{commit}" 2>/dev/null || true)"
fi
if [[ -z "$BASE_SHA" ]]; then
  echo "Cannot resolve code-health base: set BASE_SHA or fetch $BASE_REF" >&2
  exit 2
fi

BASE_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/hocus-health-base.XXXXXX")"
BASE_DIR="$BASE_PARENT/repo"
cleanup() {
  git -C "$ROOT" worktree remove --force "$BASE_DIR" >/dev/null 2>&1 || true
  rmdir "$BASE_PARENT" >/dev/null 2>&1 || true
}
trap cleanup EXIT

git -C "$ROOT" worktree add --detach "$BASE_DIR" "$BASE_SHA" >/dev/null
if [[ -d "$ROOT/ui/node_modules" ]]; then
  ln -s "$ROOT/ui/node_modules" "$BASE_DIR/ui/node_modules" 2>/dev/null || true
fi
(cd "$BASE_DIR" && "$PYTHON" scripts/code_health.py --json) > "$BASE_DIR/code-health-base.json"
"$PYTHON" "$ROOT/scripts/code_health.py" --check --markdown \
  --baseline "$BASE_DIR/code-health-base.json" \
  --score-baseline "$BASE_DIR/code-health-base.json" \
  --score-baseline-label "PR base"
