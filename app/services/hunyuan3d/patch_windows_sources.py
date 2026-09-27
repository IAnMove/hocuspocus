"""Apply Hunyuan3D-2's Windows fixes to the pinned Hunyuan3D-2.1 rasterizer.

Tencent fixed the rasterizer kernel for MSVC in Hunyuan3D-2 but not in 2.1:
torch::zeros sizes built from size_t are narrowing conversions (error C2398)
and `long` is 32-bit on Windows, so data_ptr<long> does not link against
int64 tensors (LNK2001). This rewrites the 2.1 files the same way. It is
idempotent and only edits tracked files, which
runtime_sources.sources_current tolerates.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KERNEL = ROOT / "app/services/hunyuan3d/vendor/Hunyuan3D-2.1/hy3dpaint/custom_rasterizer/lib/custom_rasterizer_kernel"
# runtime_install.js restores these before a vendor checkout, so a new
# revision is never blocked by this patch.
PATCHED = ("grid_neighbor.cpp", "rasterizer.cpp", "rasterizer_gpu.cu")

_ZEROS = re.compile(r"torch::zeros\(\{([^{}]*)\}")
_LONG_POINTER = re.compile(r"\blong\* ")


def _cast_sizes(match: re.Match) -> str:
    sizes = [part.strip() for part in match.group(1).split(",")]
    cast = [part if part.startswith("static_cast<int64_t>(") else f"static_cast<int64_t>({part})"
            for part in sizes]
    return "torch::zeros({" + ", ".join(cast) + "}"


def patch_source(name: str, source: str) -> str:
    if name == "grid_neighbor.cpp":
        source = _ZEROS.sub(_cast_sizes, source)
    source = source.replace("data_ptr<long>()", "data_ptr<int64_t>()")
    source = source.replace("(long)maxint", "(int64_t)maxint")
    return _LONG_POINTER.sub("int64_t* ", source)


def main() -> None:
    for name in PATCHED:
        path = KERNEL / name
        if not path.is_file():
            raise SystemExit(f"Missing Hunyuan3D-2.1 source: {path}")
        raw = path.read_bytes().decode("utf-8")
        patched = patch_source(name, raw)
        if patched != raw:
            path.write_bytes(patched.encode("utf-8"))
            print(f"[Hunyuan3D] Applied Windows fixes to {name}")
        else:
            print(f"[Hunyuan3D] {name} already has the Windows fixes")


if __name__ == "__main__":
    sys.exit(main())
