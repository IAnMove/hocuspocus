"""One-process TRELLIS.2/Pixal3D adapter; invoked only in their isolated runtime.

Uses the same heartbeat and process identity as the existing Hunyuan worker,
so cancellation, watchdog and orphan recovery remain owned by model3d_service.
"""
from __future__ import annotations

import argparse
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path

from worker import Heartbeat, event


def run_trellis(request: dict, output: Path) -> None:
    from PIL import Image
    from trellis2.pipelines import Trellis2ImageTo3DPipeline
    import o_voxel
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from services.trellis2.assets import BUNDLE

    settings = request["settings"]
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(str(BUNDLE))
    pipeline.cuda()
    resolution = settings["resolution"]
    pipeline_type = "512" if resolution == 512 else f"{resolution}_cascade"
    with Image.open(request["images"]["front"]) as image:
        mesh = pipeline.run(image, seed=settings["seed"], pipeline_type=pipeline_type)[0]
    mesh.simplify(16777216)
    event("export", 0.85, "Exporting native PBR GLB")
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs,
        coords=mesh.coords, attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=1000000, texture_size=4096, remesh=True,
        remesh_band=1, remesh_project=0, verbose=True,
    )
    glb.export(str(output), extension_webp=True)


def run_pixal(request: dict, output: Path, root: Path) -> None:
    # Load the upstream inference entry point without spawning an untracked child.
    inference = runpy.run_path(str(root / "inference.py"), run_name="hocuspocus_pixal_adapter")
    settings = request["settings"]
    inference["run_inference"](
        image_path=request["images"]["front"], output_path=str(output),
        seed=settings["seed"], model_path=request["model"]["repo"],
        low_vram=settings["low_vram"], resolution=settings["resolution"],
        manual_fov=settings["camera_fov"] or -1.0,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    sys.path.insert(0, str(root))
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    output = Path(args.output).resolve()
    engine = request["model"]["engine"]
    if engine == "trellis2":
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("TRELLIS.2 requires an NVIDIA CUDA GPU")
        props = torch.cuda.get_device_properties(0)
        if props.total_memory < 24064 * 1024**2 or not 8 <= props.major < 10:
            raise RuntimeError("TRELLIS.2 requires NVIDIA 24GB and Ampere/Ada/Hopper for this optional runtime")
    # Upstream preprocessing files never appear as final Library assets.
    with tempfile.TemporaryDirectory(prefix="hocus-3d-") as temporary:
        staged = Path(temporary) / "asset.glb"
        with Heartbeat("inference", 0.15, f"Running {engine}"):
            if engine == "trellis2":
                run_trellis(request, staged)
            elif engine == "pixal3d":
                run_pixal(request, staged, root)
            else:
                raise ValueError("Unknown 3D worker engine")
        if not staged.is_file() or staged.stat().st_size < 12:
            raise RuntimeError("The engine did not produce a GLB")
        # Copy across filesystems, then atomically publish in the output directory.
        import shutil
        partial = output.with_suffix(".glb.partial")
        try:
            shutil.copyfile(staged, partial)
            partial.replace(output)
        finally:
            partial.unlink(missing_ok=True)
    event("completed", 1.0, "3D asset ready")


if __name__ == "__main__":
    main()
