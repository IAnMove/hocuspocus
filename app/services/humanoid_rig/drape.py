"""Skin weights for cloth: robes, skirts and coat tails hang from the hips, capes are smoothed.

The surface weights split a long robe into a left and a right half, and its
lower half follows the shins, so a stride tears the robe down the middle and a
bent knee folds it. A skirt surface (cloth below the hips, or every surface
between the hips and the hem of a robe that hides the legs) instead hangs from
the hips: the waist follows the hips alone, lower down the thighs take over,
and the left and right thigh blend across the body axis. Knees and feet do not
pull it. Cloth above the hips, such as a cape over the shoulders, keeps its
weights but has them blurred along the surface, so a raised arm stretches the
cape smoothly instead of creasing it.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.names import BONE_NAMES

_DEFORM = tuple(name for name in BONE_NAMES if not name.endswith("_End"))
_ARMS = tuple(_DEFORM.index(f"{side}{part}") for side in ("Left", "Right") for part in ("Arm", "ForeArm", "Hand"))
_LEGS = [_DEFORM.index(f"{side}{part}") for side in ("Left", "Right") for part in ("UpLeg", "Leg", "Foot", "ToeBase")]
# Share of a skirt that follows the thighs at the knees and below; the rest stays with the hips, so a
# high knee lift swings a robe about half as far as the thigh.
_THIGHS = 0.55
_CLOTH_SMOOTH = 8
_SKIRT_SMOOTH = 4
# The blur crosses the hip line of a robe over this share of the height.
_WAIST = 0.04


def drape(table: np.ndarray, adjacency, cells: np.ndarray, cloth: np.ndarray, skeleton: dict) -> np.ndarray:
    """``table`` (cells x deform bones) with skirt and cloth cells reweighted. ``adjacency`` links touching cells."""
    top = _hip_line(skeleton)
    arms = np.isin(np.argmax(table, axis=1), _ARMS)
    skirt = _skirt_cells(cells, cloth, arms, top, skeleton)
    if not np.any(cloth | skirt):
        return table
    out = table.copy()
    out[skirt] = _skirt_weights(cells[skirt], skeleton)
    seam = skirt
    if skeleton.get("robe"):
        # No leg shows above the hips of a robe: the surface weights the thighs spread up there go to the hips.
        waist = (cells[:, 1] >= top) & ~arms
        out[waist] = _legs_to_hips(out[waist])
        seam = skirt | (waist & (cells[:, 1] < top + float(skeleton["height"]) * _WAIST))
    out = _blur(out, adjacency, cloth & ~skirt, _CLOTH_SMOOTH)
    return _blur(out, adjacency, seam, _SKIRT_SMOOTH)


def _hip_line(skeleton: dict) -> float:
    world = skeleton["world"]
    return (float(world["LeftUpLeg"][1]) + float(world["RightUpLeg"][1])) * 0.5


def _skirt_cells(cells: np.ndarray, cloth: np.ndarray, arms: np.ndarray, top: float, skeleton: dict) -> np.ndarray:
    """Cloth below the hips, and every surface between the hips and the hem of a robe that hides the legs."""
    robe = skeleton.get("robe")
    inside = (cells[:, 1] > float(robe["hem"])) if robe else np.zeros(len(cells), dtype=bool)
    return (cells[:, 1] < top) & ~arms & (cloth | inside)


def _legs_to_hips(weights: np.ndarray) -> np.ndarray:
    out = weights.copy()
    hips = _DEFORM.index("Hips")
    out[:, hips] += out[:, _LEGS].sum(axis=1)
    out[:, _LEGS] = 0.0
    return out


def _skirt_weights(points: np.ndarray, skeleton: dict) -> np.ndarray:
    world = skeleton["world"]
    left, right = np.asarray(world["LeftUpLeg"], dtype=np.float64), np.asarray(world["RightUpLeg"], dtype=np.float64)
    top = (left[1] + right[1]) * 0.5
    knees = (float(world["LeftLeg"][1]) + float(world["RightLeg"][1])) * 0.5
    centre = (left[0] + right[0]) * 0.5
    spread = max(abs(float(left[0] - right[0])) * 0.5, float(skeleton["height"]) * 0.02)
    down = _smoothstep((top - points[:, 1]) / max(top - knees, 1e-6))
    side = _smoothstep(((points[:, 0] - centre) * float(skeleton.get("facing", 1)) / spread + 1.0) * 0.5)
    weights = np.zeros((len(points), len(_DEFORM)))
    weights[:, _DEFORM.index("Hips")] = 1.0 - _THIGHS * down
    weights[:, _DEFORM.index("LeftUpLeg")] = _THIGHS * down * side
    weights[:, _DEFORM.index("RightUpLeg")] = _THIGHS * down * (1.0 - side)
    return weights


def _blur(table: np.ndarray, adjacency, chosen: np.ndarray, passes: int) -> np.ndarray:
    """Average ``chosen`` cells with their neighbours; the others stay as they are."""
    if not np.any(chosen):
        return table
    degree = np.asarray(adjacency.sum(axis=1)).reshape(-1)[:, None] + 1.0
    out = table.copy()
    for _index in range(passes):
        out[chosen] = ((out + adjacency @ out) / degree)[chosen]
    return out


def _smoothstep(value: np.ndarray) -> np.ndarray:
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)
