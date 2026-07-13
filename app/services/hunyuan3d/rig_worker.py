"""Short-lived rigging worker used by Maestro.

Adds a procedural skeleton + animation clips to an existing GLB output.
Runs inside the Hunyuan3D isolated environment (numpy/pygltflib are already
installed there) but is CPU-only and needs no network or CUDA state; it
exits after one job like the generation worker, printing MAESTRO_EVENT
progress lines for the parent process.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import procedural_rig


def event(phase: str, progress: float, message: str) -> None:
    print("MAESTRO_EVENT " + json.dumps({"phase": phase, "progress": progress, "message": message}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    source = str(request["source"])
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not Path(source).is_file():
        raise RuntimeError(f"Source model not found: {source}")

    summary = procedural_rig.rig_glb(
        source,
        str(output_path),
        clip_ids=list(request.get("animations") or list(procedural_rig.CLIPS)),
        rig_profile=str(request.get("rig_profile") or "prop"),
        spine_joints=int(request.get("spine_joints") or 5),
        axis_mode=str(request.get("axis_mode") or "auto"),
        weight_falloff=float(request.get("weight_falloff") or 2.0),
        progress=event,
    )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("Rigging did not produce an output file")
    print("MAESTRO_RESULT " + json.dumps(summary), flush=True)
    event("completed", 1.0, "Rigged model saved")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        event("failed", 0.0, str(exc))
        raise
