"""Landmarks of a T or A pose humanoid, from horizontal mesh slices.

Thresholds are fractions of the mesh height. A mesh that is not a biped with
arms clear of the torso raises ``NotHumanoid`` instead of guessing a skeleton.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.names import LANDMARK_NAMES

_SLICES = 72
_CLUSTER = 0.012
_LINK = 0.055
_LEG_SPAN = 0.12
_ARM_CLEAR = 0.08
_ASYMMETRY = 0.25
_SIDES = ("left", "right")


def detect_landmarks(positions: np.ndarray, indices: np.ndarray | None = None) -> dict:
    """Return the 14 construction landmarks for a humanoid mesh.

    ``positions`` is (N, 3) in metres, Y up, the character facing +Z.
    ``indices`` is (M, 3). Without indices, every three positions are a triangle.
    """
    triangles = _triangles(positions, indices)
    y_min = float(triangles[:, :, 1].min())
    y_max = float(triangles[:, :, 1].max())
    height = y_max - y_min
    _require_height(height)
    vertices = np.unique(np.round(triangles.reshape(-1, 3), 5), axis=0)
    slices = _slices(triangles, y_min, y_max, height)
    legs = _leg_pair(slices, y_min, height)
    torso_half = _torso_half(slices, legs, height)
    arms = _arm_pair(slices, legs, torso_half, y_min, height)
    points = _assemble(legs, arms, vertices, y_min, y_max, height)
    _require_symmetry(points, height)
    _require_names(points)
    return _payload(points, height, y_min)


def _require_height(height: float) -> None:
    if height < 1e-4:
        raise NotHumanoid("degenerate")


def _require_names(points: dict) -> None:
    missing = [name for name in LANDMARK_NAMES if name not in points]
    if missing:
        raise NotHumanoid("degenerate")


def _payload(points: dict, height: float, y_min: float) -> dict:
    ordered = {name: [float(v) for v in points[name]] for name in LANDMARK_NAMES}
    return {
        "points": ordered,
        "height": float(height),
        "y_min": float(y_min),
        "confidence": 1.0,
        "warnings": [],
    }


def _triangles(positions: np.ndarray, indices: np.ndarray | None) -> np.ndarray:
    cloud = np.asarray(positions, dtype=np.float64)
    _require_cloud(cloud)
    if indices is None:
        return _soup(cloud)
    return _indexed(cloud, indices)


def _require_cloud(cloud: np.ndarray) -> None:
    if cloud.ndim != 2 or cloud.shape[1] != 3 or len(cloud) < 9:
        raise NotHumanoid("degenerate")
    if not np.all(np.isfinite(cloud)):
        raise NotHumanoid("degenerate")


def _soup(cloud: np.ndarray) -> np.ndarray:
    if len(cloud) % 3:
        raise NotHumanoid("degenerate")
    faces = cloud.reshape(-1, 3, 3)
    if len(faces) < 4:
        raise NotHumanoid("degenerate")
    return faces


def _indexed(cloud: np.ndarray, indices: np.ndarray) -> np.ndarray:
    faces = np.asarray(indices, dtype=np.int64)
    if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) < 4:
        raise NotHumanoid("degenerate")
    if int(faces.min()) < 0 or int(faces.max()) >= len(cloud):
        raise NotHumanoid("degenerate")
    return cloud[faces]


def _slices(triangles: np.ndarray, y_min: float, y_max: float, height: float) -> list:
    levels = np.linspace(y_min, y_max, _SLICES + 2)[1:-1]
    tolerance = max(height * _CLUSTER, 1e-3)
    return [(float(level), _blobs_at(triangles, float(level), tolerance, height)) for level in levels]


def _blobs_at(triangles: np.ndarray, level: float, tolerance: float, height: float) -> list:
    blobs = _cluster_segments(_segments_at(triangles, level), tolerance)
    split = []
    for blob in blobs:
        split.extend(_split_trunk(blob, height))
    return split


def _segments_at(triangles: np.ndarray, height: float) -> np.ndarray:
    hits = (
        _edge_hit(triangles[:, 0], triangles[:, 1], height),
        _edge_hit(triangles[:, 1], triangles[:, 2], height),
        _edge_hit(triangles[:, 2], triangles[:, 0], height),
    )
    mask = np.stack([item[0] for item in hits], axis=1)
    coords = np.stack([item[1] for item in hits], axis=1)
    chosen = np.flatnonzero(mask.sum(axis=1) >= 2)
    if len(chosen) == 0:
        return np.zeros((0, 2, 3))
    segments = np.empty((len(chosen), 2, 3), dtype=np.float64)
    for row, index in enumerate(chosen):
        segments[row] = coords[index, mask[index]][:2]
    return segments


def _edge_hit(start: np.ndarray, end: np.ndarray, height: float) -> tuple[np.ndarray, np.ndarray]:
    delta = end[:, 1] - start[:, 1]
    low = np.minimum(start[:, 1], end[:, 1])
    high = np.maximum(start[:, 1], end[:, 1])
    crosses = (low < height) & (high >= height) & (np.abs(delta) > 1e-8)
    factor = np.zeros(len(start))
    factor[crosses] = (height - start[crosses, 1]) / delta[crosses]
    point = start + (end - start) * factor[:, None]
    return crosses, point


def _cluster_segments(segments: np.ndarray, tolerance: float) -> list:
    if len(segments) == 0:
        return []
    parent = np.arange(len(segments))
    ends = segments.reshape(-1, 3)
    owners = np.repeat(np.arange(len(segments)), 2)
    _union_endpoint_grid(parent, ends, owners, tolerance)
    return _segment_blobs(segments, parent)


def _union_endpoint_grid(parent: np.ndarray, ends: np.ndarray, owners: np.ndarray, tolerance: float) -> None:
    grid: dict[tuple[int, int], list[int]] = {}
    coords = np.floor(ends[:, [0, 2]] / tolerance).astype(np.int64)
    for index, key in enumerate(coords):
        grid.setdefault((int(key[0]), int(key[1])), []).append(index)
    tol2 = tolerance * tolerance
    for members in grid.values():
        _union_members(parent, owners, ends, members, tol2)
    _union_adjacent(parent, owners, ends, grid, tol2)


def _union_members(parent, owners, ends, members, tol2) -> None:
    if len(members) > 16:
        _union_all(parent, owners, members)
        return
    for left in range(len(members)):
        for right in range(left + 1, len(members)):
            if _xz2(ends[members[left]], ends[members[right]]) <= tol2:
                _union(parent, owners[members[left]], owners[members[right]])


def _union_all(parent, owners, members) -> None:
    head = int(owners[members[0]])
    for index in members[1:]:
        _union(parent, head, int(owners[index]))


def _union_adjacent(parent, owners, ends, grid, tol2) -> None:
    for (ix, iz), members in grid.items():
        for key in ((ix + 1, iz), (ix, iz + 1), (ix + 1, iz + 1), (ix + 1, iz - 1)):
            other = grid.get(key)
            if other is not None and _any_close(ends, members, other, tol2):
                _union(parent, int(owners[members[0]]), int(owners[other[0]]))


def _any_close(ends, left, right, tol2) -> bool:
    sample_a = _sample_ids(left)
    sample_b = _sample_ids(right)
    for a in sample_a:
        for b in sample_b:
            if _xz2(ends[a], ends[b]) <= tol2:
                return True
    return False


def _sample_ids(members: list[int]) -> list[int]:
    if len(members) <= 12:
        return members
    step = max(len(members) // 12, 1)
    return members[::step]


def _xz2(left: np.ndarray, right: np.ndarray) -> float:
    delta = left[[0, 2]] - right[[0, 2]]
    return float(delta @ delta)


def _find(parent: np.ndarray, index: int) -> int:
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = int(parent[index])
    return index


def _union(parent: np.ndarray, left: int, right: int) -> None:
    a, b = _find(parent, left), _find(parent, right)
    if a != b:
        parent[b] = a


def _segment_blobs(segments: np.ndarray, parent: np.ndarray) -> list:
    groups: dict[int, list[int]] = {}
    for index in range(len(segments)):
        groups.setdefault(_find(parent, index), []).append(index)
    return [_blob(segments[indexes].reshape(-1, 3)) for indexes in groups.values()]


def _blob(points: np.ndarray) -> dict:
    return {
        "centroid": points.mean(axis=0),
        "min": points.min(axis=0),
        "max": points.max(axis=0),
        "points": points,
    }


def _split_trunk(blob: dict, height: float) -> list:
    points = blob["points"]
    span = float(points[:, 0].max() - points[:, 0].min())
    if span < height * 0.34:
        return [blob]
    edges = _trunk_edges(points, height)
    if edges is None:
        return [blob]
    parts = _cut_x(points, edges[0], edges[1])
    if len(parts) < 2:
        return [blob]
    return parts


def _trunk_edges(points: np.ndarray, height: float):
    bin_w = max(height * 0.02, 1e-3)
    x0 = float(points[:, 0].min())
    count = max(int(np.ceil(float(points[:, 0].max() - x0) / bin_w)), 1)
    bins = np.clip(((points[:, 0] - x0) / bin_w).astype(np.int32), 0, count - 1)
    thickness, occupied = _bin_thickness(points, bins, count)
    centers = x0 + (np.arange(count) + 0.5) * bin_w
    return _edges_from_profile(centers, thickness, occupied, height, bin_w)


def _bin_thickness(points: np.ndarray, bins: np.ndarray, count: int):
    thickness = np.zeros(count)
    occupied = np.zeros(count, dtype=bool)
    for index in range(count):
        chosen = points[bins == index]
        if len(chosen) == 0:
            continue
        occupied[index] = True
        thickness[index] = float(chosen[:, 2].max() - chosen[:, 2].min())
    return thickness, occupied


def _edges_from_profile(centers, thickness, occupied, height, bin_w):
    central = np.abs(centers) <= height * 0.20
    if not np.any(central & occupied):
        return None
    peak = float(thickness[central].max())
    if peak < 1e-8:
        return None
    near = np.abs(centers) <= height * 0.24
    thick = occupied & (thickness >= peak * 0.78) & near
    chosen = np.flatnonzero(thick)
    if len(chosen) == 0:
        return None
    left = float(centers[chosen[0]] - bin_w)
    right = float(centers[chosen[-1]] + bin_w)
    outside = (centers < left) | (centers > right)
    if not np.any(outside & occupied):
        return None
    return left, right


def _cut_x(points: np.ndarray, left: float, right: float) -> list:
    masks = (
        points[:, 0] < left,
        (points[:, 0] >= left) & (points[:, 0] <= right),
        points[:, 0] > right,
    )
    return [_blob(points[mask]) for mask in masks if int(mask.sum()) >= 2]


def _link(slices: list, height: float) -> list:
    gap = height * _LINK
    chains: list[dict] = []
    for level, blobs in slices:
        claimed = _attach(chains, blobs, level, gap)
        _start(chains, blobs, claimed, level)
    return [chain for chain in chains if len(chain["samples"]) >= 2]


def _attach(chains, blobs, level, gap) -> set:
    claimed: set[int] = set()
    for chain in chains:
        _attach_one(chain, blobs, claimed, level, gap)
    return claimed


def _attach_one(chain, blobs, claimed, level, gap) -> None:
    if chain["closed"]:
        return
    last = chain["samples"][-1]
    if level - last["y"] > gap:
        chain["closed"] = True
        return
    index = _closest(blobs, claimed, last, gap)
    if index is None:
        return
    claimed.add(index)
    chain["samples"].append(_sample(level, blobs[index]))


def _closest(blobs, claimed, last, gap):
    best_index, best = None, gap
    for index, blob in enumerate(blobs):
        if index in claimed:
            continue
        distance = abs(float(blob["centroid"][0]) - last["x"]) + abs(float(blob["centroid"][2]) - last["z"])
        if distance < best:
            best_index, best = index, distance
    return best_index


def _start(chains, blobs, claimed, level) -> None:
    for index, blob in enumerate(blobs):
        if index in claimed:
            continue
        chains.append({"closed": False, "samples": [_sample(level, blob)]})


def _sample(level: float, blob: dict) -> dict:
    return {
        "y": float(level),
        "x": float(blob["centroid"][0]),
        "z": float(blob["centroid"][2]),
        "min": blob["min"],
        "max": blob["max"],
    }


def _span_y(chain: dict) -> float:
    ys = [sample["y"] for sample in chain["samples"]]
    return max(ys) - min(ys)


def _mean_x(chain: dict) -> float:
    return float(np.mean([sample["x"] for sample in chain["samples"]]))


def _mean_y(chain: dict) -> float:
    return float(np.mean([sample["y"] for sample in chain["samples"]]))


def _is_leg(chain: dict, y_min: float, height: float) -> bool:
    if _span_y(chain) < height * _LEG_SPAN:
        return False
    if _mean_y(chain) > y_min + height * 0.60:
        return False
    lateral = abs(_mean_x(chain))
    if lateral < height * 0.025:
        return False
    if lateral > height * 0.25:
        return False
    return True


def _leg_pair(slices, y_min: float, height: float) -> dict:
    legs = [chain for chain in _link(slices, height) if _is_leg(chain, y_min, height)]
    left = [chain for chain in legs if _mean_x(chain) > 0]
    right = [chain for chain in legs if _mean_x(chain) < 0]
    if not left or not right:
        raise NotHumanoid("single_leg")
    return {"left": max(left, key=_span_y), "right": max(right, key=_span_y)}


def _top_y(chain: dict) -> float:
    sample = max(chain["samples"], key=lambda item: item["y"])
    return float(sample["max"][1])


def _torso_half(slices, legs: dict, height: float) -> float:
    crotch = min(_top_y(legs["left"]), _top_y(legs["right"]))
    widths = _waist_widths(slices, crotch, crotch + height * 0.16, height)
    if not widths:
        return height * 0.12
    return float(np.median(widths))


def _waist_widths(slices, low: float, high: float, height: float) -> list:
    widths = []
    for level, blobs in slices:
        width = _central_width(level, blobs, low, high, height)
        if width is not None:
            widths.append(width)
    return widths


def _central_width(level, blobs, low, high, height):
    if level < low or level > high:
        return None
    central = [blob for blob in blobs if abs(float(blob["centroid"][0])) <= height * 0.08]
    if len(central) != 1:
        return None
    return float(central[0]["max"][0] - central[0]["min"][0]) * 0.5


def _arm_pair(slices, legs, torso_half: float, y_min: float, height: float) -> dict:
    low = min(_top_y(legs["left"]), _top_y(legs["right"])) + height * 0.04
    high = y_min + height * 0.90
    found = {}
    for side, sign in (("left", 1.0), ("right", -1.0)):
        found[side] = _side_arm(slices, low, high, torso_half, height, sign)
        if found[side] is None:
            raise NotHumanoid("hands_stuck")
    return found


def _side_arm(slices, low, high, torso_half, height, sign):
    blobs = _lateral(slices, low, high, torso_half, sign)
    if not blobs:
        return None
    shoulder, hand = _arm_ends(blobs, sign)
    reach = float(sign * hand[0])
    if reach < torso_half + height * _ARM_CLEAR:
        return None
    return {"shoulder": shoulder, "hand": hand, "blobs": blobs}


def _lateral(slices, low, high, torso_half, sign) -> list:
    found = []
    gate = torso_half * 0.82
    for level, blobs in slices:
        if level < low or level > high:
            continue
        for blob in blobs:
            if sign * float(blob["centroid"][0]) > gate:
                found.append((level, blob))
    return found


def _arm_ends(blobs, sign: float):
    if sign > 0:
        inner = min(blobs, key=lambda item: float(item[1]["min"][0]))
        outer = max(blobs, key=lambda item: float(item[1]["max"][0]))
        shoulder = _end_point(inner, "min")
        hand = _end_point(outer, "max")
    else:
        inner = min(blobs, key=lambda item: -float(item[1]["max"][0]))
        outer = max(blobs, key=lambda item: -float(item[1]["min"][0]))
        shoulder = _end_point(inner, "max")
        hand = _end_point(outer, "min")
    return shoulder, hand


def _end_point(item, which: str) -> np.ndarray:
    level, blob = item
    return np.array([float(blob[which][0]), float(level), float(blob["centroid"][2])])


def _assemble(legs, arms, vertices, y_min, y_max, height) -> dict:
    points = {"crown": _crown(vertices, y_max, height)}
    for side in _SIDES:
        hip = _hip_point(vertices, legs[side], height)
        foot = _sole(vertices, _mean_x(legs[side]), y_min, height)
        points[f"{side}_hip"] = hip
        points[f"{side}_foot"] = foot
        points[f"{side}_knee"] = _knee_point(legs[side], hip, foot, height)
        shoulder, hand = _refine_ends(vertices, arms[side]["shoulder"], arms[side]["hand"], height)
        points[f"{side}_shoulder"] = shoulder
        points[f"{side}_hand"] = hand
        points[f"{side}_elbow"] = _elbow_point(arms[side]["blobs"], shoulder, hand, height)
    points["crotch"] = (points["left_hip"] + points["right_hip"]) * 0.5
    _require_finite(points)
    return points


def _require_finite(points: dict) -> None:
    for point in points.values():
        if not np.all(np.isfinite(point)):
            raise NotHumanoid("degenerate")


def _hip_point(vertices: np.ndarray, chain: dict, height: float) -> np.ndarray:
    sample = max(chain["samples"], key=lambda item: item["y"])
    band = _near_column(vertices, float(sample["x"]), float(sample["y"]), height)
    if len(band) == 0:
        return np.array([float(sample["x"]), float(sample["y"]), float(sample["z"])])
    peak = float(band[:, 1].max())
    top = band[band[:, 1] >= peak - height * 0.008]
    return top.mean(axis=0)


def _near_column(vertices, x, y, height) -> np.ndarray:
    column = vertices[np.abs(vertices[:, 0] - x) <= height * 0.07]
    return column[np.abs(column[:, 1] - y) <= height * 0.02]


def _sole(vertices: np.ndarray, leg_x: float, y_min: float, height: float) -> np.ndarray:
    band = vertices[vertices[:, 1] <= y_min + height * 0.012]
    column = band[np.abs(band[:, 0] - leg_x) <= height * 0.08]
    if len(column) == 0:
        return np.array([leg_x, y_min, 0.0])
    mean = column.mean(axis=0)
    mean[1] = y_min
    return mean


def _refine_ends(vertices, shoulder, hand, height):
    direction = hand - shoulder
    length = float(np.linalg.norm(direction))
    if length < 1e-5:
        return shoulder, hand
    axis = direction / length
    delta = vertices - shoulder
    along = delta @ axis
    radial = np.linalg.norm(delta - along[:, None] * axis, axis=1)
    mask = (radial <= height * 0.08) & (along >= -height * 0.02) & (along <= length + height * 0.02)
    if int(mask.sum()) < 4:
        return shoulder, hand
    chosen, along_c = _outside_torso(vertices[mask], along[mask], shoulder, height)
    if len(chosen) < 4:
        return shoulder, hand
    return _cap(chosen, along_c, height), _cap_outer(chosen, along_c, height)


def _outside_torso(vertices, along, shoulder, height):
    if float(shoulder[0]) >= 0:
        keep = vertices[:, 0] >= float(shoulder[0]) - height * 0.015
    else:
        keep = vertices[:, 0] <= float(shoulder[0]) + height * 0.015
    return vertices[keep], along[keep]


def _cap(vertices, along, height) -> np.ndarray:
    limit = float(along.min())
    band = vertices[np.abs(along - limit) <= height * 0.015]
    if len(band) == 0:
        return vertices[np.argmin(along)]
    return band.mean(axis=0)


def _cap_outer(vertices, along, height) -> np.ndarray:
    limit = float(along.max())
    band = vertices[np.abs(along - limit) <= height * 0.015]
    if len(band) == 0:
        return vertices[np.argmax(along)]
    return band.mean(axis=0)


def _crown(vertices: np.ndarray, y_max: float, height: float) -> np.ndarray:
    top = vertices[vertices[:, 1] >= y_max - max(height * 0.012, 1e-4)]
    if len(top) == 0:
        return np.array([0.0, y_max, 0.0])
    mean = top.mean(axis=0)
    mean[1] = y_max
    return mean


def _knee_point(chain: dict, hip: np.ndarray, foot: np.ndarray, height: float) -> np.ndarray:
    values = sorted(float(sample["y"]) for sample in chain["samples"])
    low, high = float(min(hip[1], foot[1])), float(max(hip[1], foot[1]))
    center = _value_gap(values, low, high, height / _SLICES * 1.5)
    if center is None:
        return (hip + foot) * 0.5
    return np.array([float(hip[0]), center, float(hip[2])])


def _elbow_point(blobs, shoulder: np.ndarray, hand: np.ndarray, height: float) -> np.ndarray:
    direction = hand - shoulder
    length = float(np.linalg.norm(direction))
    if length < 1e-5:
        return (shoulder + hand) * 0.5
    axis = direction / length
    spans = [_projection_span(blob, shoulder, axis) for _level, blob in blobs]
    center = _span_gap(_merge_spans(spans, height * 0.012), length)
    if center is None:
        return (shoulder + hand) * 0.5
    return shoulder + axis * center


def _projection_span(blob: dict, origin: np.ndarray, axis: np.ndarray) -> tuple[float, float]:
    projection = (blob["points"] - origin) @ axis
    return float(projection.min()), float(projection.max())


def _merge_spans(spans, join: float) -> list:
    ordered = sorted(spans)
    merged = [[ordered[0][0], ordered[0][1]]]
    for low, high in ordered[1:]:
        if low <= merged[-1][1] + join:
            merged[-1][1] = max(merged[-1][1], high)
            continue
        merged.append([low, high])
    return merged


def _value_gap(values, low: float, high: float, join: float):
    if len(values) < 2:
        return None
    return _span_gap(_merge_spans([(value, value) for value in values], join), high - low, low)


def _span_gap(merged, length: float, origin: float = 0.0):
    if len(merged) < 2:
        return None
    midpoint = origin + length * 0.5
    best, best_distance = None, None
    for left, right in zip(merged, merged[1:]):
        center = (left[1] + right[0]) * 0.5
        if center < origin + length * 0.2 or center > origin + length * 0.8:
            continue
        distance = abs(center - midpoint)
        if best_distance is None or distance < best_distance:
            best, best_distance = center, distance
    return best


def _require_symmetry(points: dict, height: float) -> None:
    limit = height * _ASYMMETRY
    for name in ("hip", "knee", "foot", "shoulder", "elbow", "hand"):
        _pair_ok(points[f"left_{name}"], points[f"right_{name}"], limit)


def _pair_ok(left: np.ndarray, right: np.ndarray, limit: float) -> None:
    if left[0] <= 0 or right[0] >= 0:
        raise NotHumanoid("asymmetry")
    if abs(abs(float(left[0])) - abs(float(right[0]))) > limit:
        raise NotHumanoid("asymmetry")
    if abs(float(left[1]) - float(right[1])) > limit:
        raise NotHumanoid("asymmetry")
