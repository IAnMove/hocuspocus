#!/usr/bin/env bash
# Idempotent Cloud Agent / headless dev bootstrap for Loreframe Lab.
#
# Sets up the CPU-only Python virtualenv used to run the repository's checks
# (clean-repo guard, compileall, unittest suite) and installs the React UI
# dependencies. The GPU generation pipeline (app/launch.py, app/wgp.py) needs
# NVIDIA CUDA plus large model downloads and is intentionally NOT installed
# here; on real hardware that is handled by Pinokio (install.js / torch.js).
set -euo pipefail

# Resolve repo root from this script's location so it works from any CWD.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Loreframe Lab dev bootstrap (repo: $REPO_ROOT)"

# --- Ensure the venv module is available (default Ubuntu image ships python3
#     without ensurepip). Guarded so re-runs are a no-op. ---
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  echo "==> Installing python3-venv (system package)"
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv
fi

# --- Python virtualenv ---
if [ ! -x .venv/bin/python ]; then
  echo "==> Creating .venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade --quiet pip

# CPU-only torch stack. Pinned to the versions validated for the test suite;
# published only on the PyTorch CPU index, not PyPI.
echo "==> Installing CPU torch stack"
python -m pip install --quiet \
  --index-url https://download.pytorch.org/whl/cpu \
  torch==2.13.0 torchvision==0.28.0 torchaudio==2.11.0

echo "==> Installing Python dev/test dependencies"
python -m pip install --quiet -r .cursor/requirements-dev.txt

# --- React UI ---
echo "==> Installing UI dependencies (npm ci)"
cd ui
npm ci

echo "==> Bootstrap complete."
