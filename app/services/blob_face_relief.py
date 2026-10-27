"""Relief for a painted face: the picture's own depth, so the mould's face matches what was painted.

A texture painted over a smooth mould is a mask: the nose is flat paint on a flat face and seen from the side the two disagree.
Here the front portrait of the head picture goes through a monocular depth model (Depth Anything V2, the base size, on the CPU, a
few seconds) and the face patch of the mould is pushed forward by that depth: the nose, the brows, the lips, the chin, the
cheekbones come from the painting itself, so the geometry and the picture agree from the front to about 60 degrees.
The patch moves along +Z only, so the front projection of the picture stays exact on every vertex. Pure numpy after the model;
the model is optional (``relief_from_picture`` returns None without it, and the face stays flat)."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

import numpy as np

CHECKPOINT = Path(__file__).resolve().parents[1] / "ckpts" / "depth" / "depth_anything_v2_vitb.pth"
PATCH_YAW = 58.0                 # degrees each way from the face: the patch covers the face, the skull the rest
PATCH_LATS = (-66.0, 46.0)       # from under the chin to the hairline
NOSE_SHARE = 0.15                # a relief of 1 protrudes by this share of the head's height (the nose tip of a real head)


def depth_of_picture(picture) -> np.ndarray:
    """Float depth in 0 (far) to 1 (near) for an RGB picture, same size as the picture. CPU, Depth Anything V2 base."""
    import os
    import sys

    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")   # a few seconds on the CPU: no GPU family is touched
    from preprocessing.depth_anything_v2.depth import DepthV2Annotator
    import torch

    annotator = DepthV2Annotator({"PRETRAINED_MODEL": str(CHECKPOINT), "MODEL_VARIANT": "vitb"}, device=torch.device("cpu"))
    depth = annotator.forward(np.asarray(picture.convert("RGB")))[..., 0].astype(np.float32)
    return depth / 255.0


def _blur(array: np.ndarray, sigma: float) -> np.ndarray:
    from scipy import ndimage

    return ndimage.gaussian_filter(array, sigma)


def relief_sampler(depth: np.ndarray, frame: dict, head_height: float) -> Callable[[float, float], float]:
    """``relief(x, y)`` in metres, for a point of the face in the T-pose frame, from the front tile's depth picture. The tile is the
    front third of the head picture: ``frame["head"]`` is its (centre y, height in metres, cut), a third is as wide as it is tall / 1.5."""
    cy, span_y, _cut = frame["head"]
    span_x = span_y / 1.5
    smooth = _blur(depth, max(1.0, depth.shape[0] / 300))
    h, w = smooth.shape
    xs = (np.arange(w) + 0.5) / w - 0.5
    ys = 0.5 - (np.arange(h) + 0.5) / h
    # the face's reach: the baseline is a low percentile of the depth over the cheeks and forehead, the top a high percentile (the nose)
    inside = (np.abs(xs)[None, :] * span_x < 0.42 * span_y / 1.5) & (np.abs(ys[:, None] * span_y) < 0.45 * span_y)
    region = smooth[inside]
    base, top = float(np.percentile(region, 35)), float(np.percentile(region, 99.5))
    scale = max(top - base, 1e-3)

    def relief(x: float, y: float) -> float:
        u = (x / span_x + 0.5) * w - 0.5
        v = (0.5 - (y - cy) / span_y) * h - 0.5
        if not (0 <= u < w - 1 and 0 <= v < h - 1):
            return 0.0
        i, j = int(v), int(u)
        fv, fu = v - i, u - j
        d = (smooth[i, j] * (1 - fu) + smooth[i, j + 1] * fu) * (1 - fv) + (smooth[i + 1, j] * (1 - fu) + smooth[i + 1, j + 1] * fu) * fv
        return max(0.0, min(1.0, (d - base) / scale)) * NOSE_SHARE * head_height

    return relief


def relief_from_picture(picture, frame: dict, head_height: float):
    """The sampler for the front tile of ``picture`` (the whole head picture, three tiles side by side), or None without the model."""
    if not CHECKPOINT.is_file():
        return None
    width, height = picture.size
    front = picture.convert("RGB").crop((0, 0, width // 3, height))
    return relief_sampler(depth_of_picture(front), frame, head_height)


def edge_fade(yaw: float, lat: float, lats: tuple[float, float] = PATCH_LATS, yaw_limit: float = PATCH_YAW) -> float:
    """1 inside the patch, falling to 0 at its border over about a fifth of its size, so the relief melts into the skull."""
    def ramp(distance: float, size: float) -> float:
        t = max(0.0, min(1.0, distance / (0.22 * size)))
        return t * t * (3 - 2 * t)

    return ramp(yaw_limit - abs(yaw), 2 * yaw_limit) * ramp(min(lat - lats[0], lats[1] - lat), lats[1] - lats[0])


def smoothstep_deg(value: float, low: float, high: float) -> float:
    t = max(0.0, min(1.0, (value - low) / (high - low)))
    return t * t * (3 - 2 * t)


__all__ = ["relief_from_picture", "relief_sampler", "edge_fade", "depth_of_picture", "PATCH_YAW", "PATCH_LATS", "math"]
