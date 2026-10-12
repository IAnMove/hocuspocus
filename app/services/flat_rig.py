"""Rig a flat cutout character so it can talk: one call from a keyed pose to a Character Kit.

For each pose (an RGBA image with the background keyed out) this finds the two
white eyes and the painted mouth under them, wipes that mouth by inpainting,
and measures pose-local anchors. It then draws nine paper mouths and a blink
made from the base pose's own eye shapes. The result is saved on the kit.

It suits flat styles with light eyes on a plain face (paper cutout, simple
cartoon, anime eyes whose white is only a crescent beside a big iris). A face that is a screen (a laptop or robot character) uses
``screen``: light marks on a dark screen. On a face drawn as a texture (code
glyphs, scales) the mouth is the wide mark darker than the texture's own ink,
and it is wiped with a copy of the texture. When no painted mouth is found the
mouth is placed under the eyes and nothing is wiped; the result says so.

A face with realistic proportions (small eyes in a wide head, as in graphic-novel
art with flat black shadows) has its mouth much lower and eye bags, wrinkles and
spectacle rims right under the eyes: there the mouth is the thin, roughly level
stroke nearest the row where such a mouth sits. Hints (a point per pose) narrow
the eye or mouth search for anything else. Where no hint is given, DWPose face
landmarks (``face_landmarks``, when its models are installed) place the search:
the mark search alone takes a nose stroke or a socket shadow for a graphic-novel
mouth and misses a bust's shaded eyes. With ``mouthStyle: "ink"`` the painted
mouth is kept as the rest shape and the open shapes are drawn in its own ink;
with ``"warp"`` each pose talks with its own drawing (``flat_rig_warp``): the
lower lip and jaw move down and the gap is inked, one set of patches per pose.
A re-rig keeps the kit's look (the last rig's, or its style preset's) for every
``style`` key the call leaves out, so a warp kit stays warp (``flat_rig_look``). Which way each pose looks is read
from the same landmarks and kept on the pose as ``facing`` (``pose_facing``; one the user set since is kept).

Ported from the agent script that rigged the six "Uncanny Valley" characters.
Only OpenCV, numpy and Pillow are needed.
"""
from __future__ import annotations

import copy
import hashlib
import io
import math
import os
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np
from PIL import Image, ImageDraw

from services import face_landmarks, flat_rig_hints, flat_rig_warp, pose_facing
from services.character_kit_library import patch_character_kit, read_character_kit_library
from services.face_enlarge import face_caption
from services.flat_rig_base import INK, SPRITE, STATES, FlatRigError, _anchor, _paste_inside
from services.flat_rig_ink import _ink_sprite_width, draw_ink_mouth, ink_colour
# The rig's look lives in flat_rig_look; rig_style stays importable from here.
from services.flat_rig_look import kit_look, rig_style
# Keep existing eye and mask imports available to callers.
from services.flat_rig_metrics import attach_openings, opening_caption
from services.flat_rig_eyes import (
    SCREEN_INK, _CROSS, LUMA, MAX_SPRITE_RATIO,
    _mask, _open, _close, _dilate,
    _components, _eye_pair, _half, _split_touching,
    _head_candidates, _small_face_eyes, _eye_components, _hinted_pair,
    _with_fragments, _eyes_near, find_eyes, _centre,
    _fill_holes, _not_skin, _upper_lid, _eye_opening,
    _hull, _whole_white, eye_openings, _lid_colour,
    _shadow_lid, _cover, blink_sprite, _blink_box,
    _eye_skin, _outlined_eyes,
)

MAPPING = {"rest": "closed", "M": "pressed", "A": "wide", "E": "medium", "I": "small",
           "O": "round", "U": "pucker", "F": "bite", "L": "tongue"}
CAVITY = (92, 26, 30, 255)
TEETH, TONGUE = (250, 248, 240, 255), (222, 98, 110, 255)
SCREEN_CAVITY = (10, 22, 70, 255)
MAX_PIXELS = 16_777_216


HINT_KEYS = ("mouth", "eyes", "mouthWidth", "exact")


def _hint_value(pose: str, key: str, value: Any):
    """A hint point ``[x, y]`` in % of the pose image, ``mouthWidth``: the mouth corner to corner in % of its width, or
    ``exact``: true when a person placed the mouth on the image (``flat_rig_hints``)."""
    if key == "exact":
        if not isinstance(value, bool):
            raise FlatRigError("invalid_hints", f"hints.{pose}.exact must be true or false")
        return value
    if key == "mouthWidth":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0.5 <= value <= 100:
            raise FlatRigError("invalid_hints", f"hints.{pose}.mouthWidth must be a number from 0.5 to 100 (% of the pose image width)")
        return round(float(value), 3)
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 100 for v in value)):
        raise FlatRigError("invalid_hints", f"hints.{pose}.{key} must be [x, y] in % of the pose image, from 0 to 100")
    return [round(float(value[0]), 3), round(float(value[1]), 3)]


def rig_hints(value: Any) -> dict[str, dict[str, Any] | None]:
    """Placement hints per pose: ``{"<pose>": {"mouth": [x, y], "eyes": [x, y], "mouthWidth": w}}`` in % of that pose
    image (the keyed source, before cropping), 0–100. ``null`` or ``{}`` for a pose clears the hints saved for it."""
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 32:
        raise FlatRigError("invalid_hints", "hints must be an object with at most 32 pose ids")
    hints: dict[str, dict[str, list[float]] | None] = {}
    for pose, hint in value.items():
        if not isinstance(pose, str) or not pose or len(pose) > 160:
            raise FlatRigError("invalid_hints", "hints must be keyed by pose id")
        if hint is None or hint == {}:
            hints[pose] = None
            continue
        if not isinstance(hint, dict) or any(key not in HINT_KEYS for key in hint):
            raise FlatRigError("invalid_hints", f"hints.{pose} takes mouth and eyes points, a mouthWidth and exact")
        hints[pose] = {key: _hint_value(pose, key, point) for key, point in hint.items()}
    return hints


def _clean_alpha(image: Image.Image) -> Image.Image:
    """Drop faint keyed speckles and keep the figure (every part over 2 % of the largest)."""
    pixels = np.array(image)
    alpha = pixels[..., 3]
    alpha[alpha < 64] = 0
    labels, parts = _components(alpha > 0)
    if len(parts) > 1:
        largest = max(part["size"] for part in parts)
        keep = np.isin(labels, [part["label"] for part in parts if part["size"] > largest * 0.02])
        alpha[~keep] = 0
    pixels[..., 3] = alpha
    return Image.fromarray(pixels)


def _figure_box(image: Image.Image, margin: float = 0.02) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """The cleaned pose and the box ``crop_figure`` cuts from it."""
    image = _clean_alpha(image.convert("RGBA"))
    alpha = np.array(image)[..., 3]
    ys, xs = np.nonzero(alpha > 128)
    if not len(xs):
        raise FlatRigError("not_keyed", "The pose has no visible figure; key its background first")
    pad = int(max(image.size) * margin)
    return image, (int(max(0, xs.min() - pad)), int(max(0, ys.min() - pad)),
                   int(min(image.width, xs.max() + pad + 1)), int(min(image.height, ys.max() + pad + 1)))


def crop_figure(image: Image.Image, margin: float = 0.02) -> Image.Image:
    image, box = _figure_box(image, margin)
    return image.crop(box)


# Features -------------------------------------------------------------------

def _mouth_marks(region: np.ndarray, inside: np.ndarray, eye_height: int, screen: bool, faint: bool = False):
    lum = region @ np.array([0.299, 0.587, 0.114])
    if screen:
        mark = (region.min(axis=2) > 200) & inside
        top = region[: max(4, int(eye_height * 0.25))]
        background = np.median(top[top.min(axis=2) < 200], axis=0)
        return mark, mark, background
    lighter = inside & (lum > np.percentile(lum[inside], 40))
    # A perfectly flat fill has no pixel above its own percentile; paper texture always does.
    background = np.median(region[lighter if lighter.any() else inside], axis=0)
    skin = float(background @ np.array([0.299, 0.587, 0.114]))
    mark, dark = (0.8, 0.7) if faint else (0.62, 0.5)
    return (lum < skin * mark) & inside, (lum < skin * dark) & inside, background


def _mouth_candidates(region, inside, eye_height, screen, faint, smallest):
    """Marks darker than the skin, big enough and with the face colour around them (collars and jaws are not)."""
    mark, dark, background = _mouth_marks(region, inside, eye_height, screen, faint)
    face = _close(np.abs(region - background).sum(axis=2) < 60, 6)
    closing = min(3 if faint else 2, max(1, eye_height // 30))
    labels, parts = _components(_close(mark, closing))
    good = []
    for part in parts:
        piece = labels[part["y0"]:part["y1"], part["x0"]:part["x1"]] == part["label"]
        if part["size"] < smallest or not dark[part["y0"]:part["y1"], part["x0"]:part["x1"]][piece].any():
            continue
        ring = face[max(0, part["y0"] - 6):part["y1"] + 6, max(0, part["x0"] - 6):part["x1"] + 6]
        if ring.mean() >= 0.55:
            good.append({**part, "pixels": labels == part["label"]})
    return good, background


def _strokes(strict, faint):
    """Whole strokes: a faint mark that holds a dark one is the complete line the dark pieces broke from."""
    whole = [part for part in faint if any(part["pixels"][dark["pixels"]].any() for dark in strict)]
    covered = [dark for dark in strict if not any(part["pixels"][dark["pixels"]].any() for part in whole)]
    return whole + covered if strict else faint


def _near_end(part, group, reach_x, reach_y):
    gx0, gx1 = min(p["x0"] for p in group), max(p["x1"] for p in group)
    gy0, gy1 = min(p["y0"] for p in group), max(p["y1"] for p in group)
    return (part["y1"] >= gy0 - reach_y and part["y0"] <= gy1 + reach_y
            and any(part["x1"] >= end - reach_x and part["x0"] <= end + reach_x for end in (gx0, gx1)))


def _grow(group, pool, reach_x, reach_y, widest, hops):
    for _ in range(hops):
        near = [p for p in pool if _near_end(p, group, reach_x, reach_y)
                and max(q["x1"] for q in group + [p]) - min(q["x0"] for q in group + [p]) <= widest]
        if not near:
            break
        group = group + near
        pool = [p for p in pool if all(p is not q for q in near)]
    return group


# A mouth stroke at least this share of the eye pair's width is wide enough for the face; a nose mark is narrower.
WIDE_MOUTH = 0.14


def _mouth_seed(strokes, middle, eye_width):
    """The stroke the mouth grows from. ``middle`` is the face's middle column and the row a tenth of the eye pair's
    width under the eyes. A stroke wide enough for the face wins (the topmost near the middle), so a nose mark above
    the mouth stays. Without one, the largest small mark in the middle, under that row and not upright, is the mouth:
    a small round «o» or a short line. A narrow upright stroke or a mark right under the eyes is a nose, and a mark
    off to the side is a jaw line or stubble, so none of them is ever taken."""
    centre, nose = middle
    wide = [part for part in strokes if part["x1"] - part["x0"] >= eye_width * WIDE_MOUTH]
    if wide:
        return min(wide, key=lambda part: part["y0"] + abs(_centre(part)[0] - centre) * 0.5)
    small = [part for part in strokes if part["x1"] - part["x0"] >= max(eye_width * 0.06, (part["y1"] - part["y0"]) * 0.75)
             and abs(_centre(part)[0] - centre) <= eye_width * 0.2 and _centre(part)[1] >= nose]
    return max(small, key=lambda part: part["size"], default=None)


def _mouth_parts(strict, faint, middle, span, eye_width):
    """The mouth: the stroke from ``_mouth_seed``, its broken pieces along the same line, then the small marks at
    its ends (a smirk's curled end, its arrow tip, a dimple). Left behind, those show as a stray stroke beside the
    drawn mouth. Growth only goes through an end, a little at a time, so moustaches, beards and jaws stay."""
    strokes = [p for p in _strokes(strict, faint) if p["x1"] - p["x0"] <= eye_width * 0.95 and p["y1"] - p["y0"] <= span * 0.6]
    seed = _mouth_seed(strokes, middle, eye_width)
    if seed is None:
        return []
    row = [p for p in strokes + faint if p is not seed and abs(_centre(p)[1] - _centre(seed)[1]) < span * 0.14]
    group = _grow([seed], row, eye_width * 0.1, span * 0.1, eye_width * 0.95, 8)
    if seed["x1"] - seed["x0"] < eye_width * WIDE_MOUTH:
        # A small mouth has no curled ends to take: both its ends are near the middle, under the nose.
        return group
    small = max(30, sum(part["size"] for part in group) * 0.35)
    taken = {id(part) for part in group}
    pool = [p for p in faint + strict if id(p) not in taken and p["size"] <= small
            and p["x1"] - p["x0"] <= eye_width * 0.35 and p["y1"] - p["y0"] <= span * 0.3]
    return _grow(group, pool, eye_width * 0.1, span * 0.22, eye_width * 0.95, 2)


# Textured faces ---------------------------------------------------------------
# A face drawn as a texture (falling code glyphs, scales, hatching) is light and dark everywhere: the gaps between
# its glyphs are as dark as a pen line against the glyphs, so every mark threshold took the whole face as one mark
# and no mouth was found, and a screen face's light marks were the glyphs, not a mouth. The animated mouth was then
# placed under the painted one and both showed.

# A share of the skin whose fine grain varies above this is a texture. A plain or paper skin is flat almost
# everywhere: the lines drawn on it (a nose, wrinkles, a moustache, stubble) vary on under a third of it.
TEXTURED = 0.5
# The face's grain is measured with the eye pair resampled to this width. A texture is finer than the drawing's own
# lines at that size; a small face's wrinkles and beard strands, a few pixels apart in the image, are not.
GRAIN_EYES = 256


def _grain(lum: np.ndarray, where: np.ndarray) -> float:
    """Share of ``where`` whose 3×3 neighbourhood varies by more than paper grain or noise does."""
    if not where.any():
        return 0.0
    lum = lum.astype(np.float32)
    mean, square = cv2.blur(lum, (3, 3)), cv2.blur(lum * lum, (3, 3))
    return float((np.sqrt(np.maximum(square - mean * mean, 0)) > 10)[where].mean())


def _skin(lum: np.ndarray, inside: np.ndarray, size: int) -> np.ndarray:
    """The face around its thick dark marks: where a grey closing of ``size``, a little wider than the gaps between
    a texture's glyphs, stays light. A big flat mouth or goatee is not the skin."""
    filled = np.where(inside, lum, np.median(lum[inside])).astype(np.float32)
    closed = cv2.morphologyEx(filled, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    return inside & (closed >= np.median(closed[inside]) * 0.5)


def _face_textured(region: np.ndarray, inside: np.ndarray, eye_height: int, eye_width: int) -> bool:
    """Whether the skin in a window under the eyes is a texture, measured with the eye pair ``GRAIN_EYES`` wide."""
    scale = GRAIN_EYES / max(1, eye_width)
    size = (max(1, round(region.shape[1] * scale)), max(1, round(region.shape[0] * scale)))
    lum = cv2.resize((region @ LUMA).astype(np.float32), size,
                     interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    inside = cv2.resize(inside.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
    if not inside.any():
        return False
    skin = _skin(lum, inside, max(3, int(eye_height * scale * 0.12)) | 1)
    return _grain(lum, ~_dilate(~skin, 1)) > TEXTURED


def _textured_mouth(region: np.ndarray, inside: np.ndarray, eye_height: int, eye_width: int, centre: float):
    """The painted mouth on a textured face. The darkest fifth of the skin (``_skin``, closed at a size from the
    eyes) is the texture's own ink; marks under half of it and thicker than the texture's grain (an opening of the
    same size) are what is painted on it. The mouth is one that is wide, at least twice as wide as tall (an open
    mouth too, not a goatee), near the middle and not running off the window's sides (the face's outline or hair);
    the topmost near the middle, as ``_mouth_seed`` takes it. Its thin ends, lost to the opening, are taken back."""
    lum = (region @ LUMA).astype(np.float32)
    size = max(3, int(eye_height * 0.12)) | 1
    skin = _skin(lum, inside, size)
    if not skin.any():
        return []
    black = (lum < np.percentile(lum[skin], 20) * 0.5) & inside
    labels, parts = _components(_open(black, size // 2))
    width, found = region.shape[1], []
    for part in parts:
        reach, _ = _components(black & _dilate(labels == part["label"], size))
        pixels = np.isin(reach, np.unique(reach[labels == part["label"]]))
        ys, xs = np.nonzero(pixels)
        mark = {"label": part["label"], "size": int(pixels.sum()), "x0": int(xs.min()), "y0": int(ys.min()),
                "x1": int(xs.max()) + 1, "y1": int(ys.max()) + 1, "pixels": pixels}
        w, h = mark["x1"] - mark["x0"], mark["y1"] - mark["y0"]
        if (eye_width * 0.25 <= w <= eye_width * 0.95 and w >= h * 2 and mark["x0"] > 0 and mark["x1"] < width
                and abs(_centre(mark)[0] - centre) <= eye_width * 0.2):
            found.append(mark)
    return [min(found, key=lambda mark: mark["y0"] + abs(_centre(mark)[0] - centre) * 0.5)] if found else []


def _mouth_window(width: int, eyes_box):
    """Where a mouth is looked for under the eyes: its columns, top row and the two depths tried."""
    x0, _y0, x1, y1 = eyes_box
    eye_height, eye_width = y1 - eyes_box[1], x1 - x0
    # Eyes peeking over sunglasses are short, the face under them is not: measure the face by the eyes' width too.
    span = max(eye_height, eye_width * 0.55)
    # A smirk's curled end can reach past the eyes' edge.
    rx0, rx1 = max(0, int(x0 - eye_width * 0.15)), min(width, int(x1 + eye_width * 0.15))
    # The second window reaches past sunglasses' lenses.
    depths = sorted({int(y1 + span * 1.35), int(y1 + max(span * 1.35, eye_width * 1.1))})
    return rx0, rx1, int(y1 + eye_height * 0.12), depths


def skin_textured(rgb: np.ndarray, alpha: np.ndarray, eyes_box) -> bool:
    """Whether the face under the eyes, where the mouth is looked for first, is a texture."""
    rx0, rx1, ry0, depths = _mouth_window(alpha.shape[1], eyes_box)
    inside = alpha[ry0:depths[0], rx0:rx1] > 200
    return bool(inside.any()) and _face_textured(rgb[ry0:depths[0], rx0:rx1].astype(float), inside,
                                                 eyes_box[3] - eyes_box[1], eyes_box[2] - eyes_box[0])


# Realistic faces --------------------------------------------------------------
# Drawn with realistic proportions (graphic-novel or tenebrist art: small eyes, eye bags and wrinkles as dark strokes,
# spectacles, moustaches, big flat black shadows), a face has its mouth far lower than a cartoon's: about 0.85–1.0 of
# the eye pair's width under the eye line, against 0.2–0.6 on the cartoon and anime casts. Taking the topmost wide mark
# under the eyes took an eye bag or a spectacle rim, wiped it and placed the mouth there. The flat shadows also join
# the nose, the mouth line and the cheek (or the rims, the moustache and the beard) into one mark, so the mouth is
# found as a thin stroke instead.

# The eyes are small against the head: the taller eye opening is at most this share of the head's width at the eye
# rows. Measured on the eyes' whole whites (``_whole_whites``): 0.058–0.079 on the realistic poses on hand, 0.109 and up
# on every cartoon or anime one; big round eyes behind spectacles measure 0.21 ...
REALISTIC_EYES = 0.1
# ... and not round: at most this share of the eye pair's width (0.18–0.25 realistic, three-quarter views included;
# 0.35 and up on round cartoon eyes, which a wide head of hair or a raised hand could make look small against the head).
REALISTIC_EYE_HEIGHT = 0.3
# Where the mouth is looked for and expected, in eye-pair widths under the eye line. The window starts under the eye
# bags and spectacle rims (down to ~0.44) and above the chin.
REALISTIC_WINDOW = (0.45, 1.35)
REALISTIC_MOUTH = 0.9
# A stroke is thin where its dark run down each column is at most this share of the eye pair's width: a pen line,
# not a shadow, a moustache or a filled nostril.
THIN_STROKE = 0.09


def _head_width(alpha: np.ndarray, eyes_box) -> float:
    """The figure's width at the eye rows: the median run of opaque pixels through the eye pair's middle column."""
    x0, y0, x1, y1 = eyes_box
    centre, widths = (x0 + x1) // 2, []
    for y in range(y0, y1):
        row = alpha[y] > 200
        if not row[centre]:
            continue
        left = np.flatnonzero(~row[:centre])
        right = np.flatnonzero(~row[centre:])
        widths.append((centre + (right[0] if len(right) else row.size - centre)) - (left[-1] + 1 if len(left) else 0))
    return float(np.median(widths)) if widths else 0.0


def _whole_whites(rgb: np.ndarray, alpha: np.ndarray, eyes_mask: np.ndarray) -> np.ndarray:
    """The eyes' whites with their shaded or tinted parts, which the eye search leaves out: the light, nearly grey
    blobs that touch what it found. Taking in something light beside an eye (a collar, grey hair) only makes the eye
    measure bigger, so a cartoon face is never taken for a realistic one by it."""
    colour = rgb.astype(np.int16)
    light = (colour.min(axis=2) > 190) & (colour.max(axis=2) - colour.min(axis=2) < 45) & (alpha > 200)
    _, labels = cv2.connectedComponents(_mask(light), connectivity=8)
    seen = np.unique(labels[eyes_mask & light])
    return eyes_mask | np.isin(labels, seen[seen > 0])


def eye_extent(rgb: np.ndarray, alpha: np.ndarray, eyes_box, eyes_mask: np.ndarray):
    """The box of the eyes' whole whites. ``find_eyes`` cuts a long almond white in two (it takes it for two eyes
    drawn touching) and may keep a half of each eye, so its box is narrower than the eye pair; a realistic face's
    mouth is placed from this one. ``eyes_box`` when the whites run into something light much wider than the eyes."""
    ys, xs = np.nonzero(_whole_whites(rgb, alpha, eyes_mask))
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    width, height = eyes_box[2] - eyes_box[0], eyes_box[3] - eyes_box[1]
    return box if box[2] - box[0] <= width * 1.5 and box[3] - box[1] <= max(height * 2, width * 0.5) else tuple(eyes_box)


def face_realistic(rgb: np.ndarray, alpha: np.ndarray, eyes_box, eyes_mask: np.ndarray) -> bool:
    """Whether the face has realistic proportions, measured from the eyes' whole openings and the head's width."""
    x0, y0, x1, y1 = eyes_box
    head = _head_width(alpha, eyes_box)
    below = slice(y1, min(alpha.shape[0], y1 + (y1 - y0))), slice(x0, x1)
    lit = alpha[below] > 200
    if not head or not lit.any():
        return False
    openings = eye_openings(rgb, alpha, _whole_whites(rgb, alpha, eyes_mask), np.median(rgb[below][lit], axis=0))
    tallest = max(int(np.ptp(np.flatnonzero((openings == value).any(axis=1)))) + 1 for value in np.unique(openings) if value)
    whole = eye_extent(rgb, alpha, eyes_box, eyes_mask)
    return tallest <= head * REALISTIC_EYES and tallest <= (whole[2] - whole[0]) * REALISTIC_EYE_HEIGHT


def _thin_strokes(region: np.ndarray, inside: np.ndarray, eye_width: int, faint: bool):
    """Dark pen strokes in ``region`` as marks, and the face colour around them: thin down each column, and a few
    pixels long across (hair strands of a moustache or beard hanging onto the mouth line are not)."""
    mark, _dark, background = _mouth_marks(region, inside, 0, False, faint)
    tall = cv2.morphologyEx(_mask(mark), cv2.MORPH_OPEN, np.ones((max(3, round(eye_width * THIN_STROKE)) + 1, 1), np.uint8)) > 0
    across = cv2.morphologyEx(_mask(mark & ~tall), cv2.MORPH_OPEN, np.ones((1, max(3, round(eye_width * 0.03))), np.uint8)) > 0
    # A closing joins a pen line broken by a pixel or two.
    labels, parts = _components(_close(across, 1))
    return [{**part, "pixels": labels == part["label"]} for part in parts], background


def _level(part, most: float = 35.0) -> bool:
    """Whether a mark runs within ``most`` degrees of level (its pixels' principal axis) and is wider than tall. A
    mouth drawn at a slant in a three-quarter view is level enough; a fold from the nose is not."""
    ys, xs = np.nonzero(part["pixels"])
    if part["x1"] - part["x0"] < part["y1"] - part["y0"] or len(xs) < 3:
        return False
    cov = np.cov(xs, ys)
    return abs(math.degrees(0.5 * math.atan2(2 * cov[0, 1], cov[0, 0] - cov[1, 1]))) <= most


def _realistic_mouth(rgb: np.ndarray, alpha: np.ndarray, eyes_box):
    """The painted mouth on a realistic face: in ``REALISTIC_WINDOW``, the level stroke (``_level``) at least a fifth
    of the eye pair wide, near the middle and not running into the window from its top or sides (a fold from the nose, a rim, a
    jaw line), nearest ``REALISTIC_MOUTH`` (a stroke under that row counts half as far again: a lip shadow or chin
    crease lies under the mouth); then its broken pieces along the same line."""
    x0, y0, x1, y1 = eyes_box
    eye_width, line = x1 - x0, (y0 + y1) / 2
    rx0, rx1 = max(0, int(x0 - eye_width * 0.15)), min(alpha.shape[1], int(x1 + eye_width * 0.15))
    ry0 = int(line + eye_width * REALISTIC_WINDOW[0])
    ry1 = min(alpha.shape[0], int(line + eye_width * REALISTIC_WINDOW[1]))
    region, inside = rgb[ry0:ry1, rx0:rx1].astype(float), alpha[ry0:ry1, rx0:rx1] > 200
    if ry1 - ry0 < 4 or inside.mean() < 0.2:
        raise FlatRigError("mouth_not_found", "No face was found where the mouth is")
    expected, middle = line + eye_width * REALISTIC_MOUTH - ry0, (x0 + x1) / 2 - rx0
    for faint in (False, True):
        strokes, background = _thin_strokes(region, inside, eye_width, faint)
        level = [p for p in strokes if eye_width * 0.2 <= p["x1"] - p["x0"] <= eye_width * 0.95
                 and p["y0"] > 0 and p["x0"] > 0 and p["x1"] < rx1 - rx0
                 and abs(_centre(p)[0] - middle) <= eye_width * 0.4 and _level(p)]
        if level:
            break
    if not level:
        raise FlatRigError("mouth_not_found", "No painted mouth was found where a realistic face has it")

    def distance(part):
        dy = _centre(part)[1] - expected
        return (dy * 1.5 if dy > 0 else -dy) + abs(_centre(part)[0] - middle) * 0.25
    seed = min(level, key=distance)
    pieces = [p for p in strokes if p is not seed and p["x1"] - p["x0"] <= eye_width * 0.5
              and abs(_centre(p)[1] - _centre(seed)[1]) < eye_width * 0.1]
    group = _grow([seed], pieces, eye_width * 0.1, eye_width * 0.06, eye_width * 0.95, 8)
    return _placed(alpha.shape, group, rx0, ry0, region.shape), background


def _placed(shape, parts, rx0: int, ry0: int, size):
    """The marks found in a window, as a mask and box of the whole figure."""
    mask = np.zeros(shape, bool)
    for part in parts:
        mask[ry0:ry0 + size[0], rx0:rx0 + size[1]] |= part["pixels"]
    ys, xs = np.nonzero(mask)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1), mask


def _hinted_mouth(rgb: np.ndarray, alpha: np.ndarray, eyes_box, screen: bool, near):
    """With a mouth hint: in a window around it, the mark (a drawn mark the face colour surrounds, or a thin stroke)
    nearest the hint, no farther than a fifth of the eye pair from it, and its pieces along the same line. Marks
    wider than the eye pair or taller than half of it (shadows, a beard, a moustache) are never taken."""
    x0, y0, x1, y1 = eyes_box
    eye_height, eye_width = y1 - y0, x1 - x0
    span = max(eye_height, eye_width * 0.55)
    hx, hy = near
    rx0, rx1 = max(0, int(hx - eye_width * 0.7)), min(alpha.shape[1], int(hx + eye_width * 0.7))
    ry0, ry1 = max(0, int(hy - eye_width * 0.4)), min(alpha.shape[0], int(hy + eye_width * 0.4))
    region, inside = rgb[ry0:ry1, rx0:rx1].astype(float), alpha[ry0:ry1, rx0:rx1] > 200
    if rx1 - rx0 < 4 or ry1 - ry0 < 4 or not inside.any():
        raise FlatRigError("mouth_not_found", "No face was found at the mouth hint")
    strict, background = _mouth_candidates(region, inside, eye_height, screen, False, 12)
    faint, _ = _mouth_candidates(region, inside, eye_height, screen, True, 5)
    # A thin stroke drawn at a slant is taller than a flat mark may be; it is still a line, not a shadow.
    thin = [] if screen else [p for p in _thin_strokes(region, inside, eye_width, False)[0] if p["y1"] - p["y0"] <= eye_width * 0.5]
    marks = [p for p in _strokes(strict, faint) if p["y1"] - p["y0"] <= span * 0.6] + thin
    marks = [p for p in marks if eye_width * 0.06 <= p["x1"] - p["x0"] <= eye_width * 0.95]
    px, py = hx - rx0, hy - ry0

    def gap(part):
        return math.hypot(max(part["x0"] - px, 0, px - part["x1"]), max(part["y0"] - py, 0, py - part["y1"]))
    marks = [p for p in marks if gap(p) <= eye_width * 0.2]
    if not marks:
        raise FlatRigError("mouth_not_found", "No painted mouth was found at the mouth hint")
    seed = min(marks, key=lambda part: (round(gap(part), 1), -part["size"]))
    row = [p for p in faint + strict if p is not seed and abs(_centre(p)[1] - _centre(seed)[1]) < span * 0.14
           and p["x1"] - p["x0"] <= eye_width * 0.5 and p["y1"] - p["y0"] <= span * 0.3]
    group = _grow([seed], row, eye_width * 0.1, span * 0.1, eye_width * 0.95, 8)
    return _placed(alpha.shape, group, rx0, ry0, region.shape), background


def find_mouth(rgb: np.ndarray, alpha: np.ndarray, eyes_box, screen: bool = False, *, realistic: bool = False, near=None):
    """Dark marks under the eyes that the face colour surrounds (so collars and jaws are skipped). ``near`` (a mouth
    hint, in figure pixels) searches only there; ``realistic`` (``face_realistic``) looks for a thin stroke lower down."""
    if near is not None or realistic:
        (box, mask), background = (_hinted_mouth(rgb, alpha, eyes_box, screen, near) if near is not None
                                   else _realistic_mouth(rgb, alpha, eyes_box))
        return box, mask, background
    x0, _y0, x1, y1 = eyes_box
    eye_height, eye_width = y1 - eyes_box[1], x1 - x0
    span = max(eye_height, eye_width * 0.55)
    rx0, rx1, ry0, depths = _mouth_window(alpha.shape[1], eyes_box)
    windows = []
    for depth in depths:
        region = rgb[ry0:depth, rx0:rx1].astype(float)
        inside = alpha[ry0:depth, rx0:rx1] > 200
        if not inside.any():
            raise FlatRigError("mouth_not_found", "No face was found under the eyes")
        strict, background = _mouth_candidates(region, inside, eye_height, screen, False, 12)
        # A thin pen-line mouth breaks into tiny faint pieces: a softer threshold and smaller pieces find them.
        faint, _ = _mouth_candidates(region, inside, eye_height, screen, True, 5)
        parts = _mouth_parts(strict, faint, ((rx1 - rx0) / 2, y1 + eye_width * 0.1 - ry0), span, eye_width)
        windows.append((depth, region, inside, background))
        if parts:
            break
    if not parts:
        # Every mark found above was the texture's. Only after both windows, so a plain face keeps what they find.
        for depth, region, inside, background in windows:
            if _face_textured(region, inside, eye_height, eye_width):
                parts = _textured_mouth(region, inside, eye_height, eye_width, (x0 + x1) / 2 - rx0)
            if parts:
                break
    if not parts:
        raise FlatRigError("mouth_not_found", "No painted mouth was found under the eyes")
    mask = np.zeros(alpha.shape, bool)
    for part in parts:
        mask[ry0:depth, rx0:rx1] |= part["pixels"]
    ys, xs = np.nonzero(mask)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1), mask, background




def stray_marks(rgb: np.ndarray, alpha: np.ndarray, eyes_box, mouth_box) -> bool:
    """After the wipe: a small dark mark still right beside where the painted mouth was (a smirk's curl, a dimple)
    would show next to the drawn mouth. Marks that run out of that box (a moustache, a beard, sunglasses, the jaw
    line) or are big belong to the character, not to the old mouth."""
    x0, y0, x1, y1 = eyes_box
    eye_width, span = x1 - x0, max(y1 - y0, (x1 - x0) * 0.55)
    mx0, my0, mx1, my1 = mouth_box
    zx0, zx1 = max(0, int(mx0 - eye_width * 0.15)), min(alpha.shape[1], int(mx1 + eye_width * 0.15))
    zy0, zy1 = max(0, int(my0 - span * 0.15)), min(alpha.shape[0], int(my1 + span * 0.15))
    region, inside = rgb[zy0:zy1, zx0:zx1].astype(float), alpha[zy0:zy1, zx0:zx1] > 200
    if region.size == 0 or not inside.any():
        return False
    marks, _ = _mouth_candidates(region, inside, y1 - y0, False, True, 6)
    height, width = region.shape[:2]
    return any(part["size"] <= (eye_width * 0.12) ** 2 and part["x0"] > 0 and part["y0"] > 0
               and part["x1"] < width and part["y1"] < height for part in marks)


def eyes_covered(rgb: np.ndarray, alpha: np.ndarray, eyes_box, eyes_mask: np.ndarray) -> bool:
    """Sunglasses: what was found as eyes is only their tops, with lenses under them far darker than the face
    around the eyes. Such a pose must not blink. A dark face (a red book cover) is not a lens."""
    x0, y0, x1, y1 = eyes_box
    grow = max(4, int((y1 - y0) * 0.3))
    ring = _dilate(eyes_mask, grow) & ~_dilate(eyes_mask, max(1, grow // 3)) & (alpha > 200)
    ring[y1:] = False
    below = slice(y1, min(alpha.shape[0], y1 + (y1 - y0))), slice(x0, x1)
    lit = alpha[below] > 200
    if not ring.any() or not lit.any():
        return False
    face = np.median(rgb[ring].astype(float), axis=0)
    pixels = rgb[below][lit].astype(float)
    lens = (np.abs(pixels - face).sum(axis=1) > 120) & (pixels @ LUMA < min(70.0, float(face @ LUMA) * 0.45))
    return bool(lens.mean() > 0.35)


def _texture_fill(pixels: np.ndarray, area: np.ndarray, grow: int) -> np.ndarray | None:
    """Fill ``area`` with the face's own texture: a copy of the face just above or below it, at the offset whose
    edge best continues the texture around the hole and whose brightness is the face's, blended in over a few pixels.
    Inpainting smears a texture into a smooth smudge. None when no such patch of face is in the figure."""
    rgb, alpha = pixels[..., :3].astype(np.float32), pixels[..., 3]
    feather = max(2, grow // 2)
    edge = _dilate(area, feather * 2) & ~area
    rows, cols = np.nonzero(edge)
    y0, y1, x0, x1 = int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1
    hole, seam = area[y0:y1, x0:x1], edge[y0:y1, x0:x1]
    held = np.flatnonzero(hole.any(axis=1))
    tall = int(held[-1] - held[0]) + 1
    # The copy starts clear of the hole and its edge, and stays within a few mouth heights of it.
    near, far = tall + feather * 4, tall * 3 + feather * 4
    sy0, sy1 = max(0, y0 - far), min(alpha.shape[0], y1 + far)
    sx0, sx1 = max(0, x0 - grow), min(alpha.shape[1], x1 + grow)
    search, patch = rgb[sy0:sy1, sx0:sx1], rgb[y0:y1, x0:x1]
    # For every offset at once: the mismatch along the edge, the brightness inside and any background it would copy.
    mismatch = cv2.matchTemplate(search, patch, cv2.TM_SQDIFF, mask=cv2.merge([seam.astype(np.float32)] * 3))
    level = cv2.matchTemplate(search @ LUMA.astype(np.float32), hole.astype(np.float32), cv2.TM_CCORR) / hole.sum()
    keyed = cv2.matchTemplate((alpha[sy0:sy1, sx0:sx1] <= 200).astype(np.float32), (hole | seam).astype(np.float32),
                              cv2.TM_CCORR)
    dy = np.arange(mismatch.shape[0])[:, None] + sy0 - y0
    dx = np.arange(mismatch.shape[1])[None, :] + sx0 - x0
    cost = np.sqrt(np.maximum(mismatch, 0) / (seam.sum() * 3)) + np.abs(level - float((patch @ LUMA)[seam].mean()))
    cost[(keyed > 0.5) | (np.abs(dy) < near) | (np.abs(dy) >= far) | (np.abs(dx) > grow)] = np.inf
    if not np.isfinite(cost).any():
        return None
    row, col = np.unravel_index(int(np.argmin(cost)), cost.shape)
    shift_y, shift_x = int(dy[row, 0]), int(dx[0, col])
    blend = cv2.GaussianBlur(_dilate(area, feather).astype(np.float32), (feather * 2 + 1, feather * 2 + 1), 0)
    blend[area] = 1.0
    ys, xs = np.nonzero(area | edge)
    weight = blend[ys, xs][:, None]
    out = pixels.copy()
    out[ys, xs, :3] = np.round(rgb[ys + shift_y, xs + shift_x] * weight + rgb[ys, xs] * (1 - weight)).astype(np.uint8)
    return out


def wipe(image: Image.Image, mask: np.ndarray, grow: int, textured: bool = False) -> Image.Image:
    """Paint the mouth out: inpainted, or filled with the face's texture when the face is ``textured``
    (``skin_textured``)."""
    pixels = np.array(image)
    area = _dilate(mask, grow)
    if textured:
        filled = _texture_fill(pixels, area, grow)
        if filled is not None:
            return Image.fromarray(filled)
    bgr = cv2.cvtColor(pixels[..., :3], cv2.COLOR_RGB2BGR)
    area = area.astype(np.uint8) * 255
    pixels[..., :3] = cv2.cvtColor(cv2.inpaint(bgr, area, max(3, grow + 2), cv2.INPAINT_TELEA), cv2.COLOR_BGR2RGB)
    return Image.fromarray(pixels)


# Drawing --------------------------------------------------------------------

def _arc(draw, centre, width, curve, height, ink, thickness, smirk=0.0) -> None:
    cx, cy = centre
    points = []
    for i in range(41):
        t = i / 40 * 2 - 1
        # curve > 0 smiles; smirk lifts the right corner.
        y = cy + curve * (1 - t * t) * height * 0.32 - curve * height * 0.16 - smirk * max(0.0, t) ** 2 * height * 0.28
        points.append((cx + t * width / 2, y))
    draw.line(points, fill=ink, width=thickness, joint="curve")
    radius = thickness / 2
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=ink)


def _open_mouth(image, draw, centre, width, height, style, ink, cavity, thickness, *, teeth=True, tongue=True) -> None:
    """A D-shaped open mouth: flatter top lip, round bottom."""
    ox, oy = centre
    outline = [(ox - math.cos(math.pi * i / 59) * width / 2, oy + math.sin(math.pi * i / 59) * height / 2) for i in range(60)]
    outline += [(ox + width / 2 - i / 29 * width, oy - (1 - (2 * i / 29 - 1) ** 2) * height * 0.125) for i in range(30)]
    draw.polygon(outline, fill=cavity)
    if teeth and not style["screen"]:
        _paste_inside(image, outline, TEETH, (ox - width / 2, oy - height, ox + width / 2, oy + height * 0.12), "rectangle")
    if tongue and not style["screen"]:
        _paste_inside(image, outline, TONGUE, (ox - width * 0.28, oy + height * 0.12, ox + width * 0.28, oy + height * 0.75), "ellipse")
    draw.line(outline + [outline[0]], fill=ink, width=thickness, joint="curve")


def draw_mouth(state: str, style: dict[str, Any]) -> Image.Image:
    """One paper mouth sprite (512×320, transparent), drawn at 4× and reduced for smooth edges."""
    width, height, k = SPRITE[0], SPRITE[1], 4
    image = Image.new("RGBA", (width * k, height * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    cx, cy, h = width * k / 2, height * k / 2, height * k
    base = width * k * style["width"]
    line = max(2, int(h * 0.045))
    ink, cavity = (SCREEN_INK, SCREEN_CAVITY) if style["screen"] else (INK, CAVITY)

    def opened(w, oh, shift=0.0, **flags):
        _open_mouth(image, draw, (cx, cy + shift * h), w, oh, style, ink, cavity, line, **flags)

    if state == "closed":
        _arc(draw, (cx, cy), base * 0.78, style["smile"], h, ink, line, style["smirk"])
    elif state == "pressed":
        _arc(draw, (cx, cy), base * 0.62, 0.02, h, ink, int(line * 1.5))
    elif state == "small":
        opened(base * 0.5, h * 0.22, tongue=False)
    elif state == "medium":
        opened(base * 0.72, h * 0.34)
    elif state == "wide":
        opened(base * 0.86, h * 0.58, 0.05)
    elif state in ("round", "pucker"):
        r = h * (0.22 if state == "round" else 0.13)
        draw.ellipse((cx - r * (0.9 if state == "round" else 0.85), cy - r, cx + r * (0.9 if state == "round" else 0.85), cy + r),
                     fill=cavity, outline=ink, width=line if state == "round" else int(line * 1.2))
    elif state == "bite":
        w2, h2 = base * 0.6, h * 0.2
        draw.rounded_rectangle((cx - w2 / 2, cy - h2 / 2, cx + w2 / 2, cy + h2 / 2), radius=h2 / 2, fill=cavity, outline=ink, width=line)
        if not style["screen"]:
            draw.rectangle((cx - w2 / 2 + line, cy - h2 / 2 + line, cx + w2 / 2 - line, cy + h2 * 0.1), fill=TEETH)
        draw.line((cx - w2 / 2, cy + h2 * 0.18, cx + w2 / 2, cy + h2 * 0.18), fill=ink, width=line)
    elif state == "tongue":
        opened(base * 0.62, h * 0.32, tongue=False)
        if not style["screen"]:
            draw.ellipse((cx - base * 0.14, cy - h * 0.06, cx + base * 0.14, cy + h * 0.12), fill=TONGUE, outline=ink, width=max(2, line // 2))
    else:
        raise FlatRigError("invalid_state", f"Unknown mouth state {state}")
    return image.resize(SPRITE, Image.LANCZOS)


def _guided_eyes(rgb: np.ndarray, alpha: np.ndarray, near, guide: dict[str, Any]):
    """The eyes at a hint as before; else at the landmarks' eyes, then by the search, then from their outlines."""
    if near is not None or "eyes" not in guide:
        return find_eyes(rgb, alpha, near=near)
    for attempt in (lambda: find_eyes(rgb, alpha, near=guide["eyes"]), lambda: find_eyes(rgb, alpha)):
        try:
            return attempt()
        except FlatRigError as error:
            if error.code != "eyes_not_found":
                raise
    return _outlined_eyes(rgb, alpha, guide["eye_outlines"])


def _pose_guides(image: Image.Image, crop, size, hint, landmarks) -> tuple[dict[str, Any], dict[str, Any]]:
    """The pose's hints and what the landmarks give that no hint does, in pixels of the cropped figure."""
    def inside(x, y):
        return min(max(x - crop[0], 0), size[0] - 1), min(max(y - crop[1], 0), size[1] - 1)
    hint, ignored = flat_rig_hints.trusted(hint, landmarks, image.size)
    points = {key: point for key, point in (hint or {}).items() if key not in ("mouthWidth", "exact")}
    near = {key: inside(point[0] / 100 * image.width, point[1] / 100 * image.height) for key, point in points.items()}
    guide = {key: value for key, value in face_landmarks.guides(landmarks).items() if key not in near}
    for key in ("eyes", "mouth"):
        if key in guide:
            guide[key] = inside(*guide[key])
    if "eye_outlines" in guide:
        guide["eye_outlines"] = [outline - np.array(crop[:2], dtype=float) for outline in guide["eye_outlines"]]
    if "mouth_points" in guide:
        guide["mouth_points"] = guide["mouth_points"] - np.array(crop[:2], dtype=float)
    if (hint or {}).get("mouthWidth"):
        # A width hint is the mouth corner to corner, in % of the pose image's width.
        near["mouthWidth"] = guide["mouth_width"] = hint["mouthWidth"] / 100 * image.width
    if ignored:
        guide["hint_ignored"] = ignored
    return near, guide


def _rig_mouth(figure, rgb, alpha, eyes_box, face_eyes, style, ink, mouth_near, realistic):
    """Find or place the mouth, preserving painted ink and the existing wipe policy."""
    ex0, ey0, ex1, ey1 = eyes_box
    try:
        mouth_box, mouth_mask, background = find_mouth(rgb, alpha, face_eyes, style["screen"], realistic=realistic,
                                                       near=mouth_near)
        found, colour = True, ink_colour(rgb, mouth_mask, background)
        if ink:
            # The painted mouth is the rest shape: nothing is wiped.
            rigged, wiped = figure, False
        else:
            grow = max(4, int((ey1 - ey0) * 0.08))
            rigged, wiped = wipe(figure, mouth_mask, grow, skin_textured(rgb, alpha, eyes_box)), True
        mx, my = (mouth_box[0] + mouth_box[2]) / 2, (mouth_box[1] + mouth_box[3]) / 2
        if ink:
            # The openings hang from the painted line itself, not from the middle of its box (a slanted line's box
            # is tall).
            my = float(np.median(np.nonzero(mouth_mask)[0]))
    except FlatRigError as error:
        if error.code != "mouth_not_found":
            raise
        rigged, wiped, found, colour, mouth_box = figure, False, False, None, None
        if mouth_near:
            mx, my = mouth_near
        elif realistic:
            mx, my = (face_eyes[0] + face_eyes[2]) / 2, (face_eyes[1] + face_eyes[3]) / 2 + (face_eyes[2] - face_eyes[0]) * REALISTIC_MOUTH
        else:
            # Under the eyes, where a cutout mouth sits: 0.19–0.31 of the eye-pair width on the six
            # production characters, so its median; nothing painted to wipe.
            mx, my = (ex0 + ex1) / 2, ey1 + (ex1 - ex0) * 0.28
        ring = alpha[ey1:min(alpha.shape[0], ey1 + (ey1 - ey0)), ex0:ex1] > 200
        background = np.median(rgb[ey1:min(alpha.shape[0], ey1 + (ey1 - ey0)), ex0:ex1][ring], axis=0) if ring.any() else np.array([200, 160, 130])
    return rigged, wiped, found, colour, mouth_box, mx, my, background


def rig_pose(image: Image.Image, style: dict[str, Any], hint: dict[str, list[float]] | None = None,
             landmarks: dict[str, Any] | None = None) -> dict[str, Any]:
    """Crop, find the face, wipe the painted mouth (paper mouths) and measure anchors for one keyed pose. ``hint``
    holds the pose's ``eyes`` and ``mouth`` points in % of ``image`` (``rig_hints``); ``landmarks`` are the face points
    ``face_landmarks.detect`` found on ``image``, used for what no hint gives."""
    if image.width * image.height > MAX_PIXELS:
        raise FlatRigError("image_too_large", "Use a pose image up to 16 megapixels")
    cleaned, crop = _figure_box(image)
    figure = cleaned.crop(crop)
    pixels = np.array(figure)
    rgb, alpha = pixels[..., :3], pixels[..., 3]
    near, guide = _pose_guides(image, crop, figure.size, hint, landmarks)
    face_size = (landmarks or {}).get("face")
    eyes_box, eyes_mask = _guided_eyes(rgb, alpha, near.get("eyes"), guide)
    ex0, ey0, ex1, ey1 = eyes_box
    covered = eyes_covered(rgb, alpha, eyes_box, eyes_mask)
    realistic = not style["screen"] and face_realistic(rgb, alpha, eyes_box, eyes_mask)
    # A realistic face's mouth is looked for and placed from the eyes' whole whites; a cartoon's as it always was.
    face_eyes = eye_extent(rgb, alpha, eyes_box, eyes_mask) if realistic else eyes_box
    # Warp mouths keep the painted mouth too; their line is placed from it, the hints and the landmarks (rig_warp).
    ink = style.get("mouthStyle") in ("ink", "warp")
    mouth_near = near.get("mouth") or guide.get("mouth")
    rigged, wiped, found, colour, mouth_box, mx, my, background = _rig_mouth(
        figure, rgb, alpha, eyes_box, face_eyes, style, ink, mouth_near, realistic)
    width, height = rigged.size
    warnings = ["eyes_low"] if ey0 / height > 0.4 else []
    if not found:
        warnings.append("mouth_not_found")
    if (guide.get("hint_ignored") or {}).get("far"):
        warnings.append("mouth_hint_ignored")
    elif wiped and stray_marks(np.array(rigged)[..., :3], alpha, face_eyes, mouth_box):
        warnings.append("stray_mark")
    sprite_width = _ink_sprite_width(mouth_box, guide, eyes_box) if ink else (ex1 - ex0) * style["mouth_scale"]
    lids = background if style["screen"] else _eye_skin(rgb, alpha, eyes_box, background)
    openings = eye_openings(rgb, alpha, eyes_mask, lids, style["screen"])
    ys, xs = np.nonzero(openings)
    # The whole openings, not just the whites: an anime iris and its lid reach past them.
    ox0, oy0, ox1, oy1 = min(ex0, int(xs.min())), min(ey0, int(ys.min())), max(ex1, int(xs.max()) + 1), max(ey1, int(ys.max()) + 1)
    pad = int((oy1 - oy0) * 0.25)
    bx0, by0, bx1, by1 = _blink_box(max(0, ox0 - pad), max(0, oy0 - pad), min(width, ox1 + pad), min(height, oy1 + pad), height)
    return {
        "image": rigged, "before": figure, "width": width, "height": height, "wiped": wiped, "found": found,
        "realistic": realistic, "ink": colour, "skin": tuple(int(v) for v in background), "blinks": not covered,
        "warnings": warnings,
        "mouth": _anchor(mx, my, sprite_width * SPRITE[1] / SPRITE[0], width, height),
        "eyes": _anchor((bx0 + bx1) / 2, (by0 + by1) / 2, by1 - by0, width, height),
        "blink": blink_sprite(rgb[by0:by1, bx0:bx1], openings[by0:by1, bx0:bx1], lids, style["screen"],
                              alpha[by0:by1, bx0:bx1]),
        "eyes_box": list(eyes_box), "mouth_box": list(mouth_box) if mouth_box else None,
        "guided": sorted(key for key in ("eyes", "mouth") if key in guide),
        # Where the figure was cut from the pose image and that image's size; the warp mouths' seeds in figure pixels.
        "frame": (crop[0], crop[1], image.width, image.height),
        "seeds": {"point": near.get("mouth"), "width": near.get("mouthWidth"), "lips": guide.get("mouth_points"),
                  "lips_score": guide.get("mouth_score"), "face": face_size, "exact": bool((hint or {}).get("exact")),
                  "hint_ignored": guide.get("hint_ignored")},
        # The head's size class and the landmark pass (face_landmarks.detect); warp mouths add their enlargement.
        "face_size": face_size,
    }


def place(base: Image.Image, overlay: Image.Image, anchor: dict[str, float]) -> Image.Image:
    """Composite ``overlay`` on ``base`` the way the kit binds it (height = scale × longer edge)."""
    out = base.copy()
    edge = max(out.size)
    h = max(1, int(round(anchor["scale"] * edge)))
    w = max(1, int(round(h * overlay.width / overlay.height)))
    cx, cy = out.width / 2 + anchor["offsetX"] * edge / 100, out.height / 2 + anchor["offsetY"] * edge / 100
    out.alpha_composite(overlay.resize((w, h), Image.LANCZOS), (int(round(cx - w / 2)), int(round(cy - h / 2))))
    return out


def _face_crop(image: Image.Image, rig: dict[str, Any]) -> Image.Image:
    """The face from the eyes to below the mouth, where a wrong placement or a leftover stroke shows. A realistic
    face's mouth is lower than the usual crop reaches: the crop then goes down to it."""
    x0, y0, x1, y1 = rig["eyes_box"]
    width, span = x1 - x0, max(y1 - y0, (x1 - x0) * 0.55)
    mouth = image.height / 2 + rig["mouth"]["offsetY"] * max(image.size) / 100 if rig.get("mouth") else 0
    return image.crop((max(0, int(x0 - width * 0.25)), max(0, int(y0 - span * 0.2)),
                       min(image.width, int(x1 + width * 0.25)), min(image.height, int(max(y1 + span * 1.7, mouth + span * 0.5)))))


def _tile(frame: Image.Image, height: int, warn: bool) -> Image.Image:
    tile = frame.resize((max(1, int(frame.width * height / frame.height)), height), Image.LANCZOS)
    if warn:
        framed = Image.new("RGBA", tile.size, (0, 0, 0, 0))
        framed.alpha_composite(tile)
        ImageDraw.Draw(framed).rectangle((0, 0, tile.width - 1, tile.height - 1), outline=(220, 30, 30, 255), width=6)
        return framed
    return tile


def _caption(tile: Image.Image, text: str) -> None:
    """``text`` (comma-separated parts) on the tile's bottom-left corner, a part per line where the tile is narrow."""
    draw = ImageDraw.Draw(tile)
    lines: list[str] = []
    for part in text.split(", "):
        if lines and draw.textlength(f"{lines[-1]}, {part}") + 8 <= tile.width:
            lines[-1] = f"{lines[-1]}, {part}"
        else:
            lines.append(part)
    top = tile.height - 14 * len(lines) - 2
    right = min(tile.width, 8 + max(draw.textlength(line) for line in lines))
    draw.rectangle((0, top, right, tile.height), fill=(20, 20, 24, 255))
    for index, line in enumerate(lines):
        draw.text((4, top + 1 + 14 * index), line, fill=(255, 255, 255, 255))


def review_sheet(poses: dict[str, dict[str, Any]], mouths: dict[str, Image.Image], height: int = 360) -> Image.Image:
    """Per pose: the rig with its rest mouth, then an open mouth with the blink; below, the face before and after the
    wipe, enlarged. Poses with warnings are framed in red."""
    rows: list[list[Image.Image]] = [[], []]
    for rig in poses.values():
        warn = bool(rig.get("warnings"))
        # Warp mouths are the pose's own; the rest share the kit's.
        own = rig.get("sprites") or mouths
        rest = place(rig["image"], own["closed"], rig["mouth"])
        # Each pose shows its own blink at its eye anchor, as the kit plays it; covered eyes do not blink.
        talk = place(rig["image"], own["wide"], rig["mouth"])
        talk = place(talk, rig["blink"], rig["eyes"]) if rig["blinks"] else talk
        rows[0] += [_tile(rest, height, warn), _tile(talk, height, warn)]
        if rig.get("before") is not None and rig.get("eyes_box"):
            after = talk if rig.get("sprites") else rig["image"]
            rows[1] += [_tile(_face_crop(rig["before"], rig), height // 2, warn), _tile(_face_crop(after, rig), height // 2, warn)]
            if "openRatio" in (rig.get("mouth") or {}):
                _caption(rows[1][-1], opening_caption(rig["mouth"]))
        if rig.get("face_size"):
            # How the face was read and warped (a small face's on it enlarged), on the rest tile's corner.
            _caption(rows[0][-2], face_caption(rig["face_size"]))
    width = max(sum(tile.width for tile in row) + 8 * (len(row) + 1) for row in rows)
    sheet = Image.new("RGBA", (width, height + height // 2 + 24), (255, 255, 255, 255))
    for top, row in ((8, rows[0]), (height + 16, rows[1])):
        x = 8
        for tile in row:
            sheet.alpha_composite(tile, (x, top))
            x += tile.width + 8
    return sheet


# A whole kit ----------------------------------------------------------------

def _kit_warnings(rigs: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Poses to look at before using the kit. eyes_unlike_base: the eyes found are much smaller or bigger, against the
    figure's height, than the base pose's (another pair of light shapes, a collar, was taken for them)."""
    def eye_size(rig: dict[str, Any]) -> float:
        x0, _y0, x1, _y1 = rig["eyes_box"]
        return (x1 - x0) / max(1, rig["height"])
    base = eye_size(rigs["base"]) if rigs.get("base") else None
    found = {}
    for pose, rig in rigs.items():
        codes = list(rig.get("warnings") or [])
        if base and pose != "base" and not 0.7 <= eye_size(rig) / base <= 1.4:
            codes.append("eyes_unlike_base")
        rig["warnings"] = codes
        if codes:
            found[pose] = codes
    return found


def _workspace_file(source: str, workspace: str, workspace_dir: str) -> str:
    parsed = urlparse(source)
    if not parsed.path.startswith("/api/v1/file/"):
        raise FlatRigError("unsupported_source", "Pose images must be workspace files (/api/v1/file/...)")
    owner = (parse_qs(parsed.query).get("workspace") or [workspace])[0]
    if owner != workspace:
        raise FlatRigError("unsupported_source", "Pose images must belong to this workspace")
    name = unquote(parsed.path[len("/api/v1/file/"):])
    root = os.path.realpath(workspace_dir)
    path = os.path.realpath(os.path.join(root, name))
    if os.path.dirname(path) != root and not path.startswith(root + os.sep):
        raise FlatRigError("unsupported_source", "Pose images must stay inside the workspace")
    if not os.path.isfile(path):
        raise FlatRigError("missing_source", f"Pose image is missing: {name}", 409)
    return path


def _save(image: Image.Image, directory: str, stem: str) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()
    name = f"{stem}-{hashlib.sha256(data).hexdigest()[:8]}.png"
    with open(os.path.join(directory, name), "wb") as handle:
        handle.write(data)
    return name


def _url(name: str, workspace: str) -> str:
    return f"/api/v1/file/{name}?workspace={workspace}"


def _original_sources(kit: dict[str, Any]) -> dict[str, str]:
    """A re-rig starts from the images with painted mouths, recorded by the first rig."""
    for entry in reversed(kit.get("provenance") or []):
        if entry.get("method") == "flat-rig" and isinstance(entry.get("sources"), dict):
            return dict(entry["sources"])
    return {}


def _saved_hints(kit: dict[str, Any]) -> dict[str, dict[str, list[float]]]:
    """The hints the last rig used, so a re-rig places each pose the same way. A provenance edited by hand into
    something that is not hints is ignored rather than blocking every later rig."""
    for entry in reversed(kit.get("provenance") or []):
        if entry.get("method") == "flat-rig":
            try:
                return {pose: hint for pose, hint in rig_hints(entry.get("hints")).items() if hint}
            except FlatRigError:
                return {}
    return {}


def _kit_hints(kit: dict[str, Any], hints: Any) -> dict[str, dict[str, list[float]]]:
    """The saved hints with this call's on top: a pose's hints replace its saved ones, and null or {} clears them."""
    asked = rig_hints(hints)
    poses = {"base", *(kit.get("poses") or {})}
    unknown = sorted(pose for pose in asked if pose not in poses)
    if unknown:
        raise FlatRigError("unknown_pose", f"Hints name poses the character does not have: {', '.join(unknown)}")
    merged = {pose: hint for pose, hint in _saved_hints(kit).items() if pose in poses}
    for pose, hint in asked.items():
        if hint:
            merged[pose] = hint
        else:
            merged.pop(pose, None)
    return merged


def _kit_mouths(rigs: dict[str, dict[str, Any]], look: dict[str, Any]) -> dict[str, Image.Image]:
    """Paper mouths, ink mouths in the base pose's painted ink (another pose's when the base has no painted mouth), or
    the base pose's own warp mouths."""
    if look.get("mouthStyle") == "warp":
        return rigs["base"]["sprites"]
    if look.get("mouthStyle") != "ink":
        return {state: draw_mouth(state, look) for state in STATES}
    painted = [rig for pose, rig in sorted(rigs.items(), key=lambda item: item[0] != "base") if rig.get("ink")]
    ink, skin = (painted[0]["ink"], painted[0]["skin"]) if painted else (INK, (200, 160, 130))
    return {state: draw_ink_mouth(state, ink, skin) for state in STATES}


def _overlay(kit_id: str, name: str, label: str, file: str, workspace: str) -> dict[str, Any]:
    return {"id": f"{kit_id}-{label}"[:120], "name": f"{name} {label}"[:240], "source": _url(file, workspace),
            "kind": "overlay", "alphaStatus": "transparent", "reviewState": "approved", "workspace": workspace}


def pose_source(kit: dict[str, Any], pose: str) -> str:
    """The image a pose is rigged from: the recorded original only stands in for this rig's own output; a pose replaced
    since then is rigged as given."""
    current = (kit.get("base") if pose == "base" else (kit.get("poses") or {}).get(pose))["source"]
    original = _original_sources(kit).get(pose)
    return original if original and f"kit-{kit.get('id', '')}-{pose}-rig-" in current else current


def _rig_poses(kit: dict[str, Any], style, workspace: str, workspace_dir: str, pose_ids, hints=None):
    assets = {"base": kit.get("base"), **(kit.get("poses") or {})}
    wanted = list(pose_ids) if pose_ids else [pose for pose, asset in assets.items() if asset]
    if "base" not in wanted or not assets.get("base"):
        raise FlatRigError("missing_base", "Approve a base pose before rigging; the blink comes from it", 409)
    rigs, sources = {}, {}
    for pose in wanted:
        if not assets.get(pose):
            raise FlatRigError("unknown_pose", f"The character has no pose {pose}")
        sources[pose] = pose_source(kit, pose)
        with Image.open(_workspace_file(sources[pose], workspace, workspace_dir)) as image:
            landmarks = face_landmarks.detect(image)
            try:
                rigs[pose] = rig_pose(image, style, (hints or {}).get(pose), landmarks)
            except FlatRigError as error:
                raise FlatRigError(error.code, f"Pose {pose}: {error}", error.status) from error
        # Which way the pose looks, from the same landmarks (pose_facing): stored on the pose for look room.
        rigs[pose]["facing"] = pose_facing.from_landmarks(landmarks)
        if style["mouthStyle"] == "warp":
            warped = flat_rig_warp.rig_warp(rigs[pose])
            rigs[pose].update(warped, warnings=rigs[pose]["warnings"] + warped["warnings"])
    return rigs, sources


def _mouth_files(rigs: dict[str, dict[str, Any]], mouths: dict[str, Image.Image], kit_id: str, workspace_dir: str):
    """The kit's mouth files and each pose's own (warp mouths, ``{pose: {state: file}}``); with warp mouths the kit's
    are the base pose's."""
    own = {pose: {state: _save(sprite, workspace_dir, f"kit-{kit_id}-{pose}-mouth-{state}") for state, sprite in rig["sprites"].items()}
           for pose, rig in rigs.items() if rig.get("sprites")}
    return own.get("base") or {state: _save(mouths[state], workspace_dir, f"kit-{kit_id}-mouth-{state}") for state in STATES}, own


def _pose_reports(rigs: dict[str, dict[str, Any]], placed: dict) -> dict[str, dict[str, Any]]:
    """Pose-local mouth, blink, landmark and placement reports returned with the saved kit."""
    return {pose: {"mouth": rig["mouth"], "eyes": rig["eyes"], "wiped": rig["wiped"], "mouthFound": rig["found"],
                   "face": "realistic" if rig["realistic"] else "cartoon", "blinks": rig["blinks"],
                   "landmarks": rig["guided"], **({"mouthLine": rig["line"]} if "line" in rig else {}),
                   **({"faceSize": rig["face_size"]} if rig.get("face_size") else {}),
                   **({"facing": rig["facing"]} if rig.get("facing") else {}),
                   **({"hintIgnored": rig["seeds"]["hint_ignored"]} if (rig.get("seeds") or {}).get("hint_ignored") else {}),
                   **({"hints": placed[pose]} if pose in placed else {})}
            for pose, rig in rigs.items()}


def rig_character(workspace_dir: str, workspace: str, kit_id: str, *, base_revision: int,
                  style: Any = None, pose_ids: list[str] | None = None, hints: Any = None) -> dict[str, Any]:
    """Rig the kit's base and poses, write the images to the workspace and save the kit. ``style`` keys left out keep
    the kit's look (``kit_look``). ``hints`` (``rig_hints``) are kept in the provenance with the ones saved before, and
    a later rig reuses them."""
    library = read_character_kit_library(workspace_dir)
    kit = copy.deepcopy((library.get("kits") or {}).get(kit_id))
    if kit is None:
        raise FlatRigError("character_not_found", "Character not found", 404)
    look = kit_look(kit, style)
    placed = _kit_hints(kit, hints)
    rigs, sources = _rig_poses(kit, look, workspace, workspace_dir, pose_ids, placed)
    mouths = _kit_mouths(rigs, look)
    attach_openings(rigs, mouths)
    name = kit.get("name") or kit_id
    shared, own_mouths = _mouth_files(rigs, mouths, kit_id, workspace_dir)
    kit["mouth"] = {state: _overlay(kit_id, name, f"mouth-{state}", shared[state], workspace) for state in STATES}
    kit["mouthMapping"] = dict(MAPPING)
    blink_file = _save(rigs["base"]["blink"], workspace_dir, f"kit-{kit_id}-blink")
    kit["eyes"] = {"blink": _overlay(kit_id, name, "blink", blink_file, workspace)}
    anchors, facings = dict(kit.get("anchors") or {}), pose_facing.rigged_facings(kit)
    for pose, rig in rigs.items():
        file = _save(rig["image"], workspace_dir, f"kit-{kit_id}-{pose}-rig")
        target = kit["base"] if pose == "base" else kit["poses"][pose]
        target.update({"source": _url(file, workspace), "width": rig["width"], "height": rig["height"],
                       "alphaStatus": "transparent", "workspace": workspace})
        facings[pose] = pose_facing.settle(target, rig["facing"], facings.get(pose))
        # Each pose closes its own eyes: the base blink, scaled to another pose's eye height, left the
        # sclera showing wherever the eyes sit wider apart or larger than in the base.
        own = {"blinkSource": _url(_save(rig["blink"], workspace_dir, f"kit-{kit_id}-{pose}-blink"), workspace)} if rig["blinks"] else {}
        if pose in own_mouths:
            # Warp mouths are cut from this pose's own drawing: they are its own, in place of the kit's.
            own["mouthSources"] = {state: _url(file, workspace) for state, file in own_mouths[pose].items()}
        anchors[pose] = {"mouth": rig["mouth"], "eyes": rig["eyes"], **own, **({} if rig["blinks"] else {"blink": False})}
    kit["anchors"] = anchors
    kit["style"] = "cutout"
    warnings = _kit_warnings(rigs)
    sheet = _save(review_sheet(rigs, mouths), workspace_dir, f"kit-{kit_id}-rig-review")
    # Poses whose painted mouth was not found (with ink mouths nothing is wiped on purpose).
    unwiped = sorted(pose for pose, rig in rigs.items() if not rig["found"])
    kit["provenance"] = [*(kit.get("provenance") or []), {
        "method": "flat-rig", "sources": {**_original_sources(kit), **sources}, "style": look, "hints": placed,
        "facings": {pose: facing for pose, facing in facings.items() if facing},
        "unwipedPoses": unwiped, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **({"mouthLines": {pose: rig["line"] for pose, rig in rigs.items()}} if look["mouthStyle"] == "warp" else {}),
    }]
    saved = patch_character_kit(workspace_dir, kit_id, kit, base_revision=base_revision)
    return {
        "revision": saved.get("revision"), "character": saved["kits"][kit_id],
        "review": _url(sheet, workspace), "unwipedPoses": unwiped, "warnings": warnings, "style": look,
        "poses": _pose_reports(rigs, placed),
    }
