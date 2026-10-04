"""Front silhouette of a mesh as a pixel mask, plus the 2D tools landmarks need.

Rows grow with Y (row 0 is the floor), columns grow with X. One pixel is
``height / resolution`` metres, so every threshold can stay relative to the
body height.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

_MAX_SAMPLES = 1 << 22


class Silhouette:
    """A boolean mask with the transform between pixels and metres."""

    def __init__(self, mask: np.ndarray, origin: tuple[float, float], pixel: float) -> None:
        self.mask = mask
        self.origin = origin
        self.pixel = pixel

    def to_metres(self, row: float, col: float) -> tuple[float, float]:
        """Pixel centre to ``(x, y)``."""
        return self.origin[0] + (col + 0.5) * self.pixel, self.origin[1] + (row + 0.5) * self.pixel

    def col_of(self, x: float) -> int:
        return int(math.floor((x - self.origin[0]) / self.pixel))

    def row_of(self, y: float) -> int:
        return int(math.floor((y - self.origin[1]) / self.pixel))

    def px(self, metres: float) -> float:
        return metres / self.pixel


def front_silhouette(triangles: np.ndarray, height: float, resolution: int = 288) -> Silhouette:
    """Rasterize every triangle seen from +Z onto the XY plane."""
    pixel = height / resolution
    low = triangles[:, :, :2].reshape(-1, 2).min(axis=0) - pixel * 3
    high = triangles[:, :, :2].reshape(-1, 2).max(axis=0) + pixel * 3
    shape = (int(math.ceil((high[1] - low[1]) / pixel)) + 1, int(math.ceil((high[0] - low[0]) / pixel)) + 1)
    flat = (triangles[:, :, :2] - low) / pixel
    mask = np.zeros(shape, dtype=bool)
    _fill_triangles(mask, flat[:, :, ::-1])
    mask = ndimage.binary_closing(mask, structure=np.ones((3, 3), dtype=bool), border_value=0) | mask
    return Silhouette(_fill_small_holes(mask, max(4, int(resolution * resolution * 0.0003))), (float(low[0]), float(low[1])), pixel)


def _fill_triangles(mask: np.ndarray, tri: np.ndarray) -> None:
    """Mark every pixel a triangle covers, by dense barycentric sampling."""
    span = np.ceil((tri.max(axis=1) - tri.min(axis=1)).max(axis=1)).astype(np.int64)
    steps = np.maximum(1, 2 ** np.ceil(np.log2(np.maximum(span * 2, 1))).astype(np.int64))
    for step in np.unique(steps):
        chosen = tri[steps == step]
        weights = _barycentric_grid(int(step))
        for start in range(0, len(chosen), max(1, _MAX_SAMPLES // len(weights))):
            block = chosen[start:start + max(1, _MAX_SAMPLES // len(weights))]
            points = np.einsum("kj,tjd->tkd", weights, block).reshape(-1, 2)
            _mark(mask, points)


def _barycentric_grid(step: int) -> np.ndarray:
    values = np.arange(step + 1) / step
    u, v = np.meshgrid(values, values, indexing="ij")
    keep = (u + v) <= 1.0 + 1e-9
    u, v = u[keep], v[keep]
    return np.stack((1.0 - u - v, u, v), axis=1)


def _mark(mask: np.ndarray, points: np.ndarray) -> None:
    rows = np.clip(np.floor(points[:, 0]).astype(np.int64), 0, mask.shape[0] - 1)
    cols = np.clip(np.floor(points[:, 1]).astype(np.int64), 0, mask.shape[1] - 1)
    mask[rows, cols] = True


def _fill_small_holes(mask: np.ndarray, limit: int) -> np.ndarray:
    labels, count = ndimage.label(~mask)
    if count <= 1:
        return mask
    sizes = np.bincount(labels.reshape(-1), minlength=count + 1)
    border = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
    small = sizes <= limit
    small[border] = False
    small[0] = False
    return mask | small[labels]


def runs(row: np.ndarray) -> list[tuple[int, int]]:
    """Inclusive ``(start, end)`` columns of each foreground run in a row."""
    padded = np.concatenate(([False], row, [False]))
    changes = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(changes[i]), int(changes[i + 1] - 1)) for i in range(0, len(changes), 2)]


def run_at(row: np.ndarray, col: int, reach: int = 3) -> tuple[int, int] | None:
    """The run containing ``col``, or the nearest run within ``reach`` columns."""
    best, best_gap = None, reach + 1
    for start, end in runs(row):
        gap = 0 if start <= col <= end else min(abs(col - start), abs(col - end))
        if gap < best_gap:
            best, best_gap = (start, end), gap
    return best


def disk(radius: float) -> np.ndarray:
    size = int(math.ceil(radius))
    y, x = np.mgrid[-size:size + 1, -size:size + 1]
    return (x * x + y * y) <= radius * radius + 1e-9


def components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    return ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))


def geodesic(region: np.ndarray, sources: np.ndarray) -> np.ndarray:
    """8-connected path length, in pixels, from ``sources`` inside ``region``.

    Pixels outside the region, or not reachable, are ``inf``.
    """
    coords = np.argwhere(region)
    distance = np.full(region.shape, np.inf)
    if len(coords) == 0:
        return distance
    index = np.full(region.shape, -1, dtype=np.int64)
    index[coords[:, 0], coords[:, 1]] = np.arange(len(coords))
    graph = _pixel_graph(region, index, coords)
    starts = index[sources & region]
    if len(starts) == 0:
        return distance
    found = dijkstra(graph, directed=False, indices=starts, min_only=True)
    distance[coords[:, 0], coords[:, 1]] = found
    return distance


def _pixel_graph(region: np.ndarray, index: np.ndarray, coords: np.ndarray):
    rows, cols, weights = [], [], []
    height, width = region.shape
    for dr, dc, weight in ((0, 1, 1.0), (1, 0, 1.0), (1, 1, math.sqrt(2.0)), (1, -1, math.sqrt(2.0))):
        near = coords + np.array([dr, dc])
        inside = (near[:, 0] < height) & (near[:, 1] >= 0) & (near[:, 1] < width)
        inside[inside] = region[near[inside, 0], near[inside, 1]]
        rows.append(index[coords[inside, 0], coords[inside, 1]])
        cols.append(index[near[inside, 0], near[inside, 1]])
        weights.append(np.full(int(inside.sum()), weight))
    count = len(coords)
    return coo_matrix((np.concatenate(weights), (np.concatenate(rows), np.concatenate(cols))), shape=(count, count)).tocsr()


def centerline(region: np.ndarray, distance: np.ndarray, step: float) -> np.ndarray:
    """Centroids of iso-distance bands: a tube's medial line from its source end.

    Returns ``(K, 3)`` rows of ``(band distance, row, col)`` ordered outward.
    """
    finite = region & np.isfinite(distance)
    if not np.any(finite):
        return np.zeros((0, 3))
    coords = np.argwhere(finite)
    values = distance[finite]
    bands = np.floor(values / step).astype(np.int64)
    rows = []
    for band in np.unique(bands):
        chosen = coords[bands == band]
        rows.append((float(band * step + step * 0.5), float(chosen[:, 0].mean()), float(chosen[:, 1].mean())))
    return np.asarray(rows, dtype=np.float64)
