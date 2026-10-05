"""Rig a flat cutout character so it can talk: one call from a keyed pose to a Character Kit.

For each pose (an RGBA image with the background keyed out) this finds the two
white eyes and the painted mouth under them, wipes that mouth by inpainting,
and measures pose-local anchors. It then draws nine paper mouths and a blink
made from the base pose's own eye shapes. The result is saved on the kit.

It suits flat styles with light eyes on a plain face (paper cutout, simple
cartoon). A face that is a screen (a laptop or robot character) uses
``screen``: light marks on a dark screen. When no painted mouth is found the
mouth is placed under the eyes and nothing is wiped; the result says so.

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

from services.character_kit_library import patch_character_kit, read_character_kit_library

STATES = ("closed", "small", "wide", "round", "pressed", "medium", "pucker", "bite", "tongue")
MAPPING = {"rest": "closed", "M": "pressed", "A": "wide", "E": "medium", "I": "small",
           "O": "round", "U": "pucker", "F": "bite", "L": "tongue"}
SPRITE = (512, 320)
INK, CAVITY = (34, 22, 20, 255), (92, 26, 30, 255)
TEETH, TONGUE = (250, 248, 240, 255), (222, 98, 110, 255)
SCREEN_INK, SCREEN_CAVITY = (245, 250, 255, 255), (10, 22, 70, 255)
STYLE_LIMITS = {"smile": (-1.0, 1.0, 0.15), "smirk": (0.0, 1.0, 0.0), "width": (0.3, 0.9, 0.62),
                "mouth_scale": (0.4, 1.2, 0.78)}
MAX_PIXELS = 16_777_216
_CROSS = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))


class FlatRigError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def rig_style(value: Any) -> dict[str, Any]:
    """Mouth look: ``smile`` -1..1, ``smirk`` 0..1, ``width`` and ``mouth_scale``; ``screen`` for a screen face."""
    raw = value if isinstance(value, dict) else {}
    style: dict[str, Any] = {"screen": raw.get("screen") is True}
    for key, (low, high, default) in STYLE_LIMITS.items():
        number = raw.get(key, default)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not low <= float(number) <= high:
            raise FlatRigError("invalid_style", f"style.{key} must be a number from {low} to {high}")
        style[key] = float(number)
    return style


# Masks ----------------------------------------------------------------------

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


def crop_figure(image: Image.Image, margin: float = 0.02) -> Image.Image:
    image = _clean_alpha(image.convert("RGBA"))
    alpha = np.array(image)[..., 3]
    ys, xs = np.nonzero(alpha > 128)
    if not len(xs):
        raise FlatRigError("not_keyed", "The pose has no visible figure; key its background first")
    pad = int(max(image.size) * margin)
    return image.crop((max(0, xs.min() - pad), max(0, ys.min() - pad),
                       min(image.width, xs.max() + pad + 1), min(image.height, ys.max() + pad + 1)))


# Features -------------------------------------------------------------------

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


def _eye_components(rgb: np.ndarray, alpha: np.ndarray, top_fraction: float):
    height, width = alpha.shape
    white = (rgb.min(axis=2) > 218) & (alpha > 200)
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


def find_eyes(rgb: np.ndarray, alpha: np.ndarray, top_fraction: float = 0.55):
    """The two largest white blobs of similar size side by side, in the top of the figure."""
    labels, parts = _eye_components(rgb, alpha, top_fraction)
    left, right = sorted(_eye_pair(parts), key=lambda part: part["x0"])
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


def _centre(part):
    return (part["x0"] + part["x1"]) / 2, (part["y0"] + part["y1"]) / 2


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


def _mouth_parts(strict, faint, centre, span, eye_width):
    """The mouth: the topmost stroke near the middle, its broken pieces along the same line, then the small marks at
    its ends (a smirk's curled end, its arrow tip, a dimple). Left behind, those show as a stray stroke beside the
    drawn mouth. Growth only goes through an end, a little at a time, so moustaches, beards and jaws stay."""
    strokes = [p for p in _strokes(strict, faint) if p["x1"] - p["x0"] <= eye_width * 0.95 and p["y1"] - p["y0"] <= span * 0.6]
    if not strokes:
        return []
    seeds = [part for part in strokes if part["x1"] - part["x0"] >= eye_width * 0.14]
    if not seeds:
        return []
    seed = min(seeds, key=lambda part: part["y0"] + abs(_centre(part)[0] - centre) * 0.5)
    row = [p for p in strokes + faint if p is not seed and abs(_centre(p)[1] - _centre(seed)[1]) < span * 0.14]
    group = _grow([seed], row, eye_width * 0.1, span * 0.1, eye_width * 0.95, 8)
    small = max(30, sum(part["size"] for part in group) * 0.35)
    taken = {id(part) for part in group}
    pool = [p for p in faint + strict if id(p) not in taken and p["size"] <= small
            and p["x1"] - p["x0"] <= eye_width * 0.35 and p["y1"] - p["y0"] <= span * 0.3]
    return _grow(group, pool, eye_width * 0.1, span * 0.22, eye_width * 0.95, 2)


def find_mouth(rgb: np.ndarray, alpha: np.ndarray, eyes_box, screen: bool = False):
    """Dark marks under the eyes that the face colour surrounds (so collars and jaws are skipped)."""
    x0, _y0, x1, y1 = eyes_box
    eye_height, eye_width = y1 - eyes_box[1], x1 - x0
    # Eyes peeking over sunglasses are short, the face under them is not: measure the face by the eyes' width too.
    span = max(eye_height, eye_width * 0.55)
    # A smirk's curled end can reach past the eyes' edge.
    rx0, rx1 = max(0, int(x0 - eye_width * 0.15)), min(alpha.shape[1], int(x1 + eye_width * 0.15))
    ry0 = int(y1 + eye_height * 0.12)
    # The second window reaches past sunglasses' lenses.
    for depth in sorted({int(y1 + span * 1.35), int(y1 + max(span * 1.35, eye_width * 1.1))}):
        region = rgb[ry0:depth, rx0:rx1].astype(float)
        inside = alpha[ry0:depth, rx0:rx1] > 200
        if not inside.any():
            raise FlatRigError("mouth_not_found", "No face was found under the eyes")
        strict, background = _mouth_candidates(region, inside, eye_height, screen, False, 12)
        # A thin pen-line mouth breaks into tiny faint pieces: a softer threshold and smaller pieces find them.
        faint, _ = _mouth_candidates(region, inside, eye_height, screen, True, 5)
        parts = _mouth_parts(strict, faint, (rx1 - rx0) / 2, span, eye_width)
        if parts:
            break
    if not (strict or faint):
        raise FlatRigError("mouth_not_found", "No painted mouth was found under the eyes")
    if not parts:
        raise FlatRigError("mouth_not_found", "No painted mouth was found under the eyes")
    mask = np.zeros(alpha.shape, bool)
    for part in parts:
        mask[ry0:depth, rx0:rx1] |= part["pixels"]
    ys, xs = np.nonzero(mask)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1), mask, background


LUMA = np.array([0.299, 0.587, 0.114])


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


def wipe(image: Image.Image, mask: np.ndarray, grow: int) -> Image.Image:
    pixels = np.array(image)
    bgr = cv2.cvtColor(pixels[..., :3], cv2.COLOR_RGB2BGR)
    area = _dilate(mask, grow).astype(np.uint8) * 255
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


def _paste_inside(image, outline, fill, box_or_ellipse, kind) -> None:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).polygon(outline, fill=255)
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    getattr(ImageDraw.Draw(layer), kind)(box_or_ellipse, fill=fill)
    clip = Image.composite(layer, Image.new("RGBA", image.size, (0, 0, 0, 0)), mask)
    image.paste(layer, (0, 0), clip.split()[3])


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


def blink_sprite(rgb: np.ndarray, eyes: np.ndarray, fallback, screen: bool = False) -> Image.Image:
    """Closed eyes: each eye covered with the colour around it, plus a lid line."""
    height, width = eyes.shape
    k = 4
    image = Image.new("RGBA", (width * k, height * k), (0, 0, 0, 0))
    labels, parts = _components(eyes)
    parts = sorted(parts, key=lambda part: -part["size"])[:2]
    grow = max(4, int(min(height, width) * 0.05))
    line = max(3, int(height * k * 0.035))
    colour = SCREEN_INK if screen else INK
    for part in parts:
        cover = _dilate(labels == part["label"], grow)
        ring = _dilate(cover, grow) & ~cover
        local = np.median(rgb[ring], axis=0) if ring.any() else np.array(fallback)
        mask = Image.fromarray((cover * 255).astype(np.uint8)).resize((width * k, height * k), Image.BILINEAR)
        image.paste(Image.new("RGBA", image.size, tuple(int(v) for v in local) + (255,)), (0, 0), mask)
    draw = ImageDraw.Draw(image)
    for part in parts:
        x0, x1 = part["x0"] * k, part["x1"] * k
        lid = (part["y0"] + (part["y1"] - part["y0"]) * 0.58) * k
        sag = (part["y1"] - part["y0"]) * k * 0.1
        points = [(x0 + (x1 - x0) * (0.08 + 0.84 * t / 20), lid + math.sin(math.pi * t / 20) * sag) for t in range(21)]
        draw.line(points, fill=colour, width=line, joint="curve")
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - line / 2, y - line / 2, x + line / 2, y + line / 2), fill=colour)
    return image.resize((width, height), Image.LANCZOS)


# One pose -------------------------------------------------------------------

def _anchor(cx: float, cy: float, size: float, width: int, height: int) -> dict[str, float]:
    edge = max(width, height)
    return {"offsetX": round((cx - width / 2) / edge * 100, 3), "offsetY": round((cy - height / 2) / edge * 100, 3),
            "scale": round(size / edge, 5), "rotation": 0.0}


def rig_pose(image: Image.Image, style: dict[str, Any]) -> dict[str, Any]:
    """Crop, find the face, wipe the painted mouth and measure anchors for one keyed pose."""
    if image.width * image.height > MAX_PIXELS:
        raise FlatRigError("image_too_large", "Use a pose image up to 16 megapixels")
    figure = crop_figure(image)
    pixels = np.array(figure)
    rgb, alpha = pixels[..., :3], pixels[..., 3]
    eyes_box, eyes_mask = find_eyes(rgb, alpha)
    ex0, ey0, ex1, ey1 = eyes_box
    covered = eyes_covered(rgb, alpha, eyes_box, eyes_mask)
    try:
        mouth_box, mouth_mask, background = find_mouth(rgb, alpha, eyes_box, style["screen"])
        rigged, wiped = wipe(figure, mouth_mask, max(4, int((ey1 - ey0) * 0.08))), True
        mx, my = (mouth_box[0] + mouth_box[2]) / 2, (mouth_box[1] + mouth_box[3]) / 2
    except FlatRigError as error:
        if error.code != "mouth_not_found":
            raise
        # Under the eyes, where a cutout mouth sits: 0.19–0.31 of the eye-pair width on the six
        # production characters, so its median; nothing painted to wipe.
        rigged, wiped, mouth_box = figure, False, None
        mx, my = (ex0 + ex1) / 2, ey1 + (ex1 - ex0) * 0.28
        ring = alpha[ey1:min(alpha.shape[0], ey1 + (ey1 - ey0)), ex0:ex1] > 200
        background = np.median(rgb[ey1:min(alpha.shape[0], ey1 + (ey1 - ey0)), ex0:ex1][ring], axis=0) if ring.any() else np.array([200, 160, 130])
    width, height = rigged.size
    warnings = ["eyes_low"] if ey0 / height > 0.4 else []
    if not wiped:
        warnings.append("mouth_not_found")
    elif stray_marks(np.array(rigged)[..., :3], alpha, eyes_box, mouth_box):
        warnings.append("stray_mark")
    sprite_width = (ex1 - ex0) * style["mouth_scale"]
    pad = int((ey1 - ey0) * 0.25)
    bx0, by0, bx1, by1 = max(0, ex0 - pad), max(0, ey0 - pad), min(width, ex1 + pad), min(height, ey1 + pad)
    return {
        "image": rigged, "before": figure, "width": width, "height": height, "wiped": wiped, "blinks": not covered,
        "warnings": warnings,
        "mouth": _anchor(mx, my, sprite_width * SPRITE[1] / SPRITE[0], width, height),
        "eyes": _anchor((bx0 + bx1) / 2, (by0 + by1) / 2, by1 - by0, width, height),
        "blink": blink_sprite(rgb[by0:by1, bx0:bx1], eyes_mask[by0:by1, bx0:bx1], background, style["screen"]),
        "eyes_box": list(eyes_box), "mouth_box": list(mouth_box) if mouth_box else None,
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
    """The face from the eyes to below the mouth, where a wrong placement or a leftover stroke shows."""
    x0, y0, x1, y1 = rig["eyes_box"]
    width, span = x1 - x0, max(y1 - y0, (x1 - x0) * 0.55)
    return image.crop((max(0, int(x0 - width * 0.25)), max(0, int(y0 - span * 0.2)),
                       min(image.width, int(x1 + width * 0.25)), min(image.height, int(y1 + span * 1.7))))


def _tile(frame: Image.Image, height: int, warn: bool) -> Image.Image:
    tile = frame.resize((max(1, int(frame.width * height / frame.height)), height), Image.LANCZOS)
    if warn:
        framed = Image.new("RGBA", tile.size, (0, 0, 0, 0))
        framed.alpha_composite(tile)
        ImageDraw.Draw(framed).rectangle((0, 0, tile.width - 1, tile.height - 1), outline=(220, 30, 30, 255), width=6)
        return framed
    return tile


def review_sheet(poses: dict[str, dict[str, Any]], mouths: dict[str, Image.Image], blink: Image.Image, height: int = 360) -> Image.Image:
    """Per pose: the rig with its rest mouth, then an open mouth with the blink; below, the face before and after the
    wipe, enlarged. Poses with warnings are framed in red."""
    rows: list[list[Image.Image]] = [[], []]
    for rig in poses.values():
        warn = bool(rig.get("warnings"))
        rest = place(rig["image"], mouths["closed"], rig["mouth"])
        # The kit has one blink, from the base pose, placed with each pose's eye anchor; covered eyes do not blink.
        talk = place(rig["image"], mouths["wide"], rig["mouth"])
        talk = place(talk, blink, rig["eyes"]) if rig["blinks"] else talk
        rows[0] += [_tile(rest, height, warn), _tile(talk, height, warn)]
        if rig.get("before") is not None and rig.get("eyes_box"):
            rows[1] += [_tile(_face_crop(rig["before"], rig), height // 2, warn), _tile(_face_crop(rig["image"], rig), height // 2, warn)]
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


def _overlay(kit_id: str, name: str, label: str, file: str, workspace: str) -> dict[str, Any]:
    return {"id": f"{kit_id}-{label}"[:120], "name": f"{name} {label}"[:240], "source": _url(file, workspace),
            "kind": "overlay", "alphaStatus": "transparent", "reviewState": "approved", "workspace": workspace}


def _rig_poses(kit: dict[str, Any], style, workspace: str, workspace_dir: str, pose_ids):
    originals = _original_sources(kit)
    assets = {"base": kit.get("base"), **(kit.get("poses") or {})}
    wanted = list(pose_ids) if pose_ids else [pose for pose, asset in assets.items() if asset]
    if "base" not in wanted or not assets.get("base"):
        raise FlatRigError("missing_base", "Approve a base pose before rigging; the blink comes from it", 409)
    rigs, sources = {}, {}
    for pose in wanted:
        if not assets.get(pose):
            raise FlatRigError("unknown_pose", f"The character has no pose {pose}")
        current = assets[pose]["source"]
        # The recorded original only stands in for this rig's own output; a pose replaced since then is rigged as given.
        rigged = f"kit-{kit.get('id', '')}-{pose}-rig-" in current
        sources[pose] = originals[pose] if rigged and originals.get(pose) else current
        with Image.open(_workspace_file(sources[pose], workspace, workspace_dir)) as image:
            try:
                rigs[pose] = rig_pose(image, style)
            except FlatRigError as error:
                raise FlatRigError(error.code, f"Pose {pose}: {error}", error.status) from error
    return rigs, sources


def rig_character(workspace_dir: str, workspace: str, kit_id: str, *, base_revision: int,
                  style: Any = None, pose_ids: list[str] | None = None) -> dict[str, Any]:
    """Rig the kit's base and poses, write the images to the workspace and save the kit."""
    library = read_character_kit_library(workspace_dir)
    kit = copy.deepcopy((library.get("kits") or {}).get(kit_id))
    if kit is None:
        raise FlatRigError("character_not_found", "Character not found", 404)
    look = rig_style(style)
    rigs, sources = _rig_poses(kit, look, workspace, workspace_dir, pose_ids)
    mouths = {state: draw_mouth(state, look) for state in STATES}
    name = kit.get("name") or kit_id
    kit["mouth"] = {state: _overlay(kit_id, name, f"mouth-{state}", _save(mouths[state], workspace_dir, f"kit-{kit_id}-mouth-{state}"), workspace)
                    for state in STATES}
    kit["mouthMapping"] = dict(MAPPING)
    blink_file = _save(rigs["base"]["blink"], workspace_dir, f"kit-{kit_id}-blink")
    kit["eyes"] = {"blink": _overlay(kit_id, name, "blink", blink_file, workspace)}
    anchors = dict(kit.get("anchors") or {})
    for pose, rig in rigs.items():
        file = _save(rig["image"], workspace_dir, f"kit-{kit_id}-{pose}-rig")
        target = kit["base"] if pose == "base" else kit["poses"][pose]
        target.update({"source": _url(file, workspace), "width": rig["width"], "height": rig["height"],
                       "alphaStatus": "transparent", "workspace": workspace})
        anchors[pose] = {"mouth": rig["mouth"], "eyes": rig["eyes"], **({} if rig["blinks"] else {"blink": False})}
    kit["anchors"] = anchors
    kit["style"] = "cutout"
    warnings = _kit_warnings(rigs)
    sheet = _save(review_sheet(rigs, mouths, rigs["base"]["blink"]), workspace_dir, f"kit-{kit_id}-rig-review")
    unwiped = sorted(pose for pose, rig in rigs.items() if not rig["wiped"])
    kit["provenance"] = [*(kit.get("provenance") or []), {
        "method": "flat-rig", "sources": {**_original_sources(kit), **sources}, "style": look,
        "unwipedPoses": unwiped, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }]
    saved = patch_character_kit(workspace_dir, kit_id, kit, base_revision=base_revision)
    return {
        "revision": saved.get("revision"), "character": saved["kits"][kit_id],
        "review": _url(sheet, workspace), "unwipedPoses": unwiped, "warnings": warnings,
        "poses": {pose: {"mouth": rig["mouth"], "eyes": rig["eyes"], "wiped": rig["wiped"], "blinks": rig["blinks"]}
                  for pose, rig in rigs.items()},
    }
