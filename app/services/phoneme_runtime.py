"""Explicit, pinned installation of the optional CPU phoneme alignment model."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import threading

REPO = "facebook/wav2vec2-lv-60-espeak-cv-ft"
REVISION = "ae45363bf3413b374fecd9dc8bc1df0e24c3b7f4"
WEIGHT_SHA = "3173bde9e9ce490fa0f989e413c42f25bc1820c020adc1e6b9b87025b3cfcc5e"
DOWNLOAD_BYTES = 1_263_535_127
FILES = ("config.json", "preprocessor_config.json", "tokenizer_config.json",
         "special_tokens_map.json", "vocab.json", "README.md", "pytorch_model.bin")
ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "phonemes" / REVISION
_LOCK = threading.Lock()


def capabilities(root: Path = ROOT) -> dict:
    dependencies = all(importlib.util.find_spec(name) is not None
                       for name in ("torch", "transformers", "phonemizer", "espeakng_loader"))
    ready = False
    try:
        marker = json.loads((root / "verified.json").read_text())
        ready = (marker == {"revision": REVISION, "sha256": WEIGHT_SHA}
                 and all((root / name).is_file() for name in FILES)
                 and (root / "pytorch_model.bin").stat().st_size == DOWNLOAD_BYTES)
    except (OSError, ValueError):
        pass
    return {"installed": ready, "dependencies_available": dependencies, "device": "cpu",
            "model": REPO, "revision": REVISION, "download_bytes": DOWNLOAD_BYTES,
            "source": f"https://huggingface.co/{REPO}", "license": "apache-2.0"}


def install(root: Path = ROOT) -> dict:
    with _LOCK:
        status = capabilities(root)
        if status["installed"]:
            return status
        if not status["dependencies_available"]:
            raise RuntimeError("Repair the app runtime before installing phoneme alignment.")
        from services import safe_download  # Native timeout/progress hooks before HF import.
        from huggingface_hub import hf_hub_download
        del safe_download
        root.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            hf_hub_download(REPO, name, revision=REVISION, local_dir=root, token=False)
        digest = hashlib.sha256()
        with (root / "pytorch_model.bin").open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != WEIGHT_SHA:
            raise RuntimeError("Phoneme model checksum mismatch; runtime not enabled.")
        (root / "verified.json").write_text(json.dumps({"revision": REVISION, "sha256": WEIGHT_SHA}))
        return capabilities(root)
