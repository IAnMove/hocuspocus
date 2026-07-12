"""Short-lived UniRig auto-rigging worker used by Maestro.

Drives the vendored UniRig pipeline (skeleton prediction → skinning weight
prediction → merge into the original GLB) inside the optional rigging
environment, then bakes Maestro's animation clip library onto the predicted
skeleton with the shared procedural_rig module. Exits after one job and
prints MAESTRO_EVENT progress lines for the parent process.

Linux/macOS only: UniRig's inference entry points are bash scripts.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENDOR_DIR = HERE / "vendor" / "UniRig"
# UniRig's launch/inference/*.sh scripts invoke bare `python`/`python3`
# rather than sys.executable. Without this, that resolves via PATH to
# whatever interpreter is first there — typically the base conda env, which
# has neither bpy nor UniRig's other dependencies installed. Prepending this
# worker's own interpreter directory makes those bare calls resolve to the
# rigging env instead.
_ENV_BIN_DIR = str(Path(sys.executable).resolve().parent)
# The clip baker lives with the procedural engine; it only needs
# numpy/pygltflib, both installed in this environment too.
sys.path.insert(0, str(HERE.parent / "hunyuan3d"))

import procedural_rig  # noqa: E402


def event(phase: str, progress: float, message: str) -> None:
    print("MAESTRO_EVENT " + json.dumps({"phase": phase, "progress": progress, "message": message}), flush=True)


def run_unirig(script: str, arguments: list[str]) -> None:
    """Run one of UniRig's launch/inference bash scripts, streaming output."""
    env = os.environ.copy()
    env["PATH"] = _ENV_BIN_DIR + os.pathsep + env.get("PATH", "")
    command = ["bash", f"launch/inference/{script}", *arguments]
    process = subprocess.run(command, cwd=str(VENDOR_DIR), env=env)
    if process.returncode != 0:
        raise RuntimeError(f"UniRig {script} failed with exit code {process.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    source = Path(str(request["source"])).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        raise RuntimeError(f"Source model not found: {source}")
    if not VENDOR_DIR.is_dir():
        raise RuntimeError("UniRig is not installed; run 'Install AI Rigging (UniRig)' from the Maestro menu")
    clip_ids = list(request.get("animations") or list(procedural_rig.CLIPS))
    seed = int(request.get("seed") or 12345)

    with tempfile.TemporaryDirectory(prefix="maestro_unirig_") as temp_name:
        temp_dir = Path(temp_name)
        skeleton_fbx = temp_dir / "skeleton.fbx"
        skin_fbx = temp_dir / "skin.fbx"
        merged_glb = temp_dir / "merged.glb"

        event("skeleton", 0.1, "Predicting skeleton (first run downloads UniRig weights)")
        run_unirig("generate_skeleton.sh", ["--input", str(source), "--output", str(skeleton_fbx), "--seed", str(seed)])
        if not skeleton_fbx.is_file():
            raise RuntimeError("UniRig did not produce a skeleton")

        event("skinning", 0.45, "Predicting skinning weights")
        run_unirig("generate_skin.sh", ["--input", str(skeleton_fbx), "--output", str(skin_fbx)])
        if not skin_fbx.is_file():
            raise RuntimeError("UniRig did not produce skinning weights")

        event("merge", 0.7, "Merging rig into the original model")
        run_unirig("merge.sh", ["--source", str(skin_fbx), "--target", str(source), "--output", str(merged_glb)])
        if not merged_glb.is_file():
            raise RuntimeError("UniRig merge did not produce a rigged model")

        summary = procedural_rig.bake_clips_onto_existing_rig(str(merged_glb), str(output_path), clip_ids, progress=event)

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("UniRig rigging did not produce an output file")
    print("MAESTRO_RESULT " + json.dumps(summary), flush=True)
    event("completed", 1.0, "AI-rigged model saved")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        event("failed", 0.0, str(exc))
        raise
