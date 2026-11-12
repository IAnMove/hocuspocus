"""Scale the poses of a walk drawn pose by pose by their torso, so the figure does not change size from one cell to the next.

The model draws every pose of a walk at a slightly different size, and ``build_sheet`` (``services/character_animations.py``) gives every pose
one shared scale, so a pose drawn 8 % smaller plays as a figure that shrinks and grows (``figure_height`` allows 3 %). Scaling each pose
by its own height would remove that, but also the bob of a walk (the body is about 4 % lower with the legs apart), which is real. The torso is
what a walk does not change: the distance from the neck to the middle of the hips, which the pose model (DWPose, ``face_landmarks``, on the CPU,
already shipped for the face tools and the puppet) finds in each pose. Every pose is then scaled so its torso is as long as the median of
the cycle; the feet stay on one line because ``build_sheet`` puts the lowest row of each figure on it.

It is a refinement, never a requirement. With no model, a pose whose neck or hips the model is not sure of, torsos that differ by more than
``NOISE`` (the model guessed: that is not the drawing's size jitter) or a scale that would change a pose by more than ``RANGE``, no ratios are
returned and the sheet keeps its one shared scale, as before. Only a walk drawn pose by pose uses it: a puppet and a video clip have a real bob
and a body that is one drawing.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from PIL import Image

from services import face_landmarks

NECK, RIGHT_HIP, LEFT_HIP = 1, 8, 11    # OpenPose indexes of the body points ``face_landmarks.detect`` returns
MIN_SCORE = 0.3                          # the pose model's own confidence a joint needs
NOISE = 1.5                              # the longest torso over the shortest: more than this is a guess, not a drawing at another size
RANGE = (0.8, 1.25)                      # how much one pose may be scaled to match the others

Detector = Callable[[Image.Image], "dict[str, Any] | None"]


def applies(job: dict[str, Any]) -> bool:
    """A catalog walk drawn pose by pose (not a puppet, not a clip, not the author's own)."""
    definition = job["definition"]
    return job.get("method") not in ("video", "puppet") and not definition.get("custom") and definition.get("guide") == "walk"


def torso_length(figure: Image.Image, detect: Detector | None = None) -> float:
    """The distance (pixels) from the neck to the middle of the hips of a keyed figure, 0.0 when the model is missing or not sure of them."""
    page = Image.new("RGBA", figure.size, (255, 255, 255, 255))
    page.alpha_composite(figure.convert("RGBA"))
    try:
        found = (detect or face_landmarks.detect)(page.convert("RGB"))
    except Exception:  # noqa: BLE001 - an optional CPU model: nothing found is not an error
        return 0.0
    body = (found or {}).get("body") or []
    wanted = [body[index] for index in (NECK, RIGHT_HIP, LEFT_HIP) if index < len(body)]
    if len(wanted) < 3 or any(point[2] < MIN_SCORE for point in wanted):
        return 0.0
    neck, hips = np.array(wanted[0][:2], float), (np.array(wanted[1][:2], float) + np.array(wanted[2][:2], float)) / 2
    return float(np.linalg.norm(hips - neck))


def ratios(figures: Sequence[Image.Image], detect: Detector | None = None) -> list[float] | None:
    """The factor each pose is scaled by so every torso is the median's, None when the shared scale should stay (see the module docstring)."""
    measures = [torso_length(figure, detect) for figure in figures]
    if len(measures) < 2 or min(measures) <= 0 or max(measures) / min(measures) > NOISE:
        return None
    median = float(np.median(measures))
    found = [median / measure for measure in measures]
    return found if all(RANGE[0] <= value <= RANGE[1] for value in found) else None
