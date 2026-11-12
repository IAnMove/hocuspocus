"""Legs hidden by a long robe or skirt, placed from the feet that show under the hem.

The front silhouette shows two feet with a short gap between them, and above
the gap one run, the robe, at least as wide as both feet and no wider higher up
(a body that bulges out above its feet, like a penguin, is not a robe). The
legs are then straight lines from under the hips to the middle of each foot,
and the crotch is placed from the neck height with adult proportions. Without
two feet under a hanging hem the legs cannot be found and the mesh is refused.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.silhouette import run_at, runs

# Crotch height over neck height, both above the floor (an adult is about 0.47 / 0.84).
_CROTCH_SHARE = 0.56
# Feet show at least this share of the height under the hem.
_FEET = 0.02
# The hem covers at least this share of the width across both feet.
_COVER = 0.85
# The robe above the hem may not grow wider than this over the legs.
_BULGE = 1.1
_SHIN = 0.3
# The hem itself is the widest of its first rows (a hem often rolls out over a few rows).
_HEM = 0.04
# The hidden hip joints sit this share of the half-width of the robe at the crotch from the body axis.
_HIP_SPREAD = 0.5


def robe_legs(mask: np.ndarray, gap: dict | None, floor: int, top: int) -> dict:
    """Legs for a robe whose hem closes the gap between the feet at ``gap``. Raises ``NotHumanoid``."""
    tall = top - floor + 1
    if gap is None or gap["rows"] < max(2, tall * _FEET):
        raise NotHumanoid("single_leg")
    hem = gap["top"] + 1
    col = gap["col"]
    feet = _feet(mask[gap["start"]], gap["gap"])
    if feet is None or not _hangs(mask, feet, hem, tall, col):
        raise NotHumanoid("legs_too_short")
    return {"floor": floor, "top": top, "crotch_row": hem, "crotch_col": float(col), "gap": gap["gap"], "feet_row": gap["start"],
            "robe": {"hem": int(hem), "feet": feet}}


def _feet(row: np.ndarray, gap: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """The runs on each side of the gap, right foot first (lower columns)."""
    found = runs(row)
    right = [item for item in found if item[1] < gap[0]]
    left = [item for item in found if item[0] > gap[1]]
    if not right or not left:
        return None
    return right[-1], left[0]


def _hangs(mask: np.ndarray, feet: tuple, hem: int, tall: int, col: float) -> bool:
    """The hem spans both feet and the robe does not bulge out above it, over the legs."""
    widths = []
    for row in range(hem + 1, min(hem + int(tall * _SHIN), mask.shape[0] - 1) + 1):
        found = run_at(mask[row], int(round(col)), reach=2)
        if found is None:
            return False
        widths.append(found[1] - found[0] + 1)
    flare = max(widths[:max(1, int(tall * _HEM))], default=0)
    if flare < (feet[1][1] - feet[0][0] + 1) * _COVER:
        return False
    return max(widths, default=0) <= flare * _BULGE


def place_crotch(legs: dict, neck: dict) -> dict:
    """Put the hidden crotch at adult proportions below the neck, above the hem."""
    placed = dict(legs)
    floor = legs["floor"]
    row = floor + int(round((neck["row"] - floor) * _CROTCH_SHARE))
    placed["crotch_row"] = int(max(row, legs["robe"]["hem"] + 2))
    return placed


def robe_regions(mask: np.ndarray, legs: dict) -> dict:
    """A straight band per leg, from under the hip to the middle of its foot."""
    feet = legs["robe"]["feet"]
    crotch, floor, col = legs["crotch_row"], legs["floor"], legs["crotch_col"]
    span = run_at(mask[crotch], int(round(col)), reach=3) or (int(col) - 2, int(col) + 2)
    spread = max(1.0, min(span[1] - col, col - span[0]) * _HIP_SPREAD)
    half = max(2.0, max(feet[0][1] - feet[0][0], feet[1][1] - feet[1][0]) * 0.5)
    rows = np.arange(mask.shape[0])[:, None]
    cols = np.arange(mask.shape[1])[None, :]
    share = np.clip((rows - floor) / max(crotch - floor, 1), 0.0, 1.0)
    inside = (rows >= floor) & (rows < crotch)
    bands = {}
    for side, foot, sign in (("left", feet[1], 1.0), ("right", feet[0], -1.0)):
        centre = (foot[0] + foot[1]) * 0.5 * (1.0 - share) + (col + sign * spread) * share
        bands[side] = inside & (np.abs(cols - centre) <= half)
    return bands
