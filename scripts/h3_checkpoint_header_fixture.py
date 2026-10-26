#!/usr/bin/env python3
"""Rebuild tests/fixtures/fasth3_checkpoint_headers.json from Hugging Face.

Reads only each safetensors header (two HTTP range requests) plus the few
dozen bytes of one ``comfy_quant`` descriptor, never the weights, and writes a
condensed table: tensor-name pattern -> [dtype, shape, count].  The unit tests
read that fixture, so they need no network.

    python3 scripts/h3_checkpoint_header_fixture.py [--out PATH]

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import urllib.request
from pathlib import Path

HF = "https://huggingface.co"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "fasth3_checkpoint_headers.json"

CHECKPOINTS = {
    "fused_turbo_int8_convrot": {
        "repo": "MATLOWAI/minimax-h3-fused-turbo-int8-convrot",
        "revision": "3b51096a1bf67608d98131116558202208fcf195",
        "path": "diffusion_models/minimax_h3_fused_refdelta_r1024_turbo8_mystic07_int8_convrot.safetensors",
    },
    "fasth3_v2_int8_convrot": {
        "repo": "FastVideo/FastVideo-FastH3-Comfy",
        "revision": "ec1e3aa374a91c57b0b94a1623b7e657c0498cf2",
        "path": "diffusion_models/fastvideo_fasth3_8step_v2_pruned_int8_convrot.safetensors",
    },
    "fasth3_trim_int8_convrot": {
        "repo": "FastVideo/FastVideo-FastH3-Trim-Comfy",
        "revision": "f66c13dc17391dd4da99242a407918b92bf7d5fc",
        "path": "diffusion_models/fastvideo_fasth3_trim_8step_int8_convrot.safetensors",
    },
}
DESCRIPTOR_TENSORS = (
    "blocks.0.attn.qkv_proj.comfy_quant",
    "token_refiner.blocks.0.attn.qkv_proj.comfy_quant",
    "blocks.0.attn.to_gate_compress.comfy_quant",
)


def _range(url: str, first: int, last: int) -> bytes:
    request = urllib.request.Request(url, headers={"Range": f"bytes={first}-{last}"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def read_header(url: str) -> tuple[dict, int]:
    length = struct.unpack("<Q", _range(url, 0, 7))[0]
    raw = _range(url, 8, 8 + length - 1)
    if len(raw) != length:
        raise RuntimeError(f"short header read from {url}")
    return json.loads(raw), length


def condense(header: dict) -> dict[str, list]:
    table: dict[str, list] = {}
    for name, info in header.items():
        if name == "__metadata__":
            continue
        pattern = re.sub(r"\.(\d+)\.", ".N.", name)
        entry = [info["dtype"], list(info["shape"])]
        if pattern in table:
            if table[pattern][:2] != entry:
                raise RuntimeError(f"{pattern} has mixed dtype/shape")
            table[pattern][2] += 1
        else:
            table[pattern] = entry + [1]
    return dict(sorted(table.items()))


def lfs_info(repo: str, revision: str, path: str) -> dict:
    url = f"{HF}/api/models/{repo}/revision/{revision}?blobs=true"
    with urllib.request.urlopen(url, timeout=60) as response:
        siblings = json.load(response)["siblings"]
    item = next(entry for entry in siblings if entry["rfilename"] == path)
    return {"size": item["size"], "sha256": item["lfs"]["sha256"]}


def build(spec: dict) -> dict:
    url = f"{HF}/{spec['repo']}/resolve/{spec['revision']}/{spec['path']}"
    header, header_bytes = read_header(url)
    descriptors = {}
    for name in DESCRIPTOR_TENSORS:
        if name in header:
            first, last = header[name]["data_offsets"]
            raw = _range(url, 8 + header_bytes + first, 8 + header_bytes + last - 1)
            descriptors[name[: -len(".comfy_quant")]] = raw.decode("utf-8")
    sizes = sorted({
        info["data_offsets"][1] - info["data_offsets"][0]
        for name, info in header.items()
        if name.endswith(".comfy_quant")
    })
    return {
        "source": {**spec, **lfs_info(spec["repo"], spec["revision"], spec["path"])},
        "header_bytes": header_bytes,
        "metadata": header.get("__metadata__"),
        "comfy_quant_sizes": sizes,
        "comfy_quant": descriptors,
        "tensors": condense(header),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    fixture = {
        "schema": 1,
        "note": "Condensed safetensors headers; regenerate with scripts/h3_checkpoint_header_fixture.py",
        "checkpoints": {name: build(spec) for name, spec in CHECKPOINTS.items()},
    }
    args.out.write_text(json.dumps(fixture, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
