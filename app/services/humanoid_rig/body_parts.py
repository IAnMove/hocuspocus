"""Legs, neck and arms on the front silhouette of a T or A pose humanoid.

Every step either finds its part with a clear margin or raises ``NotHumanoid``.
Results are in pixels of the ``Silhouette``; ``landmarks`` turns them into metres.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.robe_legs import robe_regions
from services.humanoid_rig.silhouette import Silhouette, centerline, components, disk, geodesic, run_at, runs

_GAP_SEARCH = 0.10
_MIN_LEG = 0.08
_NECK_DEPTH = 0.15
# A row this many lower-torso widths wide is the T-pose arm line; the neck is above it.
_ARM_SPAN = 2.5
_ARM_CLEAR = 0.05
_MAX_DROP = 72.0
_SHOULDER_INSET = 0.5
_ELBOW_AT = 0.44
_WRIST_AT = 0.76


def connect_pieces(silhouette: Silhouette) -> Silhouette:
    """Bridge the small gaps between separate pieces, as in a box-built robot.

    Only a radius that actually joins pieces is kept, so a loose prop that never
    joins does not make the bridging close the gap between the feet.
    """
    best = _drop_specks(silhouette.mask)
    pieces = _piece_count(best)
    limit = max(2, int(round(silhouette.mask.shape[0] * 0.03)))
    for radius in range(1, limit + 1):
        if pieces <= 1:
            break
        closed = _drop_specks(ndimage.binary_closing(silhouette.mask, structure=disk(radius), border_value=0) | silhouette.mask)
        count = _piece_count(closed)
        if count < pieces:
            best, pieces = closed, count
    return Silhouette(best, silhouette.origin, silhouette.pixel)


def _drop_specks(mask: np.ndarray) -> np.ndarray:
    labels, count = components(mask)
    if count <= 1:
        return mask
    sizes = np.bincount(labels.reshape(-1), minlength=count + 1)
    sizes[0] = 0
    keep = sizes >= max(4.0, float(sizes.max()) * 0.004)
    keep[0] = False
    return keep[labels]


def _piece_count(mask: np.ndarray) -> int:
    return components(mask)[1]


def body_rows(mask: np.ndarray) -> tuple[int, int]:
    filled = np.flatnonzero(mask.any(axis=1))
    return int(filled[0]), int(filled[-1])


def find_legs(mask: np.ndarray) -> dict:
    """Track the background gap between the feet up to the crotch."""
    floor, top, best = leg_gap(mask)
    tall = top - floor + 1
    if best is None:
        raise NotHumanoid("single_leg")
    if best["top"] - floor < tall * _MIN_LEG:
        raise NotHumanoid("legs_too_short")
    return {"floor": floor, "top": top, "crotch_row": best["top"] + 1, "crotch_col": best["col"], "gap": best["gap"],
            "feet_row": best["start"]}


def leg_gap(mask: np.ndarray) -> tuple[int, int, dict | None]:
    """The floor and top rows, and the tallest gap that starts between the feet."""
    floor, top = body_rows(mask)
    tall = top - floor + 1
    best = None
    for row in range(floor, floor + max(2, int(tall * _GAP_SEARCH))):
        for gap in _gaps(mask[row]):
            found = _track_gap(mask, row, gap, top)
            if best is None or found["rows"] > best["rows"]:
                best = found
    return floor, top, best


def _gaps(row: np.ndarray) -> list[tuple[int, int]]:
    found = runs(row)
    return [(found[i][1] + 1, found[i + 1][0] - 1) for i in range(len(found) - 1)]


def _track_gap(mask: np.ndarray, row: int, gap: tuple[int, int], top: int) -> dict:
    current, start = gap, row
    while row + 1 <= top:
        above = [item for item in _gaps(mask[row + 1]) if item[0] <= current[1] and item[1] >= current[0]]
        if not above:
            break
        center = (current[0] + current[1]) * 0.5
        current = min(above, key=lambda item: abs((item[0] + item[1]) * 0.5 - center))
        row += 1
    return {"top": row, "rows": row - start, "col": (current[0] + current[1]) * 0.5, "gap": current, "start": start}


def leg_regions(mask: np.ndarray, legs: dict) -> dict:
    """Both leg components below the crotch, split at the gap. Legs hidden by a robe are straight bands."""
    below = mask.copy()
    below[legs["crotch_row"]:] = False
    labels, _count = components(below)
    floor_rows = slice(legs["floor"], legs["floor"] + 3)
    touching = np.unique(labels[floor_rows][labels[floor_rows] > 0])
    region = np.isin(labels, touching)
    if "robe" in legs:
        return {**robe_regions(mask, legs), "all": region}
    cols = np.arange(mask.shape[1])[None, :]
    return {"left": region & (cols > legs["crotch_col"]), "right": region & (cols < legs["crotch_col"]), "all": region}


def central_widths(mask: np.ndarray, start: int, top: int, col: float) -> tuple[np.ndarray, np.ndarray]:
    """Width and centre of the run under the body axis, row by row upward."""
    widths = np.zeros(top + 1)
    centers = np.full(top + 1, float(col))
    center = float(col)
    for row in range(start, top + 1):
        found = run_at(mask[row], int(round(center)), reach=4)
        if found is None:
            continue
        widths[row] = found[1] - found[0] + 1
        centers[row] = center
        center = center * 0.6 + (found[0] + found[1]) * 0.2
    return widths, centers


def find_neck(mask: np.ndarray, legs: dict) -> dict:
    """The narrowest row between the head and the shoulders."""
    crotch, top = legs["crotch_row"], legs["top"]
    widths, centers = central_widths(mask, crotch, top, legs["crotch_col"])
    smooth = np.convolve(widths, np.ones(3) / 3.0, mode="same")
    span = top - crotch
    arms = _above_arms(widths, crotch, top)
    low, high = max(crotch + int(span * 0.25), arms), top - max(2, int((top - legs["floor"]) * 0.04))
    best_row, best_depth = None, 0.0
    for row in range(low, high):
        above = float(smooth[row:top + 1].max())
        below = float(smooth[crotch + int(span * 0.1):row + 1].max())
        depth = (min(above, below) - float(smooth[row])) / max(min(above, below), 1.0)
        if depth > best_depth:
            best_row, best_depth = row, depth
    found = best_row is not None and best_depth >= _NECK_DEPTH
    row = best_row if found else max(crotch + int(span * 0.72), min(arms, high))
    head_width = float(widths[row:top + 1].max()) if top >= row else float(widths[row])
    return {"row": int(row), "col": float(centers[row]), "width": float(widths[row]), "found": bool(found), "widths": widths,
            "head_width": head_width}


def _above_arms(widths: np.ndarray, crotch: int, top: int) -> int:
    """The first row above a T-pose arm line, or ``crotch`` when there is none (an A pose).

    Long hair can hide the neck notch while a skirt or a belt makes the waist the deepest one; the
    waist was then taken for the neck and the arms for part of the head (``hands_stuck``).
    """
    span = top - crotch
    torso = [float(width) for width in widths[crotch + int(span * 0.1):crotch + max(int(span * 0.35), int(span * 0.1) + 1)] if width > 0]
    if not torso:
        return crotch
    limit = float(np.median(torso)) * _ARM_SPAN
    wide = [row for row in range(crotch + int(span * 0.25), top + 1) if widths[row] > limit]
    if not wide:
        return crotch
    # The lowest wide band only: big ears or a hat brim higher up are part of the head.
    end = wide[0]
    for row in wide[1:]:
        if row - end > 2:
            break
        end = row
    return end + 1


def torso_half(widths: np.ndarray, legs: dict, neck: dict) -> float:
    span = neck["row"] - legs["crotch_row"]
    rows = range(legs["crotch_row"] + int(span * 0.15), legs["crotch_row"] + max(int(span * 0.35), int(span * 0.15) + 1))
    values = [widths[row] * 0.5 for row in rows if widths[row] > 0]
    if not values:
        raise NotHumanoid("degenerate")
    return float(np.median(values))


def find_arms(mask: np.ndarray, legs: dict, neck: dict, half: float) -> dict:
    """Both arms as thin branches off the torso core, with the head and legs set aside."""
    leg_parts = leg_regions(mask, legs)
    upper = mask.copy()
    head = slice(max(0, int(neck["col"] - neck["head_width"] * 0.5) - 2), int(neck["col"] + neck["head_width"] * 0.5) + 3)
    upper[neck["row"]:, head] = False
    upper &= ~leg_parts["all"]
    tall = legs["top"] - legs["floor"] + 1
    center = float(legs["crotch_col"])
    for factor in (0.5, 0.7, 0.9):
        found = _arms_at(upper, leg_parts["all"], half, factor, center, tall)
        if found is not None:
            return found
    raise NotHumanoid("hands_stuck")


def _arms_at(upper, legs_mask, half, factor, center, tall):
    radius = max(1.5, half * factor)
    core = _main_core(ndimage.binary_opening(upper, structure=disk(radius)), upper, center)
    if core is None:
        return None
    limbs = upper & ~ndimage.binary_dilation(core, structure=disk(1.5))
    labels, _count = components(limbs)
    arms = {}
    for side, sign in (("left", 1.0), ("right", -1.0)):
        arm = _side_arm(labels, sign, center, half, tall, ndimage.binary_dilation(core, structure=disk(2.5)))
        if arm is None or _touches(arm, legs_mask):
            return None
        arms[side] = {"mask": arm, "attach": _attachment(arm, core), "core": core}
    return arms


def _attachment(arm: np.ndarray, core: np.ndarray) -> np.ndarray:
    """Arm pixels next to the torso; for a floating arm piece, its inner end."""
    touching = arm & ndimage.binary_dilation(core, structure=disk(2.5))
    if np.any(touching):
        return touching
    gap = ndimage.distance_transform_edt(~core)
    nearest = float(gap[arm].min())
    return arm & (gap <= nearest + 2.0)


def _main_core(opened: np.ndarray, upper: np.ndarray, center: float):
    """The largest opened piece that crosses the body axis."""
    labels, count = components(opened)
    if count == 0:
        return None
    column = int(round(center))
    crossing = np.unique(labels[:, max(0, column - 2):column + 3])
    crossing = crossing[crossing > 0]
    if len(crossing) == 0:
        return None
    sizes = np.bincount(labels.reshape(-1), minlength=count + 1)
    return labels == int(crossing[np.argmax(sizes[crossing])])


def _side_arm(labels: np.ndarray, sign: float, center: float, half: float, tall: int, near_core: np.ndarray):
    """The farthest-reaching branch on one side. A branch joined to the torso wins over a loose
    piece that reaches less than twice as far past the torso, so a prop held at the hand is not
    taken for the arm, while a box-built arm floating beside the torso still beats a small bump."""
    cols = np.arange(labels.shape[1])
    best = {True: (None, half + tall * _ARM_CLEAR), False: (None, half + tall * _ARM_CLEAR)}
    for label in np.unique(labels[labels > 0]):
        part = labels == label
        reach = float((sign * (cols[part.any(axis=0)] - center)).max())
        joined = bool(np.any(part & near_core))
        if reach > best[joined][1]:
            best[joined] = (part, reach)
    (joined_arm, joined_reach), (loose_arm, loose_reach) = best[True], best[False]
    if joined_arm is not None and (loose_arm is None or joined_reach - half >= (loose_reach - half) * 0.5):
        return joined_arm
    return loose_arm


def _touches(arm: np.ndarray, legs_mask: np.ndarray) -> bool:
    return bool(np.any(ndimage.binary_dilation(arm, structure=np.ones((3, 3), dtype=bool)) & legs_mask))


def arm_line(mask: np.ndarray, arm: dict, tall: int) -> dict:
    """Shoulder, elbow, wrist and fingertip pixels along the arm's medial line."""
    distance = geodesic(arm["mask"], arm["attach"])
    line = centerline(arm["mask"], distance, 2.0)
    if len(line) < 4:
        raise NotHumanoid("hands_stuck")
    points = line[:, 1:]
    thickness = ndimage.distance_transform_edt(mask)
    radius = float(np.median(thickness[points[:, 0].astype(int), points[:, 1].astype(int)]))
    anchor, direction = _upper_arm_axis(line, tall)
    joined = np.argwhere(arm["attach"]).mean(axis=0)
    root = anchor + direction * float(np.dot(joined - anchor, direction))
    root = _torso_edge(arm["core"], root, direction, radius * 2.5)
    shoulder = root - direction * radius * _SHOULDER_INSET
    path = np.vstack((shoulder, root, points))
    forearm = _along(path, _WRIST_AT) - _along(path, _ELBOW_AT)
    path = np.vstack((shoulder, root, points[:-1], _far_end(arm["mask"], forearm, points[-1])))
    return {
        "shoulder": shoulder,
        "elbow": _along(path, _ELBOW_AT),
        "wrist": _along(path, _WRIST_AT),
        "tip": path[-1],
        "radius": radius,
        "length": _length(path),
    }


def _far_end(arm: np.ndarray, forearm: np.ndarray, last: np.ndarray) -> np.ndarray:
    """The middle of the hand's outer edge along the forearm. The last iso-distance band of a
    blunt hand is often one corner, which would put the fingertip off the arm's line."""
    if float(np.linalg.norm(forearm)) < 1e-6:
        return last
    pixels = np.argwhere(arm).astype(np.float64)
    along = pixels @ _unit(forearm)
    return pixels[along >= along.max() - 1.5].mean(axis=0)


def _upper_arm_axis(line: np.ndarray, tall: int) -> tuple[np.ndarray, np.ndarray]:
    """A point and outward direction fitted on the upper arm, past the junction with the body."""
    chosen = line[(line[:, 0] >= tall * 0.04) & (line[:, 0] <= tall * 0.18), 1:]
    if len(chosen) < 3:
        chosen = line[: max(3, len(line) // 3), 1:]
    anchor = chosen.mean(axis=0)
    _u, _s, axes = np.linalg.svd(chosen - anchor)
    direction = _unit(axes[0])
    if float(np.dot(line[-1, 1:] - anchor, direction)) < 0.0:
        direction = -direction
    return anchor, direction


def _torso_edge(core: np.ndarray, start: np.ndarray, direction: np.ndarray, reach: float) -> np.ndarray:
    """Walk from the arm's root back along it, at most ``reach`` pixels, until the torso core begins."""
    for step in np.arange(0.0, reach, 0.5):
        point = start - direction * step
        row, col = int(round(point[0])), int(round(point[1]))
        if not (0 <= row < core.shape[0] and 0 <= col < core.shape[1]):
            break
        if core[row, col]:
            return point
    return start


def arm_drop(line: dict, sign: float) -> float:
    """Degrees below horizontal from shoulder to wrist."""
    delta = line["wrist"] - line["shoulder"]
    return float(math.degrees(math.atan2(-delta[0], sign * delta[1])))


def require_arm_angle(drop: float) -> None:
    if drop > _MAX_DROP:
        raise NotHumanoid("hands_stuck")
    if drop < -35.0:
        raise NotHumanoid("arms_raised")


def _unit(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    return vector / length if length > 1e-9 else np.array([0.0, 1.0])


def _length(path: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())


def _along(path: np.ndarray, fraction: float) -> np.ndarray:
    steps = np.linalg.norm(np.diff(path, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(steps)))
    target = cumulative[-1] * fraction
    index = int(np.clip(np.searchsorted(cumulative, target) - 1, 0, len(steps) - 1))
    local = (target - cumulative[index]) / max(steps[index], 1e-9)
    return path[index] + (path[index + 1] - path[index]) * local


def leg_center(region: np.ndarray, row: int) -> float | None:
    """Middle column of one leg's pixels on ``row``."""
    cols = np.flatnonzero(region[row])
    if len(cols) == 0:
        return None
    return float((cols.min() + cols.max()) * 0.5)
