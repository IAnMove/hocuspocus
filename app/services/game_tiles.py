"""Seam metric, tile roll and 9-slice margins. CPU only.

``seam_error`` matches the J0 trial: mean wrap difference divided by the mean
interior neighbor difference. Below 1.5 is an acceptable seam.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image


def _array(image: Any) -> np.ndarray:
    return np.asarray(image)


def _as_image(original: Any, array: np.ndarray) -> Any:
    if isinstance(original, Image.Image):
        return Image.fromarray(array)
    return array


def _roll(img: Any, axes: tuple[int, ...], sign: int) -> Any:
    rolled = _array(img)
    for axis in axes:
        rolled = np.roll(rolled, sign * (rolled.shape[axis] // 2), axis=axis)
    return _as_image(img, rolled)


def roll_half(img: Any, axes: tuple[int, ...] = (0, 1)) -> Any:
    """Roll by half the size (rounded down) on each axis."""
    return _roll(img, axes, 1)


def unroll(img: Any, axes: tuple[int, ...] = (0, 1)) -> Any:
    """Exact inverse of ``roll_half``, odd sizes included: roll back by the same amount."""
    return _roll(img, axes, -1)


def seam_mask(w: int, h: int, band: int, axes: tuple[int, ...] = (0, 1)) -> np.ndarray:
    """Cross (or one band) centered where a half-roll brings the edges together."""
    mask = np.zeros((h, w), dtype=np.uint8)
    half = max(1, int(band) // 2)
    if 1 in axes:
        center = w // 2
        mask[:, max(0, center - half):center + half] = 255
    if 0 in axes:
        center = h // 2
        mask[max(0, center - half):center + half, :] = 255
    return mask


def seam_error(img: Any, axes: tuple[int, ...] = (0, 1)) -> float:
    """Wrap error over interior variation. One axis skips the other direction."""
    data = _array(img).astype(np.float32)
    if data.ndim == 3:
        data = data[..., :3]
    scores = []
    if 1 in axes and data.shape[1] > 2:
        wrap = np.abs(data[:, 0] - data[:, -1]).mean()
        interior = np.abs(np.diff(data[:, 1:-1], axis=1)).mean()
        scores.append(float(wrap / max(float(interior), 1e-6)))
    if 0 in axes and data.shape[0] > 2:
        wrap = np.abs(data[0] - data[-1]).mean()
        interior = np.abs(np.diff(data[1:-1], axis=0)).mean()
        scores.append(float(wrap / max(float(interior), 1e-6)))
    if not scores:
        return 0.0
    return float(sum(scores) / len(scores))


def slice_grid(img: Any, cols: int, rows: int) -> list[np.ndarray]:
    """Cut an even grid, row-major. Trailing pixels that do not fill a cell are dropped."""
    data = _array(img)
    cell_h = data.shape[0] // rows
    cell_w = data.shape[1] // cols
    cells = []
    for row in range(rows):
        for col in range(cols):
            cells.append(data[row * cell_h:(row + 1) * cell_h, col * cell_w:(col + 1) * cell_w])
    return cells


def _flat_run(diff: np.ndarray, limit: float) -> tuple[int, int]:
    flat = diff < limit
    best = (0, 0, -1)
    start = None
    for index, flag in enumerate(flat.tolist()):
        if flag and start is None:
            start = index
        if not flag and start is not None:
            if index - start > best[2]:
                best = (start, index - 1, index - start)
            start = None
    if start is not None and len(flat) - start > best[2]:
        best = (start, len(flat) - 1, len(flat) - start)
    return best[0], best[1]


# A mirrored frame whose mean absolute difference stays under this shares one margin per pair.
_MIRROR_LIMIT = 12.0


def _content_crop(data: np.ndarray, color: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Opaque crop, plus padding ``(top, bottom, left, right)``. A fully opaque image is unchanged."""
    if data.ndim != 3 or data.shape[2] < 4:
        return color, (0, 0, 0, 0)
    rows = np.any(data[..., 3] > 0, axis=1)
    cols = np.any(data[..., 3] > 0, axis=0)
    if not bool(rows.any()):
        return color, (0, 0, 0, 0)
    top = int(np.argmax(rows))
    bottom = int(len(rows) - np.argmax(rows[::-1]))
    left = int(np.argmax(cols))
    right = int(len(cols) - np.argmax(cols[::-1]))
    height, width = int(color.shape[0]), int(color.shape[1])
    return color[top:bottom, left:right], (top, height - bottom, left, width - right)


def _axis_diff(color: np.ndarray, axis: int) -> np.ndarray:
    values = np.asarray(color, dtype=np.float32)
    if axis == 1:
        delta = np.abs(values[:, 1:] - values[:, :-1])
        return delta.mean(axis=(0, 2)) if values.ndim == 3 else delta.mean(axis=0)
    delta = np.abs(values[1:] - values[:-1])
    return delta.mean(axis=(1, 2)) if values.ndim == 3 else delta.mean(axis=1)


def _pair_margins(diff: np.ndarray, length: int, scale: float) -> tuple[int, int]:
    left_index, right_index = _flat_run(diff, scale)
    left = max(2, int(left_index))
    right = max(2, int(length - (right_index + 2)))
    if left + right >= length:
        return 2, 2
    return left, right


def _mirror_mean(data: np.ndarray, axis: int) -> float:
    flipped = np.flip(data, axis=axis)
    return float(np.mean(np.abs(data.astype(np.float32) - flipped.astype(np.float32))))


def _snap_pair(left: int, right: int, length: int, delta: float) -> tuple[int, int]:
    if left + right >= length:
        return 2, 2
    if delta > _MIRROR_LIMIT:
        return left, right
    shared = max(2, int(round((left + right) / 2.0)))
    if shared * 2 >= length:
        return left, right
    return shared, shared


def nine_slice_margins(rgba: Any) -> dict[str, int]:
    """Margins of the stretchable center. The minimum reported margin is 2 px.

    Transparent padding is not treated as the center. A frame that mirrors
    within ``_MIRROR_LIMIT`` gets the same margin on both sides of each pair.
    """
    data = _array(rgba)
    color = data[..., :3] if data.ndim == 3 else data
    height, width = int(color.shape[0]), int(color.shape[1])
    crop, pad = _content_crop(data, color)
    if int(crop.shape[0]) < 3 or int(crop.shape[1]) < 3:
        return {"left": 2, "right": 2, "top": 2, "bottom": 2}
    scale = max(float(np.asarray(crop, dtype=np.float32).mean()) * 0.02, 1.0)
    left, right = _pair_margins(_axis_diff(crop, 1), int(crop.shape[1]), scale)
    top, bottom = _pair_margins(_axis_diff(crop, 0), int(crop.shape[0]), scale)
    left, right = _snap_pair(left + pad[2], right + pad[3], width, _mirror_mean(data, 1))
    top, bottom = _snap_pair(top + pad[0], bottom + pad[1], height, _mirror_mean(data, 0))
    return {"left": left, "right": right, "top": top, "bottom": bottom}
