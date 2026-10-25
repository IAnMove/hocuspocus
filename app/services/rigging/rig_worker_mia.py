"""Short-lived Make-It-Animatable worker used by HocusPocus.

GLB in, rigged GLB out. The vendored model writes a rest-pose skin (Blender),
then ``procedural_rig.bake_clips_onto_existing_rig`` bakes the clip library,
including humanoid limb clips when the profile is humanoid. Prints
MAESTRO_EVENT progress lines and one MAESTRO_RESULT for the parent process.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pygltflib import GLTF2

HERE = Path(__file__).resolve().parent
VENDOR_DIR = HERE.parent / "mia" / "vendor" / "Make-It-Animatable"
PREDICT_PATH = HERE / "mia_predict.py"
# Same relative paths as services.rigging.mia. A test locks the two lists together.
WEIGHT_RELATIVE = (
    "output/best/new/bw.pth",
    "output/best/new/bw_normal.pth",
    "output/best/new/joints.pth",
    "output/best/new/joints_coarse.pth",
    "output/best/new/pose.pth",
)
TEMPLATE_RELATIVE = "data/Mixamo/bones.fbx"
_ENV_BIN_DIR = str(Path(sys.executable).resolve().parent)
sys.path.insert(0, str(HERE.parent / "hunyuan3d"))

import procedural_rig  # noqa: E402


def event(phase: str, progress: float, message: str) -> None:
    print("MAESTRO_EVENT " + json.dumps({"phase": phase, "progress": progress, "message": message}), flush=True)


def _weights_ready() -> bool:
    needed = (*WEIGHT_RELATIVE, TEMPLATE_RELATIVE)
    return VENDOR_DIR.is_dir() and all((VENDOR_DIR / relative).is_file() for relative in needed)


def predict_rest_glb(source: Path, destination: Path, seed: int) -> None:
    """Run the vendored model. Tests replace this function and skip the checkout."""
    if not (VENDOR_DIR / "app.py").is_file() or not _weights_ready():
        raise RuntimeError(
            "Make-It-Animatable is not installed. Run 'Install Make-It-Animatable' from the HocusPocus Lab menu."
        )
    env = os.environ.copy()
    env["PATH"] = _ENV_BIN_DIR + os.pathsep + env.get("PATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    env["HF_HUB_OFFLINE"] = "1"
    command = [sys.executable, str(PREDICT_PATH), "--source", str(source), "--output", str(destination), "--seed", str(seed)]
    completed = subprocess.run(command, cwd=str(VENDOR_DIR), env=env)
    if completed.returncode != 0 or not destination.is_file():
        raise RuntimeError("Make-It-Animatable did not write a rest-pose GLB")


def _require_skin(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 20:
        raise RuntimeError("Make-It-Animatable did not write a rest-pose GLB")
    gltf = GLTF2().load_binary(str(path))
    if not gltf.meshes or not gltf.skins or not any(skin.joints for skin in gltf.skins):
        raise RuntimeError("Make-It-Animatable wrote a GLB with no skin")


def _result_payload(summary: dict) -> dict:
    payload = {"ok": True}
    for key, value in summary.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            payload[key] = value
        elif isinstance(value, (list, dict)):
            payload[key] = value
        else:
            item = getattr(value, "item", None)
            payload[key] = item() if callable(item) else str(value)
    payload["joint_count"] = payload.pop("joints", 0)
    payload["animation_chain_joints"] = payload.pop("chain_length", 0)
    return payload


def run(request: dict, output_path: Path) -> None:
    source = Path(str(request["source"])).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        raise RuntimeError(f"Source model not found: {source}")
    clip_ids = list(request.get("animations") or list(procedural_rig.CLIPS))
    seed = int(request.get("seed", 12345))
    with tempfile.TemporaryDirectory(prefix="maestro_mia_") as temp_name:
        rest = Path(temp_name) / "rest.glb"
        event("predict", 0.15, "Predicting a skeleton with Make-It-Animatable")
        predict_rest_glb(source, rest, seed)
        _require_skin(rest)
        event("animating", 0.7, "Baking the clip library onto the predicted skeleton")
        summary = procedural_rig.bake_clips_onto_existing_rig(
            str(rest), str(output_path), clip_ids, progress=event,
            rig_profile=str(request.get("rig_profile") or "humanoid"),
            animation_bpm=float(request.get("animation_bpm", 120)),
        )
    names = [procedural_rig.CLIPS[clip_id] for clip_id in clip_ids]
    gltf = GLTF2().load_binary(str(output_path))
    found = {animation.name for animation in gltf.animations or []}
    missing = [name for name in names if name not in found]
    if missing:
        raise RuntimeError("Animated GLB is missing clips: " + ", ".join(missing))
    print("MAESTRO_RESULT " + json.dumps(_result_payload(summary)), flush=True)
    event("completed", 1.0, "Make-It-Animatable rig saved")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    run(request, Path(args.output).resolve())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        event("failed", 0.0, str(exc))
        print("MAESTRO_RESULT " + json.dumps({"ok": False, "error": "rig_failed", "reason": str(exc)}), flush=True)
        raise
