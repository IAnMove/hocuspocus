"""Warped mouths for the flat rig (``mouthStyle: "warp"``): each pose talks with its own drawing.

Paper and ink mouths are drawn sprites. On painted graphic-novel busts they read as pasted on. Here the mouth is the
drawing itself: the upper lip stays, the lower lip, chin and beard move down (the drawing's own pixels, displaced with
a smooth falloff under the mouth) and the gap opened between them is filled with a flat dark mouth in the character's
ink, with muted teeth only in ``wide`` and ``bite``. ``round`` and ``pucker`` also gather the lips toward the middle.

Each state is a square RGBA patch of the pose's lower face, cut from that pose's own image, so the sprites are per
pose. ``closed`` is the drawing's pixels unchanged, so the rest shape shows no seam, and every patch fades out at its
edge where nothing moves.

The mouth line is placed from (in this order) a hint point, the DWPose outer-lip points, or the rig's painted mouth,
then snapped onto the darkest thin stroke along it (a pen line between the lips, light above and below): a nose fold
or a moustache's edge is dark on one side only, or runs across the line, and is never taken.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from PIL import Image

from services.flat_rig_base import INK, SPRITE, STATES, _anchor
from services.flat_rig_ink import INK_SPAN

# state: (jaw drop, opening width, lips gathering, teeth share of the opening) in mouth widths. closed is the drawing.
WARP_STATES = {"closed": (0.0, 0.0, 0.0, 0.0), "pressed": (-0.025, 0.0, 0.05, 0.0), "small": (0.08, 0.72, 0.0, 0.0),
               "medium": (0.16, 0.86, 0.0, 0.0), "wide": (0.28, 0.96, 0.0, 0.22), "round": (0.22, 0.52, 0.2, 0.0),
               "pucker": (0.12, 0.36, 0.3, 0.0), "bite": (0.07, 0.8, 0.0, 0.55), "tongue": (0.15, 0.8, 0.0, 0.0)}
# How full each opening's lower edge hangs: (1 - |u|^2.2)^belly, higher is more pointed at the corners.
_BELLY = {"small": 1.0, "bite": 1.0, "medium": 0.75, "tongue": 0.75, "wide": 0.6, "round": 0.45, "pucker": 0.5}
# The jaw, in mouth widths: its half width (it moves whole over the middle third of it), how far under the mouth line
# it moves whole (the chin, a short beard) and over how much more it eases back to still (the neck, a long beard).
JAW_HALF, JAW_FLAT, CHIN, FALL = 1.3, 0.4, 1.25, 1.4
# Above the mouth line only the lips gathering moves anything, this far up.
ABOVE = 0.55
# The patch edge fades over this share of its side; nothing moves there.
FEATHER = 0.06
BONE, FLESH = (232, 222, 200), (150, 52, 46)
# Snapping: a stroke counts as the line when it is this much darker (share of the skin's brightness) than the face a
# few pixels above and below it, on average across the middle of the mouth.
RIDGE = 0.1
# Below this score the landmarks' lips were half guessed (a mouth under a moustache seen from below scores 0.39): the
# line they place is reported as unsure.
SURE_LIPS = 0.5


@dataclass
class MouthLine:
    """The line between the lips in figure pixels: ``y = polyval(poly, x)`` from ``x0`` to ``x1`` (the corners)."""
    poly: np.ndarray
    x0: float
    x1: float
    found: bool = False
    source: str = "guess"

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def centre(self) -> tuple[float, float]:
        cx = (self.x0 + self.x1) / 2
        return cx, float(np.polyval(self.poly, cx))

    def y(self, x: np.ndarray) -> np.ndarray:
        """The line's row at ``x``; past the corners it runs on straight at its end slope (at most 1:2)."""
        clipped = np.clip(x, self.x0, self.x1)
        slope = np.polyval(np.polyder(self.poly), clipped) if len(self.poly) > 1 else np.zeros_like(clipped)
        return np.polyval(self.poly, clipped) + np.clip(slope, -0.5, 0.5) * (x - clipped)


# The line -------------------------------------------------------------------

def _luma(rgba: np.ndarray) -> np.ndarray:
    """Brightness, with the keyed-out background taken as white (as the landmarks see the figure)."""
    alpha = rgba[..., 3:4].astype(np.float32) / 255
    rgb = rgba[..., :3].astype(np.float32) * alpha + 255 * (1 - alpha)
    return rgb @ np.array([0.299, 0.587, 0.114], np.float32)


def _ridge(lum: np.ndarray, reach: int) -> np.ndarray:
    """How much darker each pixel is than both the pixels ``reach`` rows above and below it: high on a thin dark
    stroke with light on both sides, low on the edge of a dark mass (a moustache, a shadow)."""
    padded = np.pad(lum, ((reach, reach), (0, 0)), mode="edge")
    return np.maximum(np.minimum(padded[:-2 * reach], padded[2 * reach:]) - lum, 0)


def _sample(field: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """``field`` at integer columns ``xs`` and rows ``ys`` (clipped), the best of the row and its two neighbours."""
    h, w = field.shape
    xs = np.clip(xs, 0, w - 1)
    rows = np.clip(np.rint(ys).astype(int)[None, :] + np.array([-1, 0, 1])[:, None], 0, h - 1)
    return field[rows, xs[None, :]].max(axis=0)


def _skin_level(lum: np.ndarray, line: MouthLine) -> float:
    """The face's brightness around the mouth: the brighter half of a window over the line."""
    cx, cy = line.centre
    h, w = lum.shape
    x0, x1 = int(max(0, cx - line.width * 0.6)), int(min(w, cx + line.width * 0.6))
    y0, y1 = int(max(0, cy - line.width * 0.5)), int(min(h, cy + line.width * 0.5))
    window = lum[y0:y1, x0:x1]
    return float(np.percentile(window, 60)) if window.size else 255.0


def snap_line(rgba: np.ndarray, seed: MouthLine, up: float, down: float, tilt: float = 0.0) -> MouthLine:
    """The seed moved onto the painted line near it: the thin dark stroke (``_ridge``) best followed by the seed's
    curve shifted ``up``..``down`` mouth widths (and tilted up to ``tilt``), over the middle of the mouth; then fitted
    to that stroke column by column. The seed unchanged (not found) when no stroke is dark enough there."""
    lum = _luma(rgba)
    width = max(4.0, seed.width)
    ridge = _ridge(lum, max(2, round(width * 0.06)))
    skin = max(40.0, _skin_level(lum, seed))
    cx, _cy = seed.centre
    xs = np.arange(int(round(cx - width * 0.35)), int(round(cx + width * 0.35)) + 1)
    base = seed.y(xs.astype(float))
    best = (-1.0, 0.0, 0.0)
    shifts = np.arange(-up * width, down * width + 0.5, 1.0)
    tilts = np.linspace(-tilt, tilt, 9) if tilt else [0.0]
    for slope in tilts:
        tilted = base + slope * (xs - cx)
        for shift in shifts:
            # A small pull toward the seed: of two strokes as dark, the nearer.
            score = float(_sample(ridge, xs, tilted + shift).mean()) / skin - abs(shift) / width * 0.04
            if score > best[0]:
                best = (score, float(shift), float(slope))
    score, shift, slope = best
    if score < RIDGE:
        return seed
    # Column by column along the whole mouth, the darkest stroke row within a few pixels of the best curve.
    cols = np.arange(int(round(seed.x0)), int(round(seed.x1)) + 1)
    near = seed.y(cols.astype(float)) + shift + slope * (cols - cx)
    reach = max(2, round(width * 0.05))
    offsets = np.arange(-reach, reach + 1)
    rows = np.clip(np.rint(near).astype(int)[None, :] + offsets[:, None], 0, lum.shape[0] - 1)
    found = ridge[rows, np.clip(cols, 0, lum.shape[1] - 1)[None, :]]
    weights = found.max(axis=0)
    ys = rows[found.argmax(axis=0), np.arange(len(cols))].astype(float)
    keep = weights > skin * RIDGE * 0.5
    if keep.sum() < max(4, len(cols) * 0.3):
        poly = np.polyfit(cols.astype(float), near, 2)
    else:
        poly = np.polyfit(cols[keep].astype(float), ys[keep], 2 if keep.sum() >= 8 else 1, w=weights[keep])
        if len(poly) == 3 and abs(poly[0]) * (width / 2) ** 2 > width * 0.15:
            # Bent more than an inked mouth is: a straight fit.
            poly = np.polyfit(cols[keep].astype(float), ys[keep], 1, w=weights[keep])
    return MouthLine(np.asarray(poly, float), seed.x0, seed.x1, True, seed.source)


def lips_line(points: Any) -> MouthLine | None:
    """The seed line from DWPose's twelve outer-lip points (corners 0 and 6, upper lip 1-5, lower lip 7-11): through
    the corners and the middles between the upper and lower lip."""
    try:
        lips = np.asarray(points, float).reshape(12, 2)
    except (TypeError, ValueError):
        return None
    middle = np.array([lips[0], lips[6], *((lips[i] + lips[12 - i]) / 2 for i in range(1, 6))])
    x0, x1 = float(min(lips[0, 0], lips[6, 0])), float(max(lips[0, 0], lips[6, 0]))
    if x1 - x0 < 4:
        return None
    return MouthLine(np.polyfit(middle[:, 0], middle[:, 1], 2), x0, x1, False, "landmarks")


def _flat(cx: float, cy: float, width: float, source: str, slope: float = 0.0) -> MouthLine:
    return MouthLine(np.array([slope, cy - slope * cx]), cx - width / 2, cx + width / 2, False, source)


def mouth_line(rgba: np.ndarray, *, point=None, width=None, lips=None, painted=None) -> MouthLine:
    """Where the lips meet, in figure pixels. ``point`` (a hint on the line) wins and is only snapped a little;
    ``width`` (a hint) sets the corners; ``lips`` are the landmarks' outer-lip points; ``painted`` is ``(cx, cy,
    width)`` of the mouth the rig found or guessed, the last resort."""
    seeded = lips_line(lips) if lips is not None else None
    if point is not None:
        px, py = float(point[0]), float(point[1])
        span = float(width or (seeded.width if seeded else (painted[2] if painted else 40.0)))
        if seeded:
            # The landmarks' bend and slant, moved to pass through the hint.
            shifted = MouthLine(seeded.poly.copy(), px - span / 2, px + span / 2, False, "hint")
            shifted.poly[-1] += py - float(seeded.y(np.array([px]))[0])
            return snap_line(rgba, shifted, 0.08, 0.08)
        return snap_line(rgba, _flat(px, py, span, "hint"), 0.08, 0.08, tilt=0.4)
    if seeded:
        if width:
            cx, _ = seeded.centre
            seeded = MouthLine(seeded.poly, cx - width / 2, cx + width / 2, False, "landmarks")
        return snap_line(rgba, seeded, 0.3, 0.25, tilt=0.08)
    cx, cy, span = painted if painted else (rgba.shape[1] / 2, rgba.shape[0] / 2, 40.0)
    return snap_line(rgba, _flat(cx, cy, float(width or span), "painted" if painted else "guess"), 0.12, 0.12, tilt=0.4)


# The warp -------------------------------------------------------------------

def _smooth(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _opening(u: np.ndarray, belly: float) -> np.ndarray:
    """The opening's depth across it (u from -1 to 1 corner to corner), 1 in the middle, pointed at the corners."""
    return np.clip(1 - np.abs(u) ** 2.2, 0, 1) ** belly


def _jaw_profile(u: np.ndarray) -> np.ndarray:
    """How much of the drop each column of the jaw takes: whole over its middle, easing to still at its sides."""
    return 0.5 * (1 + np.cos(np.pi * np.clip((np.abs(u) - JAW_FLAT) / (1 - JAW_FLAT), 0, 1)))


def patch_box(line: MouthLine) -> tuple[int, int, int]:
    """The square ``(x0, y0, side)`` that holds everything a state moves, plus its faded edge."""
    cx, _cy = line.centre
    width = line.width
    reach = JAW_HALF * width
    top = float(line.y(np.linspace(cx - 0.95 * width, cx + 0.95 * width, 33)).min()) - ABOVE * width
    bottom = float(line.y(np.linspace(cx - reach, cx + reach, 33)).max()) + (CHIN + FALL) * width
    tall, wide = bottom - top, reach * 2
    side = int(math.ceil(max(tall, wide) / (1 - 2 * FEATHER))) + 4
    return int(round(cx - side / 2)), int(round((top + bottom) / 2 - side / 2)), side


def _crop(rgba: np.ndarray, x0: int, y0: int, side: int) -> np.ndarray:
    """``rgba`` cut to the square, transparent where the square runs past the image."""
    out = np.zeros((side, side, 4), rgba.dtype)
    h, w = rgba.shape[:2]
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(w, x0 + side), min(h, y0 + side)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = rgba[sy0:sy1, sx0:sx1]
    return out


def _feather(side: int) -> np.ndarray:
    ramp = _smooth(np.minimum(np.arange(side), np.arange(side)[::-1]) / max(1.0, side * FEATHER))
    return np.minimum(ramp[:, None], ramp[None, :])


def _mix(a, b, share: float) -> np.ndarray:
    return np.array([x * (1 - share) + y * share for x, y in zip(a[:3], b[:3])], np.float32)


@dataclass
class _Field:
    """One state's displacement over the patch: the drawing at (x + dx, y - dy) lands at (x, y)."""
    dx: np.ndarray
    dy: np.ndarray
    gap: np.ndarray
    below: np.ndarray
    opening: np.ndarray


def _field(line: MouthLine, box: tuple[int, int, int], state: str) -> _Field:
    drop, share, pinch, _teeth = WARP_STATES[state]
    x0, y0, side = box
    width = line.width
    cx, _cy = line.centre
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float32)
    xx += x0
    yy += y0
    lip = line.y(xx[0]).astype(np.float32)[None, :]
    below = yy - lip
    # A whole number of pixels: where the jaw moves whole its pixels are copied as they are, not resampled.
    full = float(round(drop * width))
    jaw = full * _jaw_profile((xx[0] - cx) / (JAW_HALF * width))[None, :]
    half = max(1.0, share * width / 2)
    opening = (full * _opening((xx[0] - cx) / half, _BELLY.get(state, 1.0)) * (np.abs(xx[0] - cx) < half))[None, :] \
        if share > 0 and full > 0 else np.zeros_like(jaw)
    # Under the line the lower lip hangs at the opening's depth and the jaw's drop takes over lower down, over a height
    # that keeps the skin beside the corners from stretching to more than ~1.6 times.
    blend = max(0.3 * width, 4.0 * float(np.max(np.abs(jaw - opening))))
    reach = max(CHIN * width, blend)
    fall = 0.5 * (1 + np.cos(np.pi * np.clip((below - reach) / (FALL * width), 0, 1)))
    dy = np.where(below >= 0, (opening + (jaw - opening) * _smooth(below / blend)) * fall, 0).astype(np.float32)
    dx = np.zeros_like(dy)
    if pinch:
        r2 = ((xx - cx) / (0.95 * width)) ** 2 + (below / (ABOVE * width)) ** 2
        dx = (pinch * (xx - cx) * np.clip(1 - r2, 0, 1) ** 2).astype(np.float32)
    source_below = (yy - dy) - line.y(xx + dx).astype(np.float32)
    # Covered by the opening: on or under the line, with the drawing it would show from above the line.
    gap = np.clip(below + 0.5, 0, 1) * np.clip(0.5 - source_below, 0, 1) * np.clip(opening, 0, 1)
    return _Field(dx, dy, gap.astype(np.float32), below, np.broadcast_to(opening, dy.shape))


def _paint_mouth(rgb: np.ndarray, field: _Field, line: MouthLine, box, state: str, ink, skin) -> np.ndarray:
    """The opening in the ink, a band of muted teeth under the upper lip (wide, bite) and a dark tongue (tongue)."""
    _drop, share, _pinch, teeth = WARP_STATES[state]
    paint = np.broadcast_to(np.asarray(ink[:3], np.float32), rgb.shape).copy()
    x0, y0, side = box
    cx, _cy = line.centre
    xs = np.arange(side, dtype=np.float32)[None, :] + x0
    if teeth:
        half = share * line.width / 2 * 0.55
        band = np.clip(field.opening * teeth - field.below + 0.5, 0, 1) * np.clip(half - np.abs(xs - cx) + 0.5, 0, 1)
        paint = paint * (1 - band[..., None]) + _mix(skin, BONE, 0.3) * band[..., None]
    if state == "tongue":
        depth = float(field.opening.max())
        ry, rx = max(1.0, depth * 0.35), max(1.0, share * line.width * 0.2)
        inside = ((xs - cx) / rx) ** 2 + ((field.below - depth * 0.78) / ry) ** 2
        tip = np.clip((1 - inside) * rx * 0.5, 0, 1)
        paint = paint * (1 - tip[..., None]) + _mix(ink, FLESH, 0.45) * tip[..., None]
    cover = field.gap[..., None]
    return rgb * (1 - cover) + paint * cover


def warp_state(rgba: np.ndarray, line: MouthLine, state: str, ink=INK, skin=(200, 160, 130),
               box: tuple[int, int, int] | None = None) -> Image.Image:
    """One state's patch (``patch_box`` square, RGBA). Pixels that do not move keep the drawing exactly; where the
    drawing is see-through at its outline and nothing moves the patch is empty, so laid on the pose it changes nothing."""
    if state not in STATES:
        raise ValueError(f"Unknown mouth state {state}")
    box = box or patch_box(line)
    x0, y0, side = box
    original = _crop(rgba, x0, y0, side)
    feather = _feather(side)
    opaque = original[..., 3] == 255
    if state == "closed":
        out = original.copy()
        out[..., 3] = np.round(feather * opaque * 255).astype(np.uint8)
        return Image.fromarray(out)
    field = _field(line, box, state)
    # Premultiplied, so the transparent background's colour never bleeds into the moved outline.
    pixels = original.astype(np.float32)
    pixels[..., :3] *= pixels[..., 3:] / 255
    grid_y, grid_x = np.mgrid[0:side, 0:side].astype(np.float32)
    moved = cv2.remap(pixels, grid_x + field.dx, grid_y - field.dy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    moved = np.clip(moved, 0, 255)
    alpha = moved[..., 3]
    rgb = np.where(alpha[..., None] > 0, moved[..., :3] * 255 / np.maximum(alpha[..., None], 1e-3), 0)
    rgb = _paint_mouth(rgb, field, line, box, state, ink, skin)
    alpha = np.maximum(alpha, field.gap * 255)
    changed = (np.abs(field.dy) > 1e-3) | (np.abs(field.dx) > 1e-3) | (field.gap > 0)
    alpha = np.where(changed, alpha, opaque * 255.0) * feather
    out = np.dstack([np.clip(np.round(rgb), 0, 255), np.clip(np.round(alpha), 0, 255)]).astype(np.uint8)
    return Image.fromarray(out)


def line_ink(rgba: np.ndarray, line: MouthLine, fallback=INK) -> tuple[int, ...]:
    """The colour the mouth is inked in: the darkest third of the pixels along the line, when it was found."""
    if not line.found:
        return tuple(fallback)
    xs = np.arange(int(round(line.x0 + line.width * 0.2)), int(round(line.x1 - line.width * 0.2)) + 1)
    h, w = rgba.shape[:2]
    xs = xs[(xs >= 0) & (xs < w)]
    if not len(xs):
        return tuple(fallback)
    ys = np.clip(np.rint(line.y(xs.astype(float))).astype(int), 0, h - 1)
    pixels = rgba[ys, xs, :3].astype(float)
    lum = pixels @ np.array([0.299, 0.587, 0.114])
    dark = pixels[lum <= np.percentile(lum, 34)]
    return tuple(int(v) for v in np.median(dark, axis=0)) + (255,)


def warp_states(rgba: np.ndarray, line: MouthLine, ink=INK, skin=(200, 160, 130), states=STATES) -> dict[str, Image.Image]:
    box = patch_box(line)
    return {state: warp_state(rgba, line, state, ink, skin, box) for state in states}


def face_colour(rgba: np.ndarray, line: MouthLine, fallback=(200, 160, 130)) -> tuple[int, ...]:
    """The face colour round the mouth (the teeth are mixed from it): the lighter half of the opaque pixels near the
    line, which leaves out the ink, a beard's shadows and the background."""
    cx, cy = line.centre
    h, w = rgba.shape[:2]
    x0, x1 = int(max(0, cx - line.width * 0.6)), int(min(w, cx + line.width * 0.6))
    y0, y1 = int(max(0, cy - line.width * 0.45)), int(min(h, cy + line.width * 0.45))
    region = rgba[y0:y1, x0:x1]
    pixels = region[region[..., 3] > 200][:, :3].astype(float)
    if len(pixels) < 20:
        return tuple(int(v) for v in fallback[:3])
    lum = pixels @ np.array([0.299, 0.587, 0.114])
    return tuple(int(v) for v in np.median(pixels[lum >= np.percentile(lum, 50)], axis=0))


def pose_patches(rgba: np.ndarray, line: MouthLine, ink_fallback=INK, skin_fallback=(200, 160, 130),
                 states=STATES) -> tuple[tuple[int, int, int], dict[str, Image.Image]]:
    """The patch square and each state's patch, in the line's ink (or ``ink_fallback`` when no line was found)."""
    box = patch_box(line)
    ink, skin = line_ink(rgba, line, ink_fallback), face_colour(rgba, line, skin_fallback)
    return box, {state: warp_state(rgba, line, state, ink, skin, box) for state in states}


def line_hint(line: MouthLine, frame) -> dict[str, Any]:
    """The line as a hint would give it, in % of the pose image (``frame``: where the figure was cut from it and its
    size), with whether it was found on the drawing and what placed it."""
    left, top, width, height = frame
    cx, cy = line.centre
    return {"mouth": [round(float(cx + left) / width * 100, 3), round(float(cy + top) / height * 100, 3)],
            "mouthWidth": round(float(line.width) / width * 100, 3), "found": bool(line.found), "from": line.source}


def rig_line(rgba: np.ndarray, seeds: dict[str, Any], painted) -> MouthLine:
    """The mouth line from a pose's seeds (``flat_rig.rig_pose`` ``seeds``: hint point and width, landmark lips)."""
    return mouth_line(rgba, point=seeds.get("point"), width=seeds.get("width"), lips=seeds.get("lips"), painted=painted)


def painted_seed(rig: dict[str, Any]) -> tuple[float, float, float]:
    """The mouth ``flat_rig.rig_pose`` placed as ink mouths are: centred on the painted line (or the hint, the landmarks
    or the guess under the eyes), its width INK_SPAN of the sprite; ``(cx, cy, width)`` in figure pixels."""
    width, height, anchor = rig["width"], rig["height"], rig["mouth"]
    edge = max(width, height)
    return (width / 2 + anchor["offsetX"] * edge / 100, height / 2 + anchor["offsetY"] * edge / 100,
            anchor["scale"] * edge * SPRITE[0] / SPRITE[1] * INK_SPAN)


def line_warnings(line: MouthLine, seeds: dict[str, Any]) -> list[str]:
    """``mouth_line_guessed``: no painted line was found to snap onto; ``mouth_line_unsure``: unsure landmarks placed
    it. Either way the line is worth a look in the mouth line editor (or ``characters.rig.flat.preview``)."""
    if not line.found:
        return ["mouth_line_guessed"]
    return ["mouth_line_unsure"] if line.source == "landmarks" and (seeds.get("lips_score") or 1.0) < SURE_LIPS else []


def rig_warp(rig: dict[str, Any]) -> dict[str, Any]:
    """One rigged pose's warp mouths: its nine patches, the mouth anchor (the patch square), the line in % of the pose
    image (``line_hint``) and its warnings (``line_warnings``)."""
    figure = np.array(rig["image"].convert("RGBA"))
    width, height = rig["width"], rig["height"]
    seeds = rig.get("seeds") or {}
    line = rig_line(figure, seeds, painted_seed(rig))
    (x0, y0, side), sprites = pose_patches(figure, line, rig.get("ink") or INK, rig.get("skin") or (200, 160, 130))
    return {"sprites": sprites, "mouth": _anchor(x0 + side / 2, y0 + side / 2, side, width, height),
            "line": line_hint(line, rig["frame"]), "warnings": line_warnings(line, seeds)}
