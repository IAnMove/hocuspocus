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
import subprocess
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


def restore_sources(kernel: Path = KERNEL) -> None:
    """Undo only this installer's patch, never unrelated user modifications."""
    vendor = kernel.parents[3]
    pending = []
    for name in PATCHED:
        path = kernel / name
        if not path.is_file():  # A fresh --no-checkout clone has no source files.
            continue
        relative = path.relative_to(vendor).as_posix()
        original = subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=vendor)
        current = path.read_bytes()
        # Git on Windows may check out CRLF even when blobs use LF.
        original_text = original.decode("utf-8").replace("\r\n", "\n")
        current_text = current.decode("utf-8").replace("\r\n", "\n")
        if current_text == original_text:
            continue
        if current_text != patch_source(name, original_text):
            raise RuntimeError(f"Preserving modified Hunyuan3D source: {path}. Reconcile it before Update.")
        restored = original_text.replace("\n", "\r\n") if b"\r\n" in current else original_text
        pending.append((path, restored.encode("utf-8")))
    for path, original in pending:
        path.write_bytes(original)


def main() -> None:
    if sys.argv[1:] == ["--restore"]:
        restore_sources()
        return
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
