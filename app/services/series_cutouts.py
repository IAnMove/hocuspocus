"""What a 2D Series shot reads from its cutouts' pixels: the edges a pose is cut by and where a prop's feet are.

A pose cut by its own image border (a bust cut at the chest and on one side) shows that straight cut wherever it lands
in the frame. ``cut_edges`` reads the pose's alpha: an edge is cut where a run of opaque pixels lies along it, at least
``MIN_SIDE_RUN`` of a side or ``MIN_BOTTOM_RUN`` of the bottom long, so a stray pixel, a strand of hair or the feet of a
figure resting on the bottom border are not cuts. The top edge is not read (a pose is never pushed up out of its eye
line), and an image opaque along all four borders is a picture, not a cutout. ``with_pose_sizes``
(``series_shot_bridge``) puts the runs on each pose as ``cut``, and the Series compiler (``ui/scripts/seriesShot.ts``,
``edgeSnap``) places the cutout so every cut it would show lies past the frame edge.

``ground_props`` gives a prop planned with ``ground: true`` its image size and its lowest opaque row, so the compiler
stands that row on the floor. Both read an image once per file version and give the same answer for the same pixels.
"""
from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

# A pixel at least half opaque belongs to the figure.
ALPHA = 128
# The outermost rows and columns read, so a keyed edge one pixel soft still counts as touching the border.
BAND = 2
# Shortest cut run, as a fraction of the edge: a hand or a strand of hair is shorter on a side, two feet on the bottom.
MIN_SIDE_RUN = 0.08
MIN_BOTTOM_RUN = 0.15
# Gaps up to this fraction of the edge inside one run are joined (a dark seam keyed a little transparent).
GAP = 0.01
# A border opaque along this fraction of all four sides is a picture, not a cutout.
FULL = 0.9
# A row counts toward a prop's feet with at least this many opaque pixels (fraction of the width, at least 4 px).
ROW = 0.01


def _runs(line: Any, minimum: float) -> list[list[float]]:
    """Runs of True along ``line`` at least ``minimum`` of its length, as [from, to] fractions."""
    import numpy as np

    size = len(line)
    padded = np.concatenate(([False], line, [False]))
    changes = np.flatnonzero(padded[1:] != padded[:-1])
    spans: list[list[int]] = []
    for start, end in zip(changes[::2], changes[1::2]):
        if spans and start - spans[-1][1] <= GAP * size:
            spans[-1][1] = int(end)
        else:
            spans.append([int(start), int(end)])
    return [[round(start / size, 3), round(end / size, 3)] for start, end in spans if end - start >= max(3, minimum * size)]


@lru_cache(maxsize=256)
def _measure(path: str, _version: tuple[int, int]) -> tuple[tuple[int, int], dict[str, list[list[float]]], float | None]:
    """(size, cut runs, lowest opaque row) of one image file version; no alpha means no cuts and no feet."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        size = image.size
        if image.mode not in ("RGBA", "LA", "PA") and "transparency" not in image.info:
            return size, {}, None
        alpha = np.asarray(image.convert("RGBA").getchannel("A")) >= ALPHA
    height, width = alpha.shape
    band = min(BAND, width, height)
    sides = {"left": alpha[:, :band].any(1), "right": alpha[:, -band:].any(1), "bottom": alpha[-band:, :].any(0)}
    if min(sides["left"].mean(), sides["right"].mean(), sides["bottom"].mean(), alpha[:band, :].any(0).mean()) >= FULL:
        cut: dict[str, list[list[float]]] = {}
    else:
        found = {side: _runs(line, MIN_BOTTOM_RUN if side == "bottom" else MIN_SIDE_RUN) for side, line in sides.items()}
        cut = {side: runs for side, runs in found.items() if runs}
    rows = np.flatnonzero(alpha.sum(1) >= max(4, ROW * width))
    return size, cut, (round((int(rows[-1]) + 1) / height, 4) if len(rows) else None)


def measure(path: Path) -> tuple[tuple[int, int], dict[str, list[list[float]]], float | None] | None:
    """Pixel size, cut edges and lowest opaque row (fraction of the height, from the top) of an image, or None."""
    try:
        stat = path.stat()
        size, cut, bottom = _measure(str(path), (stat.st_mtime_ns, stat.st_size))
    except (OSError, ValueError, SyntaxError):  # PIL reports some broken PNG chunks as SyntaxError
        return None
    return size, copy.deepcopy(cut), bottom


def cut_edges(path: Path) -> dict[str, list[list[float]]]:
    """The edges a cutout is cut by: ``{"left" | "right": [[from, to], ...] (fractions of the height, from the top),
    "bottom": [[from, to], ...] (fractions of the width)}``; empty for an uncut figure, a picture or an unreadable file."""
    found = measure(path)
    return found[1] if found else {}


def ground_props(spec: dict[str, Any], resolve: Any) -> None:
    """Measure the props planned with ``ground`` (``resolve`` maps a source URL to a file or None): their size and lowest
    opaque row go into ``ground`` for the compiler; a prop whose image cannot be read keeps its planned ``y``."""
    for prop in spec.get("props") or []:
        if not isinstance(prop.get("ground"), dict):
            continue
        path = resolve(prop.get("source", ""))
        found = measure(path) if path is not None else None
        if not found or found[2] is None:
            prop.pop("ground")
            continue
        (width, height), _cut, bottom = found
        prop["ground"].update(width=width, height=height, bottom=bottom)
