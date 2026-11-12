"""What the cells of a walk sheet show about the gait, read from their silhouettes (numpy only: no model, no GPU).

``walk_gait`` (``services/character_animation_cycle_checks.py``) compares how wide the lowest 28 % of each figure is. That is flat for a front
or a back walk at every phase (guide: 0.20 to 0.21), and the same for the phases ``p`` and ``p + 1/2`` of a profile one (0.719 and 0.716, 0.643
and 0.645, 0.521 and 0.523, ...), so it cannot see the order of the poses, which leg steps, where the feet land, a cell that turned around or
a cycle that does not close. This module reads four more things. Each reading of a keyed figure is made again on the mannequin of the guide the
poses were drawn over (``walk_guides``: the same camera, the same phases, ``SHIFT`` for the back view), so a sheet is compared with what its
own direction should show and no sign is worked out by hand.

Readings of one figure, all in units of its height and against its torso column (the mean column of its upper half):

* ``front`` and ``back``: how far the legs reach ahead of the torso and behind it (the lowest 28 % of the figure);
* ``foot``: where the lowest 6 % of the figure (the foot on the ground) is, against the torso column;
* ``drop``: how much lower the left half of the legs reaches in the picture than the right half. From the front the leg that steps toward
  the camera is the lower one, so this alternates in sign between the two contact poses (about +0.10 and -0.10 in the guide).

Checks (the ids are new; ``walk_gait`` stays as it was). ``order_fit`` correlates a series of readings with the guide's at every shift of the
cycle and in both directions of time; ``NEAR_SHIFTS`` are the identity and the rest is far.

* ``walk_foot_order`` (``front``, ``back``, ``foot``; profile and three-quarter views): fails when far beats near by more than the limit, or,
  in profile, when near is a weak fit. A cycle drawn in another order, started two or three cells late or played backwards fails.
* ``walk_foot_alternation`` (``drop``; front view): the same for which foot is lower. A shift by half a cycle turns the correlation to its
  opposite, so the two contact poses drawn the wrong way round fail.
* ``walk_loop_seam`` (``seam_ratio``): the silhouette distance from the last cell to the first over the median distance between neighbours.
  Reported, never failing (see below).
* ``walk_facing`` (``flipped_cells``): a cell that is nearer the other cells mirrored than as it is. Profile and three-quarter views only: a
  front or a back figure is the same mirrored.

Calibration. Labels: no sheet on disk carries a trustworthy verdict (``reviewState: approved`` by an agent is automatic), so the real sheets
are the "good" side, as far as the eye on a dozen of them says, and the "bad" side is made from them: a sheet rolled by 1 to 11 cells, played
backwards, shuffled, with two cells swapped, one cell mirrored or its last cell replaced by another. 30 distinct real 12-pose sheets were
read (45 files, every ``*walk*-sheet-*.png`` under ``/mnt/extras/hocuspocus-worktrees``; 17 profile Qwen, 3 front34, 3 back34, 4 front,
3 back, 3 LTX clips kept apart). Measured (CALIBRATION below holds the full numbers):

* order, profile: real near fit 0.46 to 0.67 and far - near at most 0.05; a sheet rolled by 2 or 3 cells (mod 6) has near below 0.28 and far -
  near of at least 0.26; backwards, a median gap of 0.19; shuffled, a median near of 0.18. Rolled by 4, 5 or 6 (mod 6) it passes: half a cell
  of tolerance on each side, as real sheets are +0 or +1. Swapping poses 6 cells apart is invisible (the guide has the same silhouette at p and
  p + 1/2): no silhouette reading sees which leg is the near one.
* order, front34 and back34: only three real sheets of each; the gap of the real ones is -0.22 to 0.15, of a sheet rolled by 2 or 3 cells 0.26
  to 0.92 in all but one of six. Shipped with a failing limit of 0.2 and no limit on the fit.
* alternation, front: real fit 0.45 to 0.75 (4 sheets); rolled by 5 to 8 cells -0.62 to -0.25. Back, front34 and back34: the real fits are
  -0.32 to 0.60 and a roll by half a cycle does not move them out of that band, so those are reported and never fail.
* seam: real ratio 0.06 to 1.24 at the seam (30 sheets), but a step between neighbours alone is up to 1.99 times the median (330 steps, p99
  1.82), so no limit below 2 is safe and a limit of 2 fails nothing real: the one real failure on disk is a clip whose first cell is the
  unkeyed reference picture, 1.85. A last cell replaced by a mid-cycle one is not seen either (median 1.03: silhouettes at different phases
  are as far apart as neighbours are; a seam of the leg readings instead is worse: 16 % above 2.5). Reported as a number, never failing.
* facing: the least mirrored over plain ratio of real sheets is 0.96 (23 sheets); a mirrored cell is below it 86 % of the time.

LTX clips sampled by ``walk_video_method`` start two cells late (best shift 2 mod 6 on the two real keyed clips: fit 0.93 and 0.94 against -0.48 and -0.40; the third is an unkeyed clip), so
``walk_foot_order`` fails them: their first cell is not the contact.
"""
from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Any

import numpy as np
from PIL import Image

from services.walk_guides import LEGS, TURN, guide_image

TORSO = 0.5          # the upper half of a figure gives its torso column
FOOT = 0.06          # the lowest share of a figure is the foot on the ground
GUIDE_SIZE = (224, 288)
CANVAS = 96          # the silhouettes of two cells are compared on a square of this many pixels
READINGS = ("front", "back", "foot", "drop")
# Which readings tell the moments of the step apart in each direction (the others are flat in that view of the guide).
ORDER_READINGS = {"side": ("front", "back", "foot"), "front34": ("front", "back", "foot"), "back34": ("front", "back", "foot")}
ALTERNATION_READINGS = {"front": ("drop",), "back": ("drop",), "front34": ("drop",), "back34": ("drop",)}
SIDED = ("side", "front34", "back34")
# The shifts (cells) a sheet may start at and still be the guide's walk: the real sheets are best fitted by 0 or +1 (a pose is drawn about half
# a cell ahead of the guide), so those two are the identity and anything else is far.
NEAR_SHIFTS = (0, 1)
# ``(least fit of the identity, most the far hypotheses may beat it by)``; no entry for a reading that is only reported.
LIMITS: dict[tuple[str, str], tuple[float | None, float]] = {
    ("order", "side"): (0.3, 0.15), ("order", "front34"): (None, 0.2), ("order", "back34"): (None, 0.2), ("alternation", "front"): (0.25, 0.2)}
SEAM_NATURAL = 2.0   # no real step between neighbours is more than this many median steps (1.99 over 330): a seam above it is reported as open
FACING_RATIO = 0.92  # a cell is turned around when it is this much nearer the other cells mirrored than as it is
CELL_ERROR = 1.2     # a cell is off the guide when its readings are this many standard deviations of the sheet from the guide's


def mask_of(figure: Image.Image | np.ndarray | None, floor: int = 8) -> np.ndarray | None:
    """The silhouette of a keyed figure (an RGBA picture or an alpha array) cropped to its outline, None for an empty one."""
    if figure is None:
        return None
    alpha = np.asarray(figure.getchannel("A")) if isinstance(figure, Image.Image) else np.asarray(figure)
    solid = alpha > floor
    rows, columns = np.nonzero(solid.any(axis=1))[0], np.nonzero(solid.any(axis=0))[0]
    return solid[rows[0]:rows[-1] + 1, columns[0]:columns[-1] + 1] if len(rows) else None


def torso_column(mask: np.ndarray) -> float:
    """The mean column of the upper half of a silhouette: the head and the trunk hold still while the legs and the arms swing."""
    columns = np.nonzero(mask[:max(1, int(mask.shape[0] * TORSO))])[1]
    return float(columns.mean()) if len(columns) else mask.shape[1] / 2


def _bottom(band: np.ndarray, first: int) -> float:
    rows = np.nonzero(band.any(axis=1))[0]
    return float(first + rows[-1] + 1) if len(rows) else 0.0


def readings(mask: np.ndarray) -> dict[str, float]:
    """The four readings of one silhouette (units of its height)."""
    height = float(mask.shape[0])
    centre = torso_column(mask)
    first = int(height * LEGS)
    band = mask[first:]
    columns = np.nonzero(band.any(axis=0))[0]
    reach = ((columns[-1] - centre) / height, (centre - columns[0]) / height) if len(columns) else (0.0, 0.0)
    split = int(round(centre))
    left, right = band[:, :split], band[:, split:]
    drop = (_bottom(left, first) - _bottom(right, first)) / height if left.any() and right.any() else 0.0
    ground = np.nonzero(mask[int(height * (1 - FOOT)):])[1]
    foot = (float(ground.mean()) - centre) / height if len(ground) else 0.0
    return {"front": float(reach[0]), "back": float(reach[1]), "foot": foot, "drop": float(drop)}


def series_of(masks: Sequence[np.ndarray | None]) -> np.ndarray:
    """``(cells, READINGS)``: the readings of every cell, zeros for an empty cell."""
    return np.array([[readings(mask)[name] for name in READINGS] if mask is not None else [0.0] * len(READINGS) for mask in masks])


@lru_cache(maxsize=32)
def guide_series(direction: str, count: int) -> np.ndarray:
    """The readings of the guide's mannequin at the ``count`` phases of a cycle seen from ``direction``."""
    masks = []
    for index in range(count):
        shown = np.asarray(guide_image(direction, index / count, GUIDE_SIZE, "mannequin").convert("L")) < 250
        masks.append(mask_of(np.where(shown, 255, 0).astype(np.uint8)))
    return series_of(masks)


def _z(values: np.ndarray) -> np.ndarray | None:
    spread = float(values.std())
    return (values - values.mean()) / spread if spread > 1e-6 else None


def _correlation(measured: np.ndarray, expected: np.ndarray, columns: Sequence[int]) -> float:
    """The mean correlation of the chosen readings (a flat series on either side counts as no correlation)."""
    found = []
    for column in columns:
        mine, theirs = _z(measured[:, column]), _z(expected[:, column])
        found.append(0.0 if mine is None or theirs is None else float((mine * theirs).mean()))
    return float(np.mean(found)) if found else 0.0


def _signed(shift: int, count: int) -> int:
    return shift - count if shift > count // 2 else shift


def _hypotheses(count: int, period: int) -> list[tuple[int, bool, bool]]:
    """Every ``(shift, backwards, near)``: near is a forward shift within ``NEAR_SHIFTS`` modulo the period of the guide's silhouette."""
    return [(shift, backwards, not backwards and shift % period in NEAR_SHIFTS) for backwards in (False, True) for shift in range(count)]


def order_fit(measured: np.ndarray, expected: np.ndarray, names: Sequence[str], period: int | None = None) -> dict[str, Any]:
    """How well a sheet's readings follow the guide's. ``near`` is the best correlation (1 is the same walk) of the shifts the identity allows,
    ``far`` the best of every other shift and of time run backwards, and ``gap`` is far - near. ``shift`` and ``backwards`` name the best of
    all. ``errors`` is, per cell, how far its readings are from the guide's at the best near shift (standard deviations of the sheet's own),
    ``cells`` the indexes above ``CELL_ERROR`` and ``worst`` all indexes from the worst. ``period`` is how many cells make the guide's
    silhouette repeat (6 in profile, else the whole cycle)."""
    columns = [READINGS.index(name) for name in names]
    count = len(measured)
    scores = {}
    for shift, backwards, near in _hypotheses(count, period or count):
        at = [(shift - k if backwards else shift + k) % count for k in range(count)]
        scores[(shift, backwards, near)] = _correlation(measured, expected[at], columns)
    near = max((key for key in scores if key[2]), key=scores.get)
    best = max(scores, key=lambda key: (scores[key], key == near))
    far = max((score for key, score in scores.items() if not key[2]), default=-1.0)
    errors = cell_errors(measured, expected, columns, near[0])
    return {"near": scores[near], "far": far, "gap": far - scores[near], "shift": _signed(best[0], count), "backwards": best[1],
            "errors": [round(float(value), 4) for value in errors], "cells": [int(i) for i in np.nonzero(errors > CELL_ERROR)[0]],
            "worst": [int(i) for i in np.argsort(-errors, kind="stable")]}


def cell_errors(measured: np.ndarray, expected: np.ndarray, columns: Sequence[int], shift: int = 0) -> np.ndarray:
    """Per cell, the mean over the chosen readings of how far (standard deviations of the sheet's own) it is from the guide's at ``shift``."""
    count = len(measured)
    rolled = expected[[(shift + k) % count for k in range(count)]]
    errors, used = np.zeros(count), 0
    for column in columns:
        mine, theirs = _z(measured[:, column]), _z(rolled[:, column])
        if mine is not None and theirs is not None:
            errors += np.abs(mine - theirs)
            used += 1
    return errors / max(1, used)


def _canvas(mask: np.ndarray, mirror: bool = False) -> np.ndarray:
    """A silhouette on a ``CANVAS`` square: its height fills it, its feet on the bottom row and its torso column in the middle."""
    height = mask.shape[0]
    centre = torso_column(mask)
    if mirror:
        mask, centre = mask[:, ::-1], mask.shape[1] - 1 - centre
    scale = (CANVAS - 1) / height
    picture = Image.fromarray(mask.astype(np.uint8) * 255).resize((max(1, round(mask.shape[1] * scale)), CANVAS), Image.Resampling.BILINEAR)
    page = np.zeros((CANVAS, CANVAS))
    left = int(round(CANVAS / 2 - centre * scale))
    source = np.asarray(picture, dtype=float) / 255.0
    start, stop = max(0, left), min(CANVAS, left + source.shape[1])
    if stop > start:
        page[:, start:stop] = source[:, start - left:stop - left]
    return page


def distance(a: np.ndarray, b: np.ndarray) -> float:
    """The share of the two silhouettes' union that only one of them covers (0 the same, 1 nothing in common)."""
    union = float(np.maximum(a, b).sum())
    return float(np.abs(a - b).sum()) / union if union else 0.0


def _pages(masks: Sequence[np.ndarray | None], mirror: bool = False) -> list[np.ndarray] | None:
    """The silhouettes on their squares, None when there are fewer than three cells or one is empty (nothing to compare)."""
    if len(masks) < 3 or any(mask is None for mask in masks):
        return None
    return [_canvas(mask, mirror) for mask in masks if mask is not None]


def seam_ratio(masks: Sequence[np.ndarray | None]) -> float | None:
    """The distance from the last cell to the first over the median distance of each cell to the next, about 1 for a cycle that closes."""
    pages = _pages(masks)
    if pages is None:
        return None
    median = float(np.median([distance(pages[index], pages[index + 1]) for index in range(len(pages) - 1)]))
    return distance(pages[-1], pages[0]) / median if median > 1e-6 else None


def facing_ratios(masks: Sequence[np.ndarray | None]) -> list[float]:
    """For each cell, its mean distance to the other cells mirrored over its mean distance to them as it is: below 1 it looks the other way."""
    plain, turned = _pages(masks), _pages(masks, mirror=True)
    if plain is None or turned is None:
        return []
    found = []
    for index, (page, mirrored) in enumerate(zip(plain, turned)):
        others = [other for place, other in enumerate(plain) if place != index]
        same = float(np.mean([distance(page, other) for other in others]))
        found.append(float(np.mean([distance(mirrored, other) for other in others])) / same if same > 1e-6 else 1.0)
    return found


def flipped_cells(masks: Sequence[np.ndarray | None]) -> list[int]:
    """The cells that are nearer the other cells mirrored than as they are (by ``FACING_RATIO``): the figure turned around in that cell."""
    return [index for index, ratio in enumerate(facing_ratios(masks)) if ratio < FACING_RATIO]


def check(name: str, ok: bool, value: Any, limit: Any, detail: str, cells: Sequence[int] = ()) -> dict[str, Any]:
    return {"id": name, "ok": bool(ok), "value": value, "limit": limit, "detail": detail, "cells": [int(index) for index in cells]}


def _numbers(reading: dict[str, Any]) -> str:
    where = ", best at shift " + str(reading["shift"]) + (" backwards" if reading["backwards"] else "") if reading["gap"] > 0 else ""
    return f"fit {reading['near']:.2f}, far hypotheses {reading['gap']:+.2f}{where}"


def fit_check(name: str, kind: str, direction: str, reading: dict[str, Any], what: str) -> dict[str, Any]:
    """``walk_foot_order`` or ``walk_foot_alternation``. It fails only where ``LIMITS`` has an entry for that reading in that direction; in the
    others the fit is a number (``limit`` ``"report"``). ``value`` is the fit of the identity."""
    limit = LIMITS.get((kind, direction))
    least, gap = limit if limit else (None, 99.0)
    ok = (least is None or reading["near"] >= least) and reading["gap"] <= gap
    shown: Any = "report" if not limit else least if least is not None else gap
    detail = f"{what} ({_numbers(reading)})" if ok else f"{what} fails: {_numbers(reading)}"
    blamed = reading["cells"] or reading["worst"][:2]  # a fit that fails with no cell far off still blames the two furthest
    return check(name, ok, round(reading["near"], 3), shown, detail, [] if ok else blamed)


def seam_check(ratio: float | None) -> dict[str, Any]:
    """``walk_loop_seam``: a number only. ``ok`` is always true; the detail says when the seam is further than any real step."""
    if ratio is None:
        return check("walk_loop_seam", True, 0.0, "report", "no cycle to close")
    open_loop = ratio > SEAM_NATURAL
    return check("walk_loop_seam", True, round(ratio, 3), "report", "the last cell is further from the first than any step of a real cycle is from the next"
                 if open_loop else "the last cell is as near the first as a cell is to the next", [0] if open_loop else [])


def facing_check(flipped: list[int]) -> dict[str, Any]:
    return check("walk_facing", not flipped, len(flipped), 0, "no cell looks the other way than the rest" if not flipped else
                 f"cell(s) {', '.join(str(index + 1) for index in flipped)} look the other way than the rest", flipped)


def turned(masks: Sequence[np.ndarray | None]) -> list[np.ndarray | None]:
    """The silhouettes mirrored: a sheet that looks left read as the guide (which looks right) is read."""
    return [mask[:, ::-1] if mask is not None else None for mask in masks]


def mask_checks(masks: Sequence[np.ndarray | None], direction: str | None, mirrored: bool = False) -> list[dict[str, Any]]:
    """The checks on the silhouettes of a walk's cells, in the order of the sheet. Only those that read something in this direction
    (the order and the facing need a side; the alternation, a foot that steps toward the viewer); none for a direction the guide lacks.
    ``mirrored``: the sheet looks left (a puppet cut from a drawing that looked left), so its cells are mirrored before they are read."""
    if direction not in TURN or not masks:
        return []
    if mirrored:
        masks = turned(masks)
    measured, expected = series_of(masks), guide_series(direction, len(masks))
    found = []
    if direction in ORDER_READINGS:
        found.append(fit_check("walk_foot_order", "order", direction, order_fit(measured, expected, ORDER_READINGS[direction], 6 if direction == "side" else None),
                               "the legs reach ahead and behind the torso in the order of the guide's walk"))
    if direction in ALTERNATION_READINGS:
        found.append(fit_check("walk_foot_alternation", "alternation", direction, order_fit(measured, expected, ALTERNATION_READINGS[direction]),
                               "the lower foot alternates between the two contact poses as the guide's does"))
    found.append(seam_check(seam_ratio(masks)))
    if direction in SIDED:
        found.append(facing_check(flipped_cells(masks)))
    return found


def blamed_cells(masks: Sequence[np.ndarray | None], direction: str | None) -> list[int]:
    """The cells the failing checks blame (a union, sorted): the poses a remake would redraw."""
    return sorted({index for item in mask_checks(masks, direction) if not item["ok"] for index in item["cells"]})


def cell_scores(masks: Sequence[np.ndarray | None], direction: str | None) -> list[float]:
    """One number per cell, lower is closer to the guide's walk: its readings' distance from the guide's (order and alternation, in
    standard deviations of the sheet's own) and, in a view with a side, how much nearer the other cells it is mirrored. Used to keep the
    best of several drawings of one pose in the context of the others. Zeros when the guide does not know the direction."""
    if direction not in TURN or not masks:
        return [0.0] * len(masks)
    measured, expected = series_of(masks), guide_series(direction, len(masks))
    totals = np.zeros(len(masks))
    for table, period in ((ORDER_READINGS, 6 if direction == "side" else None), (ALTERNATION_READINGS, None)):
        if direction in table:
            totals += np.array(order_fit(measured, expected, table[direction], period)["errors"])
    if direction in SIDED:
        totals += np.array([max(0.0, 1.0 - ratio) * 4 for ratio in facing_ratios(masks)] or [0.0] * len(masks))
    return [round(float(value), 4) for value in totals]


def gait_checks(figures: Sequence[Image.Image | None], direction: str | None, floor: int = 8, mirrored: bool = False) -> list[dict[str, Any]]:
    """``mask_checks`` of the keyed figures (RGBA pictures cropped to their outline, None for an empty cell)."""
    return mask_checks([mask_of(figure, floor) for figure in figures], direction, mirrored)
