"""Checks that only the long cycles and the directions ask for: an animation of the catalog lists them in its ``checks``.

They read the PNG ``build_sheet`` wrote and never judge who the character is (a person does that when they approve the sheet). Each one
is ``{"id", "ok", "value", "limit", "detail"}`` like the checks of ``services/character_animation_checks.py``, which runs them. The
tolerances are ``sheet.checks`` of ``app/shared/character_animations.json``.

* ``figure_height`` (``"height"``): the twelve poses of a walk are one figure, so each is as tall as the cycle's median, within 3 %
  (a pose drawn a tenth smaller makes the walk pulse). The feet need no check of their own here: ``ground_line`` already reads that
  every figure stands on the line ``feet`` of its cell within 2 % of the cell.
* ``repeated_poses`` (``"repeats"``): the same drawing (a hash of the figure) fills at most two cells in a row; three or more is a
  walk that stops.
* ``direction_mirror`` (``"mirror"``): a sheet that is the same drawing as another direction of the same kit, or its mirror, is not a
  new direction (the model ignored the view). The mirror is what the engine renders for the other side, so a duplicate would show
  the same walk twice. A sheet that cannot be read is skipped, not failed.
* ``walk_gait`` (``"gait"``): each pose of a walk has the legs as wide as the walk of ``services/walk_guides.py`` has them at that moment
  of the step, seen from the sheet's direction (``leg_spread`` against ``expected_spread``), after one scale for the whole sheet (a
  character in a long coat or with a short step is not wrong). A cell far off is a pose drawn at the wrong moment of the step or from
  the wrong side: a back view that turned three-quarter has the stride of a profile.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from services.character_animation_directions import contract_of
from services.character_animations import catalog
from services.character_kit_face_cleanup import CharacterKitFaceCleanupError, resolve_character_kit_image
from services.walk_guides import TURN, expected_spread, leg_spread

HASH_SIDE = 16


def check(name: str, ok: bool, value: Any, limit: Any, detail: str) -> dict[str, Any]:
    return {"id": name, "ok": bool(ok), "value": value, "limit": limit, "detail": detail}


def grid_cells(image: Image.Image, columns: int, rows: int, count: int) -> list[Image.Image]:
    """The cells of a sheet in reading order (equal cells: the sheet's size over its grid)."""
    rgba = image.convert("RGBA")
    wide, tall = rgba.width // max(1, columns), rgba.height // max(1, rows)
    return [rgba.crop((column * wide, row * tall, (column + 1) * wide, (row + 1) * tall))
            for row, column in ((index // columns, index % columns) for index in range(min(count, columns * rows)))]


def figure_of(cell: Image.Image, floor: int) -> Image.Image | None:
    """The figure of a cell cropped to its outline, None for an empty cell."""
    box = cell.getchannel("A").point(lambda value: 255 if value > floor else 0).getbbox()
    return cell.crop(box) if box else None


def figure_hash(figure: Image.Image, *, mirror: bool = False) -> int:
    """An average hash of a cropped figure on white: 256 bits of where it is darker than its own mean."""
    shown = ImageOps.mirror(figure) if mirror else figure
    flat = Image.new("RGB", shown.size, (255, 255, 255))
    flat.paste(shown, mask=shown.getchannel("A"))
    small = np.asarray(flat.convert("L").resize((HASH_SIDE, HASH_SIDE), Image.Resampling.BOX), dtype=np.float64)
    return int("".join("1" if bit else "0" for bit in (small > small.mean()).ravel()), 2)


def _figures(cells: list[Image.Image], floor: int) -> list[Image.Image | None]:
    return [figure_of(cell, floor) for cell in cells]


def height_check(figures: list[Image.Image | None], limit: float) -> dict[str, Any]:
    heights = [figure.height for figure in figures if figure is not None]
    median = float(np.median(heights)) if heights else 0.0
    spread = max((abs(height - median) / median for height in heights), default=1.0) if median else 1.0
    return check("figure_height", spread <= limit and len(heights) == len(figures), round(spread, 4), limit,
                 "most a figure's height is off the median of the cycle (share of it)")


def _longest_run(hashes: list[int | None], bits: int) -> tuple[int, int]:
    """The longest run of cells showing the same drawing, and where it starts."""
    best, best_at, run, at = 1, 0, 1, 0
    for index in range(1, len(hashes)):
        same = hashes[index] is not None and hashes[index - 1] is not None and (hashes[index] ^ hashes[index - 1]).bit_count() <= bits
        run, at = (run + 1, at) if same else (1, index)
        if run > best:
            best, best_at = run, at
    return best, best_at


def repeats_check(figures: list[Image.Image | None], limit: int, bits: int) -> dict[str, Any]:
    run, start = _longest_run([figure_hash(figure) if figure is not None else None for figure in figures], bits)
    return check("repeated_poses", run <= limit, run, limit,
                 f"{run} cells in a row show the same drawing (from cell {start + 1})" if run > 1 else "no drawing fills two cells in a row")


def _sibling_figures(sibling: dict[str, Any], own: dict[str, Any], floor: int) -> list[Image.Image | None]:
    with Image.open(sibling["path"]) as image:
        columns = int(sibling.get("columns") or own["columns"])
        rows = int(sibling.get("rows") or own["rows"])
        return _figures(grid_cells(image, columns, rows, int(sibling.get("count") or own["count"])), floor)


def _share(mine: list[int | None], theirs: list[int | None], bits: int) -> float:
    pairs = [(a, b) for a, b in zip(mine, theirs) if a is not None and b is not None]
    return sum((a ^ b).bit_count() <= bits for a, b in pairs) / len(pairs) if pairs else 0.0


def _duplicate_of(sibling: dict[str, Any], own: dict[str, Any], mine: list[Image.Image | None], rules: dict[str, Any], floor: int) -> str | None:
    try:
        theirs = _sibling_figures(sibling, own, floor)
    except (OSError, ValueError, KeyError):
        return None  # a sheet that cannot be read is not a failure of this one
    hashes = [figure_hash(figure) if figure is not None else None for figure in mine]
    plain = [figure_hash(figure) if figure is not None else None for figure in theirs]
    mirrored = [figure_hash(figure, mirror=True) if figure is not None else None for figure in theirs]
    limit, bits = float(rules["mirrorShare"]), int(rules["samePoseBits"])
    if _share(hashes, plain, bits) >= limit:
        return f"{sibling['id']} (same drawing)"
    return f"{sibling['id']} (its mirror)" if _share(hashes, mirrored, bits) >= limit else None


def mirror_check(mine: list[Image.Image | None], own: dict[str, Any], siblings: Sequence[dict[str, Any]], rules: dict[str, Any], floor: int) -> dict[str, Any]:
    """``siblings``: the other directions of the kit, each ``{"id", "dir", "path"}`` and, when the grid differs from this sheet's, its
    ``columns``, ``rows`` and ``count``."""
    found = [text for text in (_duplicate_of(sibling, own, mine, rules, floor) for sibling in siblings) if text]
    return check("direction_mirror", not found, len(found), 0,
                 "this direction is a copy of " + ", ".join(found) if found else f"different from the other {len(siblings)} direction(s) of the kit or their mirrors")


SCALE_RANGE = (0.7, 1.15)


def gait_check(figures: list[Image.Image | None], direction: str | None, limit: float, floor: int) -> dict[str, Any]:
    if direction not in TURN or not figures:
        return check("walk_gait", True, 0.0, limit, "no direction to compare the legs with")
    measured = np.array([leg_spread(figure, floor) if figure is not None else 0.0 for figure in figures])
    expected = np.array([expected_spread(direction, index / len(figures)) for index in range(len(figures))])
    scale = float(np.clip((measured @ expected) / max(1e-9, expected @ expected), *SCALE_RANGE))
    off = np.abs(measured - scale * expected)
    far = [index + 1 for index in np.nonzero(off > limit)[0]]
    return check("walk_gait", not far, round(float(off.max()), 3), limit,
                 f"the legs of cell(s) {', '.join(map(str, far))} are not where the step puts them (wrong moment or wrong side)" if far
                 else f"every pose has the legs of its moment of the step (scale {scale:.2f})")


def cycle_checks(image: Image.Image, sheet: dict[str, Any], definition: dict[str, Any], siblings: Sequence[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """The checks the animation asks for (``definition["checks"]``: ``height``, ``repeats``, ``gait``, ``mirror``), none for one that asks
    for none."""
    asked = definition.get("checks") or []
    if not asked:
        return []
    rules = catalog()["sheet"]["checks"]
    floor = catalog()["sheet"]["alphaFloor"]
    figures = _figures(grid_cells(image, sheet["columns"], sheet["rows"], sheet["count"]), floor)
    found: list[dict[str, Any]] = []
    if "height" in asked:
        found.append(height_check(figures, float(rules["height"])))
    if "repeats" in asked:
        found.append(repeats_check(figures, int(rules["repeatRun"]), int(rules["samePoseBits"])))
    if "gait" in asked:
        found.append(gait_check(figures, contract_of(definition["id"], definition).get("dir"), float(rules["gait"]), floor))
    if "mirror" in asked:
        others = [item for item in siblings if item.get("id") != definition["id"] and item.get("dir") != definition.get("dir")]
        found.append(mirror_check(figures, sheet, others, rules, floor))
    return found


def sibling_sheets(kit: dict[str, Any], definition: dict[str, Any], *, uploads_root: str, workspace_root: str) -> list[dict[str, Any]]:
    """The other directions of ``kit`` that do the same motion as ``definition`` (a walk against the other walks), each as
    ``{"id", "dir", "path", "columns", "rows", "count"}`` for ``direction_mirror``. A rejected sheet is not a reference to compare
    with, and one whose file cannot be found is left out. Nothing is read for an animation that does not ask for ``mirror``."""
    mine = contract_of(definition["id"], definition)
    if "mirror" not in (definition.get("checks") or []) or not mine.get("motion"):
        return []
    found = []
    for name, made in (kit.get("animations") or {}).items():
        if not isinstance(made, dict) or name == definition["id"] or made.get("reviewState") == "rejected":
            continue
        theirs = contract_of(name, made)
        if theirs.get("motion") != mine["motion"] or not theirs.get("dir"):
            continue
        sheet = made.get("sheet") or {}
        try:
            path = resolve_character_kit_image(str(sheet.get("source") or ""), uploads_root=uploads_root, workspace_root=workspace_root)
        except (CharacterKitFaceCleanupError, OSError, ValueError, KeyError):
            continue
        found.append({"id": name, "dir": theirs["dir"], "path": path, "columns": sheet.get("columns"), "rows": sheet.get("rows"), "count": sheet.get("count")})
    return found
