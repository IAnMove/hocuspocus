#!/usr/bin/env python3
"""Download the template-search weights with the studio's own Python.

Only the PyTorch and tokenizer files. The Hub repo also ships ONNX, OpenVINO
and a second pickle of the same model; those are not fetched. The folder is
the one the Installation catalog removes. A ``READY`` file is the installed
mark: there is no second virtualenv and no runtime receipt.

No timeout. A partial download is resumed by Hugging Face on the next run.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from services.template_semantic import LICENSE, MODEL_FILES, MODEL_ID  # noqa: E402

DEFAULT_DIR = ROOT / "app" / "services" / "template_semantic_model"


def destination(argv: list[str]) -> Path:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", default=os.environ.get("HOCUSPOCUS_TEMPLATE_SEMANTIC_DIR", ""))
    args = parser.parse_args(argv)
    return Path(args.dest) if args.dest else DEFAULT_DIR


def download(folder: Path) -> None:
    """Fetch the allow-listed files and write READY. Safe to run again."""
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    from huggingface_hub import snapshot_download

    folder.mkdir(parents=True, exist_ok=True)
    snapshot_download(MODEL_ID, local_dir=str(folder), allow_patterns=list(MODEL_FILES))
    (folder / "READY").write_text(f"model={MODEL_ID}\nlicense={LICENSE}\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    download(destination(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    main()
