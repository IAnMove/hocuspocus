"""When the flat rig trusts a mouth hint over the face landmarks.

A hint (``characters.rig.flat`` ``hints``) used to win outright, so a point typed without looking moved a pose's
mouth off its lips even where DWPose had found them for sure: on the 1x03 an agent's hints put Telmo's mouth on his
cheek and Inés's praying pose's on her chin (0.83 and 0.23 lip widths off) while the landmarks scored 0.94–0.97.

Now a mouth hint is followed as given only when it says ``exact`` (the Face Rig mouth line editor, where a person saw
the line, sends it). Any other:

- gives way to landmarks that are sure of the lips: they place the mouth, and a hint far from them is reported
  (``mouth_hint_ignored``) since whoever typed it was wrong;
- where the landmarks are unsure (a beard seen from below) places the mouth, its line snapped onto the painted lips
  as far as the landmarks' own line would be (``flat_rig_warp``).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from services.flat_rig_warp import lips_line

# Landmarks this sure of the lips overrule a far hint (a bearded mouth seen from below scores ~0.4–0.7).
SURE_LIPS = 0.85
# How far from the landmarks' lip line, in its widths, a hint may be and still be followed: placed lines sit within
# about 0.2 of it on painted faces.
FAR = 0.5


def offset(point: tuple[float, float], lips: Any) -> float | None:
    """How far ``point`` lies from the line the landmarks' lips draw, in that line's widths; None without a line."""
    line = lips_line(lips) if lips is not None else None
    if line is None:
        return None
    x, y = float(point[0]), float(point[1])
    along = 0.0 if line.x0 <= x <= line.x1 else min(abs(x - line.x0), abs(x - line.x1))
    return math.hypot(along, y - float(line.y(np.array([x]))[0])) / max(line.width, 4.0)


def trusted(hint: dict[str, Any] | None, landmarks: dict[str, Any] | None, size: tuple[int, int]
            ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """``hint`` without its mouth when the landmarks are sure of the lips and it is not exact, and what was left out
    (``far``: it was more than ``FAR`` lip widths off them); else as given. ``size`` is the pose image's, whose
    percentages the hint is in and whose pixels the landmarks are in."""
    if not hint or not hint.get("mouth") or hint.get("exact") or not landmarks:
        return hint, None
    score = float((landmarks.get("scores") or {}).get("mouth") or 0.0)
    point = (hint["mouth"][0] / 100 * size[0], hint["mouth"][1] / 100 * size[1])
    off = offset(point, landmarks.get("mouth")) if score >= SURE_LIPS else None
    if off is None:
        return hint, None
    lips = np.asarray(landmarks["mouth"], dtype=float).reshape(-1, 2).mean(axis=0)
    kept = {key: value for key, value in hint.items() if key not in ("mouth", "mouthWidth", "exact")}
    return kept or None, {"hint": list(hint["mouth"]), "landmarks": [round(lips[0] / size[0] * 100, 3),
                                                                     round(lips[1] / size[1] * 100, 3)],
                          "offset": round(off, 2), "far": off > FAR, "score": round(score, 2)}
