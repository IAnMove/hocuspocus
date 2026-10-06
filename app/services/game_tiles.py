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


def nine_slice_margins(rgba: Any) -> dict[str, int]:
    """Margins of the stretchable center. The minimum reported margin is 2 px."""
    data = _array(rgba).astype(np.float32)
    color = data[..., :3] if data.ndim == 3 else data
    height, width = color.shape[:2]
    column_diff = np.abs(color[:, 1:] - color[:, :-1]).mean(axis=(0, 2)) if color.ndim == 3 else np.abs(color[:, 1:] - color[:, :-1]).mean(axis=0)
    row_diff = np.abs(color[1:] - color[:-1]).mean(axis=(1, 2)) if color.ndim == 3 else np.abs(color[1:] - color[:-1]).mean(axis=1)
    scale = max(float(color.mean()) * 0.02, 1.0)

    def margins(diff: np.ndarray, length: int) -> tuple[int, int]:
        left_index, right_index = _flat_run(diff, scale)
        left = max(2, int(left_index))
        right = max(2, int(length - (right_index + 2)))
        if left + right >= length:
            left = right = 2
        return left, right

    left, right = margins(column_diff, width)
    top, bottom = margins(row_diff, height)
    return {"left": left, "right": right, "top": top, "bottom": bottom}
