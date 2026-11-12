"""Headless Make-It-Animatable driver. Runs inside the vendored checkout.

Importing upstream ``app.py`` loads Blender: ``util/dataset_mixamo.py`` builds
its kinematic tree from ``data/Mixamo/bones.fbx`` at import time. The forward
pass itself is PyTorch. The skinned rest-pose GLB is written by ``app_blender``
(bpy), which is the file this driver returns. Tests never import this module's
``main``; they replace ``predict_rest_glb`` on the worker.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from argparse import Namespace
from pathlib import Path


def blender_namespace(rest_glb: Path, template: Path) -> Namespace:
    """Arguments for ``app_blender.main``. The FBX is required; the GLB is the rest pose."""
    fbx = rest_glb.with_suffix(".fbx")
    return Namespace(
        input_path=None,
        output_path=str(fbx),
        template_path=str(template),
        keep_raw=False,
        rest_path=str(rest_glb),
        pose_local=False,
        reset_to_rest=True,
        remove_fingers=False,
        animation_path=None,
        retarget=False,
        inplace=False,
    )


def _prepare(mia_app, source: Path):
    database = mia_app.DB()
    mia_app.prepare_input(str(source), is_gs=False, db=database, export_temp=True)
    mia_app.infer(False, database)
    return database


def _apply_weights(mia_app, database) -> None:
    """Official ``vis`` post-process. Its Gradio return can fail after the arrays are stored."""
    try:
        mia_app.vis(True, "LeftArm", False, database)
    except Exception:
        if getattr(database, "joints_tail", None) is None or getattr(database, "bw", None) is None:
            raise


def _export_rest(mia_app, database, rest_glb: Path, template: Path) -> None:
    from app_blender import main as blender_main

    args = blender_namespace(rest_glb, template)
    args.input_path = {
        "mesh": database.mesh,
        "gs": None,
        "joints": database.joints,
        "joints_tail": database.joints_tail,
        "bw": database.bw,
        "pose": database.pose,
        "bones_idx_dict": dict(mia_app.bones_idx_dict_joints),
        "pose_ignore_list": mia_app.get_pose_ignore_list("T-pose", None),
    }
    blender_main(args)
    if not rest_glb.is_file():
        raise RuntimeError("Blender did not write the rest-pose GLB")


def predict(source: Path, rest_glb: Path, seed: int) -> None:
    vendor = Path.cwd()
    os.chdir(vendor)
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    import app as mia_app

    mia_app.init_models()
    try:
        import torch
        torch.manual_seed(int(seed))
    except Exception:
        pass
    database = _prepare(mia_app, source)
    output_dir = getattr(database, "output_dir", None)
    try:
        _apply_weights(mia_app, database)
        template = vendor / "data" / "Mixamo" / "bones.fbx"
        _export_rest(mia_app, database, rest_glb, template)
    finally:
        if output_dir:
            shutil.rmtree(output_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=12345)
    args = parser.parse_args()
    predict(Path(args.source).resolve(), Path(args.output).resolve(), args.seed)


if __name__ == "__main__":
    main()
