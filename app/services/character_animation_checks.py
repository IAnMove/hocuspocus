"""Automatic checks on the sprite sheet of an animation, for the job's ``autoApprove`` («Modo un solo disparo»).

``build_sheet`` (``services/character_animations.py``) stands every pose on one ground line in equal cells, so those two facts hold by
construction; what these checks read is the PNG that was written, so a change of ``build_sheet`` that breaks the contract is caught here
too, and what the model got wrong in a pose: one drawn much smaller than the others, a key that left a haze or a whole rectangle, a head
that could not be measured. A sheet is approved by an agent only when every check passes; otherwise it waits for a person with the list
of what failed. Each check is ``{"id", "ok", "value", "limit", "detail"}``.

Tolerances (the sheet's own numbers, not a model's opinion), set against 57 real Qwen sheets made by earlier runs (all passed the
picture checks: figures cover 15 to 55 % of a cell, 1 to 5 % half-transparent, 53 to 75 % of their box, feet within 0.1 % of the line;
walks 0.93 to 0.99 as big at the smallest, legs 0.94 to 0.99, heads 0.85 to 0.96, a bow 0.76):

* ``cell_count``: the poses of the animation, no more, no fewer, in a grid that holds them.
* ``cell_size``: the sheet is exactly ``columns × rows`` cells of the contract's height.
* ``filled_cells``: every figure covers at least 3 % of its cell.
* ``clean_alpha``: at most 25 % of a figure's pixels are half-transparent (a smooth edge is 1 to 5 %; a haze of key residue is
  most of the figure).
* ``silhouette``: a figure fills at most 90 % of its own box (a pose whose key failed is a rectangle, a person never is).
* ``ground_line``: the lowest row of every figure is on the line ``feet`` of the cell, within 2 % of the cell's height.
* ``scale_spread``: the smallest figure is at least 80 % as big as the biggest (80 % by legs, 70 % by head, measured before the sheet
  equalised them; 45 % for a jump or a bow, whose poses are low on purpose).
* ``scale_measure``: a sheet asked to scale by legs or head was scaled by that, not by the height it falls back to when the part could
  not be measured.

The long cycles and the directions (``checks`` of an animation in the catalog) add ``figure_height``, ``repeated_poses`` and
``direction_mirror`` (``services/character_animation_cycle_checks.py``); the animations without ``checks`` are checked as before.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from PIL import Image

from services.character_animation_cycle_checks import cycle_checks
from services.character_animations import MAX_REVIEW_NOTE, catalog

MIN_FILL = 0.03
MAX_HAZE = 0.25
MAX_BOX_FILL = 0.90
MAX_GROUND_DRIFT = 0.02
SPREAD = {"height": 0.80, "base": 0.80, "face": 0.70}
LOW_ON_PURPOSE = {"jump": 0.45, "bow": 0.45}
_OPAQUE = 250


def _check(name: str, ok: bool, value: Any, limit: Any, detail: str) -> dict[str, Any]:
    return {"id": name, "ok": bool(ok), "value": value, "limit": limit, "detail": detail}


def _cells(image: Image.Image, columns: int, rows: int, count: int, cell: dict[str, int]) -> list[np.ndarray]:
    alpha = np.asarray(image.convert("RGBA").getchannel("A"))
    wide, tall = cell["width"], cell["height"]
    return [alpha[row * tall:(row + 1) * tall, column * wide:(column + 1) * wide] for row, column in
            ((index // columns, index % columns) for index in range(min(count, columns * rows)))]


def _figure(cell: np.ndarray, floor: int) -> dict[str, float]:
    """What one cell shows: the share of it the figure covers, how much of the figure is half-transparent, how much of its box it fills,
    and where its box starts and ends (rows)."""
    mask = cell > floor
    area = int(mask.sum())
    if not area:
        return {"cover": 0.0, "haze": 0.0, "box": 0.0, "top": 0.0, "bottom": 0.0, "height": 0.0}
    rows, columns = np.nonzero(mask.any(axis=1))[0], np.nonzero(mask.any(axis=0))[0]
    box = (rows[-1] - rows[0] + 1) * (columns[-1] - columns[0] + 1)
    return {"cover": area / mask.size, "haze": float((mask & (cell < _OPAQUE)).sum()) / area, "box": area / box,
            "top": float(rows[0]), "bottom": float(rows[-1] + 1), "height": float(rows[-1] - rows[0] + 1)}


def _structure(sheet: dict[str, Any], definition: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    cell, columns, rows, count = sheet["cell"], sheet["columns"], sheet["rows"], sheet["count"]
    wanted = len(definition["poses"])
    size_ok = sheet["width"] == cell["width"] * columns and sheet["height"] == cell["height"] * rows and cell["height"] == contract["cellHeight"]
    return [
        _check("cell_count", count == wanted and columns * rows >= count, count, wanted, f"{count} cells for {wanted} poses"),
        _check("cell_size", size_ok, f"{cell['width']}x{cell['height']}", f"{columns}x{rows} cells of height {contract['cellHeight']}",
               f"sheet {sheet['width']}x{sheet['height']}"),
    ]


def _spread(sheet: dict[str, Any], definition: dict[str, Any], figures: list[dict[str, float]]) -> list[dict[str, Any]]:
    mode = definition.get("scaleBy") or sheet.get("requestedScaleBy") or "height"
    limit = LOW_ON_PURPOSE.get(definition["id"], SPREAD.get(mode, SPREAD["height"]))
    sizes = [figure["height"] for figure in figures] if sheet.get("scaleBy") == "height" else list(sheet.get("measures") or [])
    ratio = round(min(sizes) / max(sizes), 3) if sizes and max(sizes) > 0 else 0.0
    measured = (sheet.get("requestedScaleBy") or mode) == sheet.get("scaleBy")
    return [
        _check("scale_spread", ratio >= limit, ratio, limit, "smallest figure over the biggest"),
        _check("scale_measure", measured, sheet.get("scaleBy"), sheet.get("requestedScaleBy") or mode,
               "scaled by what was asked" if measured else "the part to scale by could not be measured in every pose"),
    ]


def sheet_checks(sheet: dict[str, Any], definition: dict[str, Any], siblings: Sequence[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """Every check on a sheet ``build_sheet`` wrote (``sheet``: its reply; ``definition``: the animation it was made from;
    ``siblings``: the other directions of the same kit as ``{"id", "dir", "path"}``, for ``direction_mirror``)."""
    contract = catalog()["sheet"]
    checks = _structure(sheet, definition, contract)
    with Image.open(sheet["path"]) as image:
        figures = [_figure(cell, contract["alphaFloor"]) for cell in _cells(image, sheet["columns"], sheet["rows"], sheet["count"], sheet["cell"])]
        extra = cycle_checks(image, sheet, definition, siblings)
    if not figures:
        return [*checks, _check("filled_cells", False, 0, MIN_FILL, "no cell to read")]
    height = sheet["cell"]["height"]
    line = contract["feet"] * height
    drift = max((abs(figure["bottom"] - line) / height for figure in figures if figure["cover"]), default=1.0)
    checks += [
        _check("filled_cells", min(figure["cover"] for figure in figures) >= MIN_FILL, round(min(figure["cover"] for figure in figures), 3), MIN_FILL,
               "least of a cell a figure covers"),
        _check("clean_alpha", max(figure["haze"] for figure in figures) <= MAX_HAZE, round(max(figure["haze"] for figure in figures), 3), MAX_HAZE,
               "most half-transparent share of a figure"),
        _check("silhouette", max(figure["box"] for figure in figures) <= MAX_BOX_FILL, round(max(figure["box"] for figure in figures), 3), MAX_BOX_FILL,
               "most a figure fills of its own box"),
        _check("ground_line", drift <= MAX_GROUND_DRIFT, round(drift, 4), MAX_GROUND_DRIFT, "most a figure's feet are off the ground line (share of the cell)"),
    ]
    return [*checks, *_spread(sheet, definition, figures), *extra]


def failed(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [check for check in checks if not check["ok"]]


def summary(checks: list[dict[str, Any]]) -> str:
    """One line for the note of a review: what was checked, or what failed."""
    bad = failed(checks)
    if bad:
        text = "Automatic checks failed: " + "; ".join(f"{check['id']} {check['value']} (limit {check['limit']})" for check in bad)
    else:
        text = f"Automatic checks passed ({len(checks)}): " + ", ".join(f"{check['id']} {check['value']}" for check in checks)
    return text[:MAX_REVIEW_NOTE]
