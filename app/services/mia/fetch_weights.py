"""Download the Make-It-Animatable demo weights into the vendored checkout.

Called by the install recipe after the checkout exists. Paths are the ones
``app.py`` loads (``output/best/new``) plus the Mixamo armature template
``dataset_mixamo.py`` opens at import. Nothing here is committed.

Code: MIT (Zhiyang Guo, jasongzy/Make-It-Animatable).
Weights: Apache-2.0 (jasongzy/Make-It-Animatable on Hugging Face).
Template: jasongzy/Mixamo ``bones.fbx`` (about 70 KB). That dataset card
states no SPDX licence; this script fetches that one file and not the dataset.
"""

from __future__ import annotations

import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

VENDOR = Path(__file__).resolve().parent / "vendor" / "Make-It-Animatable"
MODEL = "jasongzy/Make-It-Animatable"
WEIGHTS = (
    "output/best/new/bw.pth",
    "output/best/new/bw_normal.pth",
    "output/best/new/joints.pth",
    "output/best/new/joints_coarse.pth",
    "output/best/new/pose.pth",
)
TEMPLATE = "bones.fbx"
TEMPLATE_DEST = "data/Mixamo/bones.fbx"


def _fetch(repo: str, filename: str, dest: Path, *, dataset: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        print(f"present {dest.relative_to(VENDOR)} ({dest.stat().st_size} bytes)", flush=True)
        return
    kind = "dataset" if dataset else "model"
    print(f"download {repo} {filename} -> {dest.relative_to(VENDOR)}", flush=True)
    downloaded = hf_hub_download(repo, filename, repo_type=kind, local_dir=str(VENDOR if not dataset else dest.parent))
    saved = Path(downloaded)
    if dataset and saved.resolve() != dest.resolve():
        dest.write_bytes(saved.read_bytes())
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise RuntimeError(f"Missing after download: {dest}")
    print(f"saved {dest.relative_to(VENDOR)} ({dest.stat().st_size} bytes)", flush=True)


def main() -> None:
    if not (VENDOR / "app.py").is_file():
        raise SystemExit(f"Vendor checkout is missing: {VENDOR}. Install clones it before this step.")
    for relative in WEIGHTS:
        _fetch(MODEL, relative, VENDOR / relative, dataset=False)
    _fetch("jasongzy/Mixamo", TEMPLATE, VENDOR / TEMPLATE_DEST, dataset=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"fetch_weights failed: {exc}", file=sys.stderr, flush=True)
        raise
