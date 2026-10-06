"""CPU image ops for keyed sprites: crop, cell placement and the H3 start frame.

``clean_alpha`` and ``crop_figure`` copy ``flat_rig._clean_alpha`` and
``crop_figure`` (app/services/flat_rig.py:138 and :164). Those helpers stay
private, so the algorithm is duplicated here and the thresholds are arguments.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from PIL import Image

from services.studio_key import screen_rgba, smooth_alpha

SCREEN_RGB = {
    "magenta": (255, 0, 255),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
}


def _as_rgba(image: Any) -> np.ndarray:
    if isinstance(image, Image.Image):
        return np.asarray(image.convert("RGBA"))
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[2] != 4:
        raise ValueError("expected an RGBA image")
    return np.asarray(array, dtype=np.uint8)


def clean_alpha(rgba: Any, threshold: int = 64, min_part: float = 0.02) -> np.ndarray:
    """Zero alpha below ``threshold`` and drop parts no larger than ``min_part`` of the largest."""
    pixels = _as_rgba(rgba).copy()
    alpha = pixels[..., 3]
    alpha[alpha < threshold] = 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats((alpha > 0).astype(np.uint8), connectivity=8)
    if count > 2:
        sizes = [int(stats[label, cv2.CC_STAT_AREA]) for label in range(1, count)]
        largest = max(sizes)
        keep_labels = [label for label, size in enumerate(sizes, start=1) if size > largest * min_part]
        alpha[~np.isin(labels, keep_labels)] = 0
    pixels[..., 3] = alpha
    return pixels


def crop_figure(rgba: Any, margin: float = 0.02) -> np.ndarray:
    """Crop to the opaque box plus ``margin`` of the longest side. Copied from flat_rig.py:164."""
    image = clean_alpha(rgba)
    alpha = image[..., 3]
    ys, xs = np.nonzero(alpha > 128)
    if len(xs) == 0:
        raise ValueError("no visible figure")
    height, width = image.shape[:2]
    pad = int(max(width, height) * margin)
    x0 = max(0, int(xs.min()) - pad)
    y0 = max(0, int(ys.min()) - pad)
    x1 = min(width, int(xs.max()) + pad + 1)
    y1 = min(height, int(ys.max()) + pad + 1)
    return image[y0:y1, x0:x1]


def key_screen(rgb: Any, screen: str) -> np.ndarray:
    """Public studio key: ``screen_rgba`` plus ``smooth_alpha`` on the single frame."""
    color = np.asarray(rgb)
    if color.ndim != 3 or color.shape[2] < 3:
        raise ValueError("expected an RGB image")
    keyed = screen_rgba(color[..., :3], screen)
    return smooth_alpha([keyed])[0]


def despill(rgba: Any, screen: str) -> np.ndarray:
    """Pull the screen channel down on pixels whose alpha is still partial."""
    image = _as_rgba(rgba).copy()
    alpha = image[..., 3].astype(np.float32)
    fringe = alpha < 255
    if not fringe.any():
        return image
    scale = ((255.0 - alpha) / 255.0)[..., None]
    channels = image[..., :3].astype(np.float32)
    if screen == "magenta":
        limit = channels[..., 1:2]
        excess = np.clip(channels[..., [0, 2]] - limit, 0, None)
        channels[..., [0, 2]] -= excess * scale
    else:
        index = 1 if screen == "green" else 2
        others = np.maximum(channels[..., 0], channels[..., 2] if index == 1 else channels[..., 1])
        excess = np.clip(channels[..., index] - others, 0, None)
        channels[..., index] -= excess * scale[..., 0]
    image[..., :3] = np.clip(np.rint(channels), 0, 255).astype(np.uint8)
    return image


def to_illustration(rgba: Any, height_px: int, screen: str = "magenta") -> np.ndarray:
    """Lanczos scale on premultiplied alpha, then despill the fringe."""
    image = _as_rgba(rgba).astype(np.float32)
    alpha = image[..., 3:4] / 255.0
    premultiplied = np.concatenate([image[..., :3] * alpha, image[..., 3:4]], axis=2)
    source = Image.fromarray(np.clip(np.rint(premultiplied), 0, 255).astype(np.uint8))
    width = max(1, int(round(source.width * (height_px / source.height))))
    scaled = np.asarray(source.resize((width, int(height_px)), Image.Resampling.LANCZOS)).astype(np.float32)
    scaled_alpha = scaled[..., 3:4]
    recovered = np.zeros_like(scaled[..., :3])
    visible = scaled_alpha[..., 0] > 0
    recovered[visible] = scaled[..., :3][visible] * (255.0 / scaled_alpha[..., 0][visible][:, None])
    output = np.concatenate([np.clip(np.rint(recovered), 0, 255), scaled[..., 3:4]], axis=2).astype(np.uint8)
    return despill(output, screen)


def feet_point(rgba: Any) -> tuple[float, float]:
    """Horizontal centroid of the bottom 15 percent of the opaque figure, and its lowest row."""
    alpha = _as_rgba(rgba)[..., 3] > 0
    ys, xs = np.nonzero(alpha)
    if len(xs) == 0:
        return (0.0, 0.0)
    lowest = int(ys.max())
    span = lowest - int(ys.min()) + 1
    band_top = lowest - max(1, int(round(span * 0.15))) + 1
    band = (ys >= band_top)
    return (float(xs[band].mean()), float(lowest))


def place_on_cell(rgba: Any, cell: tuple[int, int], pivot: tuple[float, float], feet_xy: tuple[float, float]) -> np.ndarray:
    """Blit so ``feet_xy`` in the sprite lands on ``pivot`` in a ``cell`` of (width, height)."""
    sprite = _as_rgba(rgba)
    width, height = int(cell[0]), int(cell[1])
    canvas = np.zeros((height, width, 4), dtype=np.uint8)
    origin_x = int(round(pivot[0] - feet_xy[0]))
    origin_y = int(round(pivot[1] - feet_xy[1]))
    src_x0 = max(0, -origin_x)
    src_y0 = max(0, -origin_y)
    dst_x0 = max(0, origin_x)
    dst_y0 = max(0, origin_y)
    copy_w = min(sprite.shape[1] - src_x0, width - dst_x0)
    copy_h = min(sprite.shape[0] - src_y0, height - dst_y0)
    if copy_w > 0 and copy_h > 0:
        canvas[dst_y0:dst_y0 + copy_h, dst_x0:dst_x0 + copy_w] = sprite[src_y0:src_y0 + copy_h, src_x0:src_x0 + copy_w]
    return canvas


def dhash(rgba: Any, size: int = 8) -> int:
    """Horizontal difference hash. ``size`` 8 yields 64 bits."""
    gray = Image.fromarray(_as_rgba(rgba)).convert("L")
    small = np.asarray(gray.resize((size + 1, size), Image.Resampling.LANCZOS), dtype=np.int16)
    bits = (small[:, 1:] > small[:, :-1]).ravel()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def compose_start_frame(
    base_rgba: Any,
    size: tuple[int, int],
    screen: str,
    height_frac: float = 0.65,
    feet_frac: float = 0.85,
) -> np.ndarray:
    """Center a keyed figure on a flat screen. Feet sit near ``feet_frac`` of the height."""
    width, height = int(size[0]), int(size[1])
    source = np.asarray(base_rgba)
    keyed = source if source.ndim == 3 and source.shape[2] == 4 and int(source[..., 3].min()) < 255 else key_screen(source, screen)
    figure = crop_figure(keyed)
    opaque_rows = np.nonzero((figure[..., 3] > 128).any(axis=1))[0]
    figure_height = max(1, int(opaque_rows[-1] - opaque_rows[0] + 1)) if len(opaque_rows) else figure.shape[0]
    target = max(1, int(round(height * height_frac)))
    scale = target / figure_height
    resized = to_illustration(figure, max(1, int(round(figure.shape[0] * scale))), screen)
    feet_x, feet_y = feet_point(resized)
    pivot = (width / 2.0, height * feet_frac)
    placed = place_on_cell(resized, (width, height), pivot, (feet_x, feet_y))
    color = SCREEN_RGB.get(screen, SCREEN_RGB["magenta"])
    background = np.zeros_like(placed)
    background[..., 0] = color[0]
    background[..., 1] = color[1]
    background[..., 2] = color[2]
    background[..., 3] = 255
    mask = placed[..., 3] > 0
    background[mask] = placed[mask]
    return background
