"""Ink mouths for the flat rig (``mouthStyle: "ink"``).

The paper mouths are cartoon drawings: on a face inked in flat blacks they look pasted on. With mouthStyle "ink" the
painted mouth stays as the rest shape and each open shape is a hard-edged opening in the painted mouth's own ink,
hanging from it (the upper lip stays, the jaw drops), sized from its width.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from services.flat_rig_base import INK, SPRITE, STATES, FlatRigError, _paste_inside

# The painted mouth's width is this share of an ink sprite's width; the sprite is centred on the painted mouth.
INK_SPAN = 0.5
# Each open shape's width and depth in painted-mouth widths. closed and pressed draw nothing: the painted mouth shows.
INK_OPENINGS = {"small": (0.55, 0.1), "medium": (0.72, 0.22), "wide": (0.88, 0.36), "tongue": (0.66, 0.22),
                "bite": (0.62, 0.12), "round": (0.46, 0.3), "pucker": (0.3, 0.2)}
# How square each opening's lower lip hangs (higher: rounder corners) and whether the lower lip is drawn under it.
_INK_BELLY = {"small": 1.0, "bite": 1.0, "medium": 0.75, "tongue": 0.75, "wide": 0.6, "round": 0.5, "pucker": 0.55}
_INK_LOWER_LIP = ("medium", "wide", "round", "tongue")
BONE, FLESH = (232, 222, 200), (150, 52, 46)


def ink_colour(rgb: np.ndarray, mask: np.ndarray, background) -> tuple[int, ...]:
    """The painted mouth's ink: the median of the third of its pixels farthest from the face colour."""
    pixels = rgb[mask].astype(float)
    far = np.abs(pixels - np.asarray(background, dtype=float)).sum(axis=1)
    return tuple(int(v) for v in np.median(pixels[far >= np.percentile(far, 67)], axis=0)) + (255,)


def _mix(a, b, share: float) -> tuple[int, ...]:
    return tuple(round(x * (1 - share) + y * share) for x, y in zip(a[:3], b[:3])) + (255,)


def _ink_opening(cx: float, cy: float, w: float, d: float, belly: float) -> list[tuple[float, float]]:
    """An opening under the painted line: its top runs along the line (the upper lip stays) with a slight bow, its
    bottom is the dropped lower lip, pointed at the corners like an inked mouth."""
    ts = [i / 40 * 2 - 1 for i in range(41)]
    top = [(cx + t * w / 2, cy - d * 0.05 * (1 - t * t)) for t in ts]
    bottom = [(cx + t * w / 2, cy + d * (1 - abs(t) ** 2.2) ** belly) for t in reversed(ts)]
    return top + bottom


def _lower_lip(draw, cx: float, cy: float, w: float, d: float, belly: float, weight: float, ink) -> None:
    """A short pen stroke under the opening, following its curve and tapered at both ends: the lower lip as an
    inker draws it, not a cartoon outline."""
    gap = d * 0.14 + weight
    ts = [i / 30 * 1.2 - 0.6 for i in range(31)]
    curve = [(cx + t * w / 2, cy + d * (1 - abs(t) ** 2.2) ** belly + gap) for t in ts]
    upper = [(x, y - weight * (1 - (t / 0.6) ** 2)) for (x, y), t in zip(curve, ts)]
    lower = [(x, y + weight * 0.6 * (1 - (t / 0.6) ** 2)) for (x, y), t in zip(curve, ts)]
    draw.polygon(upper + list(reversed(lower)), fill=tuple(ink))


def draw_ink_mouth(state: str, ink=INK, skin=(200, 160, 130)) -> Image.Image:
    """One ink mouth sprite (512×320, transparent), drawn at 4× and averaged down: a flat opening in the painted
    mouth's ink hanging from the painted line, with a tapered lower-lip stroke under the open ones. Only ``wide`` and
    ``bite`` show a hint of upper teeth (the skin toward bone, never white) and ``tongue`` a dark tongue tip."""
    if state not in STATES:
        raise FlatRigError("invalid_state", f"Unknown mouth state {state}")
    width, height, k = SPRITE[0], SPRITE[1], 4
    image = Image.new("RGBA", (width * k, height * k), (0, 0, 0, 0))
    if state in INK_OPENINGS:
        draw = ImageDraw.Draw(image)
        painted, cx, cy = width * k * INK_SPAN, width * k / 2, height * k / 2
        w, d = (share * painted for share in INK_OPENINGS[state])
        belly = _INK_BELLY[state]
        outline = _ink_opening(cx, cy, w, d, belly)
        draw.polygon(outline, fill=tuple(ink))
        if state in ("wide", "bite"):
            band = d * (0.16 if state == "wide" else 0.5)
            _paste_inside(image, outline, _mix(skin, BONE, 0.3), (cx - w * 0.28, cy - d, cx + w * 0.28, cy + band), "rectangle")
        if state == "tongue":
            _paste_inside(image, outline, _mix(ink, FLESH, 0.45), (cx - w * 0.2, cy - d * 0.3, cx + w * 0.2, cy + d * 0.55), "ellipse")
        if state in _INK_LOWER_LIP:
            _lower_lip(draw, cx, cy, w, d, belly, painted * 0.03, ink)
    return image.resize(SPRITE, Image.BOX)


def _ink_sprite_width(mouth_box, guide: dict[str, Any], eyes_box) -> float:
    """An ink sprite holds the painted mouth (or, with none found, the landmarks' mouth or half the eye pair) in
    INK_SPAN of its width. A painted line found much shorter than the landmarks' mouth is a piece of it."""
    span = guide.get("mouth_width")
    painted = mouth_box[2] - mouth_box[0] if mouth_box else None
    if painted and not (span and painted < span * 0.6):
        return painted / INK_SPAN
    return (span or (eyes_box[2] - eyes_box[0]) * 0.5) / INK_SPAN
