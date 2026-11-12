"""Cloth that hangs off the body, seen from the front: capes, coat tails, the hollow of a robe.

A ray along Z through each pixel centre crosses the surface; the nonzero winding
rule turns the crossings into solid spans. On every row the longest span is the
torso, a leg or the head, and its middle is the body's plane on that row. A
pixel whose spans all miss the slab around that plane is cloth: a cape tent (a
front and a back sheet with air between), a cape hanging behind the legs, or
the empty inside of an open robe. Arms and legs cross the slab, so they stay.

The silhouette then has a body mask without the cloth, where the arms and the
gap between the legs show again, and each vertex can be told apart as body or
cloth for the skin weights.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from services.humanoid_rig.silhouette import Silhouette, disk

# Pixel centres are moved by an irrational sliver so a ray never runs exactly along a shared edge.
_JITTER = np.array([1e-4 * 2 ** 0.5, 1e-4 * 3 ** 0.5])
_MAX_SAMPLES = 1 << 22
# The slab reaches this share of the row's longest half-span around its middle (never less than _MIN_REACH of the height).
_SHARE = 0.35
_MIN_REACH = 0.01
_ROWS = 9
# A vertex this far (fraction of the height) outside the body span of its pixel is on a separate layer.
_LAYER = 0.01


class Covering:
    """The cloth mask of a silhouette, and the body span of every pixel."""

    def __init__(self, silhouette: Silhouette, cloth: np.ndarray, low: np.ndarray, high: np.ndarray, height: float) -> None:
        self.silhouette = silhouette
        self.mask = cloth
        self.low = low
        self.high = high
        self.height = height

    def body(self, mask: np.ndarray) -> np.ndarray:
        """``mask`` without the cloth, nor the thin rim of cloth edge that no pixel centre covered."""
        cut = mask & ~self.mask
        rim = cut & ~ndimage.binary_opening(cut, structure=disk(1.5))
        return cut & ~(rim & ndimage.binary_dilation(self.mask, structure=disk(3.0)))

    def vertices(self, points: np.ndarray) -> np.ndarray:
        """True for the vertices on cloth: off the body span of their pixel and its neighbours.

        Over a cloth pixel that is every vertex, except the rim of a limb whose edge just misses
        the pixel centre; elsewhere it is a layer apart, such as a cape behind the back. A vertex on
        the rim of the cloth, where no pixel centre found anything, goes with the cloth next to it.
        """
        sil = self.silhouette
        rows = np.clip(np.floor((points[:, 1] - sil.origin[1]) / sil.pixel).astype(np.int64), 0, self.mask.shape[0] - 1)
        cols = np.clip(np.floor((points[:, 0] - sil.origin[0]) / sil.pixel).astype(np.int64), 0, self.mask.shape[1] - 1)
        low, high = self.low[rows, cols], self.high[rows, cols]
        margin = self.height * _LAYER
        known = np.isfinite(low)
        within = (points[:, 2] >= low - margin) & (points[:, 2] <= high + margin)
        rim = ndimage.binary_dilation(self.mask, structure=np.ones((3, 3), dtype=bool))[rows, cols]
        return np.where(known, ~within, rim)


def find_covering(triangles: np.ndarray, silhouette: Silhouette, height: float) -> Covering:
    """Cloth pixels and body spans for ``triangles`` (seen from +Z) on ``silhouette``'s grid."""
    shape = silhouette.mask.shape
    pixels, low, high = _spans(triangles, silhouette)
    rows = pixels // shape[1]
    centre, reach = _body_plane(rows, low, high, shape[0], height)
    touches = (low <= centre[rows] + reach[rows]) & (high >= centre[rows] - reach[rows])
    body_low = np.full(shape[0] * shape[1], np.inf)
    body_high = np.full(shape[0] * shape[1], -np.inf)
    np.minimum.at(body_low, pixels[touches], low[touches])
    np.maximum.at(body_high, pixels[touches], high[touches])
    seen = np.zeros(shape[0] * shape[1], dtype=bool)
    seen[pixels] = True
    cloth = (seen & ~np.isfinite(body_low)).reshape(shape)
    cloth = ndimage.binary_opening(cloth, structure=disk(1.5)) & silhouette.mask
    low_map, high_map = _near(body_low.reshape(shape), body_high.reshape(shape))
    return Covering(silhouette, cloth, low_map, high_map, height)


def _near(low: np.ndarray, high: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Body spans widened to the 3x3 neighbourhood, so a vertex on a pixel edge finds its body."""
    low = ndimage.grey_erosion(low, size=(3, 3), mode="nearest")
    high = ndimage.grey_dilation(high, size=(3, 3), mode="nearest")
    return np.where(np.isfinite(low), low, np.nan), np.where(np.isfinite(high), high, np.nan)


def _body_plane(rows: np.ndarray, low: np.ndarray, high: np.ndarray, count: int, height: float) -> tuple[np.ndarray, np.ndarray]:
    """Per row, the middle of the longest span and how far the slab reaches around it."""
    length = high - low
    longest = np.full(count, -1.0)
    np.maximum.at(longest, rows, length)
    chosen = length >= longest[rows] - 1e-12
    centre = np.full(count, np.nan)
    centre[rows[chosen]] = (low[chosen] + high[chosen]) * 0.5
    filled = np.flatnonzero(np.isfinite(centre))
    if len(filled) == 0:
        return np.zeros(count), np.full(count, height * _MIN_REACH)
    index = np.arange(count)
    centre = ndimage.median_filter(np.interp(index, filled, centre[filled]), size=_ROWS, mode="nearest")
    half = ndimage.median_filter(np.interp(index, filled, longest[filled] * 0.5), size=_ROWS, mode="nearest")
    return centre, np.maximum(half * _SHARE, height * _MIN_REACH)


def _spans(triangles: np.ndarray, silhouette: Silhouette) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(pixel, z_low, z_high)`` of every solid span along the pixel-centre rays."""
    pixels, depth, sign = _crossings(triangles, silhouette)
    if len(pixels) == 0:
        return pixels, depth, depth
    order = np.lexsort((-depth, pixels))
    pixels, depth, sign = pixels[order], depth[order], sign[order]
    first = np.r_[True, pixels[1:] != pixels[:-1]]
    total = np.cumsum(sign)
    winding = total - (total - sign)[first][np.cumsum(first) - 1]
    inside = (winding != 0) & np.r_[pixels[1:] == pixels[:-1], False]
    at = np.flatnonzero(inside)
    return pixels[at], depth[at + 1], depth[at]


def _crossings(triangles: np.ndarray, silhouette: Silhouette) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pixel, depth and facing sign of every triangle crossing a pixel-centre ray along Z."""
    shape = silhouette.mask.shape
    flat = np.empty(triangles.shape[:2] + (2,))
    flat[..., 0] = (triangles[..., 1] - silhouette.origin[1]) / silhouette.pixel - 0.5 + _JITTER[0]
    flat[..., 1] = (triangles[..., 0] - silhouette.origin[0]) / silhouette.pixel - 0.5 + _JITTER[1]
    area = _edge(flat[:, 0], flat[:, 1], flat[:, 2])
    keep = np.abs(area) > 1e-12
    flat, depth, area = flat[keep], triangles[keep, :, 2], area[keep]
    low = np.ceil(flat.min(axis=1)).astype(np.int64)
    span = np.maximum(np.floor(flat.max(axis=1)).astype(np.int64) - low + 1, 0).max(axis=1)
    found = ([], [], [])
    for size in np.unique(span[span > 0]):
        grid = np.stack(np.meshgrid(np.arange(size), np.arange(size), indexing="ij"), axis=-1).reshape(-1, 2)
        chosen = np.flatnonzero(span == size)
        step = max(1, _MAX_SAMPLES // len(grid))
        for start in range(0, len(chosen), step):
            part = chosen[start:start + step]
            for bucket, values in zip(found, _hits(flat[part], depth[part], area[part], low[part, None, :] + grid[None], shape)):
                bucket.append(values)
    if not found[0]:
        return np.zeros(0, dtype=np.int64), np.zeros(0), np.zeros(0)
    return tuple(np.concatenate(bucket) for bucket in found)


def _hits(tri: np.ndarray, depth: np.ndarray, area: np.ndarray, points: np.ndarray, shape: tuple) -> tuple:
    """The candidate pixel centres ``points`` (T, K, 2) that fall inside their triangle."""
    corner = [tri[:, None, index] for index in range(3)]
    weights = [_edge(corner[1], corner[2], points), _edge(corner[2], corner[0], points), _edge(corner[0], corner[1], points)]
    facing = np.sign(area)[:, None]
    inside = (weights[0] * facing > 0) & (weights[1] * facing > 0) & (weights[2] * facing > 0)
    inside &= (points[..., 0] >= 0) & (points[..., 0] < shape[0]) & (points[..., 1] >= 0) & (points[..., 1] < shape[1])
    tri_at, point_at = np.nonzero(inside)
    z = sum(weights[index][tri_at, point_at] * depth[tri_at, index] for index in range(3)) / area[tri_at]
    chosen = points[tri_at, point_at]
    return chosen[:, 0] * shape[1] + chosen[:, 1], z, np.sign(area[tri_at])


def _edge(start: np.ndarray, end: np.ndarray, point: np.ndarray) -> np.ndarray:
    return (end[..., 0] - start[..., 0]) * (point[..., 1] - start[..., 1]) - (end[..., 1] - start[..., 1]) * (point[..., 0] - start[..., 0])
