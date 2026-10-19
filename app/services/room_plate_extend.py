"""What a plate does not show: its edges mirrored, blurred and darkened.

The side walls, the ceiling and the floor around the part the plate covers are textures baked here. A point of one of them
has a place on the plate as the plate's own camera sees it, ``(u, v)``, outside the picture. The picture is folded back by
mirroring at its edges (so the colour at the edge is the plate's), blurred more the farther the point is from the picture
(a pyramid of blurred copies) and darkened with the same distance, so a camera that moves a little finds a soft, dim
continuation of the room and never a stretched streak or a void. Inside the picture the bake is the plate itself.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
from PIL import Image, ImageFilter

BASE_WIDTH = 960
# Distance outside the picture (in plate heights) and the blur it earns (also in plate heights, as a Gaussian sigma).
_STEPS = np.array([0.0, 0.05, 0.15, 0.4, 0.9, 1.8])
_SIGMA = np.array([0.0, 0.004, 0.012, 0.03, 0.07, 0.15])
DARKEN = 0.42
FULL = 1.6   # the distance at which the darkening has run its course

Mapping = Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]


class Plate:
    """A plate and its blurred copies, to be sampled anywhere on the plane, inside the picture or not."""

    def __init__(self, picture: Image.Image) -> None:
        rgb = picture.convert("RGB")
        width = min(BASE_WIDTH, rgb.width)
        base = rgb.resize((width, max(1, round(rgb.height * width / rgb.width))), Image.Resampling.LANCZOS)
        self.aspect = rgb.width / rgb.height
        self.levels = np.stack([np.asarray(base.filter(ImageFilter.GaussianBlur(float(sigma) * base.height)) if sigma else base,
                                           dtype=np.float32) for sigma in _SIGMA])

    def sample(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Colours (float 0-255, shape ``u.shape + (3,)``) at plate fractions ``(u, v)``, which may lie outside [0, 1]."""
        e = outside(u, v, self.aspect)
        position = np.interp(e, _STEPS, np.arange(len(_STEPS)))
        low = np.floor(position).astype(int).clip(0, len(_STEPS) - 1)
        high = np.minimum(low + 1, len(_STEPS) - 1)
        mix = (position - low)[..., None]
        fu, fv = fold(u), fold(v)
        colour = self._at(low, fu, fv) * (1 - mix) + self._at(high, fu, fv) * mix
        return colour * dimming(e)[..., None]

    def _at(self, level: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        height, width = self.levels.shape[1:3]
        x, y = u * (width - 1), v * (height - 1)
        x0, y0 = np.floor(x).astype(int).clip(0, width - 1), np.floor(y).astype(int).clip(0, height - 1)
        x1, y1 = np.minimum(x0 + 1, width - 1), np.minimum(y0 + 1, height - 1)
        fx, fy = (x - x0)[..., None], (y - y0)[..., None]
        top = self.levels[level, y0, x0] * (1 - fx) + self.levels[level, y0, x1] * fx
        bottom = self.levels[level, y1, x0] * (1 - fx) + self.levels[level, y1, x1] * fx
        return top * (1 - fy) + bottom * fy


def fold(t: np.ndarray) -> np.ndarray:
    """Mirror ``t`` back into [0, 1] at every edge: 1.2 reads 0.8, -0.3 reads 0.3."""
    return np.abs(((t + 1) % 2) - 1)


def outside(u: np.ndarray, v: np.ndarray, aspect: float) -> np.ndarray:
    """How far (in plate heights) a point is from the picture; 0 inside it."""
    du = np.maximum(np.maximum(-u, u - 1), 0) * aspect
    dv = np.maximum(np.maximum(-v, v - 1), 0)
    return np.hypot(du, dv)


def dimming(e: np.ndarray) -> np.ndarray:
    """1 inside the picture, darker with distance (smoothstep), ``1 - DARKEN`` at ``FULL`` and beyond."""
    t = np.clip(e / FULL, 0, 1)
    return 1 - DARKEN * t * t * (3 - 2 * t)


def bake(plate: Plate, width: int, height: int, mapping: Mapping) -> Image.Image:
    """A ``width × height`` picture whose pixel ``(i, j)`` is the plate seen at ``mapping(i, j)``. ``mapping`` gets the pixel
    centres as fractions of the picture (0 to 1, from the top left) and returns the plate's ``(u, v)`` for each."""
    across = (np.arange(width, dtype=np.float64) + 0.5) / width
    down = (np.arange(height, dtype=np.float64) + 0.5) / height
    grid_x, grid_y = np.meshgrid(across, down)
    u, v = mapping(grid_x, grid_y)
    out = plate.sample(u.astype(np.float32), v.astype(np.float32))
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8))
