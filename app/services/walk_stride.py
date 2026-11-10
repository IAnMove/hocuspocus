"""How far a walk's feet carry the figure in one cycle, as a share of the figure's height, so a player can move the figure at the speed its
feet need and not slide them over the ground.

The guide's gait (``services/walk_guides.py``) plants a foot at contact and carries it back relative to the body until the opposite foot
lands, so the ground one step covers is the distance between the two ankles at contact (``GUIDE_STEP``: 0.449 of the height) and a cycle
is two steps (``GUIDE_STRIDE``: 0.90). The old players used 0.42 a step. A sheet whose feet are further apart than the guide's, or closer, is
drawn with a longer or a shorter step: from the side that shows in how far apart the feet are on the ground at the widest pose, so the
stride of a profile sheet is the guide's times the ratio of that span to the guide's (``span_ratio``, clamped to ``RATIO``). From any other
direction the feet cannot be read across the picture, so the guide's stride stands.

The stride is stored on the animation (``stride``) when the job joins the sheet. A sheet made before has none, and every player then
keeps the constants it had.
"""
from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

import numpy as np
from PIL import Image

from services.walk_gait_metrics import FOOT, GUIDE_SIZE, mask_of
from services.walk_guides import TURN, guide_image, walk_pose

RATIO = (0.6, 1.5)    # a measured step is never taken to be further than this from the guide's
MIN_CELLS = 4


@lru_cache(maxsize=1)
def guide_step() -> float:
    """The distance between the two ankles at contact, in heights: the ground one step covers."""
    pose = walk_pose(0.0)
    return float(pose["r_ankle"][0] - pose["l_ankle"][0])


def guide_stride() -> float:
    """The ground a cycle (two steps) covers, in heights."""
    return 2 * guide_step()


def ground_span(mask: np.ndarray) -> float:
    """How far apart (units of the figure's height) the feet are on the ground: the width of the lowest ``FOOT`` of the figure."""
    band = mask[int(mask.shape[0] * (1 - FOOT)):]
    columns = np.nonzero(band.any(axis=0))[0]
    return float(columns[-1] - columns[0] + 1) / mask.shape[0] if len(columns) else 0.0


@lru_cache(maxsize=1)
def _guide_span() -> float:
    spans = []
    for index in range(12):
        shown = np.asarray(guide_image("side", index / 12, GUIDE_SIZE, "mannequin").convert("L")) < 250
        mask = mask_of(np.where(shown, 255, 0).astype(np.uint8))
        spans.append(ground_span(mask) if mask is not None else 0.0)
    return max(spans)


def span_ratio(masks: Sequence[np.ndarray | None]) -> float | None:
    """The widest stance of a profile sheet over the guide's, clamped; None with too few figures to say."""
    found = [ground_span(mask) for mask in masks if mask is not None]
    if len(found) < MIN_CELLS or _guide_span() <= 0:
        return None
    return float(np.clip(max(found) / _guide_span(), *RATIO))


def stride_of(figures: Sequence[Image.Image | None], direction: str | None, floor: int = 8) -> float | None:
    """The stride (heights a cycle) of the walk whose cells are ``figures`` (keyed RGBA pictures), seen from ``direction``; None when it
    cannot be said (a direction the guide lacks, an empty sheet)."""
    if direction not in TURN or not figures:
        return None
    if direction != "side":
        return round(guide_stride(), 3)
    ratio = span_ratio([mask_of(figure, floor) for figure in figures])
    return None if ratio is None else round(guide_stride() * ratio, 3)


def stride_of_sheet(sheet: dict, direction: str | None, floor: int = 8) -> float | None:
    """``stride_of`` of the sheet ``build_sheet`` wrote (``sheet``: its reply), read from its cells."""
    from services.character_animation_cycle_checks import figure_of, grid_cells  # imported here: that module imports this package's metrics
    with Image.open(sheet["path"]) as image:
        cells = grid_cells(image, sheet["columns"], sheet["rows"], sheet["count"])
    return stride_of([figure_of(cell, floor) for cell in cells], direction, floor)
