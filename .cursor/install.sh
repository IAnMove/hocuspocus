#!/usr/bin/env bash
#
# Cloud Agent bootstrap for Loreframe Lab (CPU-only development environment).
#
# Loreframe Lab is a GPU application: real generation (wgp.py / launch.py) needs
# an NVIDIA GPU that Cloud Agent VMs do not have. What DOES run on CPU is the
# development loop that CI cares about:
#   - the Python test suite under tests/ (python -m unittest discover)
#   - the clean-repo guard and syntax checks
#   - the React/TypeScript UI (type-check, build, eslint, vite dev server)
#
# This script prepares exactly that. It is idempotent: re-running it only
# refreshes state and must always terminate (no servers are started here).
set -eo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> [1/4] System Python 3.10 (matches CI) + ffmpeg"
if ! command -v python3.10 >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq software-properties-common
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3.10 python3.10-venv python3.10-dev
fi
# ffmpeg is used by the media/multi-clip tests; usually already present.
command -v ffmpeg >/dev/null 2>&1 || sudo apt-get install -y -qq ffmpeg

echo "==> [2/4] Python virtualenv"
if [ ! -x .venv/bin/python ]; then
  python3.10 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip

echo "==> [3/4] Python dependencies (CPU)"
# CPU PyTorch build (no CUDA on Cloud Agent VMs).
pip install --index-url https://download.pytorch.org/whl/cpu \
  torch==2.7.0 torchvision==0.22.0 torchaudio==2.7.0
# Remaining CPU-importable test dependencies — same list CI uses.
pip install -r tests/requirements-cpu.txt

echo "==> [4/4] UI toolchain (npm ci + build)"
# Ensure node/npm from the nvm-managed base image is on PATH.
if ! command -v npm >/dev/null 2>&1; then
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  # shellcheck disable=SC1091
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
fi
( cd ui && npm ci && npm run build )

echo "==> Install complete. Activate the venv with: . .venv/bin/activate"
