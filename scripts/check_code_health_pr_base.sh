#!/usr/bin/env bash
set -euo pipefail

# Fast, explicit pre-PR check. Unlike `code_health.py --check`, this never
# compares a feature branch with the historical dashboard baseline.
# Missing base or a failed analyzer is a hard failure; the ratchet is never skipped.
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
  echo '[code-health] cannot find a usable Python interpreter' >&2
  exit 2
fi
if [[ ! -f "$ROOT/scripts/code_health.py" ]]; then
  echo '[code-health] analyzer missing: scripts/code_health.py' >&2
  exit 2
fi

HEAD_SHA="${HEAD_SHA:-$(git -C "$ROOT" rev-parse --verify HEAD 2>/dev/null || true)}"
BASE_SHA="${BASE_SHA:-}"
BASE_REF="${BASE_REF:-origin/main}"
ZERO_SHA="0000000000000000000000000000000000000000"

if [[ "$BASE_SHA" == "$ZERO_SHA" ]]; then
  BASE_SHA=""
fi
if [[ -z "$BASE_SHA" ]]; then
  BASE_SHA="$(git -C "$ROOT" rev-parse --verify "$BASE_REF^{commit}" 2>/dev/null || true)"
fi
if [[ -z "$BASE_SHA" || "$BASE_SHA" == "$ZERO_SHA" ]]; then
  echo "[code-health] cannot resolve base: set BASE_SHA or fetch $BASE_REF" >&2
  exit 2
fi
if ! git -C "$ROOT" cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
  echo "[code-health] fetching missing base $BASE_SHA"
  if ! git -C "$ROOT" fetch --no-tags --depth=1 origin "$BASE_SHA"; then
    echo "[code-health] cannot fetch base SHA: $BASE_SHA" >&2
    echo "[code-health] base SHA is not a commit in this repository: $BASE_SHA" >&2
    exit 2
  fi
fi
if ! git -C "$ROOT" cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
  echo "[code-health] base SHA is not a commit in this repository: $BASE_SHA" >&2
  exit 2
fi

echo "[code-health] HEAD=${HEAD_SHA:-unknown}"
echo "[code-health] base=$BASE_SHA"

BASE_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/hocus-health-base.XXXXXX")"
BASE_DIR="$BASE_PARENT/repo"
cleanup() {
  git -C "$ROOT" worktree remove --force "$BASE_DIR" >/dev/null 2>&1 || true
  rmdir "$BASE_PARENT" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! git -C "$ROOT" worktree add --detach "$BASE_DIR" "$BASE_SHA"; then
  echo "[code-health] failed to check out base $BASE_SHA" >&2
  exit 1
fi
if [[ -d "$ROOT/ui/node_modules" ]]; then
  ln -s "$ROOT/ui/node_modules" "$BASE_DIR/ui/node_modules" 2>/dev/null || true
fi
if ! (cd "$BASE_DIR" && "$PYTHON" scripts/code_health.py --json) > "$BASE_DIR/code-health-base.json"; then
  echo "[code-health] analyzer failed on base $BASE_SHA" >&2
  exit 1
fi
"$PYTHON" "$ROOT/scripts/code_health.py" --check --markdown \
  --baseline "$BASE_DIR/code-health-base.json" \
  --score-baseline "$BASE_DIR/code-health-base.json" \
  --score-baseline-label "PR base"
