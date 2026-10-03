"""Skin weights from distances measured along the surface, at most four influences.

Each bone seeds the surface it clearly owns (the middle of its segment, near
the bone). Distances then grow along the mesh, not through the air, so the
bottom of a big head never follows the arm under it and the inner thigh never
follows the other leg. Pieces without seeds (eyes, buttons, loose boxes) copy
the weights of the nearest seeded surface. Joints blend over a width that
follows the limb thickness.
"""

from __future__ import annotations

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES, BONE_PARENTS

_INFLUENCES = 4
_CELL = 1.0 / 240.0
_SMOOTH = 3
_DEFORM = tuple(name for name in BONE_NAMES if not name.endswith("_End"))
_SEED_SPAN = {"Hand": (0.1, 1.0), "Head": (0.15, 1.0), "ToeBase": (0.0, 1.0), "Foot": (0.0, 1.0), "Hips": (0.0, 0.7)}


def compute_weights(vertices: np.ndarray, indices: np.ndarray | None, skeleton: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(joints, weights)`` with shapes (N, 4). Weights sum to 1."""
    points = np.asarray(vertices, dtype=np.float64)
    height = float(skeleton["height"])
    cells, owner = _cluster(points, height * _CELL, float(skeleton["world"]["Hips"][0]))
    graph = _graph(cells, owner, indices, len(points))
    segments = _segments(skeleton)
    capsule, along = _capsules(cells, segments)
    head = _head_region(cells, skeleton)
    seeds = _seeds(capsule, along, head)
    table = _table(graph, seeds, capsule, height, cells)
    base = _base_region(cells, skeleton)
    table = _only(_head_mask(_side_mask(table, cells, skeleton), head), base, "Hips")
    table = _only(_head_mask(_side_mask(_smooth(table, graph), cells, skeleton), head), base, "Hips")
    return _top(table[owner])


def dominant_distance(vertices: np.ndarray, joints: np.ndarray, weights: np.ndarray, skeleton: dict) -> np.ndarray:
    """Distance from each vertex to the segment of its strongest bone."""
    capsule, _along = _capsules(np.asarray(vertices, dtype=np.float64), _segments(skeleton))
    dominant = joints[np.arange(len(joints)), np.argmax(weights, axis=1)]
    columns = np.array([_DEFORM.index(BONE_NAMES[index]) if BONE_NAMES[index] in _DEFORM else 0 for index in range(len(BONE_NAMES))])
    return capsule[np.arange(len(capsule)), columns[dominant]]


def _cluster(points: np.ndarray, cell: float, center_x: float) -> tuple[np.ndarray, np.ndarray]:
    """Weld vertices on a grid centred on the body axis, so mirrored vertices weld alike."""
    centred = points - np.array([center_x, 0.0, 0.0])
    keys = np.round(centred / cell).astype(np.int64)
    _unique, owner = np.unique(keys, axis=0, return_inverse=True)
    owner = owner.reshape(-1)
    counts = np.bincount(owner).astype(np.float64)
    cells = np.zeros((len(counts), 3))
    np.add.at(cells, owner, points)
    return cells / counts[:, None], owner


def _graph(cells: np.ndarray, owner: np.ndarray, indices: np.ndarray | None, count: int):
    faces = np.arange(count, dtype=np.int64).reshape(-1, 3) if indices is None else np.asarray(indices, dtype=np.int64)
    welded = owner[faces]
    pairs = np.concatenate((welded[:, [0, 1]], welded[:, [1, 2]], welded[:, [2, 0]]), axis=0)
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    pairs = np.unique(np.sort(pairs, axis=1), axis=0)
    length = np.linalg.norm(cells[pairs[:, 0]] - cells[pairs[:, 1]], axis=1) + 1e-9
    size = len(cells)
    return coo_matrix((length, (pairs[:, 0], pairs[:, 1])), shape=(size, size)).tocsr()


def _segments(skeleton: dict) -> list[tuple[np.ndarray, np.ndarray]]:
    world = skeleton["world"]
    child = {}
    for name, parent in BONE_PARENTS:
        if parent is not None and parent not in child:
            child[parent] = name
    ends = dict(skeleton.get("tips") or {})
    ends["Hips"] = world["Spine"]
    found = []
    for name in _DEFORM:
        end = ends.get(name, world[child[name]] if name in child else world[name])
        found.append((np.asarray(world[name], dtype=np.float64), np.asarray(end, dtype=np.float64)))
    return found


def _capsules(points: np.ndarray, segments: list) -> tuple[np.ndarray, np.ndarray]:
    distance = np.zeros((len(points), len(segments)))
    along = np.zeros((len(points), len(segments)))
    for column, (start, end) in enumerate(segments):
        segment = end - start
        length_sq = max(float(segment @ segment), 1e-12)
        factor = ((points - start) @ segment) / length_sq
        clipped = np.clip(factor, 0.0, 1.0)
        distance[:, column] = np.linalg.norm(points - (start + clipped[:, None] * segment), axis=1)
        along[:, column] = factor
    return distance, along


def _head_region(cells: np.ndarray, skeleton: dict) -> np.ndarray:
    """Everything above the neck notch and within the head's width is head."""
    region = skeleton.get("head_region")
    if not region:
        return np.zeros(len(cells), dtype=bool)
    return (cells[:, 1] > float(region["y"])) & (np.abs(cells[:, 0] - float(region["x"])) <= float(region["half"]) * 1.05)


def _seeds(capsule: np.ndarray, along: np.ndarray, head: np.ndarray) -> list[np.ndarray]:
    nearest = np.argmin(capsule, axis=1)
    seeds = []
    for column, name in enumerate(_DEFORM):
        low, high = _span(name)
        own = (nearest == column) & (along[:, column] >= low) & (along[:, column] <= high)
        own = (own | head) if name == "Head" else (own & ~head)
        if np.any(own):
            radius = float(np.median(capsule[own, column]))
            own &= capsule[:, column] <= radius * 1.6 + 1e-9
        if not np.any(own):
            own = np.zeros(len(capsule), dtype=bool)
            own[int(np.argmin(capsule[:, column] + np.abs(along[:, column] - 0.5) * 1e-3))] = True
        seeds.append(np.flatnonzero(own))
    return seeds


def _span(name: str) -> tuple[float, float]:
    for suffix, span in _SEED_SPAN.items():
        if name.endswith(suffix):
            return span
    return (0.15, 0.85)


def _table(graph, seeds: list, capsule: np.ndarray, height: float, cells: np.ndarray) -> np.ndarray:
    limit = height * 0.6
    geodesic = np.full(capsule.shape, np.inf)
    for column, chosen in enumerate(seeds):
        geodesic[:, column] = dijkstra(graph, directed=False, indices=chosen, min_only=True, limit=limit)
    reached = np.isfinite(geodesic).any(axis=1)
    radius = np.array([float(np.median(capsule[chosen, column])) for column, chosen in enumerate(seeds)])
    table = _blend(geodesic, radius, height)
    _borrow(table, reached, cells, capsule)
    return table


def _blend(geodesic: np.ndarray, radius: np.ndarray, height: float) -> np.ndarray:
    nearest = np.min(geodesic, axis=1, keepdims=True)
    owner = np.argmin(geodesic, axis=1)
    width = np.maximum(np.maximum(radius[owner][:, None], radius[None, :]) * 0.9, height * 0.012)
    excess = np.where(np.isfinite(geodesic), (geodesic - np.where(np.isfinite(nearest), nearest, 0.0)) / width, np.inf)
    value = np.clip(1.0 - excess, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def _borrow(table: np.ndarray, reached: np.ndarray, cells: np.ndarray, capsule: np.ndarray) -> None:
    """Unseeded pieces copy the nearest seeded surface, else their nearest bone."""
    missing = np.flatnonzero(~reached)
    if len(missing) == 0:
        return
    if np.any(reached):
        donors = np.flatnonzero(reached)
        _distance, nearest = cKDTree(cells[donors]).query(cells[missing])
        table[missing] = table[donors[nearest]]
        return
    table[missing, np.argmin(capsule[missing], axis=1)] = 1.0


def _side_mask(table: np.ndarray, cells: np.ndarray, skeleton: dict) -> np.ndarray:
    """No weight on the far side of the body for a limb, whatever the surface did."""
    facing = float(skeleton.get("facing", 1))
    center = float(skeleton["world"]["Hips"][0])
    side = (cells[:, 0] - center) * facing
    band = float(skeleton["height"]) * 0.02
    out = table.copy()
    for name in _DEFORM:
        if name.startswith("Left") and name != "LeftShoulder":
            out[side < -band, _DEFORM.index(name)] = 0.0
        if name.startswith("Right") and name != "RightShoulder":
            out[side > band, _DEFORM.index(name)] = 0.0
    empty = out.sum(axis=1) <= 0
    out[empty] = table[empty]
    return out


def _base_region(cells: np.ndarray, skeleton: dict) -> np.ndarray:
    """A pedestal under the feet rides with the hips instead of stretching with a foot."""
    base = skeleton.get("base")
    if base is None:
        return np.zeros(len(cells), dtype=bool)
    return cells[:, 1] < float(base) - float(skeleton["height"]) * 0.005


def _only(table: np.ndarray, region: np.ndarray, bone: str) -> np.ndarray:
    if not np.any(region):
        return table
    out = table.copy()
    out[region] = 0.0
    out[region, _DEFORM.index(bone)] = 1.0
    return out


def _head_mask(table: np.ndarray, head: np.ndarray) -> np.ndarray:
    """Inside the head region only the head and neck may pull."""
    if not np.any(head):
        return table
    out = table.copy()
    keep = [_DEFORM.index("Head"), _DEFORM.index("Neck")]
    others = np.ones(len(_DEFORM), dtype=bool)
    others[keep] = False
    out[np.ix_(head, others)] = 0.0
    empty = out.sum(axis=1) <= 0
    out[empty & head, _DEFORM.index("Head")] = 1.0
    return out


def _smooth(table: np.ndarray, graph) -> np.ndarray:
    adjacency = graph.copy()
    adjacency.data[:] = 1.0
    adjacency = adjacency + adjacency.T
    degree = np.asarray(adjacency.sum(axis=1)).reshape(-1)
    smoothed = table / np.maximum(table.sum(axis=1, keepdims=True), 1e-12)
    for _index in range(_SMOOTH):
        smoothed = (smoothed + adjacency @ smoothed) / (degree[:, None] + 1.0)
    return smoothed


def _top(table: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(-table, axis=1, kind="stable")[:, :_INFLUENCES]
    picked = np.take_along_axis(table, order, axis=1)
    picked = np.where(picked < picked[:, :1] * 0.02, 0.0, picked)
    total = picked.sum(axis=1, keepdims=True)
    weights = picked / np.where(total > 0, total, 1.0)
    columns = np.array([BONE_BY_NAME[name] for name in _DEFORM], dtype=np.uint16)
    return columns[order], weights
