"""The stride of a walk: how much ground its feet carry the figure in a cycle (services/walk_stride.py)."""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from services import walk_stride
from services.walk_guides import guide_image, walk_pose

SIZE = (224, 288)


def _guide_cell(direction: str, index: int) -> Image.Image:
    shown = (np.asarray(guide_image(direction, index / 12, SIZE, "mannequin").convert("L")) < 250) * 255
    cell = Image.new("RGBA", SIZE, (90, 60, 40, 0))
    cell.putalpha(Image.fromarray(shown.astype(np.uint8)))
    return cell


def _cycle(direction: str) -> list[Image.Image]:
    return [_guide_cell(direction, index) for index in range(12)]


def _stretched(figures: list[Image.Image], factor: float) -> list[Image.Image]:
    """The same figures with every row pulled wider by ``factor`` about the torso column: feet further apart (or closer), same height."""
    found = []
    for figure in figures:
        wide = figure.resize((max(1, round(figure.width * factor)), figure.height), Image.Resampling.NEAREST)
        found.append(wide)
    return found


def test_the_guides_step_is_the_distance_between_its_ankles_at_contact_and_a_cycle_is_two_steps():
    pose = walk_pose(0.0)
    assert walk_stride.guide_step() == pytest.approx(pose["r_ankle"][0] - pose["l_ankle"][0])
    assert walk_stride.guide_stride() == pytest.approx(2 * walk_stride.guide_step()) and 0.85 < walk_stride.guide_stride() < 0.95
    # the same ankle distance at the opposite contact, so the foot a step carries back is the step the body takes
    other = walk_pose(0.5)
    assert other["l_ankle"][0] - other["r_ankle"][0] == pytest.approx(walk_stride.guide_step(), abs=0.01)


def test_a_profile_sheet_that_follows_the_guide_has_the_guides_stride_and_wider_feet_a_longer_one():
    figures = _cycle("side")
    assert walk_stride.stride_of(figures, "side") == pytest.approx(walk_stride.guide_stride(), abs=0.02)
    wider = walk_stride.stride_of(_stretched(figures, 1.2), "side")
    narrower = walk_stride.stride_of(_stretched(figures, 0.8), "side")
    assert narrower < walk_stride.stride_of(figures, "side") < wider
    assert wider / walk_stride.stride_of(figures, "side") == pytest.approx(1.2, abs=0.05)


def test_the_ratio_is_clamped_so_a_wild_measure_is_never_a_wild_stride():
    figures = _cycle("side")
    assert walk_stride.stride_of(_stretched(figures, 3.0), "side") == pytest.approx(walk_stride.guide_stride() * walk_stride.RATIO[1], abs=0.01)
    assert walk_stride.stride_of(_stretched(figures, 0.2), "side") == pytest.approx(walk_stride.guide_stride() * walk_stride.RATIO[0], abs=0.01)


def test_from_any_other_direction_the_feet_cannot_be_read_so_the_guides_stride_stands():
    for direction in ("front", "back", "front34", "back34"):
        assert walk_stride.stride_of(_cycle(direction), direction) == pytest.approx(walk_stride.guide_stride(), abs=0.001)


def test_nothing_is_said_of_a_sheet_that_cannot_be_read():
    assert walk_stride.stride_of(_cycle("side"), "up") is None and walk_stride.stride_of(_cycle("side"), None) is None
    assert walk_stride.stride_of([], "side") is None and walk_stride.stride_of(_cycle("side")[:3], "side") is None
    assert walk_stride.stride_of([None] * 12, "side") is None


def test_a_real_sheet_is_read_from_its_cells(tmp_path):
    from services.character_animations import build_sheet

    (tmp_path / "uploads").mkdir()
    names = []
    for index, figure in enumerate(_cycle("side")):
        figure.save(tmp_path / f"c{index}.png")
        names.append(f"c{index}.png")
    sheet = build_sheet(names, uploads_root=str(tmp_path / "uploads"), workspace_root=str(tmp_path), workspace="demo", name="stride", columns=6, output_dir=str(tmp_path))
    assert walk_stride.stride_of_sheet(sheet, "side") == pytest.approx(walk_stride.guide_stride(), abs=0.03)
    assert walk_stride.stride_of_sheet(sheet, "front") == pytest.approx(walk_stride.guide_stride(), abs=0.001)
