"""Short-lived See-through worker: NF4 pipeline, then source-aligned RGBA layers.

The vendor script paints every class on a square canvas (``center_square_pad_resize``).
This module runs that script with the component's interpreter and unpads the PNGs
back onto the pose. It does not import torch. There is no timeout: a pose takes minutes.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from services.runtime_environment import engine_python, isolated_environment
from services.runtime_profiles import APP_DIR

VENDOR = Path("app/services/see_through/vendor/see-through")
SCRIPT = VENDOR / "inference/scripts/inference_psd_quantized.py"
HF_HOME = Path("app/services/see_through/hf")
# Face classes the rig asks for. Anything else is kept when the pipeline painted it.
REQUIRED = ("eyewhite", "irides", "eyelash", "mouth")
ALPHA_MIN = 16


def square_pad(width: int, height: int) -> tuple[int, int, int]:
    """Side of the centered square pad, and the top-left of the original pixels on it."""
    side = max(width, height)
    return side, (side - width) // 2, (side - height) // 2


def canvas_to_source(canvas: np.ndarray, width: int, height: int, resolution: int) -> np.ndarray:
    """Inverse of the vendor's center-square pad: square canvas of ``resolution`` back to ``width``×``height``."""
    side, px1, py1 = square_pad(width, height)
    if canvas.shape[0] != side or canvas.shape[1] != side:
        interpolation = cv2.INTER_AREA if resolution > side else cv2.INTER_LINEAR
        canvas = cv2.resize(canvas, (side, side), interpolation=interpolation)
    return np.ascontiguousarray(canvas[py1:py1 + height, px1:px1 + width])


def _has_paint(image: Image.Image) -> bool:
    alpha = np.asarray(image)
    if alpha.ndim == 3:
        alpha = alpha[..., 3] if alpha.shape[-1] == 4 else alpha.max(axis=-1)
    return bool(alpha.size) and int(alpha.max()) > ALPHA_MIN


def _class_name(path: Path) -> str:
    return path.stem.strip()


def publish_layers(canvas_dir: Path, out_dir: Path, width: int, height: int, pose: str, resolution: int = 1280) -> dict:
    """Write source-sized RGBA PNGs and ``layers.json``. A missing or empty class is listed, not invented."""
    import json
    out_dir.mkdir(parents=True, exist_ok=True)
    present: dict[str, str] = {}
    if canvas_dir.is_dir():
        for path in sorted(canvas_dir.glob("*.png")):
            name = _class_name(path)
            with Image.open(path) as image:
                array = np.asarray(image.convert("RGBA"))
            layer = Image.fromarray(canvas_to_source(array, width, height, resolution))
            if not _has_paint(layer):
                continue
            filename = f"{name.replace(' ', '_')}.png"
            layer.save(out_dir / filename, format="PNG")
            present[name] = filename
    missing = [name for name in REQUIRED if name not in present]
    manifest = {"pose": pose, "width": width, "height": height, "space": "source", "classes": present, "missing": missing}
    (out_dir / "layers.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def run_pipeline(image: Path, save_dir: Path, *, resolution: int = 1280) -> Path:
    """Run ``inference_psd_quantized.py`` (NF4, group offload) and return the canvas directory it wrote."""
    root = APP_DIR.parent
    python = engine_python("see_through", root=root)
    vendor = root / VENDOR
    env = isolated_environment(python)
    env["HF_HOME"] = str(root / HF_HOME)
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    env["PYTHONPATH"] = str(vendor / "common")
    save_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(python), str(vendor / SCRIPT.relative_to(VENDOR)), "--srcp", str(image), "--save_dir", str(save_dir),
         "--resolution", str(resolution), "--quant_mode", "nf4"],
        cwd=str(vendor), env=env, check=True,
    )
    return save_dir / image.stem
