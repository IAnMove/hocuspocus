"""Eye detection, mask morphology and blink sprites for flat character rigs.

The eye pipeline depends only on image primitives and flat_rig_base; flat_rig
re-exports its existing names for callers and keeps landmark guidance there.
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image, ImageDraw

from services.flat_rig_base import INK, FlatRigError

SCREEN_INK = (245, 250, 255, 255)
_CROSS = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
LUMA = np.array([0.299, 0.587, 0.114])


def _mask(value: np.ndarray) -> np.ndarray:
    return value.astype(np.uint8)


def _open(mask: np.ndarray, iterations: int) -> np.ndarray:
    return cv2.morphologyEx(_mask(mask), cv2.MORPH_OPEN, _CROSS, iterations=iterations) > 0


def _close(mask: np.ndarray, iterations: int) -> np.ndarray:
    return cv2.morphologyEx(_mask(mask), cv2.MORPH_CLOSE, _CROSS, iterations=iterations) > 0


def _dilate(mask: np.ndarray, iterations: int) -> np.ndarray:
    return cv2.dilate(_mask(mask), _CROSS, iterations=iterations) > 0


def _components(mask: np.ndarray) -> tuple[np.ndarray, list[dict[str, int]]]:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(_mask(mask), connectivity=8)
    found = []
    for label in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[label])
        found.append({"label": label, "size": area, "x0": x, "y0": y, "x1": x + w, "y1": y + h})
    return labels, found




def _eye_pair(parts: list[dict[str, int]]) -> tuple[dict[str, int], dict[str, int]]:
    best = None
    for i in range(min(4, len(parts))):
        for j in range(i + 1, min(5, len(parts))):
            a, b = parts[i], parts[j]
            ratio = min(a["size"], b["size"]) / max(a["size"], b["size"])
            vertical = abs((a["y0"] + a["y1"]) - (b["y0"] + b["y1"])) / 2
            if ratio > 0.45 and vertical < (a["y1"] - a["y0"]) * 0.6 and (not best or a["size"] + b["size"] > best[0]):
                best = (a["size"] + b["size"], a, b)
    return (best[1], best[2]) if best else (parts[0], parts[1])


def _half(labels: np.ndarray, region: np.ndarray, part: dict[str, int], x0: int, x1: int, label: int) -> dict[str, int]:
    rows = np.flatnonzero(region[:, x0:x1].any(axis=1))
    labels[part["y0"]:part["y1"], part["x0"] + x0:part["x0"] + x1][region[:, x0:x1]] = label
    return {"label": label, "size": int(region[:, x0:x1].sum()), "x0": part["x0"] + x0, "x1": part["x0"] + x1,
            "y0": part["y0"] + int(rows[0]), "y1": part["y0"] + int(rows[-1]) + 1}


def _split_touching(labels: np.ndarray, parts: list[dict[str, int]]) -> list[dict[str, int]]:
    """Two eyes drawn touching each other come out as one wide blob: cut it at its narrowest column."""
    found, spare = [], int(labels.max()) + 1
    for part in parts:
        width, height = part["x1"] - part["x0"], part["y1"] - part["y0"]
        if width < 1.4 * height:
            found.append(part)
            continue
        region = labels[part["y0"]:part["y1"], part["x0"]:part["x1"]] == part["label"]
        low, high = int(width * 0.3), int(width * 0.7)
        cut = low + int(np.argmin(region.sum(axis=0)[low:high]))
        found += [_half(labels, region, part, 0, cut, part["label"]), _half(labels, region, part, cut, width, spare)]
        spare += 1
    return found


def _head_candidates(rgb: np.ndarray, alpha: np.ndarray):
    """Warm face regions constrain the small-eye fallback; shirts and chrome are not faces."""
    height, width = alpha.shape
    colour = rgb.astype(np.int16)
    skin = ((colour[..., 0] - colour[..., 2] > 35) & (colour[..., 1] - colour[..., 2] > 15)
            & (colour[..., 0] > 150) & (alpha > 200))
    skin[int(height * 0.4):] = False
    _, regions = _components(_open(skin, 2))
    for part in sorted(regions, key=lambda item: item["y0"]):
        w, h = part["x1"] - part["x0"], part["y1"] - part["y0"]
        centre = (part["x0"] + part["x1"]) / 2
        if (part["size"] > width * height * 0.001 and 0.04 * width < w < 0.65 * width
                and 0.035 * height < h < 0.23 * height and 0.1 * width < centre < 0.9 * width
                and part["y0"] < 0.22 * height and 0.4 < w / h < 2.5):
            yield part


def _small_face_eyes(rgb: np.ndarray, alpha: np.ndarray):
    """Find cream sclera and join fragments around a pupil inside a full-body character's face."""
    colour = rgb.astype(np.int16)
    white = (colour.min(axis=2) > 210) & (colour.max(axis=2) - colour.min(axis=2) < 25) & (alpha > 200)
    for face in _head_candidates(rgb, alpha):
        x0, x1, y0 = face["x0"], face["x1"], face["y0"]
        y1 = int(y0 + (face["y1"] - y0) * 0.8)
        region = np.zeros(alpha.shape, dtype=bool)
        region[y0:y1, x0:x1] = white[y0:y1, x0:x1]
        region = _open(_close(region, max(2, int((x1 - x0) * 0.08))), 1)
        centre = (x0 + x1) // 2
        labels, parts = _components(region)
        parts = [part for part in parts if part["size"] > 12]
        halves = [[part for part in parts if (part["x0"] + part["x1"]) / 2 < centre],
                  [part for part in parts if (part["x0"] + part["x1"]) / 2 >= centre]]
        if not all(halves):
            continue
        left, right = [min(half, key=lambda part: (part["y0"], -part["size"])) for half in halves]
        eye_height = max(left["y1"] - left["y0"], right["y1"] - right["y0"])
        vertical = abs((left["y0"] + left["y1"]) - (right["y0"] + right["y1"])) / 2
        if vertical < eye_height * 0.8:
            return labels, [left, right]
    return None


def light_sclera(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Pixels light enough to be sclera: every channel above 218, and nearly opaque."""
    return (rgb.min(axis=2) > 218) & (alpha > 200)


def _eye_components(rgb: np.ndarray, alpha: np.ndarray, top_fraction: float):
    height, width = alpha.shape
    white = light_sclera(rgb, alpha)
    white[int(height * top_fraction):] = False
    labels, parts = _components(_open(white, 2))
    parts = _split_touching(labels, parts)
    parts = sorted((part for part in parts if part["size"] > width * height * 0.0015), key=lambda part: -part["size"])
    if len(parts) < 2 and parts and parts[0]["size"] > width * height * 0.05:
        raise FlatRigError("face_too_light", "The face is as light as the eyes; give the character a skin colour")
    if len(parts) < 2:
        fallback = _small_face_eyes(rgb, alpha)
        if fallback is not None:
            labels, parts = fallback
    if len(parts) < 2:
        raise FlatRigError("eyes_not_found", "Two light eyes were not found in the top half of the pose")
    return labels, parts


def _hinted_pair(parts, near) -> tuple[dict[str, int], dict[str, int]] | None:
    """The largest pair of similar light blobs side by side whose box, grown by a quarter of its width, holds ``near``.
    The largest, not the nearest: a pupil's two highlights are a smaller pair at the same place."""
    hx, hy = near
    best = None
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            tall = max(a["y1"] - a["y0"], b["y1"] - b["y0"])
            if (min(a["size"], b["size"]) / max(a["size"], b["size"]) < 0.3 or abs(_centre(a)[1] - _centre(b)[1]) > tall * 0.8
                    or (a["x0"] < b["x1"] and b["x0"] < a["x1"])):
                continue
            x0, y0 = min(a["x0"], b["x0"]), min(a["y0"], b["y0"])
            x1, y1 = max(a["x1"], b["x1"]), max(a["y1"], b["y1"])
            grow = (x1 - x0) * 0.25
            if x0 - grow <= hx <= x1 + grow and y0 - grow <= hy <= y1 + grow and (not best or a["size"] + b["size"] > best[0]):
                best = (a["size"] + b["size"], a, b)
    return (best[1], best[2]) if best else None


def _with_fragments(labels: np.ndarray, eye: dict[str, int], parts, other: dict[str, int]) -> dict[str, int]:
    """One eye's white and the pieces of it a pupil cut off: blobs beside it, within its height, on its rows."""
    eye = dict(eye)
    height = eye["y1"] - eye["y0"]
    for part in parts:
        if (part["label"] in (eye["label"], other["label"]) or part["y1"] <= eye["y0"] or part["y0"] >= eye["y1"]
                or max(part["x0"] - eye["x1"], eye["x0"] - part["x1"]) > height
                or other["x0"] < _centre(part)[0] < other["x1"]):
            continue
        labels[labels == part["label"]] = eye["label"]
        eye.update(size=eye["size"] + part["size"], x0=min(eye["x0"], part["x0"]), x1=max(eye["x1"], part["x1"]),
                   y0=min(eye["y0"], part["y0"]), y1=max(eye["y1"], part["y1"]))
    return eye


def _eyes_near(rgb: np.ndarray, alpha: np.ndarray, near):
    """With an eyes hint: white or cream blobs anywhere in the figure, and the pair at the hint (``_hinted_pair``),
    each eye with the pieces its pupil cut off. Two eyes drawn touching are cut apart only when no pair is there
    whole: a long almond eye is not two eyes."""
    colour = rgb.astype(np.int16)
    white = (colour.min(axis=2) > 205) & (colour.max(axis=2) - colour.min(axis=2) < 40) & (alpha > 200)
    labels, found = _components(_open(white, 1))
    reach = max(alpha.shape) * 0.15
    for parts in (found, None):
        if parts is None:
            parts = _split_touching(labels, found)
        near_parts = sorted((part for part in parts if part["size"] >= 6 and abs(_centre(part)[0] - near[0]) <= reach
                             and abs(_centre(part)[1] - near[1]) <= reach), key=lambda part: -part["size"])[:12]
        pair = _hinted_pair(near_parts, near)
        if pair:
            left, right = sorted(pair, key=lambda part: part["x0"])
            return labels, [_with_fragments(labels, left, near_parts, right), _with_fragments(labels, right, near_parts, left)]
    raise FlatRigError("eyes_not_found", "No pair of light eyes was found at the eyes hint")


def find_eyes(rgb: np.ndarray, alpha: np.ndarray, top_fraction: float = 0.55, near=None):
    """The two largest white blobs of similar size side by side, in the top of the figure. With ``near`` (an eyes
    hint, in figure pixels) the pair at that point, anywhere in the figure."""
    labels, parts = _eyes_near(rgb, alpha, near) if near is not None else _eye_components(rgb, alpha, top_fraction)
    left, right = sorted(parts if near is not None else _eye_pair(parts), key=lambda part: part["x0"])
    mask = (labels == left["label"]) | (labels == right["label"])
    grow = max(4, int((left["y1"] - left["y0"]) * 0.3))
    around = _dilate(mask, grow * 2) & ~_dilate(mask, grow)
    if around.any() and (alpha[around] <= 200).mean() > 0.4:
        # The screen colour leaked into the skin and the key removed the face with the background.
        raise FlatRigError("face_keyed_out", "The face was removed with the background: its colour is too close to the screen colour. "
                                             "Choose another option or generate again")
    ring = _dilate(mask, grow) & ~_dilate(mask, max(1, grow // 3)) & (alpha > 200)
    if ring.any() and np.median(rgb[ring], axis=0).min() > 205:
        raise FlatRigError("face_too_light", "The face is as light as the eyes; give the character a skin colour")
    box = (min(left["x0"], right["x0"]), min(left["y0"], right["y0"]),
           max(left["x1"], right["x1"]), max(left["y1"], right["y1"]))
    return box, mask




def _centre(part):
    return (part["x0"] + part["x1"]) / 2, (part["y0"] + part["y1"]) / 2




# Blink ----------------------------------------------------------------------
# What find_eyes returns is only the white of each eye. An anime eye is mostly a big dark iris that touches a thick
# upper lid, with the white a thin crescent beside it: covering the white alone left the iris and the lid showing
# through a "closed" eye, and the colour taken around it (iris, lashes, hair) came out darker than the face.

def _fill_holes(mask: np.ndarray) -> np.ndarray:
    """The mask plus everything it encloses (a pupil inside the white, a highlight inside the iris)."""
    outside = np.pad(~mask, 1, constant_values=True).astype(np.uint8)
    _, labels = cv2.connectedComponents(outside, connectivity=4)
    return mask | (labels[1:-1, 1:-1] != labels[0, 0])


def _not_skin(rgb: np.ndarray, skin: np.ndarray, screen: bool) -> np.ndarray:
    """Pixels that are not the face: far from its colour or much darker. Face shading is neither."""
    colour = rgb.astype(float)
    far = np.abs(colour - skin).sum(axis=2) > 120
    # A screen face is dark itself: there only its light marks are not the face.
    return far if screen else far | (colour @ LUMA < float(skin @ LUMA) * 0.6)


def _upper_lid(dark: np.ndarray, opening: np.ndarray, cap: int) -> np.ndarray:
    """The dark lid line resting on the eye (thick anime lashes): in each column, the dark run straight above the
    opening. It is as thick as it is across the middle of the eye: a brow that joins it at a corner, or a thin
    outline with a brow on it, adds no more than that. A brow with skin between is never reached."""
    lid = np.zeros_like(opening)
    cols = np.flatnonzero(opening.any(axis=0))
    if not len(cols) or cap < 1:
        return lid
    tops = opening[:, cols].argmax(axis=0)
    runs, alive = np.zeros(len(cols), int), np.ones(len(cols), bool)
    for step in range(1, cap + 1):
        alive &= tops - step >= 0
        alive[alive] = dark[(tops - step)[alive], cols[alive]]
        runs += alive
    middle = runs[len(cols) // 5:len(cols) - len(cols) // 5]
    thickness = min(cap, int(np.median(middle if len(middle) else runs)) + 1)
    rows = np.arange(opening.shape[0])[:, None]
    lid[:, cols] = (rows < tops) & (rows >= tops - np.minimum(runs, thickness))
    return lid


def _eye_opening(rgb: np.ndarray, alpha: np.ndarray, sclera: np.ndarray, skin: np.ndarray, x_limits: tuple[int, int],
                 screen: bool) -> np.ndarray:
    """One whole eye from its white: what is drawn inside the eye beside and in it (iris, pupil, highlights, the lid
    and lash lines) up to the skin, within the white's rows and ``x_limits``; then a dark upper lid resting on it,
    a little way up; then the holes. Brows and bangs above, and hair beside, stay outside."""
    ys, xs = np.nonzero(sclera)
    y0, y1, h = int(ys.min()), int(ys.max()) + 1, int(ys.max()) + 1 - int(ys.min())
    side, x0, x1 = int(h * 0.75), int(xs.min()), int(xs.max()) + 1
    wx0, wx1 = min(x0, max(x_limits[0], x0 - side)), max(x1, min(x_limits[1], x1 + side))
    reach = int(h * 0.3)
    # Below the white: the lower lid line, which can sit a few pixels under it.
    wy0, wy1 = max(0, y0 - reach - 1), min(alpha.shape[0], y1 + max(2, int(h * 0.25)))
    white, colour = sclera[wy0:wy1, wx0:wx1], rgb[wy0:wy1, wx0:wx1]
    inside = (_not_skin(colour, skin, screen) & (alpha[wy0:wy1, wx0:wx1] > 200)) | white
    # Above the white only the upper lid may be added, and only straight up: that is where brows and bangs are.
    top = max(0, y0 - max(1, int(h * 0.1)) - wy0)
    inside[:top] = white[:top]
    _, labels = cv2.connectedComponents(inside.astype(np.uint8), connectivity=4)
    opening = np.isin(labels, np.unique(labels[white]))
    border = np.zeros_like(opening)
    border[:, 0] = border[:, -1] = border[-1] = True
    if (opening & border & ~white).any():
        # Hair, a black socket shadow or the face's outline joined to the eye's lines runs out of the window: the eye
        # is what lies close round its white, not that whole shape.
        opening &= _dilate(_hull(white), max(2, int(h * 0.25)))
    if not screen:
        dark = (colour.astype(float) @ LUMA < float(skin @ LUMA) * 0.45) & (alpha[wy0:wy1, wx0:wx1] > 200)
        opening |= _upper_lid(dark, opening, reach)
    found = np.zeros(sclera.shape, bool)
    found[wy0:wy1, wx0:wx1] = _fill_holes(opening)
    return found


def _hull(mask: np.ndarray) -> np.ndarray:
    """The convex hull of a mask, filled."""
    points = cv2.findNonZero(_mask(mask))
    hull = np.zeros(mask.shape, np.uint8)
    if points is not None:
        cv2.fillConvexPoly(hull, cv2.convexHull(points), 1)
    return hull > 0


def _whole_white(rgb: np.ndarray, alpha: np.ndarray, white: np.ndarray, pair_width: int) -> np.ndarray:
    """One eye's white with its ivory or shaded parts: the eye search keeps only the brightest, at times a sliver
    beside the pupil, so the rest of the white showed round the closed lid. Light that runs on past the eye (a
    collar, grey hair: wider than half the eye pair) leaves the white as found."""
    colour = rgb.astype(np.int16)
    # Looser than the eye search: the white's shaded rim is greyer and darker, but never the saturated skin.
    light = (colour.min(axis=2) > 150) & (colour.max(axis=2) - colour.min(axis=2) < 60) & (alpha > 200)
    _, labels = cv2.connectedComponents(_mask(light), connectivity=8)
    seen = np.unique(labels[white & light])
    whole = white | np.isin(labels, seen[seen > 0])
    ys, xs = np.nonzero(white)
    height, width = int(np.ptp(ys)) + 1, int(np.ptp(xs)) + 1
    wys, wxs = np.nonzero(whole)
    if (np.ptp(wxs) + 1 > max(width * 1.8, height * 3, pair_width * 0.6)
            or np.ptp(wys) + 1 > max(height * 2.5, width * 0.9, pair_width * 0.35)):
        return white
    return whole


def eye_openings(rgb: np.ndarray, alpha: np.ndarray, eyes: np.ndarray, skin, screen: bool = False) -> np.ndarray:
    """Each eye's whole opening, labelled 1 (left) and 2 (right), grown from the whites ``find_eyes`` returns."""
    labels, parts = _components(eyes)
    if len(parts) == 1:
        # Two eyes drawn touching were found as two halves of one blob (find_eyes): cut it the same way again.
        parts = _split_touching(labels, parts)
    parts = sorted(sorted(parts, key=lambda part: -part["size"])[:2], key=lambda part: part["x0"])
    skin = np.asarray(skin, dtype=float)
    found = np.zeros(eyes.shape, np.uint8)
    for index, part in enumerate(parts):
        # Each eye may reach up to the other one's white, not a fixed middle: eyes looking aside have both irises on
        # the same side of their whites, one of them well past the middle between the whites.
        limits = (parts[0]["x1"] if index else 0, parts[1]["x0"] if index == 0 and len(parts) == 2 else eyes.shape[1])
        white = labels == part["label"]
        if not screen:
            white = _whole_white(rgb, alpha, white, max(p["x1"] for p in parts) - min(p["x0"] for p in parts))
            white[:, :limits[0]] = white[:, limits[1]:] = False
        found[_eye_opening(rgb, alpha, white, skin, limits, screen) & (found == 0)] = index + 1
    return found


def _lid_colour(rgb: np.ndarray, alpha: np.ndarray, cover: np.ndarray, skin: np.ndarray) -> tuple[int, ...]:
    """The face colour right around one covered eye, from face pixels only (not iris, lashes or hair)."""
    grow = max(2, int(np.sqrt(cover.sum()) * 0.2))
    ring = _dilate(cover, grow) & ~cover & (alpha > 200)
    face = ring & (np.abs(rgb.astype(float) - skin).sum(axis=2) < 70)
    local = np.median(rgb[face], axis=0) if face.sum() >= 8 else skin
    return tuple(int(v) for v in local) + (255,)


def _shadow_lid(rgb: np.ndarray, alpha: np.ndarray, cover: np.ndarray, skin: np.ndarray) -> tuple[int, ...] | None:
    """The colour of a lid closed inside a flat black shadow: when most of the face round the covered eye is that
    shadow, the lid is too (a light almond in a shadowed socket gave the blink away). None when the eye is lit."""
    grow = max(2, int(np.sqrt(cover.sum()) * 0.3))
    ring = _dilate(cover, grow) & ~cover & (alpha > 200)
    # A mass of shadow, not the wrinkles and lash strokes drawn round an eye.
    dark = ring & _open(rgb.astype(float) @ LUMA < float(skin @ LUMA) * 0.45, max(1, grow // 3))
    if ring.sum() < 8 or dark.sum() < ring.sum() * 0.55:
        return None
    return tuple(int(v) for v in np.median(rgb[dark], axis=0)) + (255,)


def _cover(opening: np.ndarray, face: np.ndarray, grow: int) -> np.ndarray:
    """The opening and a few pixels round it, so the cover's soft edge lies on skin, not on the eye's outline: onto
    the face, and over loose bits of the eye's lines left in that margin (lash tips, anti-aliased edges). A brow, hair
    or a scar that reaches into the margin from outside stays, and so does the background."""
    margin = _dilate(opening, grow) & ~opening
    count, labels = cv2.connectedComponents((~face & ~opening).astype(np.uint8), connectivity=8)
    loose = np.bincount(labels[margin], minlength=count) == np.bincount(labels.ravel(), minlength=count)
    loose[0] = False
    return opening | (margin & face) | loose[labels]


def blink_sprite(rgb: np.ndarray, eyes: np.ndarray, fallback, screen: bool = False,
                 alpha: np.ndarray | None = None) -> Image.Image:
    """Closed eyes: each eye's whole opening covered with the face colour around it, plus a lid line across it.

    ``eyes`` labels each eye's opening (``eye_openings``); a boolean mask is split into its parts."""
    height, width = eyes.shape
    k = 4
    image = Image.new("RGBA", (width * k, height * k), (0, 0, 0, 0))
    if eyes.dtype == bool:
        labels, parts = _components(eyes)
        values = [part["label"] for part in sorted(parts, key=lambda part: -part["size"])[:2]]
    else:
        labels, values = eyes, [int(value) for value in np.unique(eyes) if value]
    alpha = np.full(eyes.shape, 255, np.uint8) if alpha is None else alpha
    skin = np.asarray(fallback, dtype=float)
    face = ~_not_skin(rgb, skin, screen) & (alpha > 200)
    line = max(3, int(height * k * 0.035))
    colour = SCREEN_INK if screen else INK
    boxes, covers = [], []
    for value in values:
        opening = labels == value
        ys, xs = np.nonzero(opening)
        boxes.append((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
        covers.append(_cover(opening, face, max(2, int((ys.max() - ys.min()) * 0.08))))
    for cover in covers:
        mask = Image.fromarray((cover * 255).astype(np.uint8)).resize((width * k, height * k), Image.BILINEAR)
        # Composited, not pasted: a paste blends the colour with the transparent black around it, and that dark
        # fringe showed as a ring around each closed eye.
        shadow = None if screen else _shadow_lid(rgb, alpha, cover, skin)
        layer = Image.new("RGBA", image.size, shadow or _lid_colour(rgb, alpha, cover, skin))
        layer.putalpha(mask)
        image.alpha_composite(layer)
    draw = ImageDraw.Draw(image)
    for x0, y0, x1, y1 in boxes:
        x0, x1 = x0 * k, x1 * k
        lid = (y0 + (y1 - y0) * 0.58) * k
        sag = (y1 - y0) * k * 0.1
        points = [(x0 + (x1 - x0) * (0.08 + 0.84 * t / 20), lid + math.sin(math.pi * t / 20) * sag) for t in range(21)]
        draw.line(points, fill=colour, width=line, joint="curve")
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - line / 2, y - line / 2, x + line / 2, y + line / 2), fill=colour)
    # Averaged down, not Lanczos: its overshoot at the cover's edge drew a light ring around each closed eye.
    return image.resize((width, height), Image.BOX)


# One pose -------------------------------------------------------------------

# Video 2D fits every layer into a frame-shaped box: a sprite wider than 16:9 is drawn narrower than its anchor
# height says. A pair of round eyes is ~2.5:1, so the closed lids came out at ~70% and the eyes showed around them.
MAX_SPRITE_RATIO = 16 / 9


def _blink_box(x0: int, y0: int, x1: int, y1: int, height: int) -> tuple[int, int, int, int]:
    """The blink crop, grown upward and downward (transparent around the lids) until it is at most 16:9."""
    missing = math.ceil((x1 - x0) / MAX_SPRITE_RATIO) - (y1 - y0)
    if missing > 0:
        top = min(y0, (missing + 1) // 2)
        bottom = min(height - y1, missing - top)
        y0, y1 = y0 - top, y1 + bottom
        y0 -= min(y0, max(0, missing - top - bottom))
    return x0, y0, x1, y1


def _eye_skin(rgb: np.ndarray, alpha: np.ndarray, eyes_box, fallback) -> np.ndarray:
    """The face colour right under the eyes (the cheeks), which the lids are painted in. The colour found round the
    mouth is a beard's on a bearded face, and white lids closed over a monk's eyes."""
    x0, y0, x1, y1 = eyes_box
    region = slice(y1, min(alpha.shape[0], int(y1 + (x1 - x0) * 0.35))), slice(x0, x1)
    colour = rgb[region].astype(np.int16)
    lum = colour @ LUMA
    face = (alpha[region] > 200) & (colour.max(axis=-1) - colour.min(axis=-1) > 40) & (lum > 60) & (lum < 235)
    return np.median(rgb[region][face], axis=0) if face.sum() >= 20 else np.asarray(fallback, dtype=float)


def _outlined_eyes(rgb: np.ndarray, alpha: np.ndarray, outlines) -> tuple[tuple[int, int, int, int], np.ndarray]:
    """Eyes from the landmarks' outlines when no white blob is there to find (small or shaded eyes): the light pixels
    in and round each outline grown a little, or the outline itself with them. On a small face the points sit a pixel
    or two off the eye, and a highlight left out of the cover showed through the closed lid."""
    colour = rgb.astype(np.int16)
    light = (colour.min(axis=2) > 170) & (colour.max(axis=2) - colour.min(axis=2) < 60) & (alpha > 200)
    mask = np.zeros(alpha.shape, bool)
    for outline in outlines:
        shape = np.zeros(alpha.shape, np.uint8)
        cv2.fillPoly(shape, [np.round(np.asarray(outline)).astype(np.int32)], 1)
        width = max(2, int(np.ptp(np.asarray(outline)[:, 0])))
        shape = _dilate(shape > 0, max(1, int(width * 0.15)))
        white = _dilate(shape, max(2, int(width * 0.2))) & light
        mask |= white if white.sum() >= shape.sum() * 0.15 else shape | white
    if not mask.any():
        raise FlatRigError("eyes_not_found", "The eyes the landmarks found are outside the figure")
    ys, xs = np.nonzero(mask)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1), mask
