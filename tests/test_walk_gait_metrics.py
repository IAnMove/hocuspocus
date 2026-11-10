"""The gait readings of a walk sheet (services/walk_gait_metrics.py), on figures made from the guide's own mannequin and on cut and
reordered copies of them. No model and no GPU."""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from services import walk_gait_metrics as metrics
from services.walk_guides import guide_image

SIZE = (224, 288)


def _figure(direction: str, index: int, count: int = 12, mirror: bool = False) -> Image.Image:
    """The mannequin of the guide at one phase as a keyed RGBA figure: solid where the picture is not white."""
    guide = guide_image(direction, index / count, SIZE, "mannequin")
    shown = (np.asarray(guide.convert("L")) < 250) * 255
    figure = Image.new("RGBA", SIZE, (90, 60, 40, 0))
    figure.putalpha(Image.fromarray(shown.astype(np.uint8)))
    return figure.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if mirror else figure


def _cycle(direction: str, shift: int = 0, backwards: bool = False) -> list[Image.Image]:
    base = [_figure(direction, index) for index in range(12)]
    return [base[(shift - index if backwards else shift + index) % 12] for index in range(12)]


def _by_id(checks: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in checks}


@pytest.mark.parametrize("direction", ["side", "front34", "back34", "front", "back"])
def test_the_guides_own_cycle_passes_every_check_it_gets(direction):
    checks = _by_id(metrics.gait_checks(_cycle(direction), direction))
    assert all(item["ok"] for item in checks.values()), checks
    assert "walk_loop_seam" in checks and checks["walk_loop_seam"]["limit"] == "report"
    expected = {"side": {"walk_foot_order", "walk_facing"}, "front34": {"walk_foot_order", "walk_facing"}, "back34": {"walk_foot_order", "walk_facing"},
                "front": {"walk_foot_alternation"}, "back": {"walk_foot_alternation"}}[direction]
    assert expected <= set(checks), "each direction lists the checks that read something there"
    if direction in ("front", "back"):
        assert not {"walk_facing", "walk_foot_order"} & set(checks), "a front or a back figure has no side to read"


def test_the_order_check_fails_a_profile_cycle_started_three_cells_late_and_names_the_cells():
    late = _by_id(metrics.gait_checks(_cycle("side", shift=3), "side"))["walk_foot_order"]
    assert not late["ok"] and late["cells"], late
    assert "fails" in late["detail"] and "far hypotheses" in late["detail"]


def test_the_order_check_fails_a_cycle_played_backwards():
    backwards = _by_id(metrics.gait_checks(_cycle("side", backwards=True), "side"))["walk_foot_order"]
    assert not backwards["ok"] and "backwards" in backwards["detail"]


def test_a_cycle_one_cell_off_is_within_the_half_cell_the_real_sheets_are_off():
    assert _by_id(metrics.gait_checks(_cycle("side", shift=1), "side"))["walk_foot_order"]["ok"]


def test_a_profile_sheet_drawn_half_a_cycle_late_cannot_be_told_from_a_right_one():
    """The silhouette of the phases p and p + 1/2 is the same from the side, so no reading sees which leg is the near one."""
    on_time, late = metrics.series_of([metrics.mask_of(figure) for figure in _cycle("side")]), metrics.series_of([metrics.mask_of(figure) for figure in _cycle("side", shift=6)])
    assert np.abs(on_time[:, :2] - late[:, :2]).max() < 0.02
    assert _by_id(metrics.gait_checks(_cycle("side", shift=6), "side"))["walk_foot_order"]["ok"]


def test_the_alternation_check_fails_the_contact_poses_of_a_front_walk_drawn_the_wrong_way_round():
    swapped = _by_id(metrics.gait_checks(_cycle("front", shift=6), "front"))["walk_foot_alternation"]
    assert not swapped["ok"] and swapped["value"] < 0
    assert _by_id(metrics.gait_checks(_cycle("front"), "front"))["walk_foot_alternation"]["value"] > 0.9


def test_the_alternation_of_the_back_and_three_quarter_views_is_reported_and_never_fails():
    for direction in ("back", "front34", "back34"):
        reading = metrics.fit_check("walk_foot_alternation", "alternation", direction,
                                    {"near": -0.9, "far": 0.9, "gap": 1.8, "shift": 6, "backwards": False, "cells": [0]}, "x")
        assert reading["ok"] and reading["limit"] == "report" and reading["cells"] == []


def test_a_cell_that_looks_the_other_way_is_named_by_the_facing_check():
    figures = _cycle("side")
    figures[4] = figures[4].transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    facing = _by_id(metrics.gait_checks(figures, "side"))["walk_facing"]
    assert not facing["ok"] and facing["cells"] == [4] and "cell(s) 5" in facing["detail"]
    assert _by_id(metrics.gait_checks(_cycle("side"), "side"))["walk_facing"]["ok"]


def test_the_seam_is_a_number_and_a_clean_cycle_closes_as_a_step_does():
    ratio = metrics.seam_ratio([metrics.mask_of(figure) for figure in _cycle("side")])
    assert ratio is not None and 0.5 < ratio < 1.6
    broken = _cycle("side")
    broken[-1] = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    broken[-1].paste(Image.new("RGBA", (40, 40), (10, 10, 10, 255)), (90, 240))
    seam = _by_id(metrics.gait_checks(broken, "side"))["walk_loop_seam"]
    assert seam["ok"] and seam["value"] > 2.0 and seam["cells"] == [0], "a last cell that is not the figure is reported, never failed"


def test_an_empty_cell_or_a_direction_without_a_guide_reads_nothing_and_does_not_raise():
    figures: list[Image.Image | None] = list(_cycle("side"))
    figures[3] = None
    checks = _by_id(metrics.gait_checks(figures, "side"))
    assert checks["walk_loop_seam"]["value"] == 0.0 and checks["walk_facing"]["ok"]
    assert metrics.gait_checks(_cycle("side"), "up") == [] and metrics.gait_checks([], "side") == [] and metrics.gait_checks(_cycle("side"), None) == []


def test_the_readings_of_a_figure_are_in_units_of_its_height():
    mask = np.zeros((100, 60), bool)
    mask[:50, 28:32] = True           # the trunk: its torso column is 29.5
    mask[72:100, 10:20] = True        # one leg far behind
    mask[72:96, 40:50] = True         # one leg ahead, a little shorter
    found = metrics.readings(mask)
    assert found["front"] == pytest.approx((49 - 29.5) / 100) and found["back"] == pytest.approx((29.5 - 10) / 100)
    assert found["drop"] == pytest.approx((100 - 96) / 100), "the picture's left half reaches lower by this much"
    assert metrics.mask_of(None) is None and metrics.mask_of(np.zeros((4, 4), np.uint8)) is None
