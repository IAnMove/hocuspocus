"""Detect truncated Hugging Face safetensors in the Hunyuan cache.

A partial download looks like a successful snapshot (symlinks exist) but
`safe_open` then raises MetadataIncompleteBuffer after minutes of GPU load.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path


DIT_REPO = "Tencent-Hunyuan/HunyuanDiT-v1.1-Diffusers-Distilled"


def safetensors_expected_size(path: Path) -> int | None:
    try:
        with path.open("rb") as handle:
            header_len_bytes = handle.read(8)
            if len(header_len_bytes) < 8:
                return 8
            header_len = struct.unpack("<Q", header_len_bytes)[0]
            if header_len > 50_000_000:
                return None
            header = handle.read(header_len)
            if len(header) < header_len:
                return 8 + header_len
            meta = json.loads(header)
    except (OSError, ValueError, json.JSONDecodeError, struct.error):
        return None
    max_offset = 0
    for value in meta.values():
        if isinstance(value, dict) and "data_offsets" in value:
            try:
                max_offset = max(max_offset, int(value["data_offsets"][1]))
            except (TypeError, ValueError, IndexError, KeyError):
                continue
    return 8 + header_len + max_offset


def truncated_safetensors(root: Path) -> list[Path]:
    if not root.exists():
        return []
    truncated: list[Path] = []
    for path in root.rglob("*.safetensors"):
        if not path.is_file():
            continue
        expected = safetensors_expected_size(path)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if expected is not None and size < expected:
            truncated.append(path)
    return truncated


def purge_truncated_safetensors(root: Path) -> list[str]:
    removed: list[str] = []
    for path in truncated_safetensors(root):
        real = path.resolve()
        try:
            if path.is_symlink() or path.exists():
                path.unlink()
                removed.append(str(path))
            if real != path and real.exists() and real.is_file():
                real.unlink()
                removed.append(str(real))
        except OSError:
            continue
    return removed


def dit_cache_root(hf_home: Path) -> Path:
    return hf_home / "hub" / f"models--{DIT_REPO.replace('/', '--')}"
