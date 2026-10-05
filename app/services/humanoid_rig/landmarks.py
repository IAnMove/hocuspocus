"""Landmarks of a T or A pose humanoid, from its front silhouette and depth.

The silhouette finds the legs (the gap up to the crotch), the neck (the
narrowest row under the head) and the arms (thin branches off the torso).
Mesh cross-sections then give each joint its depth. A mesh that is not an
upright biped with its arms clear of the body raises ``NotHumanoid``.
Thresholds are fractions of the mesh height, so proportions do not matter.

Cloth that hangs off the body (a cape, coat tails, an open robe) can fill the
gaps under the arms or between the legs. The arms and legs are then looked for
again on the body without that cloth, and legs hidden in a solid robe are
placed from the feet under its hem. ``cloth`` marks the input vertices that
lie on such cloth, for the skin weights.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.body_parts import (
    arm_drop,
    arm_line,
    central_widths,
    connect_pieces,
    find_arms,
    find_legs,
    find_neck,
    leg_center,
    leg_gap,
    leg_regions,
    require_arm_angle,
    torso_half,
)
from services.humanoid_rig.covering import Covering, find_covering
from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.landmark_depth import Depth
from services.humanoid_rig.names import LANDMARK_NAMES
from services.humanoid_rig.robe_legs import place_crotch, robe_legs
from services.humanoid_rig.silhouette import components, front_silhouette, run_at

_ASYMMETRY = 0.25
_SIDES = (("left", 1.0), ("right", -1.0))
# Arms found on the body under the cloth replace the plain ones when their shoulder sits this much
# (a fraction of the body's pixel height) nearer the body axis: the cloth had been taken for torso.
_COVERED_SHIFT = 0.02
# ... and cloth fills at least this share of the square under the stretch of arm it hid.
_CLOTH_BELOW = 0.15
# Hollow cloth this tall (share of the body's pixel height) right over the gap between the feet is a robe.
_ROBE_HOLLOW = 0.1
# Warnings that describe the model without lowering the confidence.
_NOTES = ("facing_back", "on_a_base", "covered_arms", "covered_legs")


def detect_landmarks(positions: np.ndarray, indices: np.ndarray | None = None) -> dict:
    """Return the construction landmarks for a humanoid mesh.

    ``positions`` is (N, 3) in metres, Y up. ``indices`` is (M, 3); without
    indices, every three positions are a triangle. A body facing -Z is turned
    for the analysis and the landmarks are turned back. Besides the landmarks,
    ``cloth`` (N,) marks the positions on cloth that hangs off the body and
    ``robe`` is ``{"hem": y}`` when the legs were placed inside a robe, else None.
    """
    triangles = _triangles(positions, indices)
    y_min = float(triangles[:, :, 1].min())
    height = float(triangles[:, :, 1].max()) - y_min
    _require_height(height)
    _require_upright(triangles, height)
    vertices = np.unique(np.round(triangles.reshape(-1, 3), 5), axis=0)
    facing, pivot = _facing(vertices, y_min, height)
    if facing < 0:
        triangles, vertices = _turn(triangles, pivot), _turn(vertices, pivot)
    found = _analyse(triangles, vertices, y_min, height)
    cloud = np.asarray(positions, dtype=np.float64)
    found["cloth"] = found.pop("covering").vertices(_turn(cloud, pivot) if facing < 0 else cloud)
    if facing < 0:
        found["points"] = {name: _turn(np.asarray(point), pivot) for name, point in found["points"].items()}
        found["head"]["x"] = 2.0 * float(pivot[0]) - found["head"]["x"]
        found["warnings"].append("facing_back")
    return _payload(found, height, y_min, facing)


def _analyse(triangles: np.ndarray, vertices: np.ndarray, y_min: float, height: float) -> dict:
    silhouette = connect_pieces(front_silhouette(triangles, height))
    covering = find_covering(triangles, silhouette, height)
    refused = None
    for legs, leg_mask, notes, refusal in _leg_options(silhouette.mask, covering):
        try:
            found = _upper_body(silhouette, covering, legs, leg_mask, notes, vertices, y_min, height)
        except NotHumanoid as error:
            # Legs guessed inside a robe keep the plain refusal when the rest of the body is not found.
            refused = refusal or error
            continue
        found["covering"] = covering
        return found
    raise refused


def _upper_body(silhouette, covering: Covering, legs: dict, leg_mask: np.ndarray, notes: list, vertices: np.ndarray,
                y_min: float, height: float) -> dict:
    mask = silhouette.mask
    neck = find_neck(mask, legs)
    for _step in range(2 if "robe" in legs else 0):
        legs = place_crotch(legs, neck)
        neck = find_neck(mask, legs)
    half = torso_half(neck["widths"], legs, neck)
    tall = legs["top"] - legs["floor"] + 1
    lines, covered = _arm_lines(mask, covering, legs, neck, half, tall)
    drops = {side: arm_drop(lines[side], sign) for side, sign in _SIDES}
    for drop in drops.values():
        require_arm_angle(drop)
    notes = notes + (["covered_arms"] if covered else [])
    base = _base_top(legs, mask, silhouette, tall)
    depths = _depths(vertices, covering, notes, (silhouette, height, y_min, base))
    points = _assemble(depths, legs, neck, half, lines, leg_regions(leg_mask, legs))
    _require_symmetry(points, height)
    _require_facing_front(points, height)
    head = {"y": float(points["neck"][1]), "x": float(points["neck"][0]), "half": neck["head_width"] * 0.5 * silhouette.pixel}
    warnings = _warnings(neck, drops, points, height) + ([] if base is None else ["on_a_base"]) + notes
    robe = {"hem": silhouette.origin[1] + legs["robe"]["hem"] * silhouette.pixel} if "robe" in legs else None
    return {"points": points, "warnings": warnings, "arm_drop": float(np.mean(list(drops.values()))), "head": head, "base": base,
            "robe": robe}


def _depths(vertices: np.ndarray, covering: Covering, notes: list, frame: tuple) -> dict:
    """Depth for the spine, legs and arms. A limb that cloth hid takes its depth from the body
    without the cloth, so a cape behind the back does not pull the knees back."""
    plain = Depth(vertices, *frame)
    body = vertices[~covering.vertices(vertices)] if {"covered_arms", "covered_legs"} & set(notes) else vertices
    if len(body) == len(vertices) or len(body) < len(vertices) // 2:
        return {"spine": plain, "legs": plain, "arms": plain}
    bare = Depth(body, *frame)
    return {"spine": plain, "legs": bare if "covered_legs" in notes else plain, "arms": bare if "covered_arms" in notes else plain}


def _leg_options(mask: np.ndarray, covering: Covering) -> list[tuple]:
    """Ways to read the legs, best first: ``(legs, mask, notes, refusal)``.

    The gap on the silhouette, unless it ends under hollow cloth (the hem of an open robe); then
    the legs on the body behind a cape or coat; then legs inside a robe, placed from the feet; and
    last the silhouette gap anyway. ``refusal`` replaces the error of an option that was a guess.
    """
    plain, first = None, None
    try:
        plain = find_legs(mask)
    except NotHumanoid as refused:
        first = refused
    if plain is not None and not _hem_over(plain, covering):
        return [(plain, mask, [], None)]
    options = []
    behind = _legs_behind(mask, covering)
    if behind is not None:
        options.append((behind, covering.body(mask), ["covered_legs"], None))
    floor, top, gap = leg_gap(mask)
    try:
        options.append((robe_legs(mask, gap, floor, top), mask, ["legs_hidden"], first))
    except NotHumanoid:
        pass
    if plain is not None:
        options.append((plain, mask, [], None))
    if not options:
        raise first
    return options


def _hem_over(legs: dict, covering: Covering) -> bool:
    """The gap between the feet ends under a tall hollow: the hem of an open robe, not the crotch.

    The little hollow under a short skirt is not enough; the hollow of a robe reaches up to the hips.
    """
    tall = legs["top"] - legs["floor"] + 1
    column = covering.mask[legs["crotch_row"]:, int(round(legs["crotch_col"]))]
    start = np.flatnonzero(column[:max(2, int(tall * 0.03))])
    if len(start) == 0:
        return False
    column = column[start[0]:]
    hollow = int(np.argmin(column)) if not np.all(column) else len(column)
    return hollow >= tall * _ROBE_HOLLOW


def _legs_behind(mask: np.ndarray, covering: Covering) -> dict | None:
    """Legs on the body without the cloth, when a pelvis closes the gap between them."""
    if not np.any(covering.mask):
        return None
    body = covering.body(mask)
    try:
        legs = find_legs(body)
    except NotHumanoid:
        return None
    pelvis = run_at(body[min(legs["crotch_row"], body.shape[0] - 1)], int(round(legs["crotch_col"])), reach=1)
    if pelvis is None or pelvis[0] >= legs["gap"][0] or pelvis[1] <= legs["gap"][1]:
        return None
    return legs


def _arm_lines(mask: np.ndarray, covering: Covering, legs: dict, neck: dict, half: float, tall: int) -> tuple[dict, bool]:
    """Arm lines on the silhouette, or on the body under a cape where the cape had been taken for torso."""
    lines = _lines(mask, legs, neck, half, tall)
    covered = False
    if np.any(covering.mask):
        body = covering.body(mask)
        under = _lines(body, legs, neck, None, tall)
        for side in under:
            if _hidden_by_cloth(lines.get(side), under[side], covering.mask, legs, tall):
                lines[side], covered = under[side], True
    if len(lines) < len(_SIDES):
        raise NotHumanoid("hands_stuck")
    return lines, covered


def _lines(mask: np.ndarray, legs: dict, neck: dict, half: float | None, tall: int) -> dict:
    try:
        if half is None:
            half = torso_half(central_widths(mask, legs["crotch_row"], legs["top"], legs["crotch_col"])[0], legs, neck)
        arms = find_arms(mask, legs, neck, half)
        return {side: arm_line(mask, arms[side], tall) for side, _sign in _SIDES}
    except NotHumanoid:
        return {}


def _hidden_by_cloth(plain: dict | None, under: dict, cloth: np.ndarray, legs: dict, tall: int) -> bool:
    """The arm under the cloth starts nearer the body axis, and cloth hangs below the stretch of arm it hid."""
    if plain is not None and _reach(under, legs) >= _reach(plain, legs) - tall * _COVERED_SHIFT:
        return False
    inner = under["shoulder"]
    outer = plain["shoulder"] if plain is not None else under["elbow"]
    low_col, high_col = sorted((int(round(inner[1])), int(round(outer[1]))))
    length = max(high_col - low_col, 2)
    top = int(round(min(inner[0], outer[0]) - under["radius"]))
    rows, cols = slice(max(0, top - length), max(0, top)), slice(low_col, high_col + 1)
    below = cloth[rows, cols]
    if below.size == 0 or float(below.mean()) < _CLOTH_BELOW:
        return False
    # A few specks of cloth are not a cape: the cloth reaching under the arm must be a piece of some size.
    labels, _count = components(cloth)
    reaching = np.unique(labels[rows, cols])
    return int(np.isin(labels, reaching[reaching > 0]).sum()) >= 2.0 * under["radius"] ** 2


def _reach(line: dict, legs: dict) -> float:
    """Columns from the body axis to the shoulder."""
    return abs(float(line["shoulder"][1]) - float(legs["crotch_col"]))


def _base_top(legs: dict, mask: np.ndarray, silhouette, tall: int) -> float | None:
    """The top of a pedestal: the feet separate well above the lowest point, over something wider than them."""
    if legs["feet_row"] - legs["floor"] <= tall * 0.03:
        return None
    if _row_span(mask[legs["floor"] + 1]) <= _row_span(mask[legs["feet_row"]]) * 1.25:
        return None
    return silhouette.origin[1] + legs["feet_row"] * silhouette.pixel


def _row_span(row: np.ndarray) -> int:
    filled = np.flatnonzero(row)
    return int(filled[-1] - filled[0] + 1) if len(filled) else 0


def _require_facing_front(points: dict, height: float) -> None:
    """A body turned away from the camera puts one shoulder and one hand far behind the other."""
    hands = abs(float(points["left_wrist"][2]) - float(points["right_wrist"][2]))
    shoulders = abs(float(points["left_shoulder"][2]) - float(points["right_shoulder"][2]))
    if hands > height * 0.12 or shoulders > height * 0.06:
        raise NotHumanoid("turned")


def _assemble(depths: dict, legs: dict, neck: dict, half: float, lines: dict, regions: dict) -> dict:
    points = depths["spine"].spine(legs, neck, half)
    if depths["legs"] is not depths["spine"]:
        points["crotch"] = depths["legs"].spine(legs, neck, half)["crotch"]
    for side, _sign in _SIDES:
        points.update(depths["legs"].leg(side, regions[side], legs, points["crotch"], leg_center))
        points.update(depths["arms"].arm(side, lines[side]))
    _require_finite(points)
    return points


def _warnings(neck: dict, drops: dict, points: dict, height: float) -> list[str]:
    warnings = []
    if not neck["found"]:
        warnings.append("neck_not_found")
    if max(drops.values()) > 55.0:
        warnings.append("arms_steep")
    if float(points["crotch"][1] - points["left_ankle"][1]) < height * 0.2:
        warnings.append("short_legs")
    reach = np.linalg.norm(points["left_hand_tip"] - points["left_shoulder"])
    if float(reach) < height * 0.22:
        warnings.append("short_arms")
    return warnings


def _payload(found: dict, height: float, y_min: float, facing: float) -> dict:
    ordered = {name: [float(v) for v in found["points"][name]] for name in LANDMARK_NAMES}
    floor = y_min if found["base"] is None else float(found["base"])
    warnings = list(dict.fromkeys(found["warnings"]))
    drop = float(found["arm_drop"])
    return {
        "points": ordered,
        "height": float(height),
        "y_min": float(floor),
        "base": found["base"],
        "facing": int(facing),
        "arm_drop": round(drop, 2),
        "pose": "t" if drop < 20.0 else "a",
        "confidence": round(max(0.3, 1.0 - 0.15 * len([item for item in warnings if item not in _NOTES])), 2),
        "warnings": warnings,
        "head_region": dict(found["head"]),
        "robe": found["robe"],
        "cloth": found["cloth"],
    }


def _require_height(height: float) -> None:
    if height < 1e-4:
        raise NotHumanoid("degenerate")


def _require_upright(triangles: np.ndarray, height: float) -> None:
    extent = triangles.reshape(-1, 3).max(axis=0) - triangles.reshape(-1, 3).min(axis=0)
    if float(extent[2]) > height * 1.0 or float(extent[0]) > height * 2.4:
        raise NotHumanoid("not_upright")


def _require_finite(points: dict) -> None:
    for point in points.values():
        if not np.all(np.isfinite(point)):
            raise NotHumanoid("degenerate")


def _facing(vertices: np.ndarray, y_min: float, height: float) -> tuple[float, np.ndarray]:
    """-1 when the feet clearly point to -Z. Turned bodies keep their place."""
    low = vertices[:, [0, 2]].min(axis=0)
    high = vertices[:, [0, 2]].max(axis=0)
    pivot = (low + high) * 0.5
    shins = vertices[(vertices[:, 1] > y_min + height * 0.08) & (vertices[:, 1] < y_min + height * 0.16)]
    feet = vertices[vertices[:, 1] < y_min + height * 0.035]
    if len(shins) < 8 or len(feet) < 8:
        return 1.0, pivot
    middle = float(np.median(shins[:, 2]))
    forward = float(np.percentile(feet[:, 2], 98)) - middle
    backward = middle - float(np.percentile(feet[:, 2], 2))
    if backward > forward * 1.35 and backward - forward > height * 0.02:
        return -1.0, pivot
    return 1.0, pivot


def _turn(points: np.ndarray, pivot: np.ndarray) -> np.ndarray:
    turned = np.array(points, dtype=np.float64, copy=True)
    turned[..., 0] = 2.0 * pivot[0] - turned[..., 0]
    turned[..., 2] = 2.0 * pivot[1] - turned[..., 2]
    return turned


def _triangles(positions: np.ndarray, indices: np.ndarray | None) -> np.ndarray:
    cloud = np.asarray(positions, dtype=np.float64)
    if cloud.ndim != 2 or cloud.shape[1] != 3 or len(cloud) < 9 or not np.all(np.isfinite(cloud)):
        raise NotHumanoid("degenerate")
    if indices is None:
        if len(cloud) % 3:
            raise NotHumanoid("degenerate")
        faces = cloud.reshape(-1, 3, 3)
    else:
        index = np.asarray(indices, dtype=np.int64)
        if index.ndim != 2 or index.shape[1] != 3 or not index.size or int(index.min()) < 0 or int(index.max()) >= len(cloud):
            raise NotHumanoid("degenerate")
        faces = cloud[index]
    if len(faces) < 4:
        raise NotHumanoid("degenerate")
    return faces


def _require_symmetry(points: dict, height: float) -> None:
    limit = height * _ASYMMETRY
    center = float(points["crotch"][0])
    for name in ("hip", "knee", "ankle", "shoulder", "elbow", "wrist"):
        left, right = points[f"left_{name}"], points[f"right_{name}"]
        if left[0] <= center or right[0] >= center:
            raise NotHumanoid("asymmetry")
        if abs((float(left[0]) - center) - (center - float(right[0]))) > limit or abs(float(left[1]) - float(right[1])) > limit:
            raise NotHumanoid("asymmetry")
