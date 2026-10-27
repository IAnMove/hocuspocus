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
PATCH_YAW = 53.0                 # degrees each way from the face: the patch covers the face, the skull the rest
PATCH_LATS = (-66.0, 46.0)       # from under the chin to the hairline
NOSE_SHARE = 0.10                # a relief of 1 protrudes by this share of the head's height (a nose tip a little under a real one)


def depth_of_picture(picture) -> np.ndarray:
    """Float depth in 0 (far) to 1 (near) for an RGB picture, same size as the picture. Always the CPU (Depth Anything V2 base): the
    shared annotator moves its input to the GPU when there is one, so the steps are run here with the model and the input on the CPU."""
    import sys

    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    import torch
    import torch.nn.functional as F
    from preprocessing.depth_anything_v2.dpt import DepthAnythingV2

    model = DepthAnythingV2(encoder="vitb", features=128, out_channels=[96, 192, 384, 768])
    model.load_state_dict(torch.load(str(CHECKPOINT), map_location="cpu", weights_only=True))
    model.eval()
    rgb = np.asarray(picture.convert("RGB"))
    height, width = rgb.shape[:2]
    scale = 518 / min(height, width)
    size = (max(14, round(width * scale / 14) * 14), max(14, round(height * scale / 14) * 14))
    from PIL import Image

    small = np.asarray(Image.fromarray(rgb).resize(size, Image.BICUBIC)).astype(np.float32) / 255.0
    mean, std = np.array([0.485, 0.456, 0.406], np.float32), np.array([0.229, 0.224, 0.225], np.float32)
    tensor = torch.from_numpy(((small - mean) / std).transpose(2, 0, 1)).unsqueeze(0)
    with torch.inference_mode():
        depth = model(tensor)
        depth = F.interpolate(depth[:, None], (height, width), mode="bilinear", align_corners=True)[0, 0].numpy()
    depth = depth - depth.min()
    return (depth / max(float(depth.max()), 1e-6)).astype(np.float32)


def _blur(array: np.ndarray, sigma: float) -> np.ndarray:
    from scipy import ndimage

    return ndimage.gaussian_filter(array, sigma)


def relief_sampler(depth: np.ndarray, frame: dict, head_height: float) -> Callable[[float, float], float]:
    """``relief(x, y)`` in metres, for a point of the face in the T-pose frame, from the front tile's depth picture. The tile is the
    front third of the head picture: ``frame["head"]`` is its (centre y, height in metres, cut), a third is as wide as it is tall / 1.5."""
    cy, span_y, _cut = frame["head"]
    span_x = span_y / 1.5
    h, w = depth.shape
    smooth = _blur(depth, max(1.0, h / 500))
    # the head's own roundness is the skull's: keep only what stands out of a low-pass of the depth over the head (the nose, the brows,
    # the cheekbones, the lips, the chin), found by a masked blur so the background does not pull the average down
    head = (smooth > 0.3).astype(np.float32)
    sigma = h / 25.0
    low = _blur(smooth * head, sigma) / np.maximum(_blur(head, sigma), 1e-4)
    residual = np.clip(smooth - low, 0.0, None)
    xs = (np.arange(w) + 0.5) / w - 0.5
    ys = 0.5 - (np.arange(h) + 0.5) / h
    inside = (np.abs(xs)[None, :] * span_x < 0.42 * span_y / 1.5) & (np.abs(ys[:, None] * span_y) < 0.45 * span_y)
    scale = max(float(np.percentile(residual[inside], 99.7)), 1e-3)
    smooth = np.clip(residual / scale, 0.0, 1.0)

    def relief(x: float, y: float) -> float:
        u = (x / span_x + 0.5) * w - 0.5
        v = (0.5 - (y - cy) / span_y) * h - 0.5
        if not (0 <= u < w - 1 and 0 <= v < h - 1):
            return 0.0
        i, j = int(v), int(u)
        fv, fu = v - i, u - j
        d = (smooth[i, j] * (1 - fu) + smooth[i, j + 1] * fu) * (1 - fv) + (smooth[i + 1, j] * (1 - fu) + smooth[i + 1, j + 1] * fu) * fv
        return float(max(0.0, min(1.0, float(d))) * NOSE_SHARE * head_height)

    return relief


def relief_from_picture(picture, frame: dict, head_height: float, span: float = PATCH_YAW):
    """The sampler for the front tile of ``picture`` (the whole head picture, three tiles side by side), or None without the model.
    ``span`` (degrees each way from the face) is how far the face patch reaches; the sampler carries it as ``.yaw``."""
    if not CHECKPOINT.is_file():
        return None
    width, height = picture.size
    front = picture.convert("RGB").crop((0, 0, width // 3, height))
    sampler = relief_sampler(depth_of_picture(front), frame, head_height)
    sampler.yaw = float(span)
    return sampler


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
